"""Core package for UltraCam Studio"""
from .exceptions import UltraCamError, CameraDeviceError, CameraInUseError, DeviceNotFoundError, CameraProcessError
from .models import VideoSource, CameraCalibration, StreamConfiguration, DeviceKind
from .interfaces import IWindowEmbedder, IProcessManager, IDeviceScanner, IAppLogger

__all__ = [
    "UltraCamError", "CameraDeviceError", "CameraInUseError", "DeviceNotFoundError", "CameraProcessError",
    "VideoSource", "CameraCalibration", "StreamConfiguration", "DeviceKind",
    "IWindowEmbedder", "IProcessManager", "IDeviceScanner", "IAppLogger"
]
