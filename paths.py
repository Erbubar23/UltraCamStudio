"""
UltraCam Studio - Rutas de datos (modo portable)

Empaquetada (PyInstaller), la app guarda todo en la carpeta "data" junto al .exe:
se puede copiar a otra PC o a una memoria USB y conserva su configuración.
Si esa carpeta no se puede escribir (p. ej. dentro de Program Files) o se ejecuta
desde el código fuente, usa %APPDATA%\\UltraCamStudio.
"""

import os
import sys
import json
import shutil

APP_FOLDER = "UltraCamStudio"
_data_dir = None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Carpeta del ejecutable (empaquetada) o del código fuente."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _writable(d: str) -> bool:
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _appdata_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_FOLDER)


def data_dir() -> str:
    global _data_dir
    if _data_dir:
        return _data_dir
    candidates = []
    if is_frozen():
        candidates.append(os.path.join(app_dir(), "data"))
    candidates.append(_appdata_dir())
    for d in candidates:
        if _writable(d):
            _data_dir = d
            break
    else:
        _data_dir = candidates[-1]
    _migrate_legacy(_data_dir)
    return _data_dir


def is_portable() -> bool:
    return os.path.normcase(data_dir()) == os.path.normcase(os.path.join(app_dir(), "data"))


def settings_path() -> str:
    return os.path.join(data_dir(), "settings.json")


def presets_path() -> str:
    return os.path.join(data_dir(), "camera_presets.json")


def plugins_state_dir() -> str:
    d = os.path.join(data_dir(), "plugins")
    os.makedirs(d, exist_ok=True)
    return d


def _migrate_legacy(target: str):
    """Trae la configuración de versiones anteriores (AppData y Videos\\GalaxyCam) la primera vez."""
    settings = os.path.join(target, "settings.json")
    old_settings = os.path.join(_appdata_dir(), "settings.json")
    if not os.path.exists(settings) and os.path.exists(old_settings) and \
            os.path.normcase(old_settings) != os.path.normcase(settings):
        try:
            shutil.copy2(old_settings, settings)
        except OSError:
            pass
    presets = os.path.join(target, "camera_presets.json")
    old_presets = os.path.join(os.path.expanduser("~"), "Videos", "GalaxyCam", "camera_presets.json")
    if not os.path.exists(presets) and os.path.exists(old_presets):
        try:
            shutil.copy2(old_presets, presets)
        except OSError:
            pass


def load_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def save_json(path: str, data) -> bool:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)     # escritura atómica: un corte de luz no deja el archivo a medias
        return True
    except Exception:
        return False
