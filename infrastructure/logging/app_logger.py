"""
Sistema de logging estructurado con rotación de archivos y bus de eventos para UI.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import datetime
import traceback
from typing import Callable, List, Optional
import paths
from core.interfaces import IAppLogger


class AppLogger(IAppLogger):
    """
    Logger centralizado de la aplicación.
    Escribe en archivo rotativo en el directorio de datos (portable o AppData)
    y notifica en tiempo real a los observadores suscritos (como la consola GUI).
    """

    def __init__(self, name: str = "UltraCam"):
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self._listeners: List[Callable[[str, str], None]] = []
        self._memory_logs: List[str] = []
        self._max_memory_logs = 1000

        # Evitar duplicar handlers si se reinicializa
        if not self.logger.handlers:
            self._setup_file_handler()
            self._setup_console_handler()

    def _setup_file_handler(self):
        try:
            log_dir = os.path.join(paths.data_dir(), "logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "app.log")
            handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            formatter = logging.Formatter("[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s",
                                          datefmt="%Y-%m-%d %H:%M:%S")
            handler.setFormatter(formatter)
            handler.setLevel(logging.DEBUG)
            self.logger.addHandler(handler)
        except Exception as e:
            sys.stderr.write(f"No se pudo inicializar RotatingFileHandler: {e}\n")

    def _setup_console_handler(self):
        try:
            console = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
            console.setFormatter(formatter)
            console.setLevel(logging.INFO)
            self.logger.addHandler(console)
        except Exception:
            pass

    def add_listener(self, listener: Callable[[str, str], None]):
        """Añade un callback que recibe (mensaje, categoria) para actualizar la UI."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[str, str], None]):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def log(self, message: str, level: str = "INFO", category: str = "APP"):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] [{category}] {message}"

        # Guardar en buffer de memoria para reportes
        self._memory_logs.append(formatted)
        if len(self._memory_logs) > self._max_memory_logs:
            self._memory_logs.pop(0)

        # Enviar al logging estándar de Python
        lvl = getattr(logging, level.upper(), logging.INFO)
        self.logger.log(lvl, f"[{category}] {message}")

        # Notificar a la interfaz gráfica
        for listener in self._listeners:
            try:
                listener(formatted, category)
            except Exception:
                pass

    def warn(self, message: str, category: str = "WARN"):
        self.log(message, level="WARNING", category=category)

    def debug(self, message: str, category: str = "DEBUG"):
        """Detalle interno: queda en el archivo de registro, sin avisar a la interfaz."""
        self._memory_logs.append(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] [{category}] {message}")
        if len(self._memory_logs) > self._max_memory_logs:
            self._memory_logs.pop(0)
        self.logger.debug(f"[{category}] {message}")

    def error(self, message: str, exc: Optional[Exception] = None, category: str = "ERROR"):
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            full_msg = f"{message} - Error: {exc}\n{tb}"
            self.log(full_msg, level="ERROR", category=category)
        else:
            self.log(message, level="ERROR", category=category)

    def get_recent_logs(self, count: int = 200, filter_poll: bool = True) -> List[str]:
        logs = self._memory_logs[-count:]
        if filter_poll:
            return [l for l in logs if "[POLL]" not in l]
        return list(logs)


# Instancia singleton global para uso directo o inyección
GLOBAL_LOGGER = AppLogger()
