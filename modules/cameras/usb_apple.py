"""
UltraCam Studio - ¿Hay un iPhone conectado por cable?

Windows no puede usar la cámara del iPhone por USB por sí solo: hace falta una app en el
teléfono y en la PC (DroidCam, Camo…) que viaja por el cable con el controlador de Apple
(Apple Mobile Device Support, incluido en «Dispositivos Apple» o iTunes). Aquí solo se
detecta el iPhone para guiar esos pasos; la cámara aparece después como cualquier otra.

Se pregunta a Windows (cfgmgr32) por los dispositivos USB conectados: no abre procesos.
"""

import ctypes
import subprocess
from typing import List

APPLE_VID = "VID_05AC"
CM_GETIDLIST_FILTER_ENUMERATOR = 0x1
CM_GETIDLIST_FILTER_PRESENT = 0x100


def usb_device_ids() -> List[str]:
    """IDs de los dispositivos USB conectados ahora (p. ej. «USB\\VID_05AC&PID_12A8\\…»)."""
    try:
        cfg = ctypes.windll.cfgmgr32
    except (AttributeError, OSError):
        return []
    flags = CM_GETIDLIST_FILTER_ENUMERATOR | CM_GETIDLIST_FILTER_PRESENT
    size = ctypes.c_ulong(0)
    if cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), "USB", flags) != 0 or not size.value:
        return []
    buf = ctypes.create_unicode_buffer(size.value)
    if cfg.CM_Get_Device_ID_ListW("USB", buf, size.value, flags) != 0:
        return []
    return [s for s in buf[:size.value].split("\0") if s]


def iphone_connected(ids: List[str] = None) -> bool:
    """Un iPhone o iPad (fabricante Apple) conectado por USB."""
    ids = usb_device_ids() if ids is None else ids
    return any(APPLE_VID in i.upper() for i in ids)


def apple_driver_installed() -> bool:
    """¿Está el servicio de Apple que hace funcionar el cable (Apple Mobile Device Service)?"""
    try:
        res = subprocess.run(["sc", "query", "Apple Mobile Device Service"], capture_output=True, text=True,
                             timeout=5, creationflags=0x08000000)
        return res.returncode == 0
    except Exception:
        return False
