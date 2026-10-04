"""
UltraCam Studio - Modelo de las fuentes de video (cámaras) y utilidades de formato.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import virtualcam
from presentation.strings import t


@dataclass
class Source:
    id: str
    kind: str                      # webcam | capture | virtual | app | android
    name: str
    meta: str = ""
    ready: bool = True
    hint_title: str = ""
    hint_steps: List[str] = field(default_factory=list)
    device_name: Optional[str] = None   # DirectShow
    serial: Optional[str] = None        # Android (adb)
    battery: Optional[int] = None
    is_wifi: bool = False
    waiting: bool = False               # desconectada: se conserva elegida hasta que vuelva

    @property
    def is_dshow(self) -> bool:
        return self.device_name is not None


def vertical_size(size: str, mode: Optional[str]) -> Optional[tuple]:
    """Tamaño (ancho, alto) del video vertical que sale de una resolución y un modo:
    'crop' recorta el centro a 9:16; 'cw'/'ccw'/'phone' giran la imagen completa."""
    try:
        w, h = (int(x) for x in size.lower().split("x"))
    except (ValueError, AttributeError):
        return None
    if mode == "crop":
        return int(h * 9 / 32) * 2, h
    if mode in ("cw", "ccw", "phone"):
        return h, w
    return None


def is_own_virtual_camera(name: str) -> bool:
    """«UltraCam» no puede ser fuente de sí misma: su imagen volvería a entrar en bucle."""
    return name.strip().casefold() == virtualcam.DEVICE_NAME.casefold()


def waiting_source(prev: Source) -> Source:
    """La fuente elegida se desconectó: sigue en la lista como «Desconectada», con pasos
    para recuperarla, y la imagen vuelve sola cuando aparece (no se salta a otra cámara)."""
    s = Source(id=prev.id, kind=prev.kind, name=prev.name, meta=t("ui.main.desconectada"), ready=False,
               device_name=prev.device_name, serial=prev.serial, is_wifi=prev.is_wifi, waiting=True)
    s.hint_title = t("source.waiting_title", name=prev.name)
    back = t("ui.main.la_imagen_vuelve_sola_en")
    if prev.kind == "android":
        s.hint_steps = [
            t("ui.main.comprueba_que_el_telefono_y") if prev.is_wifi
            else t("ui.main.vuelve_a_conectar_el_cable"),
            t("ui.main.desbloquea_el_telefono_y_acepta"),
            back,
        ]
    elif prev.kind == "app":
        s.hint_steps = [
            t("ui.main.abre_la_app_de_camara"),
            t("ui.main.comprueba_que_el_telefono_y"),
            back,
        ]
    else:
        s.hint_steps = [t("ui.main.revisa_el_cable_usb_o"), back]
    return s
