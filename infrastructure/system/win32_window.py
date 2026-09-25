"""
Gestión de ventanas Win32: incrustación segura con SetParent y desvinculación limpia.
Evita el error de división por cero de scrcpy y la retención de dispositivos DirectShow por HWNDs huérfanos.
"""

import sys
import time
from typing import Optional
from core.interfaces import IWindowEmbedder
from infrastructure.logging.app_logger import GLOBAL_LOGGER


class Win32WindowEmbedder(IWindowEmbedder):
    """Manejo de incrustación de ventanas mediante Win32 API."""

    def _get_user32(self):
        if sys.platform == "win32":
            import ctypes
            return getattr(ctypes.windll, "user32", None)
        return None

    def embed_window(self, window_title: str, parent_hwnd: int, width: int, height: int, timeout: float = 6.0) -> bool:
        """
        Busca la ventana lanzada por scrcpy o ffplay y la incrusta dentro del contenedor
        de la interfaz mediante Win32 SetParent + MoveWindow, eliminando marcos y barras de título.
        Espera a que la ventana sea visible antes de tocarla para evitar división por cero (E14).
        """
        user32 = self._get_user32()
        if not user32:
            return False

        t0 = time.time()
        hwnd_child = None
        visible = False

        while time.time() - t0 < timeout:
            hwnd_child = user32.FindWindowW(None, window_title)
            if hwnd_child and user32.IsWindowVisible(hwnd_child):
                visible = True
                break
            time.sleep(0.05)

        if not hwnd_child or not visible:
            GLOBAL_LOGGER.log(f"No se pudo encontrar la ventana visible '{window_title}' tras {timeout}s", "WARN")
            return False

        try:
            user32.SetParent(hwnd_child, parent_hwnd)
            style = user32.GetWindowLongW(hwnd_child, -16)  # GWL_STYLE
            style &= ~0x00C00000
            style &= ~0x00040000
            style &= ~0x00020000
            style &= ~0x00010000
            style |= 0x40000000  # WS_CHILD
            user32.SetWindowLongW(hwnd_child, -16, style)

            user32.MoveWindow(hwnd_child, 0, 0, width, height, True)
            user32.ShowWindow(hwnd_child, 5)  # SW_SHOW
            if hasattr(user32, "UpdateWindow"):
                user32.UpdateWindow(hwnd_child)
            GLOBAL_LOGGER.log(f"Ventana '{window_title}' (HWND {hwnd_child}) incrustada exitosamente en HWND {parent_hwnd}", "PROCESS")
            return True
        except Exception as e:
            GLOBAL_LOGGER.error(f"Error al incrustar ventana '{window_title}': {e}", e, "ERROR")
            return False

    def detach_window(self, hwnd: Optional[int]) -> bool:
        """
        Restaura el parentesco de una ventana incrustada hacia el escritorio (HWND 0)
        y envía WM_CLOSE para permitir que libere sus recursos de DirectShow limpiamente.
        """
        user32 = self._get_user32()
        if not user32 or not hwnd:
            return False

        try:
            if user32.IsWindow(hwnd):
                user32.SetParent(hwnd, 0)
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                return True
        except Exception as e:
            GLOBAL_LOGGER.log(f"Aviso al desvincular HWND {hwnd}: {e}", "WARN")
        return False


GLOBAL_WINDOW_EMBEDDER = Win32WindowEmbedder()
