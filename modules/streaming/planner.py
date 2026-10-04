"""
UltraCam Studio - La calidad de la transmisión según tu conexión.

Hay un codificador por orientación: todos los destinos horizontales reciben el mismo video
(y los verticales, el suyo). Cada destino es una subida aparte, así que el total es
    video_h × n_horizontales + video_v × n_verticales + audio × n_destinos
y debe caber en el presupuesto del medidor. Se prueba de mejor a menor calidad (la imagen
horizontal primero: es la principal) hasta encontrar lo que cabe, respetando el máximo de
cada plataforma. Si nada cabe, se sugiere quitar destinos o un servicio que reparte por ti.
"""

from dataclasses import dataclass
from typing import Optional

AUDIO_KBPS = 128
# (alto, fps, kbps). La imagen sale de la cámara virtual de UltraCam: 1080p a 30 fps.
H_LADDER = [(1080, 30, 6000), (1080, 30, 4500), (720, 30, 3500), (720, 30, 2500), (720, 30, 1800)]
V_LADDER = [(1280, 30, 4000), (1280, 30, 3000), (1280, 30, 2200), (1280, 30, 1500)]
DEFAULT_BUDGET_KBPS = 12000      # sin medir: algo prudente


@dataclass
class Rung:
    height: int
    fps: int
    kbps: int

    @property
    def width(self) -> int:
        return {1080: 1920, 720: 1280, 1280: 720}[self.height]     # 1280 de alto = vertical 720×1280

    def label(self) -> str:
        return f"{self.width}×{self.height} · {self.fps} fps · {self.kbps / 1000:.1f} Mbps".replace(".", ",")


@dataclass
class Plan:
    h: Optional[Rung]
    v: Optional[Rung]
    n_h: int
    n_v: int
    total_kbps: int
    fits: bool
    relay_kbps: int                  # lo que haría falta con un servicio que reparte por ti


def capacity(budget_kbps: Optional[int]) -> dict:
    """Cuántas plataformas caben a la vez con este presupuesto, por calidad (cada una es una
    subida aparte): {"1080p": n, "720p": n, "vertical": n}."""
    budget = budget_kbps or 0

    def fit(kbps):
        return max(0, int(budget // (kbps + AUDIO_KBPS)))
    return {"1080p": fit(H_LADDER[1][2]), "720p": fit(H_LADDER[3][2]), "vertical": fit(V_LADDER[1][2])}


def plan(budget_kbps: Optional[int], n_h: int, n_v: int, max_h: int = 20000, max_v: int = 20000) -> Plan:
    """Mejor combinación que cabe. max_h / max_v: el menor máximo de las plataformas de cada lado."""
    budget = budget_kbps or DEFAULT_BUDGET_KBPS
    hs = [Rung(*r) for r in H_LADDER if r[2] <= max_h] or [Rung(*H_LADDER[-1])]
    vs = [Rung(*r) for r in V_LADDER if r[2] <= max_v] or [Rung(*V_LADDER[-1])]
    audio = AUDIO_KBPS * (n_h + n_v)

    def total(h, v):
        return (h.kbps if h else 0) * n_h + (v.kbps if v else 0) * n_v + audio

    best = None
    for h in (hs if n_h else [None]):
        for v in (vs if n_v else [None]):
            if total(h, v) <= budget:
                best = (h, v)
                break
        if best:
            break
    fits = best is not None
    h, v = best if fits else ((hs[-1] if n_h else None), (vs[-1] if n_v else None))
    relay = (h.kbps if h else 0) + (v.kbps if v else 0) + AUDIO_KBPS * ((1 if n_h else 0) + (1 if n_v else 0))
    return Plan(h, v, n_h, n_v, total(h, v), fits, relay)
