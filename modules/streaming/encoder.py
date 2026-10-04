"""
UltraCam Studio - El codificador de la transmisión (un ffmpeg).

- Imagen: la cámara virtual «UltraCam» (siempre la cámara elegida, 1080p a 30 fps). Así la
  transmisión no toca la cámara ni la grabación: es otro programa que mira la cámara virtual.
- Sonido: la mezcla del mezclador, por el mismo canal que antes usaba OBS (PCM por un pipe).
- Una salida horizontal (16:9) y, si hay destinos verticales, otra 9:16 (centro recortado):
  un codificador por orientación, nunca uno por plataforma.
- H.264 + AAC, bitrate constante y un fotograma clave cada 2 s: lo que piden todas.
"""

from typing import List, Optional

HW_ORDER = ("h264_nvenc", "h264_qsv", "h264_amf")


def pick_encoder(available: List[str]) -> str:
    """GPU si la hay (NVIDIA → Intel → AMD); si no, la CPU (libx264)."""
    return next((e for e in HW_ORDER if e in available), "libx264")


def video_args(encoder: str, kbps: int, fps: int, stream_index: int) -> List[str]:
    k = f"{kbps}k"
    gop = str(fps * 2)
    base = [f"-c:v:{stream_index}", encoder, f"-b:v:{stream_index}", k, f"-maxrate:v:{stream_index}", k,
            f"-bufsize:v:{stream_index}", f"{kbps * 2}k", f"-g:v:{stream_index}", gop]
    if encoder == "h264_nvenc":
        return base + [f"-preset:v:{stream_index}", "p5", f"-rc:v:{stream_index}", "cbr",
                       f"-profile:v:{stream_index}", "high", f"-bf:v:{stream_index}", "2"]
    if encoder == "h264_qsv":
        return base + [f"-preset:v:{stream_index}", "medium", f"-profile:v:{stream_index}", "high"]
    if encoder == "h264_amf":
        return base + [f"-rc:v:{stream_index}", "cbr", f"-quality:v:{stream_index}", "balanced"]
    return base + [f"-preset:v:{stream_index}", "veryfast", f"-profile:v:{stream_index}", "high",
                   f"-x264-params:v:{stream_index}", "nal-hrd=cbr"]


def build_command(ffmpeg: str, video_device: str, audio_pipe: str, sample_rate: int, encoder: str,
                  h: Optional[tuple], v: Optional[tuple], h_url: Optional[str], v_url: Optional[str],
                  audio_delay_ms: int = 0, video_input: Optional[List[str]] = None,
                  audio_input: Optional[List[str]] = None) -> List[str]:
    """h / v: (ancho, alto, fps, kbps) de cada salida (None = sin esa salida).
    video_input / audio_input: entradas alternativas (las pruebas usan señales sintéticas)."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostats"]
    cmd += video_input or ["-f", "dshow", "-rtbufsize", "128M", "-thread_queue_size", "512", "-framerate", "30",
                           "-video_size", "1920x1080", "-i", f"video={video_device}"]
    if audio_delay_ms:
        cmd += ["-itsoffset", f"{audio_delay_ms / 1000:.3f}"]      # la imagen llega un poco después
    cmd += audio_input or ["-f", "s16le", "-ar", str(sample_rate), "-ac", "2", "-thread_queue_size", "1024",
                           "-i", audio_pipe]
    outs = [(o, url, vert) for o, url, vert in ((h, h_url, False), (v, v_url, True)) if o and url]
    graph = [f"[0:v]split={len(outs)}" + "".join(f"[s{i}]" for i in range(len(outs)))] if len(outs) > 1 else []
    for i, (o, url, vert) in enumerate(outs):
        w, hh, fps, _ = o
        src = f"[s{i}]" if len(outs) > 1 else "[0:v]"
        crop = "crop=trunc(ih*9/32)*2:ih," if vert else ""          # centro 9:16 del cuadro 16:9
        graph.append(f"{src}{crop}fps={fps},scale={w}:{hh}:flags=bicubic,format=yuv420p[o{i}]")
    cmd += ["-filter_complex", ";".join(graph)]
    for i, (o, url, vert) in enumerate(outs):
        cmd += ["-map", f"[o{i}]", "-map", "1:a"] + video_args(encoder, o[3], o[2], 0) + [
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-f", "flv", url]
    return cmd
