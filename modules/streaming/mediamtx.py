"""
UltraCam Studio - El repartidor de la transmisión (MediaMTX).

El codificador de UltraCam publica una sola vez en este servidor local (127.0.0.1); MediaMTX
reenvía ese video ya codificado a cada plataforma (`forward`). Probado: si un destino se cae,
los demás siguen sin cortes y MediaMTX lo reintenta cada ~5 s hasta que vuelve.

- La configuración en disco no tiene claves: los destinos se cargan por su API local y solo
  viven en memoria. MediaMTX tampoco escribe la clave en su registro («servidor#clave»).
- El estado de cada destino sale de su registro: «[RTMP dest N …] forwarding to» (conectando)
  y «ERR … [RTMP dest N …]» (reintentando).
"""

import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

from infrastructure.system.process_utils import bind_to_app

CONFIG = """logLevel: info
logDestinations: [stdout]
rtsp: no
hls: no
webrtc: no
srt: no
moq: no
playback: no
metrics: no
pprof: no
rtmp: yes
rtmpAddress: 127.0.0.1:{rtmp}
api: yes
apiAddress: 127.0.0.1:{api}
paths: {{}}
"""
LINE = re.compile(r"\b(INF|WAR|ERR)\b.*\[path (\w+)\] \[RTMP dest (\d+)[^\]]*\]\s*(.*)")
LIVE_AFTER_S = 4.0               # «conectando» sin errores durante este tiempo = en vivo


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def parse_line(line: str) -> Optional[Tuple[str, int, str, str]]:
    """(ruta, número de destino 1.., "connecting" | "error", detalle) o None."""
    m = LINE.search(line)
    if not m:
        return None
    level, path, idx, msg = m.groups()
    if level == "ERR" or level == "WAR":
        return path, int(idx), "error", msg.strip()
    if "forwarding to" in msg:
        return path, int(idx), "connecting", ""
    return None


class DestState:
    def __init__(self):
        self.state = "connecting"         # connecting | live | error
        self.since = time.monotonic()
        self.detail = ""


class MediaMtx:
    def __init__(self, exe: str, log: Callable[[str, str], None] = None):
        self.exe = exe
        self.log = log or (lambda m, c="LIVE": None)
        self.proc: Optional[subprocess.Popen] = None
        self.rtmp_port = self.api_port = 0
        self.dir = None
        self.states: Dict[Tuple[str, int], DestState] = {}
        self.lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, timeout: float = 8.0) -> bool:
        self.rtmp_port, self.api_port = free_port(), free_port()
        self.dir = tempfile.mkdtemp(prefix="ultracam_live_")
        cfg = os.path.join(self.dir, "mediamtx.yml")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(CONFIG.format(rtmp=self.rtmp_port, api=self.api_port))
        no_window = 0x08000000 if os.name == "nt" else 0
        self.proc = bind_to_app(subprocess.Popen([self.exe, cfg], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                 text=True, errors="replace", creationflags=no_window))
        threading.Thread(target=self._read_log, daemon=True).start()
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self._api("GET", "/v3/paths/list") is not None:
                return True
            if not self.running:
                break
            time.sleep(0.2)
        self.log("El repartidor de la transmisión (MediaMTX) no arrancó.", "ERROR")
        self.stop()
        return False

    def publish_url(self, path: str) -> str:
        return f"rtmp://127.0.0.1:{self.rtmp_port}/{path}"

    def add_path(self, path: str, dest_urls: List[str]) -> bool:
        """Crea la ruta con sus destinos (orden = número de destino 1, 2, …)."""
        with self.lock:
            for i in range(1, len(dest_urls) + 1):
                self.states[(path, i)] = DestState()
        body = {"forward": [{"dest": u} for u in dest_urls]}
        return self._api("POST", f"/v3/config/paths/add/{path}", body) is not None

    def add_relay(self, path: str, source_path: str, dest_url: str) -> bool:
        """Un destino independiente: su propia ruta toma el video ya codificado de `source_path`
        y lo reenvía. Encenderlo o apagarlo no toca a los demás ni al codificador (probado)."""
        with self.lock:
            self.states[(path, 1)] = DestState()
        body = {"source": self.publish_url(source_path), "forward": [{"dest": dest_url}]}
        return self._api("POST", f"/v3/config/paths/add/{path}", body) is not None

    def remove_relay(self, path: str) -> bool:
        with self.lock:
            self.states.pop((path, 1), None)
        return self._api("DELETE", f"/v3/config/paths/delete/{path}") is not None

    def status(self, path: str, index: int) -> DestState:
        with self.lock:
            st = self.states.get((path, index)) or DestState()
            if st.state == "connecting" and time.monotonic() - st.since > LIVE_AFTER_S:
                st.state = "live"
            return st

    def stop(self):
        p = self.proc
        self.proc = None
        if p is not None and p.poll() is None:
            p.kill()
            try:
                p.wait(timeout=3)
            except Exception:
                pass

    # --------------------------------------------------------------- interno
    def _api(self, method: str, url: str, body: Optional[Dict] = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.api_port}{url}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=2) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except Exception:
            return None

    def _read_log(self):
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            ev = parse_line(line)
            if not ev:
                continue
            path, idx, kind, detail = ev
            with self.lock:
                st = self.states.setdefault((path, idx), DestState())
                if kind == "error":
                    st.state, st.detail = "error", detail[:160]
                    st.since = time.monotonic()
                elif st.state != "connecting":
                    st.state, st.since, st.detail = "connecting", time.monotonic(), ""
            if kind == "error":
                self.log(f"Transmisión › destino {idx} ({path}): {detail[:200]}", "LIVE")
