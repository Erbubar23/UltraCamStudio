"""
UltraCam Studio - Fichas de tomas sin terminar de guardar.

Al terminar de grabar, antes de unir y comprimir, se guarda una ficha con lo necesario
para hacerlo (video, audios, opciones). Se borra cuando el MP4 queda verificado. Si la app
se cierra o la PC se apaga a mitad, la ficha sigue ahí y al volver a abrir se ofrece
«Terminar de guardar»: los originales no se borran hasta tener el archivo final completo.
"""

import datetime
import json
import os
from typing import Dict, List, Optional


def folder(data_dir: str) -> str:
    return os.path.join(data_dir, "pending_takes")


def save(data_dir: str, video_path: str, audio_info: Dict, options: Dict) -> Optional[str]:
    """Guarda la ficha y devuelve su ruta (None si no se pudo: la toma se guarda igual)."""
    clean = {k: v for k, v in options.items() if not callable(v)}
    data = {"video": video_path, "audio": audio_info, "options": clean,
            "created": datetime.datetime.now().isoformat(timespec="seconds")}
    try:
        os.makedirs(folder(data_dir), exist_ok=True)
        path = os.path.join(folder(data_dir), f"take_{clean.get('timestamp') or 'x'}_{os.getpid()}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, path)
        return path
    except OSError:
        return None


def remove(path: Optional[str]):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def pending(data_dir: str) -> List[Dict]:
    """Fichas de tomas que se pueden terminar de guardar (su video sigue en disco).
    Las que ya no tienen video se borran: no hay nada que recuperar."""
    out = []
    base = folder(data_dir)
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(base, name)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            remove(path)
            continue
        video = data.get("video")
        if not video or not os.path.exists(video):
            remove(path)
            continue
        data["path"] = path
        out.append(data)
    return out
