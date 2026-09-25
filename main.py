"""
UltraCam Studio - Punto de entrada principal
"""

import sys
import os
import multiprocessing

# Asegurar que el directorio de la aplicación esté en el path
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)


def main():
    # La interfaz se importa aquí: el proceso de audio (multiprocessing) no debe cargarla
    from gui import GalaxyCamApp
    app = GalaxyCamApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    try:
        app.mainloop()
    finally:
        # Garantiza la liberación inmediata de dispositivos USB y cierre limpio en Windows
        try:
            os._exit(0)
        except Exception:
            pass


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
