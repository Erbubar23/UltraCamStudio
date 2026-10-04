"""
UltraCam Studio - Una transmisión en curso: repartidor + sonido + codificador + destinos.

    cámara virtual «UltraCam» ─┐
    mezcla del mezclador (pipe) ┴─ ffmpeg (1 codificador por orientación) ─► MediaMTX local
                                                         «horizontal» / «vertical»
                                                         ├─ d_<id> ─► YouTube     (cada destino
                                                         ├─ d_<id> ─► Twitch …     se enciende y
                                                         └─ d_<id> ─► TikTok       apaga solo)
Cada destino es su propia ruta en MediaMTX: encender o apagar uno no corta a los demás ni
al codificador. El codificador arranca con el primer destino y se detiene con el último
(eso lo decide el módulo). No depende de la interfaz: avisa por callbacks.
"""

import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from infrastructure.system.process_utils import GLOBAL_PROCESS_MANAGER, bind_to_app
from modules.streaming.encoder import build_command
from modules.streaming.mediamtx import MediaMtx
from modules.streaming.planner import Plan
from winpipes import unique_name


@dataclass
class Target:
    did: str
    name: str
    url: str                 # servidor#clave
    vertical: bool


def relay_path(did: str) -> str:
    return "d_" + "".join(ch for ch in did if ch.isalnum())


class LiveSession:
    def __init__(self, ffmpeg: str, mediamtx_exe: str, log: Callable[[str, str], None],
                 on_end: Optional[Callable[[str], None]] = None):
        self.ffmpeg = ffmpeg
        self.mtx = MediaMtx(mediamtx_exe, log=self._log)
        self.log = log
        self.on_end = on_end
        self.proc: Optional[subprocess.Popen] = None
        self.targets: Dict[str, Target] = {}
        self.since: Dict[str, float] = {}
        self.outputs = set()                      # "horizontal" / "vertical" que produce el codificador
        self.started_at: Optional[float] = None
        self._secrets: List[str] = []
        self._stopping = False
        self._stop_feed: Optional[Callable[[], None]] = None

    def _log(self, msg: str, cat: str = "LIVE"):
        for s in self._secrets:                  # una clave nunca va al registro
            if s:
                msg = msg.replace(s, "•••")
        self.log(msg, cat)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    # ------------------------------------------------------------ codificador
    def open(self, plan: Plan, encoder: str, video_device: str, sample_rate: int, horizontal: bool, vertical: bool,
             start_feed: Callable[[str], None], stop_feed: Callable[[], None], audio_delay_ms: int = 0,
             video_input=None, audio_input=None) -> bool:
        """Arranca el repartidor y el codificador (sin destinos todavía)."""
        if not self.mtx.start():
            return False
        self.outputs = {o for o, on in (("horizontal", horizontal and plan.h), ("vertical", vertical and plan.v)) if on}
        for path in self.outputs:
            if not self.mtx.add_path(path, []):
                self._log(f"No se pudo preparar la salida {path}.", "ERROR")
                self.close()
                return False
        pipe = unique_name("live_audio")
        if audio_input is None:
            start_feed(pipe)
            self._stop_feed = stop_feed
        h = (plan.h.width, plan.h.height, plan.h.fps, plan.h.kbps) if "horizontal" in self.outputs else None
        v = (plan.v.width, plan.v.height, plan.v.fps, plan.v.kbps) if "vertical" in self.outputs else None
        cmd = build_command(self.ffmpeg, video_device, pipe, sample_rate, encoder, h, v,
                            self.mtx.publish_url("horizontal") if h else None,
                            self.mtx.publish_url("vertical") if v else None, audio_delay_ms,
                            video_input=video_input, audio_input=audio_input)
        self._log(f"Transmisión: codificador {encoder}, salidas {sorted(self.outputs)}", "LIVE")
        self.proc = bind_to_app(subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.PIPE, text=True, errors="replace",
                                                 creationflags=0x08000000))
        self.started_at = time.time()
        self._stopping = False
        threading.Thread(target=self._watch, daemon=True).start()
        return True

    def _watch(self):
        proc = self.proc
        tail = []
        for line in proc.stderr:
            tail = (tail + [line.strip()])[-20:]
        code = proc.wait()
        if not self._stopping:
            self._log(f"El codificador de la transmisión se detuvo ({code}): {' | '.join(tail[-3:])}", "ERROR")
            self.close()
            if self.on_end:
                self.on_end("error")

    # --------------------------------------------------------------- destinos
    def add(self, target: Target, key: str = "") -> bool:
        """Enciende un destino (su ruta toma el video ya codificado de su orientación)."""
        source = "vertical" if target.vertical else "horizontal"
        if source not in self.outputs:
            return False
        if key:
            self._secrets.append(key)
        ok = self.mtx.add_relay(relay_path(target.did), source, target.url)
        if ok:
            self.targets[target.did] = target
            self.since[target.did] = time.time()
            self._log(f"Transmisión › encendido «{target.name}»", "LIVE")
        return ok

    def remove(self, did: str) -> bool:
        tg = self.targets.pop(did, None)
        self.since.pop(did, None)
        if tg is None:
            return False
        self._log(f"Transmisión › apagado «{tg.name}»", "LIVE")
        return self.mtx.remove_relay(relay_path(did))

    def start(self, targets: List[Target], plan: Plan, encoder: str, video_device: str, sample_rate: int,
              start_feed: Callable[[str], None], stop_feed: Callable[[], None], audio_delay_ms: int = 0,
              keys: Optional[List[str]] = None, video_input=None, audio_input=None) -> bool:
        """Atajo: abre el codificador y enciende todos los destinos."""
        self._secrets = [k for k in (keys or []) if k]
        if not self.open(plan, encoder, video_device, sample_rate, any(not tg.vertical for tg in targets),
                         any(tg.vertical for tg in targets), start_feed, stop_feed, audio_delay_ms,
                         video_input=video_input, audio_input=audio_input):
            return False
        return all(self.add(tg) for tg in targets)

    def state_of(self, did: str) -> Dict:
        if did not in self.targets or not self.running:
            return {"state": "off", "detail": "", "elapsed": 0}
        st = self.mtx.status(relay_path(did), 1)
        return {"state": st.state, "detail": st.detail, "elapsed": time.time() - self.since.get(did, time.time())}

    def status(self) -> List[Dict]:
        """Estado de cada destino encendido: {id, name, state (connecting|live|error), detail}."""
        return [dict(self.state_of(did), id=did, name=tg.name) for did, tg in self.targets.items()]

    def elapsed(self) -> float:
        return time.time() - self.started_at if self.started_at and self.running else 0.0

    def close(self):
        self._stopping = True
        p = self.proc
        self.proc = None
        if p is not None and p.poll() is None:
            GLOBAL_PROCESS_MANAGER.kill_process_tree(p)
        if self._stop_feed:
            try:
                self._stop_feed()
            except Exception:
                pass
            self._stop_feed = None
        self.mtx.stop()
        self.targets.clear()
        self.since.clear()
        self.started_at = None

    stop = close
