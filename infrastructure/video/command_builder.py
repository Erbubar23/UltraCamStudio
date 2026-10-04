"""
Generador de comandos CLI para streaming de video (Android scrcpy, PC DirectShow, iPhone).
Aislado de la lógica de interfaz de usuario y del ciclo de vida de procesos (SRP).
"""

import os
import re
import datetime
from typing import List, Optional, Tuple, Dict, Any
import virtualcam

PREVIEW_HEIGHT = 540
PREVIEW_MAX_FPS = 30

def high_speed_sizes(listing: str) -> Dict[str, List[int]]:
    """Tamaños de «High speed capture» de una cámara en la salida de scrcpy --list-camera-sizes:
    «- 1920x1080 (fps={120, 240})» → {"1920x1080": [120, 240]}."""
    out: Dict[str, List[int]] = {}
    part = listing.split("High speed capture", 1)
    if len(part) < 2:
        return out
    for size, rates in re.findall(r"-\s*(\d+x\d+)\s*\(fps=\{([\d,\s]+)\}\)", part[1]):
        out[size] = sorted(int(r) for r in re.findall(r"\d+", rates))
    return out


def high_speed_rate(cam: Optional[Dict], size: str, fps: int) -> Optional[int]:
    """Si la cámara no da `fps` en modo normal pero sí en alta velocidad a ese tamaño, la
    frecuencia del sensor a pedir (un múltiplo: 120 para 60 fps); el teléfono descarta los
    cuadros que sobran. Así un Galaxy, que en modo normal se queda en 30, graba a 60.
    None si no hace falta o no se puede."""
    if not cam or not fps or not cam.get("fps") or fps in cam["fps"]:
        return None
    rates = (cam.get("high_speed") or {}).get(size) or []
    return next((r for r in sorted(rates) if r % fps == 0), None)


def high_speed_sizes_for(cam: Optional[Dict], fps: int) -> List[str]:
    """Tamaños a los que la cámara llega a `fps` solo con la captura de alta velocidad."""
    if not cam or not cam.get("fps") or fps in cam["fps"]:
        return []
    return [s for s in (cam.get("high_speed") or {}) if high_speed_rate(cam, s, fps)]


FULL_HD_SIDE = 1920

# Las fuentes mayores que Full HD se ven en el monitor a 720p como máximo (lado largo 1280):
# es una ayuda visual que ocupa una parte de la pantalla, y cada cuadro más chico se escala,
# copia y dibuja antes, que es lo que se nota como retraso. Una fuente menor no se agranda.
MONITOR_MAX_SIDE = 1280
MONITOR_SCALE = (f"scale=w='min(iw,{MONITOR_MAX_SIDE})':h='min(ih,{MONITOR_MAX_SIDE})'"
                 ":force_original_aspect_ratio=decrease:force_divisible_by=2:flags=fast_bilinear")


def exceeds_full_hd(size) -> bool:
    """True si «AnchoxAlto» pasa de 1920x1080 (en horizontal o en vertical)."""
    try:
        w, h = (int(v) for v in str(size).lower().split("x"))
    except ValueError:
        return False
    return max(w, h) > FULL_HD_SIDE or min(w, h) > 1080


# ffplay abre su ventana fuera de la pantalla y la interfaz la incrusta en el monitor. Si la
# imagen tarda (grabación vertical del teléfono: ~12 s), nunca aparece suelta en el escritorio.
OFFSCREEN_WINDOW = ["-left", "-32000", "-top", "-32000"]

# Monitor en vivo sin retraso acumulado. Con el reloj del video (lo normal en ffplay) cada
# cuadro se muestra a su ritmo: si llegan varios juntos tras un tirón (disco, codificador),
# se quedan en cola y el retraso ya no se recupera. Con reloj externo (tiempo real) los
# cuadros atrasados se descartan y el monitor vuelve a estar al día. Sin análisis inicial:
# el encabezado nut ya trae el formato, y los cuadros leídos al analizar eran retraso fijo.
LIVE_PLAYER_FLAGS = ["-fflags", "nobuffer", "-flags", "low_delay", "-framedrop", "-sync", "ext"]


def preview_player_command(ffplay_path: str, window_title: str) -> List[str]:
    """ffplay que muestra en el monitor el video crudo (nut) que le llega por stdin."""
    return [ffplay_path, "-hide_banner", "-loglevel", "error"] + LIVE_PLAYER_FLAGS + [
            "-probesize", "32", "-analyzeduration", "0",
            "-f", "nut", "-i", "pipe:0", "-window_title", window_title] + OFFSCREEN_WINDOW


class CommandBuilder:
    """Construcción desacoplada y testeable de argumentos de línea de comandos."""

    @staticmethod
    def build_android_command(scrcpy_path: str, config: dict) -> Tuple[List[str], Optional[str]]:
        """
        Construye el comando scrcpy para streaming desde Android.
        Devuelve (comando, ruta_archivo_grabacion).
        Garantiza compatibilidad total con Android 16 (--no-control y sin flags incompatibles).
        """
        if not scrcpy_path:
            raise FileNotFoundError("scrcpy no encontrado.")

        cmd = [
            scrcpy_path,
            "--video-source=camera",
            "--no-control"
        ]

        if config.get("serial"):
            cmd.extend(["-s", config["serial"]])

        cam_id = config.get("camera_id")
        cam_facing = config.get("camera_facing")
        if cam_id is not None and str(cam_id).strip().lower() not in ("auto", "none", ""):
            cmd.append(f"--camera-id={cam_id}")
        elif cam_facing == "front":
            cmd.append("--camera-id=1")
        elif cam_facing == "back":
            cmd.append("--camera-id=0")
        else:
            cmd.append("--camera-facing=back")

        size = config.get("size", "3840x2160")
        if size and size != "auto":
            cmd.append(f"--camera-size={size}")

        try:
            rotation = int(config.get("rotation") or 0) % 360
        except (TypeError, ValueError):
            rotation = 0
        if rotation in (90, 180, 270):
            cmd.append(f"--capture-orientation={rotation}")

        fps = config.get("fps", 30)
        high_speed = config.get("high_speed_fps")
        if fps and high_speed:
            # Sensor en alta velocidad (p. ej. 120) y el codificador del teléfono deja pasar `fps`
            cmd += ["--camera-high-speed", f"--camera-fps={high_speed}", f"--max-fps={fps}"]
        elif fps:
            cmd.append(f"--camera-fps={fps}")

        codec = config.get("codec", "h265")
        if codec:
            cmd.append(f"--video-codec={codec}")

        bitrate = config.get("bitrate", "50M")
        if bitrate:
            cmd.extend(["-b", str(bitrate)])

        if config.get("vcam_pipe"):
            cmd.append("--video-codec-options=i-frame-interval:int=1")

        full_record_path = None
        vcam_pipe = config.get("vcam_pipe")
        if config.get("record_video", False) and config.get("record_dir"):
            os.makedirs(config["record_dir"], exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            record_filename = f"android_{timestamp}.mkv"
            full_record_path = os.path.join(config["record_dir"], record_filename)
            cmd.append(f"--record={vcam_pipe or full_record_path}")
            cmd.append("--record-format=mkv")
        else:
            if vcam_pipe:
                cmd.append(f"--record={vcam_pipe}")
                cmd.append("--record-format=mkv")

        if config.get("audio_mic", False):
            cmd.append("--audio-source=mic-camcorder")
            cmd.append("--audio-codec=opus")
            cmd.append("--audio-bit-rate=128K")
        elif full_record_path and config.get("guide_audio", True):
            # Pista guía: el micrófono del teléfono va al .mkv con el mismo reloj que la imagen.
            # No se escucha ni queda en la toma final; solo sirve para alinear el audio del PC.
            cmd += ["--audio-source=mic-camcorder", "--audio-codec=opus", "--audio-bit-rate=64K",
                    "--no-audio-playback"]
        else:
            cmd.append("--no-audio")

        zoom = config.get("zoom")
        if zoom and float(zoom) > 0.0 and float(zoom) != 1.0:
            cmd.append(f"--camera-zoom={zoom}")

        # Monitor decodificado aparte (fuente mayor que Full HD): scrcpy no abre ventana y solo
        # entrega el video por el pipe; el búfer y el título son de su ventana, así que sobran.
        if config.get("decoded_monitor") and vcam_pipe:
            cmd.append("--no-window")
            return cmd, full_record_path

        video_buf = config.get("video_buffer")
        if video_buf is not None:
            cmd.append(f"--video-buffer={int(video_buf)}")
        elif config.get("low_latency", False):
            cmd.append("--video-buffer=0")
        else:
            cmd.append("--video-buffer=100")

        if config.get("no_playback", False):
            cmd.append("--no-playback")
        else:
            win_w = config.get("window_width")
            if win_w and int(win_w) > 0:
                cmd.append(f"--window-width={int(win_w)}")
            win_h = config.get("window_height")
            if win_h and int(win_h) > 0:
                cmd.append(f"--window-height={int(win_h)}")

            window_title = config.get("window_title", "UltraCam_Studio_Monitor")
            cmd.append(f"--window-title={window_title}")

        return cmd, full_record_path

    @staticmethod
    def build_pc_camera_command(ffmpeg_path: str, ffplay_path: str, encoder_args: List[str],
                                config: dict) -> Tuple[List[str], Optional[str]]:
        """
        Genera el comando FFplay (monitoreo embebido) o FFmpeg (grabación directa / vcam)
        para cualquier webcam o capturadora DirectShow de PC.
        Devuelve (comando, ruta_archivo_grabacion).
        """
        dev_name = config.get("pc_device") or config.get("device_name") or config.get("ios_device", "C505 HD Webcam")
        size = config.get("size", "1280x720")
        fps = config.get("fps", 30)
        pixel_format = config.get("pixel_format")
        vcodec = config.get("vcodec")
        if pixel_format == "mjpeg" or vcodec == "mjpeg":
            vcodec = "mjpeg"
            pixel_format = None
        record_video = config.get("record_video", False)
        window_title = config.get("window_title", "UltraCam_Studio_Monitor")

        # Filtros de calibración en tiempo real (ProcAmp)
        brightness = float(config.get("brightness", 0.0))
        contrast = float(config.get("contrast", 1.0))
        saturation = float(config.get("saturation", 1.0))
        sharpness = float(config.get("sharpness", 0.0))

        # Vertical 9:16 para redes: se recorta el centro, o se endereza una cámara montada de
        # lado (sin perder resolución). Va primero: grabación, monitor y cámara virtual salen iguales.
        filters = []
        vertical = config.get("vertical")
        if vertical == "crop":
            filters.append("crop=trunc(ih*9/32)*2:ih")
        elif vertical == "cw":
            filters.append("transpose=1")
        elif vertical == "ccw":
            filters.append("transpose=2")
        eq_parts = []
        if abs(brightness) > 0.001:
            eq_parts.append(f"brightness={brightness:.2f}")
        if abs(contrast - 1.0) > 0.001:
            eq_parts.append(f"contrast={contrast:.2f}")
        if abs(saturation - 1.0) > 0.001:
            eq_parts.append(f"saturation={saturation:.2f}")
        if eq_parts:
            filters.append(f"eq={':'.join(eq_parts)}")
        if sharpness > 0.05:
            filters.append(f"unsharp=5:5:{sharpness * 0.4:.2f}")

        vf_str = ",".join(filters) if filters else None
        vcam_pipe = config.get("vcam_pipe")

        if record_video or vcam_pipe:
            exe = ffmpeg_path
            if not exe:
                raise FileNotFoundError("ffmpeg no encontrado para grabar.")

            full_record_path = None
            if record_video:
                rec_dir = config.get("record_dir") or os.path.join(os.path.expanduser("~"), "Videos", "GalaxyCam")
                os.makedirs(rec_dir, exist_ok=True)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                clean_name = re.sub(r'[\\/*?:"<>| ]', '_', dev_name)
                record_filename = f"{clean_name}_{timestamp}.mkv"
                full_record_path = os.path.join(rec_dir, record_filename)

            cmd = [exe, "-y", "-hide_banner", "-nostats", "-progress", "pipe:2"]
            cmd.extend(["-f", "dshow", "-rtbufsize", "256M", "-thread_queue_size", "1024"])
            if vcodec:
                cmd.extend(["-vcodec", vcodec])
            elif pixel_format and pixel_format != "mjpeg":
                cmd.extend(["-pixel_format", pixel_format])
            if size and size != "auto":
                cmd.extend(["-video_size", size])
            if fps:
                cmd.extend(["-framerate", str(fps)])
            cmd.extend(["-i", f"video={dev_name}"])

            live_preview = bool(config.get("live_preview", False))
            branches = [k for k, on in (("rec", bool(full_record_path)), ("pv", live_preview),
                                        ("vc", bool(vcam_pipe))) if on]
            chain = list(filters)
            graph, tap = [], {}
            if len(branches) > 1:
                labels = "".join(f"[{b}]" for b in branches)
                graph.append("[0:v]" + ",".join(chain + [f"split={len(branches)}"]) + labels)
                tap = {b: f"[{b}]" for b in branches}
                chain = []

            def add_branch(key: str, extra: List[str]) -> List[str]:
                steps = chain + extra
                if not tap:
                    return (["-map", "0:v"] + (["-vf", ",".join(steps)] if steps else []))
                if not steps:
                    return ["-map", tap[key]]
                out = f"{key}out"
                graph.append(f"{tap[key]}" + ",".join(steps) + f"[{out}]")
                return ["-map", f"[{out}]"]

            outputs = []
            if full_record_path:
                outputs += add_branch("rec", [])
                outputs += encoder_args + ["-pix_fmt", "yuv420p", "-an", "-f", "matroska", full_record_path]

            if live_preview:
                pv_fps = min(int(fps or PREVIEW_MAX_FPS), PREVIEW_MAX_FPS)
                outputs += add_branch("pv", [f"fps={pv_fps}", f"scale=-2:{PREVIEW_HEIGHT}:flags=fast_bilinear"])
                outputs += ["-c:v", "rawvideo", "-pix_fmt", "yuv420p", "-an", "-f", "nut", "pipe:1"]

            if vcam_pipe:
                vw, vh = config.get("vcam_size") or virtualcam.OUTPUT_SIZE
                vc_fps = min(int(fps or virtualcam.VCAM_FPS), virtualcam.VCAM_FPS)
                outputs += add_branch("vc", [
                    f"fps={vc_fps}",
                    f"scale={vw}:{vh}:force_original_aspect_ratio=decrease:flags=fast_bilinear",
                    f"pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2", "format=nv12"])
                outputs += ["-an", "-f", "rawvideo", vcam_pipe]

            if graph:
                cmd.extend(["-filter_complex", ";".join(graph)])
            cmd.extend(outputs)

            return cmd, full_record_path
        else:
            exe = ffplay_path or ffmpeg_path
            if not exe:
                raise FileNotFoundError("ffplay no encontrado para el monitor.")

            cmd = [exe, "-hide_banner", "-loglevel", "warning", "-nostats", "-f", "dshow"]
            if vcodec:
                cmd.extend(["-vcodec", vcodec])
            elif pixel_format and pixel_format != "mjpeg":
                cmd.extend(["-pixel_format", pixel_format])
            if size and size != "auto":
                cmd.extend(["-video_size", size])
            if fps:
                cmd.extend(["-framerate", str(fps)])
            cmd.extend(["-i", f"video={dev_name}"])
            cmd.extend(LIVE_PLAYER_FLAGS)

            if exceeds_full_hd(size):
                vf_str = ",".join(([vf_str] if vf_str else []) + [MONITOR_SCALE])
            if vf_str:
                cmd.extend(["-vf", vf_str])

            cmd.extend(["-window_title", window_title] + OFFSCREEN_WINDOW)
            return cmd, None

    @staticmethod
    def build_ios_command(ffmpeg_path: str, ffplay_path: str, config: dict) -> List[str]:
        """Genera el comando FFplay o FFmpeg para streaming desde iPhone (Iriun / DroidCam)."""
        dshow_dev = config.get("ios_device", "Iriun Webcam")
        size = config.get("size", "1920x1080")
        fps = config.get("fps", 30)
        window_title = config.get("window_title", "UltraCam_Studio_Monitor")
        pixel_format = config.get("pixel_format")
        vcodec = config.get("vcodec")
        if pixel_format == "mjpeg" or vcodec == "mjpeg":
            vcodec = "mjpeg"
            pixel_format = None

        exe = ffplay_path or ffmpeg_path
        if not exe:
            raise FileNotFoundError("Ni ffplay ni ffmpeg están instalados.")

        cmd = [exe, "-f", "dshow"]
        if vcodec:
            cmd.extend(["-vcodec", vcodec])
        elif pixel_format and pixel_format != "mjpeg":
            cmd.extend(["-pixel_format", pixel_format])
        if size and size != "auto":
            cmd.extend(["-video_size", size])
        if fps:
            cmd.extend(["-framerate", str(fps)])
        cmd.extend(["-i", f"video={dshow_dev}", "-window_title", window_title])
        return cmd
