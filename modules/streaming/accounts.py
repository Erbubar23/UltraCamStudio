"""
UltraCam Studio - Centro de cuentas: los destinos de transmisión guardados.

Cada destino: plataforma, nombre, servidor, clave y si está marcado para la próxima
transmisión. La clave se guarda cifrada con Windows (DPAPI, ligada a tu usuario): quien copie
el archivo de configuración a otra PC o a otro usuario no puede leerla.
"""

import base64
import ctypes
import uuid
from ctypes import wintypes
from typing import Dict, List, Optional


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    b = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    b._buf = buf                      # que el búfer viva lo mismo que la estructura
    return b


def protect(text: str) -> str:
    """Cifra con DPAPI y devuelve base64 (con el prefijo «dpapi:»)."""
    if not text:
        return ""
    src, out = _blob(text.encode("utf-8")), _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), "UltraCam", None, None, None, 0x1,
                                                  ctypes.byref(out)):
        raise OSError("No se pudo cifrar la clave")
    try:
        return "dpapi:" + base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def unprotect(token: str) -> str:
    if not token:
        return ""
    if not token.startswith("dpapi:"):
        return token                   # nunca debería pasar: se guarda siempre cifrada
    src, out = _blob(base64.b64decode(token[6:])), _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0x1,
                                                    ctypes.byref(out)):
        return ""                      # de otro usuario o de otra PC: hay que volver a pegarla
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


class Accounts:
    """Destinos guardados en settings["streaming"]["destinations"] (se modifica en el lugar)."""

    def __init__(self, store: Dict):
        self.store = store
        self.store.setdefault("destinations", [])

    @property
    def items(self) -> List[Dict]:
        return self.store["destinations"]

    def get(self, did: str) -> Optional[Dict]:
        return next((d for d in self.items if d["id"] == did), None)

    def save(self, platform: str, name: str, server: str, key: str, did: Optional[str] = None) -> Dict:
        d = self.get(did) if did else None
        if d is None:
            d = {"id": f"dst_{uuid.uuid4().hex[:8]}", "enabled": True}
            self.items.append(d)
        d.update({"platform": platform, "name": name.strip() or platform, "server": server.strip()})
        if key is not None:
            d["key"] = protect(key.strip())
        return d

    def remove(self, did: str):
        self.store["destinations"] = [d for d in self.items if d["id"] != did]

    def set_enabled(self, did: str, on: bool):
        d = self.get(did)
        if d:
            d["enabled"] = bool(on)

    def key_of(self, did: str) -> str:
        d = self.get(did)
        return unprotect(d.get("key", "")) if d else ""

    def enabled(self) -> List[Dict]:
        return [d for d in self.items if d.get("enabled")]
