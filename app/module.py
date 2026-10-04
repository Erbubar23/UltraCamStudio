"""
UltraCam Studio - Contrato de un módulo del marco.

Cada módulo (Cámaras, Audio, Grabación, Transmisión, General) es una sección de la
interfaz y una carpeta de código en modules/<clave>/. El marco (app/) le pide siempre lo
mismo, así se puede trabajar, probar y activar cada uno por separado:

  - spec: clave, título, icono, orden y si es opcional (se puede ocultar).
  - build_panel(parent): lo de todos los días, en el cajón (o en la columna fija, Audio).
  - build_advanced(parent): lo que se toca poco, bajo «▸ Avanzado».
  - status(): el indicador del riel (● grabando, ◉ en vivo, ⚠ problema).
  - readiness(): qué le falta para grabar o transmitir, con su arreglo en un clic.

Un módulo no importa a otro: se comunica por app.bus (ver app/bus.py).
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass(frozen=True)
class ModuleSpec:
    key: str                       # "cameras", "audio", "recording", "streaming", "general"
    title: str                     # texto visible (ya traducido)
    icon: str                      # glifo del riel
    order: int = 0                 # posición en el riel
    optional: bool = False         # se puede ocultar y se activa con el ＋ del riel
    fixed: bool = False            # vive en la columna fija (Audio), no en el cajón
    advanced_hint: str = ""        # qué hay en su «Avanzado» (para el mensaje del ⚙)


@dataclass
class Status:
    """Indicador del módulo en el riel. level: None (nada), ok, warn, rec, live."""
    level: Optional[str] = None
    badge: str = ""


@dataclass
class Readiness:
    """Algo que falta antes de grabar o transmitir, con el botón que lo arregla."""
    message: str
    action_label: str = ""
    action: Optional[Callable[[], None]] = None
    blocking: bool = False         # True: no se puede empezar sin arreglarlo


@dataclass
class Module:
    """Base de los módulos. `app` es la ventana (GalaxyCamApp)."""
    app: object
    spec: ModuleSpec = field(default=None)

    def build_panel(self, parent) -> None:
        raise NotImplementedError

    def build_advanced(self, parent) -> None:
        """Por defecto no hay «Avanzado»."""

    def has_advanced(self) -> bool:
        return type(self).build_advanced is not Module.build_advanced

    def status(self) -> Status:
        return Status()

    def readiness(self) -> List[Readiness]:
        return []

    def on_show(self) -> None:
        """El cajón se abrió con este módulo (refrescar lo que haga falta)."""

    def on_hide(self) -> None:
        """El cajón se cerró o cambió a otro módulo."""

    def attach(self) -> None:
        """La pantalla ya está armada (o cambió qué módulos se ven): poner o quitar lo que el
        módulo agrega fuera de su cajón (indicador en la cabecera, acción en la barra)."""

    def on_app_close(self) -> None:
        """La app se cierra: soltar lo que el módulo tenga en marcha."""
