"""
UltraCam Studio - Qué codificador usa el archivo final (exportación comprimida).

Al terminar una toma, el mismo paso que hoy une video y audio puede comprimir el video en
vez de copiarlo. Se usa lo que tenga la PC, en este orden:

    GPU NVIDIA (NVENC) → gráficos Intel (Quick Sync) → GPU/APU AMD (AMF) → CPU (solo hasta 1080p)

Con solo CPU, una toma 4K tardaría el doble de su duración (medido: 0,5× en un Ryzen 7):
entonces se guarda como siempre, copiando el video. El formato del video no cambia
(HEVC sigue siendo HEVC, H.264 sigue siendo H.264) para no cambiar la compatibilidad.

Calidad medida con VMAF (≥ 95 no se distingue a simple vista): NVENC 4K ≈ 20 Mbps → 98;
1080p ≈ 5,5 Mbps → 96,7; CPU x265 1080p → 95. Ver docs del plan en la memoria del proyecto.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

HW_ORDER = ("nvenc", "qsv", "amf")
CPU_MAX_HEIGHT = 1080           # por encima, la CPU es más lenta que la duración de la toma

# Si el video ya pesa poco, comprimirlo ahorra poco y cuesta una generación de calidad.
# Bitrate típico del resultado (Mbps, HEVC) por altura; H.264 necesita ~1,6× más.
TYPICAL_HEVC_MBPS = ((2160, 20.0), (1440, 11.0), (1080, 6.0), (720, 3.0), (0, 2.0))
H264_FACTOR = 1.6
WORTH_IT = 1.4                  # comprimir solo si el original pesa al menos 1,4× el resultado típico


@dataclass(frozen=True)
class EncoderChoice:
    name: str                   # "hevc_nvenc", "libx264"…
    args: List[str]             # argumentos de video para ffmpeg (desde -c:v)
    label: str                  # para mostrar: «GPU NVIDIA», «CPU»…
    hardware: bool


def family(codec: Optional[str]) -> str:
    """"hevc" o "h264" (lo que no se reconoce se trata como H.264, el más compatible)."""
    c = (codec or "").lower()
    return "hevc" if c in ("hevc", "h265") else "h264"


def _max_rate(height: int, fam: str) -> int:
    base = 45 if height >= 2160 else 25 if height >= 1440 else 16 if height >= 1080 else 8
    return int(base * (H264_FACTOR if fam == "h264" else 1.0))


def profile(name: str, height: int) -> List[str]:
    """Argumentos de cada codificador, calibrados para una calidad casi idéntica al original."""
    fam = "hevc" if name.startswith(("hevc", "libx265")) else "h264"
    tag = ["-tag:v", "hvc1"] if fam == "hevc" else []          # QuickTime / iPhone abren el MP4
    m = _max_rate(height, fam)
    if name.endswith("_nvenc"):
        return ["-c:v", name, "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "26" if fam == "hevc" else "23",
                "-b:v", "0", "-maxrate", f"{m}M", "-bufsize", f"{m * 2}M", "-spatial-aq", "1"] + tag
    if name.endswith("_qsv"):
        return ["-c:v", name, "-preset", "medium", "-global_quality", "25" if fam == "hevc" else "23"] + tag
    if name.endswith("_amf"):
        q = ("24", "26") if fam == "hevc" else ("22", "24")
        return ["-c:v", name, "-quality", "quality", "-rc", "cqp", "-qp_i", q[0], "-qp_p", q[1]] + tag
    if name == "libx265":
        return ["-c:v", "libx265", "-preset", "superfast", "-crf", "21", "-x265-params", "log-level=error"] + tag
    if name == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"]
    raise ValueError(name)


LABELS = {"nvenc": "GPU NVIDIA", "qsv": "gráficos Intel", "amf": "GPU AMD"}


def candidates(fam: str) -> List[str]:
    """Codificadores por hardware a probar para una familia, en orden de preferencia."""
    return [f"{fam}_{hw}" for hw in HW_ORDER]


def typical_mbps(height: int, fam: str) -> float:
    mbps = next(v for h, v in TYPICAL_HEVC_MBPS if height >= h)
    return mbps * (H264_FACTOR if fam == "h264" else 1.0)


def worth_compressing(bitrate_bps: Optional[float], height: int, fam: str) -> bool:
    """False si el video ya pesa cerca de lo que pesaría comprimido (no vale la pena)."""
    if not bitrate_bps:
        return True
    return bitrate_bps / 1e6 >= typical_mbps(height, fam) * WORTH_IT


def choose(codec: Optional[str], height: int, available: Iterable[str],
           bitrate_bps: Optional[float] = None) -> Optional[EncoderChoice]:
    """El codificador para el archivo final, o None para copiar el video como siempre.
    `available`: codificadores que funcionaron en esta PC (ver probe_available)."""
    fam = family(codec)
    if not height or not worth_compressing(bitrate_bps, height, fam):
        return None
    avail = set(available)
    for name in candidates(fam):
        if name in avail:
            return EncoderChoice(name, profile(name, height), LABELS[name.split("_")[1]], True)
    if height <= CPU_MAX_HEIGHT:
        name = "libx265" if fam == "hevc" else "libx264"
        if name in avail:
            return EncoderChoice(name, profile(name, height), "CPU", False)
    return None


def probe_available(run, ffmpeg_path: str) -> List[str]:
    """Prueba cada codificador con sus argumentos reales en un clip mínimo; devuelve los que
    funcionan. `run(cmd) -> returncode` (inyectable para las pruebas). Un controlador de video
    viejo o una GPU sin ese bloque falla aquí y no al guardar una toma."""
    found = []
    for fam in ("hevc", "h264"):
        for name in candidates(fam) + ["libx265" if fam == "hevc" else "libx264"]:
            cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                   "-i", "testsrc2=size=1280x720:rate=30", "-frames:v", "5"] + profile(name, 720) + ["-f", "null", "-"]
            try:
                if run(cmd) == 0:
                    found.append(name)
            except Exception:
                continue
    return found


def describe(available: Iterable[str]) -> Dict[str, str]:
    """Para el registro: qué se usará con HEVC y con H.264 en esta PC."""
    out = {}
    for fam in ("hevc", "h264"):
        c4k, c1080 = choose(fam, 2160, available), choose(fam, 1080, available)
        out[fam] = (f"4K: {c4k.label if c4k else 'copia'} · 1080p: {c1080.label if c1080 else 'copia'}")
    return out
