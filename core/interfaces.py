"""
Contratos e interfaces abstractas (SOLID - ISP / DIP)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
import subprocess


class IWindowEmbedder(ABC):
    @abstractmethod
    def embed_window(self, title: str, parent_hwnd: int, width: int, height: int, timeout: float = 6.0) -> bool:
        """Incrusta una ventana de proceso hijo en el contenedor padre de la interfaz."""
        pass

    @abstractmethod
    def detach_window(self, hwnd: int) -> bool:
        """Restaura la ventana hija al escritorio antes de cerrar el contenedor."""
        pass


class IProcessManager(ABC):
    @abstractmethod
    def start_process(self, cmd: List[str], stdin_pipe: bool = False, stdout_pipe: bool = False,
                      stderr_pipe: bool = True, no_window: bool = True) -> subprocess.Popen:
        pass

    @abstractmethod
    def stop_process(self, proc: subprocess.Popen, graceful: bool = False, timeout: float = 3.0) -> None:
        pass

    @abstractmethod
    def kill_process_tree(self, proc: subprocess.Popen) -> None:
        """Termina forzosamente un proceso y todo su árbol de procesos descendientes."""
        pass


class IDeviceScanner(ABC):
    @abstractmethod
    def scan_adb_devices(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def scan_dshow_devices(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def probe_capabilities(self, device_name: str) -> Dict[str, Any]:
        pass


class IAppLogger(ABC):
    @abstractmethod
    def log(self, message: str, level: str = "INFO", category: str = "APP") -> None:
        pass

    @abstractmethod
    def error(self, message: str, exc: Optional[Exception] = None, category: str = "ERROR") -> None:
        pass


class IAudioEngine(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def refresh_devices(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def apply_config(self, cfg: Dict[str, Any]) -> bool:
        pass


class ISettingsManager(ABC):
    @abstractmethod
    def load_settings(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def save_settings(self, data: Dict[str, Any]) -> bool:
        pass

