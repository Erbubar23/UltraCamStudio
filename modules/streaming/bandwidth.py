"""
UltraCam Studio - Medidor de la velocidad de subida.

Sube datos ~12 s por 4 conexiones a los servidores públicos de prueba de Cloudflare
(speed.cloudflare.com/__up, los que usa su medidor oficial de código abierto). Ookla no se
usa: su licencia prohíbe incluirlo en otras aplicaciones.

Para transmitir importa lo que la conexión aguanta en sus peores momentos, no el promedio:
se toma el percentil 20 de la subida segundo a segundo (sin los primeros segundos, mientras
TCP acelera) y de eso se usa el 70 % como presupuesto seguro.
"""

import http.client
import os
import ssl
import threading
import time
from typing import Callable, Dict, List, Optional

HOST = "speed.cloudflare.com"
SAFE_FRACTION = 0.70
WARMUP_S = 3


def summarize(samples_mbps: List[float]) -> Dict:
    """Mediana, percentil 20 (estable) y presupuesto seguro de una serie de Mbps por segundo."""
    steady = sorted(samples_mbps[WARMUP_S:] or samples_mbps)
    if not steady:
        return {"median": 0.0, "stable": 0.0, "budget_kbps": 0, "samples": samples_mbps}
    median = steady[len(steady) // 2]
    stable = steady[int(len(steady) * 0.2)]
    return {"median": round(median, 1), "stable": round(stable, 1),
            "budget_kbps": int(stable * 1000 * SAFE_FRACTION), "samples": [round(x, 1) for x in samples_mbps]}


def measure(duration: float = 12.0, conns: int = 4, progress: Optional[Callable[[float], None]] = None,
            connect=None) -> Dict:
    """Mide la subida. `connect()` devuelve una conexión HTTP (inyectable en las pruebas)."""
    connect = connect or (lambda: http.client.HTTPSConnection(HOST, timeout=20, context=ssl.create_default_context()))
    chunk = os.urandom(256 * 1024)
    sent = [0]
    lock = threading.Lock()
    stop = time.time() + duration

    def worker():
        while time.time() < stop:
            size = 8 * 1024 * 1024
            c = connect()
            try:
                c.putrequest("POST", "/__up")
                c.putheader("Content-Length", str(size))
                c.putheader("Content-Type", "application/octet-stream")
                c.endheaders()
                n = 0
                while n < size and time.time() < stop:
                    part = chunk[: min(len(chunk), size - n)]
                    c.send(part)
                    n += len(part)
                    with lock:
                        sent[0] += len(part)
                if n >= size:
                    c.getresponse().read()
            except Exception:
                time.sleep(0.2)
            finally:
                c.close()

    latency = None
    try:
        c = connect()
        t0 = time.time()
        c.request("GET", "/__down?bytes=0")
        c.getresponse().read()
        latency = round((time.time() - t0) * 1000)
        c.close()
    except Exception:
        pass
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(conns)]
    for th in threads:
        th.start()
    samples, last, lt, t_start = [], 0, time.time(), time.time()
    while time.time() < stop:
        time.sleep(1)
        with lock:
            s = sent[0]
        now = time.time()
        samples.append((s - last) * 8 / max(0.001, now - lt) / 1e6)
        last, lt = s, now
        if progress:
            progress(min(1.0, (now - t_start) / duration))
    for th in threads:
        th.join(timeout=3)
    out = summarize(samples)
    out["latency_ms"] = latency
    out["time"] = time.time()
    return out
