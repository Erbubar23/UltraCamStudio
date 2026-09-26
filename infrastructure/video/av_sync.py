"""
Alineación de audio por contenido (como la sincronización por forma de onda de los editores).

El .mkv del teléfono trae una pista guía (su micrófono) con el mismo reloj que la imagen.
Se busca dónde aparece ese sonido dentro del audio del PC con correlación cruzada GCC-PHAT:
da el desfase exacto sin depender de cuándo arrancó cada proceso ni del retraso de la cámara.
Midiendo al principio y al final de la toma se obtiene también la deriva entre los dos relojes.

Tiempos: «tiempo de archivo» es el del .mkv con su comienzo en 0 (así lo ve ffmpeg al unir).
"""

import re
import subprocess
import sys
from typing import Callable, List, Optional, Tuple

import numpy as np

FS = 8000                 # suficiente para alinear al 0,125 ms; decodificar y correlacionar es rápido
BAND = (100.0, 3500.0)    # fuera de aquí hay ruido de manejo y soplidos que confunden la búsqueda
WINDOW_S = 40.0
MIN_PSR = 10.0            # pico / ruido: medido, una coincidencia real da 16–20 y una falsa 5–6
PHAT_BETA = 0.6           # blanqueo parcial: con 1.0 las bandas sin señal meten ruido (±10 ms)
LAG_RANGE = (-3.0, 25.0)  # el audio del PC empieza al hacer clic; la cámara, hasta ~15 s después


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(cmd, capture_output=True, creationflags=no_window)


def _decode(ffmpeg: str, path: str, stream: str, start: float = 0.0, dur: Optional[float] = None,
            file_time: bool = False) -> np.ndarray:
    """Audio mono a FS. Con file_time se rellena el comienzo para que la muestra 0 sea el
    tiempo 0 del archivo (la pista guía no siempre empieza junto con el archivo)."""
    cmd = [ffmpeg, "-v", "error", "-nostdin"]
    if start > 0 and not file_time:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path, "-map", stream, "-vn"]
    if file_time:
        cmd += ["-af", "aresample=async=1:first_pts=0"]
        if start > 0:
            cmd += ["-ss", f"{start:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-ac", "1", "-ar", str(FS), "-f", "f32le", "-"]
    res = _run(cmd)
    if res.returncode != 0:
        return np.zeros(0, np.float32)
    return np.frombuffer(res.stdout, np.float32)


_DUR = re.compile(r"(\d+)(ms|d|h|m|s)")
_DUR_UNITS = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def _android_duration(text: str) -> float:
    """«+3d13h26m47s229ms» → segundos."""
    return sum(int(n) * _DUR_UNITS[u] for n, u in _DUR.findall(text))


def phone_clock_gap(adb: str, serial: str) -> Optional[float]:
    """Diferencia entre los dos relojes del teléfono: con reposo (BOOTTIME) y sin él (MONOTONIC).

    Con --capture-orientation, scrcpy pasa la imagen por OpenGL y sus horas quedan en BOOTTIME,
    mientras el audio sigue en MONOTONIC: en el .mkv el video aparece horas «después». dumpsys
    alarm da el tiempo desde el arranque del sistema en ambos relojes, tomado en el mismo instante.
    """
    res = _run([adb, "-s", serial, "shell", "dumpsys alarm | grep -m2 'Runtime uptime'"])
    out = res.stdout.decode("utf-8", errors="replace") if res.returncode == 0 else ""
    el = re.search(r"\(elapsed\):\s*\+?(\S+)", out)
    up = re.search(r"\(uptime\):\s*\+?(\S+)", out)
    if not el or not up:
        return None
    return _android_duration(el.group(1)) - _android_duration(up.group(1))


def first_video_time(ffmpeg: str, path: str) -> Optional[float]:
    """Momento del primer cuadro en tiempo de archivo."""
    res = _run([ffmpeg, "-v", "info", "-nostdin", "-i", path, "-map", "0:v:0", "-frames:v", "1",
                "-vf", "showinfo", "-f", "null", "-"])
    m = re.search(r"pts_time:\s*(-?[\d.]+)", res.stderr.decode("utf-8", errors="replace"))
    return float(m.group(1)) if m else None


def _lag(guide: np.ndarray, master: np.ndarray, m_offset: float) -> Tuple[float, float]:
    """Desfase d (s) tal que guide(t) ≈ master(t + d), con master[0] en m_offset (relativo al
    comienzo de guide). Devuelve (d, psr)."""
    n = 1 << int(np.ceil(np.log2(len(guide) + len(master))))
    spec = np.conj(np.fft.rfft(guide, n)) * np.fft.rfft(master, n)
    freqs = np.fft.rfftfreq(n, 1.0 / FS)
    spec[(freqs < BAND[0]) | (freqs > BAND[1])] = 0
    spec /= (np.abs(spec) + 1e-12) ** PHAT_BETA      # PHAT: pesa la fase, así manda el ritmo y no el timbre
    corr = np.fft.irfft(spec, n)[: len(master) - len(guide) + 1]
    if corr.size < 3:
        return 0.0, 0.0
    k = int(np.argmax(corr))
    guard = int(0.01 * FS)
    rest = np.concatenate([corr[: max(0, k - guard)], corr[k + guard + 1:]])
    noise = float(rest.std()) if rest.size else 0.0
    psr = float((corr[k] - rest.mean()) / noise) if noise > 0 else 0.0
    # Interpolación parabólica: precisión por debajo de una muestra
    frac = 0.0
    if 0 < k < corr.size - 1:
        a, b, c = corr[k - 1], corr[k], corr[k + 1]
        den = a - 2 * b + c
        frac = 0.5 * (a - c) / den if den else 0.0
    return m_offset + (k + frac) / FS, psr


def _measure_at(ffmpeg: str, guide: np.ndarray, ref_wav: str, g_start: float, win: float) -> Tuple[float, float]:
    seg = guide[int(g_start * FS): int((g_start + win) * FS)]
    if seg.size < FS or float(np.abs(seg).max()) < 1e-4:
        return 0.0, 0.0                               # silencio: no hay nada que comparar
    m_start = g_start + LAG_RANGE[0]
    pad = max(0.0, -m_start)
    master = _decode(ffmpeg, ref_wav, "0:a:0", max(0.0, m_start), win + LAG_RANGE[1] - LAG_RANGE[0] - pad)
    if master.size <= seg.size:
        return 0.0, 0.0
    if pad:
        master = np.concatenate([np.zeros(int(pad * FS), np.float32), master])
    d, psr = _lag(seg, master, LAG_RANGE[0])
    return d, psr


def measure(ffmpeg: str, video_path: str, ref_wavs: List[str],
            clock_gap: Optional[Callable[[], Optional[float]]] = None) -> Optional[dict]:
    """Mide cómo alinear el audio del PC con el video usando la pista guía.

    Devuelve None si el video no trae pista guía. Si la trae: {"video_start": primer cuadro en
    tiempo de archivo (para que el video empiece en 0 al unir), "offset", "drift", "psr", "ref"};
    offset es None si ninguna coincidencia fue confiable o no se pudo ubicar la imagen en el reloj
    del sonido (clock_gap, ver phone_clock_gap). «offset» sigue la convención de la unión: inicio del audio − primer cuadro
    (negativo: el audio empezó antes y se recorta). «drift»: cuánto más rápido corre el reloj
    del PC que el del teléfono (0.00005 = 50 ppm).
    """
    guide = _decode(ffmpeg, video_path, "0:a:0", file_time=True)
    if guide.size < 2 * FS:
        return None
    v_file = first_video_time(ffmpeg, video_path)
    if v_file is None:
        return None
    best = {"video_start": v_file, "offset": None, "drift": 0.0, "psr": 0.0, "ref": None}
    v0 = v_file                                       # primer cuadro en el reloj de la pista guía
    if abs(v_file) > 60:                              # imagen y sonido con horas de relojes distintos
        gap = clock_gap() if clock_gap else None
        v0 = v_file - gap if gap is not None else None
        if v0 is None or not -5.0 < v0 < 30.0:
            return best
    total = guide.size / FS
    win = min(WINDOW_S, total)
    starts = [0.0] if total < 2.5 * win else [0.0, total - win]

    for wav in ref_wavs:
        points = [(s, *_measure_at(ffmpeg, guide, wav, s, win)) for s in starts]
        good = [(s + win / 2, d) for s, d, psr in points if psr >= MIN_PSR]
        if not good:
            continue
        psr = max(p for _, _, p in points)
        if len(good) == 2:
            (t1, d1), (t2, d2) = good
            drift = (d2 - d1) / (t2 - t1)
            if abs(drift) > 1e-3:                     # >1000 ppm: ningún reloj deriva tanto, algo no cuadra
                good, drift = good[:1], 0.0
        else:
            drift = 0.0
        t_ref, d_ref = good[0]
        d_v0 = d_ref + drift * (v0 - t_ref)           # desfase justo en el primer cuadro
        cand = {"offset": float(-(v0 + d_v0)), "drift": float(drift), "psr": float(psr), "ref": wav,
                "video_start": v_file}
        if best["offset"] is None or cand["psr"] > best["psr"]:
            best = cand
    return best
