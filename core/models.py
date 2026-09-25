"""
Modelos de dominio tipados para UltraCam Studio / GalaxyCamPro.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class DeviceKind(str, Enum):
    ANDROID = "android"
    WEBCAM = "webcam"
    CAPTURE = "capture"
    APP = "app"
    VIRTUAL = "virtual"


@dataclass
class VideoSource:
    id: str
    kind: str
    name: str
    detail: str
    ready: bool = True
    serial: Optional[str] = None
    device_name: Optional[str] = None
    vendor: Optional[str] = None
    is_dshow: bool = False
    wifi: bool = False
    state: str = "device"
    battery: Optional[int] = None
    caps: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CameraCalibration:
    brightness: float = 0.0  # -1.0 a 1.0
    contrast: float = 1.0    # 0.5 a 2.0
    saturation: float = 1.0  # 0.0 a 2.0
    sharpness: float = 0.0   # 0.0 a 5.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "brightness": round(self.brightness, 2),
            "contrast": round(self.contrast, 2),
            "saturation": round(self.saturation, 2),
            "sharpness": round(self.sharpness, 2),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CameraCalibration":
        if not data:
            return cls()
        return cls(
            brightness=float(data.get("brightness", 0.0)),
            contrast=float(data.get("contrast", 1.0)),
            saturation=float(data.get("saturation", 1.0)),
            sharpness=float(data.get("sharpness", 0.0)),
        )


@dataclass
class StreamConfiguration:
    platform: str
    size: str = "1920x1080"
    fps: int = 30
    window_title: str = "UltraCam_Monitor"
    record_video: bool = False
    record_dir: Optional[str] = None
    live_preview: bool = True
    virtual_cam: bool = False
    vcam_pipe: Optional[str] = None
    vcam_canvas: Optional[str] = None
    vcam_size: Optional[tuple] = None
    serial: Optional[str] = None
    device_name: Optional[str] = None
    pc_device: Optional[str] = None
    vcodec: Optional[str] = None
    pixel_format: Optional[str] = None
    codec: str = "h265"
    bitrate: str = "50M"
    rotation: int = 0
    camera_id: Optional[str] = None
    camera_facing: Optional[str] = None
    video_buffer: int = 100
    calibration: CameraCalibration = field(default_factory=CameraCalibration)
