"""
Gestión de persistencia de configuración y presets de cámara de forma atómica y segura.
"""

import os
import json
from typing import Dict, Any, Optional
import paths
from core.interfaces import ISettingsManager
from infrastructure.logging.app_logger import GLOBAL_LOGGER


class SettingsManager(ISettingsManager):
    """Repositorio de configuración y presets de cámara."""

    @staticmethod
    def load_settings(default: Optional[dict] = None) -> Dict[str, Any]:
        path = paths.settings_path()
        return paths.load_json(path, default or {})

    @staticmethod
    def save_settings(settings: dict) -> bool:
        path = paths.settings_path()
        ok = paths.save_json(path, settings)
        if not ok:
            GLOBAL_LOGGER.log(f"Fallo al guardar configuración en {path}", "WARN")
        return ok

    @staticmethod
    def load_presets() -> Dict[str, Any]:
        path = paths.presets_path()
        return paths.load_json(path, {})

    @staticmethod
    def save_camera_preset(device_name: str, settings: dict) -> bool:
        path = paths.presets_path()
        try:
            presets = paths.load_json(path, {})
            presets[device_name] = settings
            return paths.save_json(path, presets)
        except Exception as e:
            GLOBAL_LOGGER.error(f"Error guardando preset para {device_name}: {e}", e, "WARN")
            return False

    @staticmethod
    def load_camera_preset(device_name: str) -> Dict[str, Any]:
        presets = SettingsManager.load_presets()
        return presets.get(device_name, {})
