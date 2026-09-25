"""
UltraCam Studio - Enlace con OBS Studio (obs-websocket v5, incluido en OBS 28+)

Cuando el usuario enciende «OBS» en una cámara, UltraCam:
  1. Lee la configuración del servidor WebSocket de OBS (puerto y contraseña) del
     archivo de configuración local de OBS, para no pedírsela al usuario.
  2. Se conecta y crea (o actualiza) en la escena actual una «Fuente multimedia»
     llamada «UltraCam Studio» que recibe el video+audio por red local.
  3. La ajusta al tamaño del lienzo la primera vez.
"""

import os
import json
import subprocess
from typing import Dict, Optional

SOURCE_NAME = "UltraCam Studio"


def ws_config_path() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), "obs-studio", "plugin_config", "obs-websocket", "config.json")


def read_ws_config() -> Dict:
    try:
        with open(ws_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def obs_installed() -> bool:
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        if base and os.path.isfile(os.path.join(base, "obs-studio", "bin", "64bit", "obs64.exe")):
            return True
    return os.path.isdir(os.path.join(os.environ.get("APPDATA", ""), "obs-studio"))


def obs_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH"], capture_output=True, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW, timeout=5).stdout
        return "obs64.exe" in out.lower()
    except Exception:
        return False


class ObsLink:
    def __init__(self, host: str = "127.0.0.1", port: Optional[int] = None, password: Optional[str] = None):
        self.host = host
        self.port = port
        self.password = password

    def _credentials(self):
        cfg = read_ws_config()
        port = self.port or int(cfg.get("server_port", 4455))
        password = self.password
        if password is None and cfg.get("auth_required", True):
            password = cfg.get("server_password") or ""
        return port, password or ""

    def status(self) -> Dict:
        cfg = read_ws_config()
        return {"installed": obs_installed(), "running": obs_running(),
                "ws_enabled": bool(cfg.get("server_enabled", False)), "port": int(cfg.get("server_port", 4455))}

    def _client(self):
        import obsws_python as obs
        port, password = self._credentials()
        return obs.ReqClient(host=self.host, port=port, password=password, timeout=4)

    def ensure_source(self, url: str, name: str = SOURCE_NAME) -> Dict:
        """Crea o actualiza la fuente de UltraCam en la escena actual de OBS.
        Devuelve {"ok": bool, "message": str, "created": bool}."""
        st = self.status()
        if not st["running"]:
            return {"ok": False, "code": "not_running", "message": "OBS no está abierto."}
        if not st["ws_enabled"]:
            return {"ok": False, "code": "ws_disabled",
                    "message": "En OBS activa «Herramientas → Ajustes del servidor WebSocket → Habilitar servidor WebSocket»."}
        try:
            cl = self._client()
        except Exception as e:
            msg = str(e)
            if "auth" in msg.lower() or "4009" in msg:
                return {"ok": False, "code": "auth", "message": "OBS rechazó la contraseña del servidor WebSocket."}
            return {"ok": False, "code": "connect", "message": f"No se pudo conectar con OBS: {msg}"}
        settings = {
            "is_local_file": False, "input": url, "input_format": "mpegts",
            "hw_decode": True, "buffering_mb": 1, "reconnect_delay_sec": 1,
            "restart_on_activate": False, "close_when_inactive": False, "clear_on_media_end": False,
            "looping": False,
        }
        try:
            scene = cl.get_current_program_scene().current_program_scene_name
            existing = {i["inputName"] for i in cl.get_input_list().inputs}
            created = False
            if name in existing:
                cl.set_input_settings(name, settings, True)
                try:
                    cl.get_scene_item_id(scene, name)
                except Exception:
                    cl.create_scene_item(scene, name, True)   # existe en otra escena: agregarla a la actual
            else:
                cl.create_input(scene, name, "ffmpeg_source", settings, True)
                created = True
            if created:
                v = cl.get_video_settings()
                item_id = cl.get_scene_item_id(scene, name).scene_item_id
                cl.set_scene_item_transform(scene, item_id, {
                    "positionX": 0, "positionY": 0, "alignment": 5,
                    "boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsAlignment": 0,
                    "boundsWidth": float(v.base_width), "boundsHeight": float(v.base_height)})
            return {"ok": True, "created": created, "scene": scene,
                    "message": f"Fuente «{name}» {'creada' if created else 'actualizada'} en la escena «{scene}»."}
        except Exception as e:
            return {"ok": False, "code": "request", "message": f"OBS no aceptó la fuente: {e}"}
        finally:
            try:
                cl.disconnect()
            except Exception:
                pass

    def test(self) -> Dict:
        st = self.status()
        if not st["running"]:
            return {"ok": False, "message": "OBS no está abierto."}
        if not st["ws_enabled"]:
            return {"ok": False, "message": "El servidor WebSocket de OBS está desactivado."}
        try:
            cl = self._client()
            ver = cl.get_version()
            cl.disconnect()
            return {"ok": True, "message": f"Conectado a OBS {ver.obs_version} (WebSocket {ver.obs_web_socket_version})."}
        except Exception as e:
            return {"ok": False, "message": f"No se pudo conectar: {e}"}
