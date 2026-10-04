"""
UltraCam Studio - Espacio en disco para grabar.
"""

import os
import shutil
from typing import Optional


# Espacio en disco para grabar. Al terminar, unir video y audio crea el MP4 junto al
# archivo en curso, así que hace falta al menos otro tanto libre para poder guardar.
GB = 1024 ** 3


DISK_MIN_TO_START = 2 * GB      # por debajo no se empieza a grabar


DISK_LOW = 5 * GB               # aviso durante la grabación


DISK_RESERVE = 1 * GB           # margen que se deja siempre libre


def disk_free(folder: str):
    """(bytes libres, unidad) de la carpeta, o (None, "") si no se puede saber."""
    path = os.path.abspath(folder)
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        return None, ""
    drive = os.path.splitdrive(path)[0] or path
    return free, drive


def fmt_bytes(n: int) -> str:
    """Tamaño legible con coma decimal: «45,2 GB», «820 MB»."""
    if n >= GB:
        return f"{n / GB:.1f} GB".replace(".", ",")
    return f"{n / 1024 ** 2:.0f} MB"


def disk_verdict(free: Optional[int], recording_bytes: int = 0) -> str:
    """'ok', 'low' (avisar) o 'stop' (detener y guardar ya), según lo libre y lo grabado."""
    if free is None:
        return "ok"
    if free < DISK_RESERVE + recording_bytes:
        return "stop"
    if free < DISK_LOW + recording_bytes:
        return "low"
    return "ok"
