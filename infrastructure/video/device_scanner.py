"""
Escáner y sondeo de dispositivos de video (Android ADB, DirectShow Webcams, iPhone).
Encapsula la detección de hardware y el parseo de capacidades (SRP).
"""

import os
import sys
import re
import time
import subprocess
import tempfile
from typing import List, Dict, Any, Optional
from core.interfaces import IDeviceScanner
from infrastructure.logging.app_logger import GLOBAL_LOGGER


class DeviceScanner(IDeviceScanner):
    """Implementación de descubrimiento y sondeo de cámaras y dispositivos móviles."""

    def __init__(self, adb_path: Optional[str] = None, ffmpeg_path: Optional[str] = None,
                 scrcpy_path: Optional[str] = None):
        self.adb_path = adb_path
        self.ffmpeg_path = ffmpeg_path
        self.scrcpy_path = scrcpy_path
        self.cached_battery: Dict[str, int] = {}
        self.cached_ip: Dict[str, str] = {}
        self.cached_cameras: Dict[str, List[Dict[str, str]]] = {}
        self.cached_pc_cameras: List[Dict[str, Any]] = []
        self.cached_camera_caps: Dict[str, Dict[str, Any]] = {}
        self.cached_ios_cameras: List[Dict[str, str]] = []
        self.cached_device_info: Dict[str, dict] = {}
        self.last_device_states: Dict[str, str] = {}
        self.adb_problem: Optional[str] = None     # None | "conflict" | "timeout" | "error"
        self._adb_server_ready = False
        self._adb_conflicts: List[float] = []
        self._adb_timeouts = 0

    # Mensajes de adb cuando otro programa (Iriun, DroidCam…) usa otra versión de adb: cada
    # uno cierra el servidor del otro y el teléfono se desconecta una y otra vez.
    ADB_CONFLICT_MARKERS = ("doesn't match this client", "killing", "cannot connect to daemon",
                            "failed to start daemon", "protocol fault")

    def _adb_run(self, args: List[str], timeout: float):
        return subprocess.run([self.adb_path] + args, capture_output=True, text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                              timeout=timeout)

    def _note_adb_problem(self, problem: Optional[str], detail: str = ""):
        """Guarda el problema actual de adb (para que la interfaz lo explique) y lo anota
        en el registro una sola vez, no en cada sondeo."""
        if problem and problem != self.adb_problem:
            GLOBAL_LOGGER.log(f"ADB: {problem}. {detail}".strip(), "WARN", "ADB")
        elif not problem and self.adb_problem:
            GLOBAL_LOGGER.log("ADB vuelve a responder con normalidad.", "INFO", "ADB")
        self.adb_problem = problem

    def scan_adb_devices(self) -> List[Dict[str, Any]]:
        """Enumera dispositivos Android conectados vía ADB."""
        if not self.adb_path or not os.path.exists(self.adb_path):
            return []
        try:
            if not self._adb_server_ready:
                # Arrancar el servidor puede tardar varios segundos la primera vez.
                started = self._adb_run(["start-server"], timeout=20)
                self._adb_server_ready = started.returncode == 0
            res = self._adb_run(["devices", "-l"], timeout=8)
            self._adb_timeouts = 0
            output = (res.stdout or "") + (res.stderr or "")
            now = time.time()
            if any(m in output for m in self.ADB_CONFLICT_MARKERS):
                self._adb_conflicts = [t for t in self._adb_conflicts if now - t < 60] + [now]
            # Un choque suelto al arrancar es normal (queda un servidor viejo de otra
            # herramienta); repetido en menos de un minuto, otro programa lo está peleando.
            recent = [t for t in self._adb_conflicts if now - t < 60]
            self._note_adb_problem("conflict" if len(recent) >= 2 else None, output.strip()[:300])
            devices = []
            for line in res.stdout.strip().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    serial = parts[0]
                    state = parts[1]
                    model = "Dispositivo Android"
                    for p in parts[2:]:
                        if p.startswith("model:"):
                            model = p.split(":", 1)[1].replace("_", " ")
                    devices.append({
                        "serial": serial,
                        "state": state,
                        "model": model,
                        "is_wifi": ":" in serial
                    })
            return devices
        except subprocess.TimeoutExpired:
            self._adb_server_ready = False
            self._adb_timeouts += 1
            if self._adb_timeouts >= 2:
                self._note_adb_problem("timeout", "adb no respondió a tiempo dos veces seguidas.")
            return []
        except Exception as e:
            self._note_adb_problem("error", str(e))
            return []

    @staticmethod
    def other_adb_programs(own_path: Optional[str]) -> List[str]:
        """Programas con su propio adb en marcha (Iriun, DroidCam…), para nombrarlos al avisar."""
        if sys.platform != "win32":
            return []
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]

        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.OpenProcess.restype = wintypes.HANDLE
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
        if not snap or snap == wintypes.HANDLE(-1).value:
            return []
        paths = set()
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == "adb.exe":
                    h = k32.OpenProcess(0x1000, False, entry.th32ProcessID)   # QUERY_LIMITED_INFORMATION
                    if h:
                        buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(len(buf))
                        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                            paths.add(buf.value)
                        k32.CloseHandle(h)
                ok = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        own = os.path.normcase(os.path.abspath(own_path)) if own_path else ""
        names = []
        for p in sorted(paths):
            if os.path.normcase(p) == own:
                continue
            low = p.lower()
            name = ("Iriun Webcam" if "iriun" in low else "DroidCam" if "droidcam" in low
                    else "Android Studio" if "android" in low and "sdk" in low
                    else os.path.basename(os.path.dirname(p)))
            if name not in names:
                names.append(name)
        return names

    def check_device_changes(self, log_pings: bool = False) -> List[Dict[str, Any]]:
        """Detecta cambios de conexión (conexión/desconexión) con debounce de logs."""
        try:
            current_devices = self.scan_adb_devices()
            current_serials = {d["serial"] for d in current_devices}

            for d in current_devices:
                serial = d["serial"]
                state = d["state"]
                prev_state = self.last_device_states.get(serial)

                if prev_state is None:
                    tipo = "Wi-Fi" if d["is_wifi"] else "Cable USB"
                    GLOBAL_LOGGER.log(f"🔌 Dispositivo CONECTADO ({tipo}): {serial} ({d['model']}) | Estado: '{state}'", "USB")
                    self.last_device_states[serial] = state
                    if state == "device":
                        GLOBAL_LOGGER.log(f"✅ Dispositivo listo para transmitir: {serial}", "USB")
                elif prev_state != state:
                    GLOBAL_LOGGER.log(f"⚡ CAMBIO DE ESTADO: {serial} pasó de '{prev_state}' a '{state}'", "STATE")
                    self.last_device_states[serial] = state

            removed_serials = set(self.last_device_states.keys()) - current_serials
            for s in removed_serials:
                GLOBAL_LOGGER.log(f"❌ Dispositivo DESCONECTADO: {s}", "USB")
                self.last_device_states.pop(s, None)
                self.cached_battery.pop(s, None)
                self.cached_ip.pop(s, None)

            if log_pings and current_devices:
                dev = current_devices[0]
                GLOBAL_LOGGER.log(f"Sondeo ADB OK: {dev['serial']} ({dev['state']})", level="DEBUG", category="POLL")

            return current_devices
        except Exception as e:
            GLOBAL_LOGGER.error(f"Error en check_device_changes: {e}", e, "ERROR")
            return []

    def get_device_info(self, serial: str) -> Dict[str, Any]:
        """Obtiene detalles del hardware del dispositivo Android (marca, modelo, versión de Android)."""
        if serial in self.cached_device_info:
            return self.cached_device_info[serial]
        if not self.adb_path:
            return {
                "brand": "Desconocido", "model": "Android", "friendly_name": f"Dispositivo {serial}",
                "android_version": "Desconocida", "camera_supported": True
            }
        try:
            cmd = [
                self.adb_path, "-s", serial, "shell",
                "getprop ro.product.brand; getprop ro.product.model; "
                "getprop ro.build.version.release; getprop ro.product.marketname"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                 timeout=6)
            lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
            brand = lines[0].capitalize() if len(lines) > 0 else "Android"
            model = lines[1] if len(lines) > 1 else f"Dispositivo {serial}"
            version_str = lines[2] if len(lines) > 2 else "12"
            market_name = lines[3] if len(lines) > 3 else ""

            try:
                major_ver = int(re.search(r"\d+", version_str).group())
            except Exception:
                major_ver = 12

            camera_supported = major_ver >= 12
            friendly = market_name or f"{brand} {model}"

            info = {
                "brand": brand,
                "model": model,
                "friendly_name": friendly,
                "android_version": version_str,
                "camera_supported": camera_supported
            }
            self.cached_device_info[serial] = info
            return info
        except Exception:
            return {
                "brand": "Android", "model": f"Dispositivo {serial}",
                "friendly_name": f"Dispositivo {serial}", "android_version": "12+",
                "camera_supported": True
            }

    def get_device_battery(self, serial: str) -> Optional[int]:
        if serial in self.cached_battery:
            return self.cached_battery[serial]
        if not self.adb_path:
            return None
        try:
            res = subprocess.run(
                [self.adb_path, "-s", serial, "shell", "dumpsys", "battery"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                timeout=3
            )
            match = re.search(r"level:\s*(\d+)", res.stdout)
            if match:
                lvl = int(match.group(1))
                self.cached_battery[serial] = lvl
                return lvl
        except Exception:
            pass
        return None

    def scan_dshow_devices(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Descubre todas las fuentes de captura DirectShow reconocidas por Windows."""
        if self.cached_pc_cameras and not force_refresh:
            return self.cached_pc_cameras

        pc_devices = []
        if self.ffmpeg_path and os.path.exists(self.ffmpeg_path):
            try:
                res = subprocess.run(
                    [self.ffmpeg_path, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    timeout=5
                )
                output = res.stderr + res.stdout
                dshow_names = re.findall(r'"([^"]+)"\s*\(video\)', output)

                for name in dshow_names:
                    lower = name.lower()
                    if "cam link" in lower or "hdmi" in lower or "capture" in lower or "evga" in lower:
                        cat = "capture_card"
                        label = f"🎥 {name} (Capturadora HDMI)"
                    elif "obs" in lower or "virtual" in lower or "vcam" in lower or "split" in lower:
                        cat = "virtual"
                        label = f"🪟 {name} (Cámara Virtual)"
                    elif any(w in lower for w in ("iriun", "droidcam", "camo", "epoccam", "apple", "iphone")):
                        cat = "ios"
                        label = f"🍏 {name} (iPhone)"
                    else:
                        cat = "webcam"
                        label = f"📷 {name}"

                    pc_devices.append({
                        "name": name,
                        "category": cat,
                        "label": label,
                        "type": "directshow"
                    })
            except Exception as e:
                GLOBAL_LOGGER.error(f"Error enumerando cámaras DirectShow: {e}", e, "ERROR")

        if not pc_devices:
            pc_devices = [
                {"name": "Webcam Genérica", "category": "webcam", "label": "📷 Webcam Genérica (DirectShow)", "type": "directshow"}
            ]

        self.cached_pc_cameras = pc_devices
        return pc_devices

    def probe_capabilities(self, device_name: str, force_refresh: bool = False) -> Dict[str, Any]:
        """Sondea resoluciones nativas, framerates y formatos de pixel soportados por una webcam."""
        if not force_refresh and device_name in self.cached_camera_caps:
            return self.cached_camera_caps[device_name]

        caps = {
            "resolutions": ["1920x1080", "1280x720", "640x480"],
            "framerates": [60, 30, 24],
            "has_mjpeg": False,
            "best_pixel_format": "yuyv422",
            "default_res": "1920x1080",
            "default_fps": 30
        }

        if not self.ffmpeg_path or not os.path.exists(self.ffmpeg_path) or not device_name:
            return caps

        try:
            res = subprocess.run(
                [self.ffmpeg_path, "-list_options", "true", "-f", "dshow", "-i", f"video={device_name}"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                timeout=6
            )
            output = res.stderr + res.stdout
            sizes = re.findall(r'(?:max\s+s=|min\s+s=)(\d+x\d+)', output)
            fpss = re.findall(r'fps=(\d+(?:\.\d+)?)', output)
            has_mjpeg = "mjpeg" in output.lower()

            if sizes:
                def _area(s):
                    try:
                        w, h = s.split('x')
                        return int(w) * int(h)
                    except Exception:
                        return 0
                unique_sizes = sorted(list(set(sizes)), key=_area, reverse=True)
                caps["resolutions"] = unique_sizes
                caps["default_res"] = unique_sizes[0]

            if fpss:
                unique_fps = sorted(list(set(int(float(f)) for f in fpss if float(f) >= 15)), reverse=True)
                if unique_fps:
                    caps["framerates"] = unique_fps
                    caps["default_fps"] = 60 if 60 in unique_fps else unique_fps[0]

            caps["has_mjpeg"] = has_mjpeg
            caps["vcodec"] = "mjpeg" if has_mjpeg else None
            caps["pixel_format"] = None if has_mjpeg else "yuyv422"
            caps["best_pixel_format"] = "mjpeg" if has_mjpeg else "yuyv422"

        except Exception as e:
            GLOBAL_LOGGER.log(f"Aviso al sondear capacidades de '{device_name}': {e}", "WARN")

        self.cached_camera_caps[device_name] = caps
        return caps

    def benchmark_cable(self, serial: Optional[str] = None, size_mb: int = 3) -> Dict[str, Any]:
        """Realiza benchmark de velocidad USB para alertar sobre cables 2.0 lentos (E2)."""
        if not self.adb_path or not os.path.exists(self.adb_path):
            return {"success": False, "error": "adb_missing", "message": "ADB no encontrado."}

        GLOBAL_LOGGER.log(f"Probando velocidad del cable ({size_mb} MB)...", "BENCHMARK")
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(temp_dir, "galaxy_speed_test.bin")
        file_bytes = size_mb * 1024 * 1024

        try:
            with open(temp_file, "wb") as f:
                f.write(os.urandom(file_bytes))

            target_path = "/data/local/tmp/galaxy_speed_test.bin"
            cmd = [self.adb_path]
            if serial:
                cmd.extend(["-s", serial])
            cmd.extend(["push", temp_file, target_path])

            t0 = time.time()
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                 timeout=15)
            dt = time.time() - t0

            try:
                os.remove(temp_file)
                clean_cmd = [self.adb_path]
                if serial:
                    clean_cmd.extend(["-s", serial])
                clean_cmd.extend(["shell", "rm", "-f", target_path])
                subprocess.run(clean_cmd, capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                               timeout=5)
            except Exception:
                pass

            if res.returncode != 0:
                return {"success": False, "error": "push_failed", "message": f"Fallo al transferir datos: {res.stderr}"}

            full_out = (res.stdout or "") + " " + (res.stderr or "")
            speed_match = re.search(r"(\d+(?:\.\d+)?)\s*MB/s", full_out)
            if speed_match:
                speed_mb_s = float(speed_match.group(1))
            else:
                speed_mb_s = round(size_mb / dt, 1) if dt > 0 else 999.0

            if speed_mb_s < 8.0:
                classification = "USB 1.1 / Cable Lento"
                max_res = "720p HD (1280x720)"
                rec = "Usa 720p o conecta por Wi-Fi."
            elif speed_mb_s < 20.0:
                classification = "USB 2.0 (Estándar)"
                max_res = "1080p FHD (1920x1080)"
                rec = "Recomendado 1080p. 4K podría experimentar cortes."
            else:
                classification = "USB 3.0 / SuperSpeed"
                max_res = "4K UHD (3840x2160)"
                rec = "Óptimo para 4K 60fps sin pérdidas."

            return {
                "success": True,
                "speed_mb_s": speed_mb_s,
                "duration_s": round(dt, 2),
                "classification": classification,
                "max_res": max_res,
                "recommendation": rec
            }
        except Exception as e:
            return {"success": False, "error": str(e), "message": f"Error en benchmark: {e}"}
