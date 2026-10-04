"""
UltraCam Studio - Clasificación de plugins VST3 (instrumento o efecto)

Saber si un .vst3 es un instrumento exige cargarlo, y hay plugins que tardan, muestran
avisos o se caen al cargar. Por eso se prueban en un proceso aparte y desechable: si
uno se cae o se cuelga, se marca como «error» y se sigue con el resto en un proceso
nuevo. El resultado se guarda en la configuración (por ruta, tamaño y fecha) para no
repetirlo en cada arranque.
"""

import os
import multiprocessing as mp
from typing import Callable, Dict, List, Optional

PER_PLUGIN_TIMEOUT = 30.0
CACHE_VERSION = 2          # 2: además del tipo guarda nombre, fabricante, categoría y versión


def plugin_binary(path: str) -> str:
    """Un .vst3 puede ser una carpeta (bundle) con el binario en Contents/x86_64-win/.
    pedalboard en Windows no carga la carpeta («unsupported plugin format»), así que se
    le pasa el binario de adentro."""
    if os.path.isdir(path):
        arch = os.path.join(path, "Contents", "x86_64-win")
        inner = os.path.join(arch, os.path.basename(path))
        if os.path.isfile(inner):
            return inner
        try:
            found = [f for f in os.listdir(arch) if f.lower().endswith(".vst3")]
        except OSError:
            found = []
        if found:
            return os.path.join(arch, found[0])
    return path


def _signature(path: str) -> str:
    try:
        st = os.stat(path)
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return ""


def _worker(paths: List[str], conn):
    """Proceso hijo: carga cada plugin y cuenta qué es."""
    import pedalboard
    for p in paths:
        conn.send(("start", p))
        try:
            pl = pedalboard.load_plugin(plugin_binary(p))
            kind = "instrument" if getattr(pl, "is_instrument", False) else "effect"
            meta = {"name": getattr(pl, "name", "") or "", "vendor": getattr(pl, "manufacturer_name", "") or "",
                    "category": getattr(pl, "category", "") or "", "version": getattr(pl, "version", "") or ""}
            conn.send(("done", p, kind, meta))
            del pl
        except Exception as e:
            conn.send(("done", p, "error", {"detail": str(e)[:200]}))
    conn.send(("end",))


def _run_batch(paths: List[str], on_done: Optional[Callable[[], None]] = None) -> Dict[str, tuple]:
    """Prueba una lista en un proceso; devuelve {ruta: (tipo, datos)} de las que terminó.
    Si el proceso se cae o se cuelga, la ruta en curso queda como error."""
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_worker, args=(paths, child), daemon=True, name="UltraCamVstProbe")
    proc.start()
    child.close()
    out: Dict[str, tuple] = {}
    current: Optional[str] = None
    try:
        while True:
            if not parent.poll(PER_PLUGIN_TIMEOUT):
                break                                   # colgado (o un aviso esperando un clic)
            try:
                msg = parent.recv()
            except (EOFError, OSError):
                break                                   # el plugin tumbó el proceso
            if msg[0] == "start":
                current = msg[1]
            elif msg[0] == "done":
                out[msg[1]] = (msg[2], msg[3])
                current = None
                if on_done:
                    on_done()
            elif msg[0] == "end":
                break
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join(timeout=2)
    if current is not None:
        out[current] = ("error", {"detail": "El plugin se cerró o no respondió al cargarlo"})
    return out


def classify(plugins: List[Dict], cache: Dict[str, Dict], retry_errors: bool = False,
             log: Optional[Callable[[str, str], None]] = None,
             progress: Optional[Callable[[int, int], None]] = None) -> bool:
    """Deja en `cache` (por ruta) el tipo ("instrument" | "effect" | "error"), nombre,
    fabricante, categoría y versión de cada plugin de `plugins` (lista de scan_vst3),
    probando solo los nuevos o cambiados. También copia `kind` en cada plugin.
    progress(revisados, total) avisa de cada plugin revisado (desde este hilo).
    Devuelve True si `cache` cambió."""
    pending = []
    for pl in plugins:
        key = os.path.normcase(pl["path"])
        sig = _signature(pl["path"])
        hit = cache.get(key)
        if (hit and hit.get("sig") == sig and hit.get("v") == CACHE_VERSION
                and not (retry_errors and hit.get("kind") == "error")):
            pl["kind"] = hit.get("kind")
        else:
            pending.append(pl)
    if not pending:
        return False
    if log:
        log(f"Revisando {len(pending)} plugins VST3 nuevos (instrumento o efecto)…", "AUDIO")
    todo = [pl["path"] for pl in pending]
    results: Dict[str, tuple] = {}

    done = [0]

    def one_done():
        done[0] += 1
        if progress:
            progress(min(done[0], len(pending)), len(pending))
    while todo:
        got = _run_batch(todo, one_done)
        results.update(got)
        done[0] = len(results)                           # también cuenta el que tumbó el proceso
        todo = [p for p in todo if p not in results]
        if not got:                                      # ni siquiera arrancó: no insistir
            for p in todo:
                results[p] = ("error", {"detail": "No se pudo revisar"})
            break
    for pl in pending:
        kind, meta = results.get(pl["path"], ("error", {}))
        pl["kind"] = kind
        entry = {"sig": _signature(pl["path"]), "v": CACHE_VERSION, "kind": kind}
        entry.update({k: v for k, v in meta.items() if k != "detail" and v})
        cache[os.path.normcase(pl["path"])] = entry
        if kind == "error" and log:
            log(f"VST3 {pl['name']}: no se pudo revisar ({meta.get('detail', '')})", "WARN")
    return True
