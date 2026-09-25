"""
Excepciones de dominio para UltraCam Studio / GalaxyCamPro.
Jerarquía limpia de errores para evitar el uso de excepciones genéricas.
"""

class UltraCamError(Exception):
    """Excepción base del sistema."""
    pass


class CameraDeviceError(UltraCamError):
    """Errores relacionados con dispositivos de video físicos o virtuales."""
    pass


class CameraInUseError(CameraDeviceError):
    """La cámara DirectShow está siendo utilizada por otro proceso (Zoom, OBS, Teams)."""
    pass


class DeviceNotFoundError(CameraDeviceError):
    """No se encontró el dispositivo especificado (ADB desconectado o webcam desconectada)."""
    pass


class CameraProcessError(UltraCamError):
    """Fallo al inicializar o comunicar con subprocesos de video (scrcpy, ffmpeg, ffplay)."""
    pass


class VirtualCamError(UltraCamError):
    """Error al inicializar o transmitir hacia la cámara virtual de Windows."""
    pass


class AudioEngineError(UltraCamError):
    """Errores en el subsistema de audio, driver ASIO/WASAPI o plugins VST3."""
    pass


class ConfigurationError(UltraCamError):
    """Error al parsear o validar ajustes de configuración o presets."""
    pass
