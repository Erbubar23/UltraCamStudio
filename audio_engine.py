"""
UltraCam Studio - Cliente del motor de audio

La interfaz usa esta clase; el trabajo de audio real (dispositivos, VST3, mezcla,
monitor y grabación) ocurre en el proceso de audio_server. Aquí solo se envían
comandos y se reciben eventos (vúmetros, estadísticas, estado de los plugins).
"""

import os
import glob
import uuid
import threading
import itertools
import multiprocessing as mp
from typing import Callable, Dict, List, Optional

import audio_server

DEFAULT_CONFIG = {
    "driver": "wasapi",          # "wasapi" (Windows Audio) | "asio"
    "input_device": None,        # WASAPI: entrada del dispositivo principal
    "output_device": None,       # WASAPI: salida de monitor
    "asio_device": None,         # ASIO: un solo driver para entrada y salida
    "sample_rate": 48000,
    "buffer": 256,
    "monitor_out": [0, 1],
    "master_volume": 1.0,
    "monitor_volume": 1.0,
    "channels": [],
}

CHANNEL_COLORS = ["#6EA8FE", "#B48CF2", "#EC7FB6", "#5FD4B0", "#F2B866", "#8FB8FF", "#E88A6A", "#A3D977"]

VST3_DIRS = [
    os.path.join(os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files"), "VST3"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Common", "VST3"),
]


def new_id(prefix: str = "ch") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def new_channel(name: str, source: Dict, mode: str = "mono", monitor: bool = False, color: Optional[str] = None) -> Dict:
    return {"id": new_id("ch"), "name": name, "source": source, "mode": mode, "volume": 1.0, "mute": False,
            "solo": False, "monitor": monitor, "fx": [], "color": color}


def source_label(src: Dict, cfg: Dict) -> str:
    kind = src.get("kind")
    if kind == "main":
        cols = src.get("ch", [0])
        dev = cfg.get("asio_device") if cfg.get("driver") == "asio" else cfg.get("input_device")
        which = " + ".join(f"Entrada {c + 1}" for c in cols)
        return f"{which} · {dev or 'dispositivo principal'}"
    if kind == "device":
        return f"{src.get('device')}" + (" · Lo que suena" if src.get("loopback") else "")
    return "Sin fuente"


def scan_vst3(extra_dirs: Optional[List[str]] = None) -> List[Dict]:
    """Busca plugins VST3 en las carpetas estándar de Windows y en las que agregue el usuario."""
    found, seen = [], set()
    for d in VST3_DIRS + list(extra_dirs or []):
        if not d or not os.path.isdir(d):
            continue
        for p in glob.glob(os.path.join(d, "**", "*.vst3"), recursive=True):
            # Un .vst3 puede ser una carpeta (bundle) con otro .vst3 adentro: quedarse con el de afuera
            key = os.path.normcase(os.path.abspath(p))
            if any(key.startswith(s + os.sep) for s in seen):
                continue
            seen.add(key)
            found.append({"name": os.path.splitext(os.path.basename(p))[0], "path": p})
    found.sort(key=lambda x: x["name"].lower())
    return found


from core.interfaces import IAudioEngine


class AudioEngine(IAudioEngine):
    def __init__(self):
        self.config: Dict = dict(DEFAULT_CONFIG)
        self.proc: Optional[mp.Process] = None
        self.conn = None
        self.send_lock = threading.Lock()
        self.pending: Dict[int, Dict] = {}
        self.ids = itertools.count(1)
        self.ready = threading.Event()
        self.stats: Dict = {}
        self.devices: Dict = {}
        self.fx_status: Dict[str, List[Dict]] = {}
        self.editor_open: Optional[str] = None
        self.is_recording = False
        # Callbacks de la interfaz (se llaman desde un hilo de fondo)
        self.on_levels: Optional[Callable[[Dict, float, float], None]] = None
        self.on_stats: Optional[Callable[[Dict], None]] = None
        self.on_log: Optional[Callable[[str, str], None]] = None
        self.on_fx: Optional[Callable[[str], None]] = None
        self.on_fx_state: Optional[Callable[[str, str, str], None]] = None
        self.on_editor: Optional[Callable[[str, str, bool], None]] = None

    # ---------------------------------------------------------------- Proceso
    def start(self):
        if self.proc is not None and self.proc.is_alive():
            return
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self.conn = parent
        self.proc = ctx.Process(target=audio_server.main, args=(child,), daemon=True, name="UltraCamAudio")
        self.proc.start()
        threading.Thread(target=self._reader, daemon=True).start()
        self.ready.wait(20)

    def stop(self):
        proc = self.proc
        if proc is None:
            return
        self.proc = None
        try:
            self._send("quit", {})
        except Exception as e:
            self._log(f"Aviso al notificar detención a proceso de audio: {e}", "WARN")
        proc.join(timeout=2)
        if proc.is_alive():
            proc.kill()

    def _log(self, msg, cat="AUDIO"):
        if self.on_log:
            self.on_log(msg, cat)

    def _send(self, cmd: str, args: Dict, wait: bool = False, timeout: float = 15.0) -> Dict:
        if self.conn is None:
            return {"ok": False, "error": "El motor de audio no está iniciado."}
        rid = next(self.ids) if wait else None
        slot = None
        if wait:
            slot = {"ev": threading.Event(), "res": None}
            self.pending[rid] = slot
        try:
            with self.send_lock:
                self.conn.send((cmd, args, rid))
        except Exception as e:
            self.pending.pop(rid, None)
            return {"ok": False, "error": str(e)}
        if not wait:
            return {"ok": True}
        if not slot["ev"].wait(timeout):
            self.pending.pop(rid, None)
            return {"ok": False, "error": "El motor de audio no respondió a tiempo."}
        return slot["res"]

    def _reader(self):
        while True:
            try:
                kind, data = self.conn.recv()
            except (EOFError, OSError):
                if self.proc is None:        # cierre normal
                    break
                self._log("El motor de audio se detuvo.", "ERROR")
                self.stats = {"running": False, "error": "El motor de audio se detuvo."}
                if self.on_stats:
                    self.on_stats(self.stats)
                break
            try:
                self._dispatch(kind, data)
            except Exception as e:
                self._log(f"Evento de audio no procesado: {e}", "WARN")

    def _dispatch(self, kind: str, data: Dict):
        if kind == "reply":
            slot = self.pending.pop(data.pop("rid"), None)
            if slot:
                slot["res"] = data
                slot["ev"].set()
        elif kind == "levels":
            if self.on_levels:
                self.on_levels(data["ch"], data["master"], data["monitor"])
        elif kind == "stats":
            self.stats = data
            if self.on_stats:
                self.on_stats(data)
        elif kind == "log":
            self._log(data["msg"], data.get("cat", "AUDIO"))
        elif kind == "fx_loaded":
            self.fx_status[data["ch"]] = data["fx"]
            if self.on_fx:
                self.on_fx(data["ch"])
        elif kind == "fx_state":
            self._store_fx_state(data["ch"], data["fx"], data["state"])
            if self.on_fx_state:
                self.on_fx_state(data["ch"], data["fx"], data["state"])
        elif kind == "editor":
            self.editor_open = f"{data['ch']}/{data['fx']}" if data["open"] else None
            if self.on_editor:
                self.on_editor(data["ch"], data["fx"], data["open"])
        elif kind == "ready":
            self.ready.set()

    # ------------------------------------------------------------- Consultas
    def list_devices(self) -> Dict:
        res = self._send("devices", {}, wait=True, timeout=30)
        if res.get("ok"):
            self.devices = res["devices"]
        return self.devices

    def refresh_devices(self) -> Dict:
        """Alias de list_devices conforme al contrato IAudioEngine."""
        return self.list_devices()

    # --------------------------------------------------------- Configuración
    def apply(self, config: Optional[Dict] = None, wait: bool = False):
        """Envía la configuración completa: reabre dispositivos y carga los plugins que falten."""
        if config is not None:
            self.config = config
        return self._send("config", {"config": self.config}, wait=wait, timeout=60)

    def apply_config(self, cfg: Dict) -> bool:
        """Alias conforme al contrato IAudioEngine."""
        res = self.apply(cfg, wait=True)
        return bool(res.get("ok"))

    def channel(self, cid: str) -> Optional[Dict]:
        return next((c for c in self.config["channels"] if c["id"] == cid), None)

    def set_param(self, cid: str, key: str, value):
        ch = self.channel(cid)
        if ch is not None:
            ch[key] = value
        self._send("param", {"ch": cid, "key": key, "value": value})

    def set_master(self, master_volume: Optional[float] = None, monitor_volume: Optional[float] = None):
        args = {}
        if master_volume is not None:
            self.config["master_volume"] = args["master_volume"] = float(master_volume)
        if monitor_volume is not None:
            self.config["monitor_volume"] = args["monitor_volume"] = float(monitor_volume)
        self._send("master", args)

    def set_fx(self, cid: str, fx: List[Dict]):
        ch = self.channel(cid)
        if ch is not None:
            ch["fx"] = fx
        self._send("fx", {"ch": cid, "fx": fx})

    def open_editor(self, cid: str, fx_id: str):
        self._send("open_editor", {"ch": cid, "fx": fx_id})

    def close_editor(self):
        self._send("close_editor", {})

    def open_asio_panel(self):
        self._send("asio_panel", {})

    def _store_fx_state(self, cid: str, fx_id: str, state: str):
        ch = self.channel(cid)
        if ch:
            for f in ch["fx"]:
                if f["id"] == fx_id:
                    f["state"] = state

    def collect_fx_states(self):
        """Trae el preset actual de cada plugin (para guardarlo en la configuración)."""
        res = self._send("fx_states", {}, wait=True, timeout=3)
        for cid, per in (res.get("states") or {}).items():
            for fx_id, st in per.items():
                self._store_fx_state(cid, fx_id, st)

    # ------------------------------------------------------------- Grabación
    def start_recording(self, out_dir: str) -> Dict:
        res = self._send("rec_start", {"dir": out_dir}, wait=True)
        self.is_recording = bool(res.get("ok"))
        return res

    def stop_recording(self) -> Dict:
        self.is_recording = False
        res = self._send("rec_stop", {}, wait=True, timeout=30)
        return res if res.get("ok") else {}

    # --------------------------------------------------------- Envío a OBS
    def start_feed(self, pipe_path: str):
        return self._send("feed_start", {"pipe": pipe_path}, wait=True)

    def stop_feed(self):
        return self._send("feed_stop", {}, wait=True)
