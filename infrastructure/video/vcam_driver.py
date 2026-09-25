"""
Cámara virtual «UltraCam» propia, sin depender de OBS.

El driver (vcam_driver/, C++) es un filtro DirectShow que Windows carga dentro de
cada programa que usa la cámara (Zoom, Teams, Discord, OBS, navegadores). Este
módulo hace el resto:
  - registra el driver para el usuario actual (HKCU): no pide permisos de
    administrador y sirve igual para la versión portable;
  - deja los cuadros NV12 en la memoria compartida que lee el driver. El contrato
    completo está en vcam_driver/src/protocol.h y debe coincidir con este archivo.

Si la app se cierra, el driver sigue entregando cuadros por su cuenta (un cartel
«UltraCam Studio está cerrado»), así ningún programa pierde la cámara.
"""

import ctypes
import hashlib
import mmap
import os
import shutil
import struct
import threading
import time
import winreg
from typing import Iterable, Optional

import numpy as np

import paths

CLSID = "{E7D1A5EA-54D9-4644-9E4D-1FA4F637870A}"
FRIENDLY_NAME = "UltraCam"
VIDEO_INPUT_CATEGORY = "{860BB310-5D01-11d0-BD3B-00A0C911CE86}"

# Descripción del pin (REGFILTER2 serializado: una salida de video NV12). Windows
# la usa para listar la cámara; es la misma que escribe regsvr32.
FILTER_DATA = (
    b"\x02\x00\x00\x00\x00\x00 \x00\x01\x00\x00\x00\x00\x00\x00\x000pi3"
    b"\x08\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"0ty3\x00\x00\x00\x008\x00\x00\x00H\x00\x00\x00vids\x00\x00\x10\x00\x80\x00\x00"
    b"\xaa\x008\x9bqNV12\x00\x00\x10\x00\x80\x00\x00\xaa\x008\x9bq"
)

# ---- Contrato de memoria compartida (vcam_driver/src/protocol.h) ----
SHARED_MEMORY_NAME = r"Local\UltraCamStudio.VirtualCamera.v1"
MAGIC = 0x43564355          # "UCVC"
VERSION = 1
SLOT_COUNT = 3
DATA_OFFSET = 4096
WIDTH, HEIGHT = 1920, 1080  # la app siempre envía 1080p; el driver escala al modo de cada programa
HEARTBEAT_INTERVAL = 0.25   # el driver da la app por cerrada tras 2 s sin latido

_FIELDS = ("magic", "version", "width", "height", "slot_count", "slot_size", "data_offset",
           "latest_slot", "frame_seq", "frame_tick", "heartbeat_tick", "fps",
           "slot_seq0", "slot_seq1", "slot_seq2", "reserved")
_OFFSET = {name: i * 4 for i, name in enumerate(_FIELDS)}

_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetTickCount64.restype = ctypes.c_uint64


def _tick() -> int:
    """Reloj compartido con el driver: milisegundos, 32 bits bajos."""
    return _kernel32.GetTickCount64() & 0xFFFFFFFF


# =============================================================================
# Registro en Windows
# =============================================================================
def dll_path(bits: int) -> Optional[str]:
    """Ruta de la DLL del driver (empaquetada junto al programa o recién compilada)."""
    name = f"ultracam-vcam{bits}.dll"
    base = os.path.join(paths.app_dir(), "vcam_driver")
    for folder in (base, os.path.join(base, "bin")):
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _install_root() -> str:
    base = os.environ.get("LOCALAPPDATA") or paths.data_dir()
    return os.path.join(base, paths.APP_FOLDER, "vcam")


def installed_copy(src: str) -> str:
    """Copia la DLL a una carpeta local con nombre según su contenido y devuelve esa ruta.

    Se registra la copia, no el archivo del programa, porque:
      - al actualizar con Zoom u OBS abiertos, la DLL en uso está bloqueada: la versión
        nueva va a otra carpeta y esos programas siguen con la anterior hasta reabrirse;
      - si se mueve la carpeta portable o se saca la memoria USB, la cámara sigue
        funcionando, porque su DLL vive en el disco local.
    """
    with open(src, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:12]
    folder = os.path.join(_install_root(), digest)
    dst = os.path.join(folder, os.path.basename(src))
    if not os.path.isfile(dst):
        os.makedirs(folder, exist_ok=True)
        tmp = dst + ".tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)      # nunca queda registrada una copia a medias
    return dst


def remove_old_copies(keep: Iterable[str]):
    """Borra las versiones anteriores que ningún programa tiene abiertas (las que siguen
    en uso dentro de Zoom, OBS… se borrarán en un arranque posterior)."""
    root = _install_root()
    keep = {os.path.normcase(os.path.dirname(p)) for p in keep}
    try:
        folders = [os.path.join(root, d) for d in os.listdir(root)]
    except OSError:
        return
    for folder in folders:
        if os.path.isdir(folder) and os.path.normcase(folder) not in keep:
            shutil.rmtree(folder, ignore_errors=True)


def _views():
    """Vistas del registro: 64 bits para programas de 64 y 32 bits para los de 32."""
    return ((64, winreg.KEY_WOW64_64KEY), (32, winreg.KEY_WOW64_32KEY))


def _clsid_key(clsid: str) -> str:
    return rf"Software\Classes\CLSID\{clsid}"


def _instance_key(clsid: str) -> str:
    return rf"Software\Classes\CLSID\{VIDEO_INPUT_CATEGORY}\Instance\{clsid}"


def register(name: str = FRIENDLY_NAME, clsid: str = CLSID) -> bool:
    """Registra la cámara para el usuario actual. Se puede llamar en cada arranque:
    actualiza la ruta de la DLL si el programa cambió de carpeta.
    Devuelve False si no se encontró la DLL de 64 bits."""
    registered_64 = False
    registered = []
    for bits, view in _views():
        src = dll_path(bits)
        if not src:
            continue
        try:
            dll = installed_copy(src)
        except OSError:
            dll = src               # sin carpeta local escribible: se usa la del programa
        registered.append(dll)
        access = winreg.KEY_WRITE | view
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _clsid_key(clsid), 0, access) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, name)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _clsid_key(clsid) + r"\InprocServer32", 0, access) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, dll)
            winreg.SetValueEx(k, "ThreadingModel", 0, winreg.REG_SZ, "Both")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _instance_key(clsid), 0, access) as k:
            winreg.SetValueEx(k, "FriendlyName", 0, winreg.REG_SZ, name)
            winreg.SetValueEx(k, "CLSID", 0, winreg.REG_SZ, clsid)
            winreg.SetValueEx(k, "FilterData", 0, winreg.REG_BINARY, FILTER_DATA)
        registered_64 = registered_64 or bits == 64
    if registered:
        remove_old_copies(registered)
    return registered_64


def _delete_tree(path: str, view: int):
    try:
        with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | view) as k:
            children = []
            i = 0
            while True:
                try:
                    children.append(winreg.EnumKey(k, i))
                    i += 1
                except OSError:
                    break
        for child in children:
            _delete_tree(path + "\\" + child, view)
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, view, 0)
    except FileNotFoundError:
        pass


def unregister(clsid: str = CLSID):
    """Quita la cámara del usuario actual (las dos vistas del registro)."""
    for _bits, view in _views():
        _delete_tree(_instance_key(clsid), view)
        _delete_tree(_clsid_key(clsid), view)


def registered_name(clsid: str = CLSID) -> Optional[str]:
    """Nombre con el que está registrada la cámara (64 bits), o None si no lo está
    o si su DLL ya no existe (p. ej. se movió la carpeta portable)."""
    try:
        view = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, _instance_key(clsid), 0, view) as k:
            name, _ = winreg.QueryValueEx(k, "FriendlyName")
        with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, _clsid_key(clsid) + r"\InprocServer32", 0, view) as k:
            dll, _ = winreg.QueryValueEx(k, "")
        return name if os.path.isfile(dll) else None
    except OSError:
        return None


# =============================================================================
# Envío de cuadros
# =============================================================================
class SharedFrameWriter:
    """Deja cuadros NV12 en la memoria compartida que lee el driver.

    El productor llena back_buffer() directamente sobre la memoria compartida (sin
    copias) y llama a publish(). Un hilo mantiene el latido para que el driver
    sepa que la app sigue abierta aunque no haya imagen.
    """

    def __init__(self, width: int = WIDTH, height: int = HEIGHT, fps: int = 30):
        self.width, self.height, self.fps = int(width), int(height), int(fps)
        self.slot_size = self.width * self.height * 3 // 2
        self._mm = mmap.mmap(-1, DATA_OFFSET + SLOT_COUNT * self.slot_size, tagname=SHARED_MEMORY_NAME)
        self._slots = [np.frombuffer(self._mm, dtype=np.uint8, count=self.slot_size,
                                     offset=DATA_OFFSET + i * self.slot_size) for i in range(SLOT_COUNT)]
        self._lock = threading.Lock()
        self._writing: Optional[int] = None
        self._hold_until = 0.0
        self.frames_in = 0
        self._init_header()
        self._stop = threading.Event()
        self._beat = threading.Thread(target=self._heartbeat, daemon=True)
        self._beat.start()

    @property
    def frame_bytes(self) -> int:
        return self.slot_size

    @property
    def frames_sent(self) -> int:
        return self.frames_in

    def _get(self, field: str) -> int:
        return struct.unpack_from("<I", self._mm, _OFFSET[field])[0]

    def _set(self, field: str, value: int):
        struct.pack_into("<I", self._mm, _OFFSET[field], value & 0xFFFFFFFF)

    def _init_header(self):
        # Si un programa sigue usando la cámara desde una sesión anterior, la memoria
        # ya existe: se continúa la numeración para que el driver no se confunda.
        same = (self._get("magic") == MAGIC and self._get("version") == VERSION and
                self._get("width") == self.width and self._get("height") == self.height)
        if not same:
            self._set("magic", 0)
            for field, value in (("version", VERSION), ("width", self.width), ("height", self.height),
                                 ("slot_count", SLOT_COUNT), ("slot_size", self.slot_size),
                                 ("data_offset", DATA_OFFSET), ("latest_slot", 0), ("frame_seq", 0),
                                 ("frame_tick", 0), ("slot_seq0", 0), ("slot_seq1", 0), ("slot_seq2", 0)):
                self._set(field, value)
        self._set("fps", self.fps)
        self._set("heartbeat_tick", _tick())
        self._set("magic", MAGIC)   # último: el driver solo lee si el encabezado está completo

    def _heartbeat(self):
        while not self._stop.wait(HEARTBEAT_INTERVAL):
            now = _tick()
            self._set("heartbeat_tick", now)
            if time.monotonic() < self._hold_until:
                self._set("frame_tick", now)   # el driver sigue dando por reciente el último cuadro

    def hold_last_frame(self, seconds: float):
        """Durante un cambio de fuente pedido por el usuario, el driver sigue mostrando el
        último cuadro (como mucho `seconds`) en vez de pasar a «Sin señal»: abrir una
        webcam puede tardar varios segundos y el cartel parpadearía en cada cambio.
        Cuando llega la imagen nueva, simplemente la sustituye."""
        self._hold_until = time.monotonic() + seconds

    def back_buffer(self) -> np.ndarray:
        """Slot libre que debe llenar el productor antes de llamar a publish()."""
        with self._lock:
            slot = (self._get("latest_slot") + 1) % SLOT_COUNT
            self._set(f"slot_seq{slot}", 0)   # el driver no lo leerá mientras está en obras
            self._writing = slot
            return self._slots[slot]

    def publish(self):
        """Entrega el cuadro recién escrito en back_buffer()."""
        with self._lock:
            slot = self._writing
            if slot is None:
                return
            seq = (self._get("frame_seq") + 1) & 0xFFFFFFFF or 1   # 0 significa «en obras»
            self._set(f"slot_seq{slot}", seq)
            self._set("latest_slot", slot)
            self._set("frame_tick", _tick())
            self._set("frame_seq", seq)
            self._writing = None
        self.frames_in += 1

    def send(self, frame) -> bool:
        """Envía un cuadro NV12 completo (bytes o array). False si el tamaño no cuadra."""
        data = np.frombuffer(frame, dtype=np.uint8) if not isinstance(frame, np.ndarray) else frame.reshape(-1)
        if data.size != self.slot_size:
            return False
        self.back_buffer()[:] = data
        self.publish()
        return True

    def idle(self):
        """Sin cuadros nuevos el driver retiene el último 1,5 s y luego muestra
        «Sin señal»: no hace falta avisarle."""

    def close(self):
        """Cierra el envío. El driver pasa enseguida al cartel de app cerrada."""
        self._stop.set()
        self._beat.join(timeout=1.0)
        try:
            past = _tick() - 60_000
            self._set("heartbeat_tick", past)
            self._set("frame_tick", past)
        except ValueError:
            return   # ya cerrada
        self._slots = []
        try:
            self._mm.close()
        except BufferError:
            pass     # aún hay un búfer prestado: se libera cuando lo suelte el productor
