"""
UltraCam Studio / GalaxyCamPro - Motor de Captura y Streaming (Fachada del Backend).
Refactorizado bajo principios SOLID y Clean Architecture.
Coordina CommandBuilder, DeviceScanner, StreamManager, Win32WindowEmbedder y ReportService.
"""

import os
import sys
import glob
import time
import shutil
import datetime
import subprocess
import tempfile
import json
import re
import wave
import threading
from typing import Optional, List, Dict, Any, Callable, Tuple

import paths
import virtualcam
from infrastructure.logging.app_logger import GLOBAL_LOGGER
from infrastructure.system.process_utils import GLOBAL_PROCESS_MANAGER, bind_to_app
from infrastructure.system.win32_window import GLOBAL_WINDOW_EMBEDDER
from infrastructure.video.command_builder import (CommandBuilder, PREVIEW_HEIGHT, PREVIEW_MAX_FPS, MONITOR_SCALE,
                                                  exceeds_full_hd, preview_player_command, high_speed_sizes)
from infrastructure.video.device_scanner import DeviceScanner
from infrastructure.video.stream_manager import StreamManager
from infrastructure.video.report_service import ReportService
from infrastructure.video import av_sync
from infrastructure.persistence.settings_manager import SettingsManager

# Codificadores por hardware en orden de preferencia
HW_ENCODERS = [
    ("h264_nvenc", ["-preset", "p4", "-rc", "vbr", "-cq", "19", "-b:v", "0"]),
    ("h264_qsv", ["-preset", "medium", "-global_quality", "20"]),
    ("h264_amf", ["-quality", "balanced", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22"]),
    ("h264_mf", ["-hw_encoding", "true", "-rate_control", "quality", "-quality", "70"]),
]
CPU_ENCODER = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18"]


def parse_media_info(ffmpeg_stderr: str, size_bytes: int = 0) -> Dict[str, Any]:
    """Lee de la salida de «ffmpeg -i» el primer video (códec, tamaño), la duración, el bitrate
    del video (estimado si el contenedor no lo dice) y cuántas pistas de audio hay."""
    info: Dict[str, Any] = {"codec": None, "width": None, "height": None, "duration": None, "bitrate": None,
                            "audio_streams": 0}
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", ffmpeg_stderr)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in ffmpeg_stderr.splitlines():
        if "Stream #" not in line:
            continue
        if ": Video:" in line and info["codec"] is None:
            c = re.search(r"Video: (\w+)", line)
            info["codec"] = c.group(1) if c else None
            wh = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
            if wh:
                info["width"], info["height"] = int(wh.group(1)), int(wh.group(2))
            br = re.search(r"(\d+) kb/s", line)
            if br:
                info["bitrate"] = int(br.group(1)) * 1000
        elif ": Audio:" in line:
            info["audio_streams"] += 1
    if info["bitrate"] is None and info["duration"] and size_bytes:
        info["bitrate"] = size_bytes * 8 / info["duration"]
    return info


def last_frames(ffmpeg_stderr: str) -> Optional[int]:
    """El último «frame=N» de las estadísticas de ffmpeg (cuántos cuadros escribió)."""
    found = re.findall(r"frame=\s*(\d+)", ffmpeg_stderr or "")
    return int(found[-1]) if found else None


class CameraEngine:
    """
    Fachada principal del subsistema de video.
    Mantiene compatibilidad de interfaz (DIP) mientras delega la lógica en componentes especializados.
    """

    def __init__(self):
        self.scrcpy_path: Optional[str] = None
        self.adb_path: Optional[str] = None
        self.ffmpeg_path: Optional[str] = None
        self.ffplay_path: Optional[str] = None

        self.stream_manager = StreamManager()
        self.scanner = DeviceScanner()

        self.active_platform: str = "android"
        self.log_pings: bool = False
        self.last_benchmark_result: Optional[dict] = None
        self._encoder_args: Optional[List[str]] = None

        self.find_binaries()

    # -------------------------------------------------------------------------
    # PROPIEDADES DELEGADAS PARA COMPATIBILIDAD
    # -------------------------------------------------------------------------
    @property
    def process(self) -> Optional[subprocess.Popen]:
        return self.stream_manager.process

    @process.setter
    def process(self, val: Optional[subprocess.Popen]):
        self.stream_manager.process = val

    @property
    def preview_process(self) -> Optional[subprocess.Popen]:
        return self.stream_manager.preview_process

    @preview_process.setter
    def preview_process(self, val: Optional[subprocess.Popen]):
        self.stream_manager.preview_process = val

    @property
    def is_running(self) -> bool:
        return self.stream_manager.is_running

    @is_running.setter
    def is_running(self, val: bool):
        self.stream_manager.is_running = val

    @property
    def recording_started(self):
        return self.stream_manager.recording_started

    @recording_started.setter
    def recording_started(self, val):
        self.stream_manager.recording_started = val

    @property
    def current_recording_file(self) -> Optional[str]:
        return self.stream_manager.current_recording_file

    @current_recording_file.setter
    def current_recording_file(self, val: Optional[str]):
        self.stream_manager.current_recording_file = val

    @property
    def vcam(self):
        return self.stream_manager.vcam

    @vcam.setter
    def vcam(self, val):
        self.stream_manager.vcam = val

    @property
    def session_logs(self) -> List[str]:
        return GLOBAL_LOGGER._memory_logs

    @session_logs.setter
    def session_logs(self, val: List[str]):
        GLOBAL_LOGGER._memory_logs = val

    @property
    def last_device_states(self) -> Dict[str, str]:
        return self.scanner.last_device_states

    @last_device_states.setter
    def last_device_states(self, val: Dict[str, str]):
        self.scanner.last_device_states = val

    @property
    def cached_battery(self) -> Dict[str, int]:
        return self.scanner.cached_battery

    @property
    def cached_ip(self) -> Dict[str, str]:
        return self.scanner.cached_ip

    @property
    def cached_cameras(self) -> Dict[str, List[Dict[str, str]]]:
        return self.scanner.cached_cameras

    @property
    def cached_pc_cameras(self) -> List[Dict[str, Any]]:
        return self.scanner.cached_pc_cameras

    @cached_pc_cameras.setter
    def cached_pc_cameras(self, val: List[Dict[str, Any]]):
        self.scanner.cached_pc_cameras = val

    @property
    def cached_camera_caps(self) -> Dict[str, Dict[str, Any]]:
        return self.scanner.cached_camera_caps

    @property
    def cached_ios_cameras(self) -> List[Dict[str, str]]:
        return self.scanner.cached_ios_cameras

    @cached_ios_cameras.setter
    def cached_ios_cameras(self, val: List[Dict[str, str]]):
        self.scanner.cached_ios_cameras = val

    @property
    def cached_device_info(self) -> Dict[str, dict]:
        return self.scanner.cached_device_info

    @cached_device_info.setter
    def cached_device_info(self, val: Dict[str, dict]):
        self.scanner.cached_device_info = val

    # -------------------------------------------------------------------------
    # LOGGING
    # -------------------------------------------------------------------------
    def log(self, message: str, category: str = "INFO"):
        GLOBAL_LOGGER.log(message, level="INFO", category=category)

    # -------------------------------------------------------------------------
    # LOCALIZACIÓN DE EJECUTABLES
    # -------------------------------------------------------------------------
    def find_binaries(self):
        self.scrcpy_path = shutil.which("scrcpy")
        self.adb_path = shutil.which("adb")
        self.ffmpeg_path = shutil.which("ffmpeg")
        self.ffplay_path = shutil.which("ffplay")

        for bin_dir in self._bundled_bin_dirs():
            for attr, exe in (("scrcpy_path", "scrcpy.exe"), ("adb_path", "adb.exe"),
                              ("ffmpeg_path", "ffmpeg.exe"), ("ffplay_path", "ffplay.exe")):
                candidate = os.path.join(bin_dir, exe)
                if os.path.isfile(candidate):
                    setattr(self, attr, candidate)

        local_app = os.environ.get("LOCALAPPDATA", "")
        if not self.scrcpy_path and local_app:
            pattern = os.path.join(local_app, "Microsoft", "WinGet", "Packages", "*scrcpy*", "**", "scrcpy.exe")
            matches = glob.glob(pattern, recursive=True)
            if matches:
                self.scrcpy_path = matches[0]
                adb_cand = os.path.join(os.path.dirname(self.scrcpy_path), "adb.exe")
                if os.path.exists(adb_cand):
                    self.adb_path = adb_cand

        if self.scrcpy_path and not self.adb_path:
            candidate = os.path.join(os.path.dirname(self.scrcpy_path), "adb.exe")
            if os.path.exists(candidate):
                self.adb_path = candidate

        if not self.ffmpeg_path and local_app:
            pattern = os.path.join(local_app, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "ffmpeg.exe")
            matches = glob.glob(pattern, recursive=True)
            if matches:
                self.ffmpeg_path = matches[0]
                ffplay_cand = os.path.join(os.path.dirname(self.ffmpeg_path), "ffplay.exe")
                if os.path.exists(ffplay_cand):
                    self.ffplay_path = ffplay_cand

        self.scanner.adb_path = self.adb_path
        self.scanner.ffmpeg_path = self.ffmpeg_path
        self.scanner.scrcpy_path = self.scrcpy_path

        if self.scrcpy_path:
            self.log(f"scrcpy localizado: {self.scrcpy_path}", "INIT")
        if self.adb_path:
            self.log(f"adb localizado: {self.adb_path}", "INIT")
        if self.ffmpeg_path:
            self.log(f"ffmpeg localizado: {self.ffmpeg_path}", "INIT")

    @staticmethod
    def _bundled_bin_dirs() -> List[str]:
        roots = []
        if getattr(sys, "frozen", False):
            roots.append(os.path.dirname(sys.executable))
            if hasattr(sys, "_MEIPASS"):
                roots.append(sys._MEIPASS)
        roots.append(os.path.dirname(os.path.abspath(__file__)))
        dirs = []
        for r in roots:
            for sub in ("bin", os.path.join("bin", "scrcpy"), os.path.join("bin", "ffmpeg")):
                d = os.path.join(r, sub)
                if os.path.isdir(d) and d not in dirs:
                    dirs.append(d)
        return dirs

    def repair_adb(self) -> str:
        self.log("Reiniciando servidor ADB...", "ADB")
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/IM", "adb.exe"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(0.5)
            if self.adb_path:
                subprocess.run([self.adb_path, "start-server"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                return "Servidor ADB reiniciado con éxito."
            return "No se encontró adb.exe para reiniciar."
        except Exception as e:
            return f"Error al reparar ADB: {e}"

    # -------------------------------------------------------------------------
    # DISPOSITIVOS Y HARDWARE
    # -------------------------------------------------------------------------
    def get_connected_devices(self) -> List[Dict[str, Any]]:
        return self.scanner.scan_adb_devices()

    def check_device_changes(self, log_pings: bool = False) -> List[Dict[str, Any]]:
        return self.scanner.check_device_changes(log_pings=log_pings)

    def get_device_info(self, serial: str) -> Dict[str, Any]:
        return self.scanner.get_device_info(serial)

    def get_device_battery(self, serial: str) -> Optional[int]:
        return self.scanner.get_device_battery(serial)

    def get_device_wifi_ip(self, serial: str) -> Optional[str]:
        if serial in self.scanner.cached_ip:
            return self.scanner.cached_ip[serial]
        if not self.adb_path:
            return None
        try:
            res = subprocess.run(
                [self.adb_path, "-s", serial, "shell", "ip", "-f", "inet", "addr", "show", "wlan0"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0, timeout=4
            )
            match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", res.stdout)
            if match:
                ip = match.group(1)
                self.scanner.cached_ip[serial] = ip
                self.log(f"IP Wi-Fi detectada: {ip}", "WIFI")
                return ip
        except Exception:
            pass
        return None

    @staticmethod
    def local_ipv4() -> List[str]:
        """Direcciones IPv4 de esta PC (sin la de bucle local)."""
        import socket
        ips = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ips.add(info[4][0])
        except OSError:
            pass
        return sorted(ip for ip in ips if not ip.startswith("127."))

    @staticmethod
    def same_network(phone_ip: str, pc_ips: List[str]) -> bool:
        """Heurística de red doméstica (/24): 192.168.1.20 y 192.168.1.35 están en la misma."""
        prefix = phone_ip.rsplit(".", 1)[0]
        return any(ip.rsplit(".", 1)[0] == prefix for ip in pc_ips)

    def connect_wifi(self, endpoint: str, timeout: float = 5) -> bool:
        """adb connect a un teléfono que ya estuvo por Wi‑Fi (para reconectar sin cable)."""
        if not self.adb_path:
            return False
        try:
            res = subprocess.run([self.adb_path, "connect", endpoint], capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                 timeout=timeout)
        except Exception:
            return False
        out = (res.stdout or "").lower()
        return "connected to" in out or "already connected" in out

    def setup_wireless_mode(self, serial: str) -> Dict[str, Any]:
        """Pasa un teléfono conectado por cable a Wi‑Fi (adb tcpip). Si falla, `reason` dice
        por qué, para que la interfaz explique qué hacer:
          no_ip           el teléfono no está en ninguna red Wi‑Fi
          other_network   el teléfono y la PC están en redes distintas
          unreachable     misma red, pero la PC no llega (aislamiento del router, red pública)
          error           otro fallo (detalle en `message`, solo para el registro)"""
        if not self.adb_path:
            return {"success": False, "reason": "error", "message": "ADB no disponible."}
        self.log(f"Configurando conexión Wi-Fi para {serial}...", "WIFI")
        ip = self.get_device_wifi_ip(serial)
        if not ip:
            return {"success": False, "reason": "no_ip", "message": "El teléfono no tiene IP Wi‑Fi."}
        pc_ips = self.local_ipv4()
        endpoint = f"{ip}:5555"
        try:
            subprocess.run([self.adb_path, "-s", serial, "tcpip", "5555"], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0, timeout=6)
            time.sleep(1)
            ok = self.connect_wifi(endpoint, timeout=8)
            self.log(f"Wi‑Fi {endpoint}: {'conectado' if ok else 'sin respuesta'} (IP de la PC: {', '.join(pc_ips) or '?'})", "WIFI")
            if ok:
                return {"success": True, "ip": ip, "endpoint": endpoint, "message": f"Conectado por Wi‑Fi a {endpoint}"}
            reason = "unreachable" if not pc_ips or self.same_network(ip, pc_ips) else "other_network"
            return {"success": False, "reason": reason, "ip": ip, "pc_ips": pc_ips,
                    "message": f"No se pudo conectar a {endpoint}"}
        except Exception as e:
            return {"success": False, "reason": "error", "message": f"Error configurando Wi-Fi: {e}"}

    def test_cable_speed(self, serial: Optional[str] = None, size_mb: int = 3) -> Dict[str, Any]:
        res = self.scanner.benchmark_cable(serial, size_mb)
        if res.get("success"):
            self.last_benchmark_result = res
        return res

    def benchmark_cable(self, serial: Optional[str] = None, size_mb: int = 3) -> Dict[str, Any]:
        return self.test_cable_speed(serial, size_mb)

    def get_device_cameras(self, serial: Optional[str] = None) -> List[Dict[str, str]]:
        if serial and serial in self.scanner.cached_cameras:
            return self.scanner.cached_cameras[serial]
        if not self.scrcpy_path or not os.path.exists(self.scrcpy_path):
            return self._default_camera_options()
        try:
            cmd = [self.scrcpy_path, "--video-source=camera"]
            if serial:
                cmd.extend(["-s", serial])
            # Con los tamaños, scrcpy también lista la «captura de alta velocidad» (120/240 fps):
            # en muchos teléfonos (Samsung) es la única forma de pasar de 30 fps.
            cmd.append("--list-camera-sizes")

            res = subprocess.run(cmd, capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0, timeout=10)
            head = re.compile(r"--camera-id=(\d+)\s*\((back|front|external)(?:,\s*(\d+x\d+))?([^)\n]*)")
            heads = list(head.finditer(res.stdout))
            if not heads:
                return self._default_camera_options()

            cameras = []
            for k, m in enumerate(heads):
                cam_id, facing, res_size, rest = m.groups()
                block = res.stdout[m.end():heads[k + 1].start() if k + 1 < len(heads) else len(res.stdout)]
                icon = "📷" if facing == "back" else "🤳"
                orient = "Trasera" if facing == "back" else "Frontal"
                size_str = f" - {res_size}" if res_size else ""
                cam = {
                    "id": cam_id,
                    "facing": facing,
                    "resolution": res_size or "",
                    "label": f"{icon} Cámara {orient} (ID: {cam_id}{size_str})"
                }
                # En los móviles con varios objetivos (p. ej. Galaxy S23 Ultra) la cámara
                # trasera principal los reúne todos: 0.6× gran angular, 3× y 10× tele se
                # eligen con el zoom, no con otro ID.
                fps = re.search(r"fps=\{([\d,\s]+)\}", rest)
                if fps:
                    cam["fps"] = [int(f) for f in re.findall(r"\d+", fps.group(1))]
                zoom = re.search(r"zoom-range=\[([\d.]+),\s*([\d.]+)\]", rest)
                if zoom:
                    cam["zoom_min"], cam["zoom_max"] = float(zoom.group(1)), float(zoom.group(2))
                cam["high_speed"] = high_speed_sizes(block)
                cameras.append(cam)

            if serial:
                self.scanner.cached_cameras[serial] = cameras
            self.log(f"Lentes de cámara detectados: {len(cameras)} sensores disponibles", "CAM")
            return cameras
        except Exception:
            return self._default_camera_options()

    def _default_camera_options(self) -> List[Dict[str, str]]:
        return [
            {"id": "auto", "facing": "back", "resolution": "", "label": "📷 Cámara Trasera Principal (Auto)"},
            {"id": "auto", "facing": "front", "resolution": "", "label": "🤳 Cámara Frontal (Selfie)"},
            {"id": "0", "facing": "back", "resolution": "", "label": "📷 Cámara ID 0 (Sensor Principal)"},
            {"id": "1", "facing": "front", "resolution": "", "label": "🤳 Cámara ID 1 (Sensor Frontal)"},
            {"id": "2", "facing": "back", "resolution": "", "label": "🌄 Cámara ID 2 (Gran Angular / Secundario)"},
            {"id": "3", "facing": "front", "resolution": "", "label": "🔍 Cámara ID 3 (Auxiliar / Teleobjetivo)"}
        ]

    def get_ios_cameras(self) -> List[Dict[str, str]]:
        return self.scanner.cached_ios_cameras if self.scanner.cached_ios_cameras else [
            {"name": "Iriun Webcam", "type": "directshow", "label": "🍏 iPhone vía Iriun Webcam (USB / Wi-Fi 4K)"},
            {"name": "DroidCam Video", "type": "directshow", "label": "🍏 iPhone vía DroidCam (USB / Wi-Fi)"},
            {"name": "SRT_Receiver", "type": "network", "label": "🍏 iPhone vía Red de Alta Velocidad (SRT / QR)"}
        ]

    def get_pc_cameras(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        return self.scanner.scan_dshow_devices(force_refresh=force_refresh)

    def probe_camera_capabilities(self, device_name: str, force_refresh: bool = False) -> Dict[str, Any]:
        return self.scanner.probe_capabilities(device_name, force_refresh=force_refresh)

    def open_camera_hardware_dialog(self, device_name: str) -> bool:
        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path) or not device_name:
            return False

        if self.stream_manager.hw_dialog_process and self.stream_manager.hw_dialog_process.poll() is None:
            GLOBAL_PROCESS_MANAGER.kill_process_tree(self.stream_manager.hw_dialog_process)
            self.stream_manager.hw_dialog_process = None

        cmd = [
            self.ffmpeg_path,
            "-f", "dshow",
            "-show_video_device_dialog", "true",
            "-i", f"video={device_name}",
            "-t", "0.1",
            "-f", "null",
            "-"
        ]
        try:
            self.log(f"Abriendo propiedades de hardware DirectShow para '{device_name}'...", "CAM")
            self.stream_manager.hw_dialog_process = bind_to_app(subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            ))
            return True
        except Exception as e:
            self.log(f"Error al abrir diálogo DirectShow: {e}", "ERROR")
            return False

    # -------------------------------------------------------------------------
    # PRESETS Y PERSISTENCIA
    # -------------------------------------------------------------------------
    def get_presets_file_path(self) -> str:
        return paths.presets_path()

    def save_camera_preset(self, device_name: str, settings: dict) -> bool:
        path = self.get_presets_file_path()
        try:
            presets = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    presets = json.load(f)
            presets[device_name] = settings
            with open(path, "w", encoding="utf-8") as f:
                json.dump(presets, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            self.log(f"Error al guardar presets de cámara: {e}", "WARN")
            return False

    def load_camera_preset(self, device_name: str) -> Dict[str, Any]:
        path = self.get_presets_file_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    presets = json.load(f)
                return presets.get(device_name, {})
        except Exception:
            pass
        return {}

    # -------------------------------------------------------------------------
    # CONSTRUCCIÓN DE COMANDOS
    # -------------------------------------------------------------------------
    def build_command(self, config: dict) -> List[str]:
        cmd, record_path = CommandBuilder.build_android_command(self.scrcpy_path, config)
        if record_path:
            self.stream_manager.current_recording_file = record_path
            self.log(f"Grabando video en: {record_path}", "REC")
        return cmd

    def build_ios_command(self, config: dict) -> List[str]:
        return CommandBuilder.build_ios_command(self.ffmpeg_path, self.ffplay_path, config)

    def video_encoder_args(self) -> List[str]:
        if self._encoder_args is not None:
            return self._encoder_args
        self._encoder_args = list(CPU_ENCODER)
        if not self.ffmpeg_path:
            return self._encoder_args
        no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        for name, opts in HW_ENCODERS:
            probe = [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                     "-i", "color=c=black:s=640x360:r=30", "-frames:v", "3",
                     "-c:v", name] + opts + ["-pix_fmt", "yuv420p", "-f", "null", "-"]
            try:
                done = subprocess.run(probe, capture_output=True, timeout=20, creationflags=no_window)
                if done.returncode == 0:
                    self._encoder_args = ["-c:v", name] + opts
                    self.log(f"Grabación acelerada por hardware con {name}: la CPU queda libre "
                             f"para la cámara virtual y el monitor.", "REC")
                    return self._encoder_args
            except Exception:
                continue
        self.log("Sin codificador por hardware disponible: se graba con la CPU (libx264).", "REC")
        return self._encoder_args

    def build_pc_camera_command(self, config: dict) -> List[str]:
        cmd, record_path = CommandBuilder.build_pc_camera_command(
            self.ffmpeg_path, self.ffplay_path, self.video_encoder_args(), config
        )
        if record_path:
            self.stream_manager.current_recording_file = record_path
            self.log(f"Grabando video de cámara PC en: {record_path}", "REC")
        return cmd

    # -------------------------------------------------------------------------
    # EJECUCIÓN Y CONTROL DE STREAMING
    # -------------------------------------------------------------------------
    def start_stream(self, config: dict, on_exit: Optional[Callable[[int], None]] = None) -> bool:
        if self.is_running:
            return True

        platform_mode = config.get("platform", "android")
        self.active_platform = platform_mode
        self.stream_manager.current_recording_file = None

        # Un fallo al preparar (pipe de la cámara virtual, comando, binario ausente)
        # se informa como False: quien llama muestra el error en vez de quedarse
        # esperando una imagen que nunca llegará.
        try:
            config = self._setup_vcam(config, platform_mode)

            if platform_mode in ("pc", "webcam", "dshow"):
                cmd = self.build_pc_camera_command(config)
            elif platform_mode == "ios":
                cmd = self.build_ios_command(config)
            else:
                cmd = self.build_command(config)
                if self.vcam and self.stream_manager.current_recording_file:
                    self.vcam.record_path = self.stream_manager.current_recording_file
        except Exception as e:
            self.log(f"No se pudo preparar la cámara: {e}", "ERROR")
            self._stop_vcam()
            return False

        self.log(f"Ejecutando streaming ({platform_mode.upper()}): {' '.join(cmd)}", "PROCESS")

        is_ffmpeg_rec = platform_mode in ("pc", "webcam", "dshow") and (
            config.get("record_video", False) or bool(config.get("vcam_pipe")))
        piped_preview = is_ffmpeg_rec and config.get("live_preview", False)
        window_title = config.get("window_title", "UltraCam_Studio_Monitor")

        return self.stream_manager.start_stream(
            cmd=cmd,
            is_ffmpeg_rec=is_ffmpeg_rec,
            piped_preview=piped_preview,
            ffplay_path=self.ffplay_path,
            window_title=window_title,
            vcam_bridge=self.vcam,
            on_exit=on_exit
        )

    def stop_stream(self):
        self.stream_manager.stop_stream()

    def _setup_vcam(self, config: dict, platform_mode: str) -> dict:
        is_pc = platform_mode in ("pc", "webcam", "dshow")
        # Teléfono por encima de Full HD: scrcpy decodifica por CPU y el monitor se atrasa.
        # Entonces scrcpy no dibuja ventana y el monitor sale del reparto (GPU, ≤ Full HD).
        decoded = (platform_mode == "android" and not config.get("no_playback")
                   and bool(self.ffmpeg_path and self.ffplay_path)
                   and exceeds_full_hd(config.get("size")))
        want_vcam = bool(config.get("virtual_cam")) and virtualcam.available()
        if not want_vcam and not decoded:
            return config

        size = virtualcam.OUTPUT_SIZE
        # El enlace con el driver lo presta el servicio: si no pudo abrirse, la
        # fuente se muestra igual en el monitor, sin cámara virtual.
        sink = virtualcam.SERVICE.acquire() if want_vcam else None
        if want_vcam and sink is None:
            self.log(f"Cámara virtual no disponible: {virtualcam.SERVICE.last_error or 'motivo desconocido'}", "WARN")
            if not decoded:
                return config

        preview = None
        if decoded:
            preview = {"cmd": preview_player_command(self.ffplay_path, config.get("window_title", "UltraCam_Studio_Monitor")),
                       "vf": MONITOR_SCALE, "fps": min(int(config.get("fps") or PREVIEW_MAX_FPS), PREVIEW_MAX_FPS)}
            self.log(f"Monitor reducido a Full HD y decodificado por GPU (la toma queda en {config.get('size')}).", "PROCESS")
        bridge = virtualcam.VirtualCamBridge(
            mode="raw" if is_pc else "encoded",
            width=size[0], height=size[1],
            fps=virtualcam.VCAM_FPS,
            ffmpeg_path=self.ffmpeg_path,
            log=self.log,
            sink=sink,
            preview=preview,
        )
        bridge.start()
        self.stream_manager.vcam = bridge
        return dict(config, vcam_pipe=bridge.pipe_path, vcam_size=size, decoded_monitor=decoded)

    def _stop_vcam(self):
        self.stream_manager._cleanup_vcam()

    def _kill_preview(self):
        self.stream_manager._cleanup_preview()

    @staticmethod
    def embed_window_into_hwnd(window_title: str, parent_hwnd: int, width: int, height: int, timeout: float = 6.0) -> bool:
        return GLOBAL_WINDOW_EMBEDDER.embed_window(window_title, parent_hwnd, width, height, timeout)

    # -------------------------------------------------------------------------
    # POST-PROCESAMIENTO Y REPORTES
    # -------------------------------------------------------------------------
    def _guide_sync(self, video_path: str, refs: List[str], serial: Optional[str]) -> Optional[Dict[str, Any]]:
        """Medir la sincronía nunca debe costar la toma: ante cualquier fallo, se une sin ella."""
        def clock_gap():
            return av_sync.phone_clock_gap(self.adb_path, serial) if self.adb_path and serial else None
        try:
            return av_sync.measure(self.ffmpeg_path, video_path, refs, clock_gap=clock_gap)
        except Exception as e:
            self.log(f"No se pudo medir la sincronía por pista guía: {e}", "WARN")
            return None

    @staticmethod
    def _wav_rate(path: str) -> int:
        try:
            with wave.open(path, "rb") as w:
                return w.getframerate()
        except (OSError, wave.Error, EOFError):
            return 48000

    def probe_media(self, path: str) -> Dict[str, Any]:
        """Códec, tamaño, duración y bitrate del primer video de un archivo (solo lee el
        encabezado). Lo que no se pueda leer queda en None."""
        info: Dict[str, Any] = {"codec": None, "width": None, "height": None, "duration": None, "bitrate": None,
                                "audio_streams": 0}
        if not self.ffmpeg_path or not path or not os.path.exists(path):
            return info
        no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            res = subprocess.run([self.ffmpeg_path, "-hide_banner", "-i", path], capture_output=True, text=True,
                                 errors="replace", timeout=20, creationflags=no_window)
        except Exception:
            return info
        return parse_media_info(res.stderr or "", os.path.getsize(path))

    def cancel_export(self):
        """Corta el guardado en curso (al cerrar la app a mitad): los originales se conservan."""
        proc = getattr(self, "_export_proc", None)
        if proc is not None and proc.poll() is None:
            GLOBAL_PROCESS_MANAGER.kill_process_tree(proc)

    def _run_export(self, cmd: List[str], progress: Optional[Callable], duration: Optional[float],
                    min_speed: Optional[float]) -> Dict[str, Any]:
        """Ejecuta ffmpeg. Sin `progress`, igual que siempre (subprocess.run). Con `progress`,
        avisa del avance y, si `min_speed`, corta cuando va más lento que eso (×tiempo real)
        después de unos segundos: comprimir no debe tener la PC ocupada más que la toma."""
        no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        if progress is None:
            res = subprocess.run(cmd, capture_output=True, text=True, creationflags=no_window)
            return {"returncode": res.returncode, "stderr": res.stderr or "", "slow": False,
                    "frames": last_frames(res.stderr or "")}
        full = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
        proc = bind_to_app(subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                            errors="replace", creationflags=no_window))
        self._export_proc = proc
        tail: List[str] = []

        def read_err():
            for line in proc.stderr:
                tail.append(line)
                del tail[:-200]
        t_err = threading.Thread(target=read_err, daemon=True)
        t_err.start()
        t0, slow, speed, out_s, frames = time.monotonic(), False, None, 0.0, None
        for line in proc.stdout:
            key, _, val = line.strip().partition("=")
            if key == "out_time_us" and val.isdigit():
                out_s = int(val) / 1e6
            elif key == "frame" and val.isdigit():
                frames = int(val)
            elif key == "speed" and val.endswith("x"):
                try:
                    speed = float(val[:-1])
                except ValueError:
                    pass
            elif key == "progress":
                elapsed = time.monotonic() - t0
                if min_speed and elapsed > 12 and speed is not None and speed < min_speed:
                    slow = True
                    GLOBAL_PROCESS_MANAGER.kill_process_tree(proc)
                    break
                frac = min(1.0, out_s / duration) if duration else None
                eta = (duration - out_s) / speed if duration and speed else None
                try:
                    progress(frac, speed, eta)
                except Exception:
                    pass
        code = proc.wait()
        t_err.join(timeout=2)
        self._export_proc = None
        return {"returncode": code, "stderr": "".join(tail), "slow": slow, "frames": frames}

    def _verify_export(self, path: str, n_audio: int, frames_written: Optional[int]) -> Tuple[bool, str]:
        """¿El archivo nuevo está completo? Se lee entero (sin decodificar): debe abrirse, tener
        el video, todas las pistas de audio y los cuadros que ffmpeg dijo escribir. Recién así
        se borran los originales. (No se compara la duración total: el audio puede durar unos
        segundos más que el video y no es un error.)"""
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return False, "el archivo no se creó"
        no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        res = subprocess.run([self.ffmpeg_path, "-hide_banner", "-stats", "-i", path, "-map", "0",
                              "-c", "copy", "-f", "null", "-"], capture_output=True, text=True, errors="replace",
                             creationflags=no_window)
        err = res.stderr or ""
        if res.returncode != 0:
            return False, f"no se puede leer completo ({err.strip()[-200:]})"
        info = parse_media_info(err, os.path.getsize(path))
        if not info["codec"]:
            return False, "no tiene video"
        if info["audio_streams"] < n_audio:
            return False, f"le faltan pistas de audio ({info['audio_streams']} de {n_audio})"
        read = last_frames(err)
        if frames_written and read is not None and abs(read - frames_written) > 2:
            return False, f"tiene {read} cuadros de {frames_written}"
        return True, ""

    def post_process_session(self, video_path: str, audio_info: dict, options: dict) -> Dict[str, Any]:
        """Une video y audio en el MP4 final (alineados) y, si se pide (`video_args`), comprime
        el video en el mismo paso. Se escribe a un «.part»; solo si se verifica completo pasa a
        ser el MP4 y se borran los originales. Si comprimir falla, va lento o no ahorra espacio,
        se guarda como siempre (copiando el video). Opciones nuevas:
          video_args: argumentos del codificador (None: copiar, como siempre)
          progress(paso, fracción, velocidad, segundos_restantes): avance para la barra de guardado
          timestamp: hora de la toma para el nombre (al recuperar una toma, la original)"""
        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path):
            return {"success": False, "error": "ffmpeg_missing", "message": "FFmpeg no encontrado."}

        out_dir = options.get("output_dir", os.path.join(os.path.expanduser("~"), "Videos", "GalaxyCam"))
        os.makedirs(out_dir, exist_ok=True)
        report = options.get("progress")

        def step(name, frac=None, speed=None, eta=None):
            if report:
                try:
                    report(name, frac, speed, eta)
                except Exception:
                    pass

        prefix = options.get("prefix", "UltraCam_Session")
        timestamp = options.get("timestamp") or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        res_tag = options.get("resolution_tag", "4K")
        final_filename = f"{prefix}_{timestamp}_{res_tag}.mp4"
        final_mp4_path = os.path.join(out_dir, final_filename)

        master_wav = audio_info.get("master_wav")
        channel_tracks = [(t.get("wav"), t.get("name") or f"Pista {i}")
                          for i, t in enumerate(audio_info.get("tracks") or [], 1)]
        if not channel_tracks:
            channel_tracks = [(audio_info.get("system_wav"), "Audio del Sistema (Salida General)"),
                              (audio_info.get("in1_wav") or audio_info.get("mic_wav"), "Entrada 1"),
                              (audio_info.get("in2_wav"), "Entrada 2")]
        channel_tracks = [(w, n) for w, n in channel_tracks if w]

        embed_multitrack = options.get("embed_multitrack", True)
        normalize = options.get("normalize", "ebu_r128")
        sync_offset_ms = options.get("sync_offset_ms", 0)
        export_stems = options.get("export_stems", False)

        # Alineación: primero por el sonido (pista guía del teléfono); si no hay o no es confiable,
        # por las horas de inicio (audio_start − video_start, en el mismo reloj). Más el ajuste manual.
        offset = float(options.get("av_offset_s") or 0.0)
        video_shift, drift = 0.0, 0.0
        refs = [w for w in [master_wav] + [w for w, _ in channel_tracks] if w and os.path.exists(w)]
        if options.get("guide_sync", True) and refs:
            step("sync")
        sync = (self._guide_sync(video_path, refs, options.get("phone_serial"))
                if options.get("guide_sync", True) and refs else None)
        if sync:
            video_shift = sync["video_start"]        # el .mkv empieza con la pista guía: el video, un poco después
            if sync["offset"] is not None:
                offset, drift = sync["offset"], sync["drift"]
                self.log(f"Sincronía por pista guía: audio {offset:+.3f} s, deriva {drift * 1e6:+.0f} ppm "
                         f"(calidad {sync['psr']:.0f}, referencia {os.path.basename(sync['ref'])})", "REC")
            else:
                self.log("La pista guía no coincidió con el audio del PC; se alinea por las horas de inicio.", "WARN")
        offset += sync_offset_ms / 1000.0
        # La deriva solo se corrige si llega a notarse en la toma (más de 10 ms entre inicio y final).
        drift_filter = None
        if abs(drift) * float(audio_info.get("duration") or 0.0) > 0.010 and master_wav and os.path.exists(master_wav):
            sr = self._wav_rate(master_wav)
            drift_filter = f"asetrate={round(sr * (1 + drift))},aresample={sr}"
        cmd = [self.ffmpeg_path, "-y"]
        if video_shift > 0.0005:
            cmd.extend(["-itsoffset", f"{-video_shift:.3f}"])
        cmd.extend(["-i", video_path])

        audio_tracks_to_add = []
        if master_wav and os.path.exists(master_wav):
            audio_tracks_to_add.append((master_wav, "Mezcla Master (Stereo)"))

        if embed_multitrack:
            for wav, title in channel_tracks:
                if os.path.exists(wav):
                    audio_tracks_to_add.append((wav, title))

        for wav, _ in audio_tracks_to_add:
            if offset > 0.0005:
                cmd.extend(["-itsoffset", f"{offset:.3f}"])   # el audio empezó después: se retrasa
            elif offset < -0.0005:
                cmd.extend(["-ss", f"{-offset:.3f}"])         # empezó antes: se recorta su comienzo
            cmd.extend(["-i", wav])

        maps = ["-map", "0:v:0"]
        for i, (_, title) in enumerate(audio_tracks_to_add, start=1):
            maps.extend(["-map", f"{i}:a:0", f"-metadata:s:a:{i-1}", f"title={title}"])

        # La normalización es para publicar: va solo en la mezcla final (pista 1). Las pistas por
        # canal quedan tal cual para editar; además, loudnorm sobre una pista en silencio hacía
        # fallar al codificador AAC y se perdía la toma entera.
        norm_filter = {"ebu_r128": "loudnorm=I=-14:TP=-1.0:LRA=11",
                       "peak": "alimiter=limit=0.891:level=disabled"}.get(normalize)   # techo de −1 dBFS
        has_master = bool(audio_tracks_to_add) and audio_tracks_to_add[0][0] == master_wav
        part_path = final_mp4_path + ".part"

        def build(video_args, with_norm):
            """Mismo comando de siempre; comprimir solo cambia «-c:v copy» por el codificador.
            Las marcas de tiempo pasan tal cual (passthrough): la sincronía no cambia."""
            c = list(cmd)
            if video_args:
                c[2:2] = ["-hwaccel", "auto"]          # decodifica con la GPU si puede (va antes del video)
            c += maps
            if video_args:
                c += list(video_args) + ["-fps_mode", "passthrough", "-enc_time_base", "demux"]
            else:
                c += ["-c:v", "copy"]
            c += ["-c:a", "aac", "-b:a", "320k", "-ar", "48000"]
            for i in range(len(audio_tracks_to_add)):
                chain = [drift_filter] if drift_filter else []
                if with_norm and i == 0 and norm_filter and has_master:
                    chain.append(norm_filter)
                if chain:
                    c += [f"-filter:a:{i}", ",".join(chain)]
            return c + ["-f", "mp4", part_path]

        def drop_part():
            try:
                if os.path.exists(part_path):
                    os.remove(part_path)               # nada de MP4 a medias en la carpeta
            except OSError:
                pass

        src = options.get("source_info") or {}
        duration = src.get("duration") or audio_info.get("duration")
        src_size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
        video_args = list(options.get("video_args") or []) or None
        attempts = ([(video_args, True), (video_args, False)] if video_args else []) + [(None, True), (None, False)]

        self.log(f"Multiplexando post-grabación con FFmpeg (audio desplazado {offset:+.3f} s)...", "REC")
        t0 = time.perf_counter()
        tried, ok, res, used_args, compress = [], False, None, None, bool(video_args)
        for vargs, with_norm in attempts:
            c = build(vargs, with_norm)
            if c in tried or (vargs and not compress):
                continue
            tried.append(c)
            name = "encode" if vargs else "join"
            step(name, 0.0)
            res = self._run_export(c, (lambda f, s, e, n=name: step(n, f, s, e)) if report else None,
                                   duration, options.get("min_speed", 0.8) if vargs else None)
            if res["slow"]:
                self.log("Comprimir iba más lento que la toma: se guarda sin comprimir.", "WARN")
                compress = False
                drop_part()
                continue
            if res["returncode"] != 0:
                if with_norm and norm_filter:
                    # Sin normalizar, antes que perder la toma.
                    self.log(f"La normalización falló; se guarda sin normalizar. {res['stderr'][-600:]}", "WARN")
                elif vargs:
                    self.log(f"No se pudo comprimir; se guarda sin comprimir. {res['stderr'][-600:]}", "WARN")
                    compress = False
                drop_part()
                continue
            step("verify")
            good, why = self._verify_export(part_path, len(audio_tracks_to_add), res.get("frames"))
            if good and vargs and src_size and os.path.exists(part_path) and os.path.getsize(part_path) >= 0.9 * src_size:
                good, why = False, "comprimido no ahorraba espacio"
            if good:
                ok, used_args = True, vargs
                break
            self.log(f"El archivo final no pasó la verificación ({why}).", "WARN")
            drop_part()
            if vargs:
                compress = False
            else:
                break
        t_duration = round(time.perf_counter() - t0, 2)

        if not ok:
            # El final del error es lo que explica el fallo (el principio es la versión de ffmpeg).
            msg = res["stderr"] if res else "No se intentó unir"
            self.log(f"Error en multiplexado FFmpeg: {msg[-1500:]}", "ERROR")
            drop_part()
            return {"success": False, "error": "ffmpeg_failed", "message": msg}

        if os.path.exists(part_path):
            os.replace(part_path, final_mp4_path)
        file_size_mb = round(os.path.getsize(final_mp4_path) / (1024 * 1024), 2) if os.path.exists(final_mp4_path) else 0.0
        how = f"comprimido con {used_args[1]}" if used_args else "sin recomprimir"
        self.log(f"✅ Video exportado con éxito en {t_duration}s ({how}): {final_mp4_path} ({file_size_mb} MB)", "REC")
        step("done", 1.0)

        stems_dir = None
        if export_stems and channel_tracks:
            stems_dir = os.path.join(out_dir, f"{prefix}_{timestamp}_stems")
            os.makedirs(stems_dir, exist_ok=True)
            try:
                if master_wav and os.path.exists(master_wav):
                    shutil.copy2(master_wav, os.path.join(stems_dir, "00_Mezcla_Master.wav"))
                for i, (wav, title) in enumerate(channel_tracks, 1):
                    if os.path.exists(wav):
                        safe = re.sub(r'[\\/*?:"<>|]', "_", title).strip().replace(" ", "_")
                        shutil.copy2(wav, os.path.join(stems_dir, f"{i:02d}_{safe}.wav"))
                self.log(f"📁 Stems WAV exportados en: {stems_dir}", "REC")
            except Exception as e:
                self.log(f"Error copiando stems: {e}", "WARN")

        if options.get("reveal_in_explorer", True):
            try:
                subprocess.Popen(["explorer.exe", f"/select,{os.path.normpath(final_mp4_path)}"])
            except Exception:
                pass

        if options.get("auto_play", False):
            try:
                os.startfile(final_mp4_path)
            except Exception:
                pass

        for tmp_file in [video_path, master_wav] + [w for w, _ in channel_tracks]:
            if tmp_file and os.path.exists(tmp_file) and tmp_file != final_mp4_path:
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

        return {
            "success": True,
            "final_path": final_mp4_path,
            "file_size_mb": file_size_mb,
            "render_time_s": t_duration,
            "compressed": bool(used_args),
            "original_size_mb": round(src_size / (1024 * 1024), 2),
            "stems_dir": stems_dir,
            "tracks": [{"name": title} for wav, title in audio_tracks_to_add if wav != master_wav],
            "message": f"Video renderizado exitosamente en {t_duration}s"
        }

    def finalize_recording(self, video_path: str, audio_info: dict, options: dict) -> Dict[str, Any]:
        """Alias para post_process_session para garantizar compatibilidad con tests."""
        return self.post_process_session(video_path, audio_info, options)

    def generate_ai_report(self, user_notes: str, active_config: Optional[dict] = None) -> Dict[str, Any]:
        active_serial = active_config.get("serial") if active_config else (
            list(self.last_device_states.keys())[0] if self.last_device_states else None)
        dev_info_raw = self.cached_device_info.get(active_serial, {}) if active_serial else {}

        dev_info = {
            "platform": self.active_platform,
            "serial": active_serial,
            "brand": dev_info_raw.get("brand", "Desconocido"),
            "model": dev_info_raw.get("friendly_name", dev_info_raw.get("model", "Desconocido")),
            "android_version": dev_info_raw.get("android_version", "Desconocida"),
            "battery": self.cached_battery.get(active_serial) if active_serial else None,
            "cable_benchmark": self.last_benchmark_result
        }
        env_paths = {
            "scrcpy_path": self.scrcpy_path,
            "adb_path": self.adb_path,
            "ffmpeg_path": self.ffmpeg_path
        }
        return ReportService.generate_ai_report(
            user_notes=user_notes,
            active_config=active_config,
            env_paths=env_paths,
            device_info=dev_info,
            log_trace=GLOBAL_LOGGER.get_recent_logs()
        )

    def save_problem_report(self, user_notes: str, active_config: Optional[dict] = None) -> Dict[str, Any]:
        report = self.generate_ai_report(user_notes, active_config)
        return ReportService.save_problem_report(report)
