"""
UltraCam Studio - Bus de eventos entre módulos.

Los módulos no se importan entre sí: cuando algo cambia, quien lo sabe lo anuncia
(`emit`) y quien le interesa se suscribe (`on`). Todo ocurre en el hilo de la interfaz;
un hilo de fondo debe pasar por app._ui antes de anunciar.
"""

from typing import Callable, Dict, List

# Eventos conocidos (datos que llevan)
CAMERA_CHANGED = "camera.changed"        # source: Source o None
REC_STATE = "rec.state"                  # state: idle | starting | recording | saving
SAVE_PROGRESS = "rec.save_progress"      # fraction: 0..1, step: str, eta_s: float | None
LIVE_STATE = "live.state"                # state: off | connecting | live | error, destinations: list
MODULES_CHANGED = "app.modules_changed"  # visible: lista de claves de módulos visibles
MODULE_STATUS = "app.module_status"      # key: módulo, badge: str, level: ok | warn | rec | live | None


class EventBus:
    def __init__(self, report: Callable[[str, BaseException], None] = None):
        self._subs: Dict[str, List[Callable]] = {}
        self._report = report

    def on(self, event: str, fn: Callable) -> Callable[[], None]:
        """Suscribe `fn(**datos)` a `event`. Devuelve la función que anula la suscripción."""
        self._subs.setdefault(event, []).append(fn)

        def off():
            subs = self._subs.get(event, [])
            if fn in subs:
                subs.remove(fn)
        return off

    def emit(self, event: str, **data):
        """Avisa a cada suscriptor. Si uno falla, los demás igual se enteran."""
        for fn in list(self._subs.get(event, [])):
            try:
                fn(**data)
            except Exception as e:          # un módulo roto no debe tumbar a los otros
                if self._report:
                    self._report(event, e)
