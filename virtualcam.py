"""
UltraCam Studio - Cámara virtual de Windows

La cámara «UltraCam» la pone el driver propio (vcam_driver/): Zoom, Teams,
Discord, OBS y los navegadores la ven siempre, con la app abierta o cerrada. Aquí
solo se decide qué imagen le llega:
  - VirtualCamService: registra el driver al abrir la app y mantiene el enlace
    con él (sin imagen, el driver muestra «Sin señal»; con la app cerrada,
    «UltraCam Studio está cerrado»).
  - VirtualCamBridge: reparte el video de la fuente elegida a la cámara virtual
    y, en Android, también a la grabación.

La cámara virtual siempre recibe 1920x1080: el driver lo escala al modo que
elija cada programa, así cambiar de fuente o girar el teléfono nunca les cambia
el formato.
"""

import sys
import threading
import subprocess
from typing import Callable, Optional, Dict

from winpipes import NamedPipeServer, unique_name
from infrastructure.video import vcam_driver

DEVICE_NAME = vcam_driver.FRIENDLY_NAME
# Líneas de «-progress» de ffmpeg: se leen para saber cuándo llega imagen, no se registran.
PROGRESS_KEYS = ("frame=", "fps=", "stream_", "bitrate=", "total_size=", "out_time",
                 "dup_frames=", "drop_frames=", "speed=", "progress=")
OUTPUT_SIZE = (vcam_driver.WIDTH, vcam_driver.HEIGHT)

# Ritmo al que la app alimenta la cámara virtual. 30 cuadros por segundo es lo que
# usan Zoom, Meet, Teams y Discord, y así el reparto no le quita velocidad a la
# grabación, que sigue con los fps nativos de la cámara. Si un programa pide 60,
# el driver repite cuadros.
VCAM_FPS = 30

# Entrada de versiones anteriores: «UltraCam» apuntando al driver de OBS.
_LEGACY_INSTANCE = (r"Software\Classes\CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}"
                    r"\Instance\{7D129774-8B8E-47C2-9E9C-A2E4B17961C4}")


def _guard(log: Optional[Callable[[str, str], None]]) -> Callable[[str, str], None]:
    """Envuelve un registro de mensajes para que nunca tumbe a quien lo llama."""
    def safe(message: str, category: str = "VCAM"):
        try:
            if log:
                log(message, category)
        except Exception:
            pass
    return safe


def available() -> bool:
    """Hay driver para esta PC (Windows y la DLL compilada o empaquetada)."""
    return sys.platform == "win32" and vcam_driver.dll_path(64) is not None


def _remove_legacy_registration():
    """Borra la «UltraCam» de versiones anteriores, que dependía de OBS: si quedara,
    Windows mostraría dos cámaras con el mismo nombre."""
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _LEGACY_INSTANCE)
    except OSError:
        pass


class VirtualCamService:
    """Enlace con el driver mientras la app está abierta.

    Las fuentes se enganchan y desenganchan por debajo: los programas ven siempre el
    mismo dispositivo «UltraCam», que no aparece ni desaparece al cambiar de cámara.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.writer: Optional[vcam_driver.SharedFrameWriter] = None
        self.last_error: str = ""
        self._log: Callable[[str, str], None] = _guard(None)

    def start(self, log: Optional[Callable[[str, str], None]] = None) -> bool:
        """Registra el driver (sin permisos de administrador) y abre el enlace.
        Devuelve False si no se pudo; el motivo queda en last_error."""
        with self._lock:
            if log:
                self._log = _guard(log)
            if self.writer:
                return True
            if not available():
                self.last_error = "no se encontró el driver de la cámara virtual"
                return False
            try:
                _remove_legacy_registration()
                vcam_driver.register()
                self.writer = vcam_driver.SharedFrameWriter(fps=VCAM_FPS)
            except Exception as e:
                self.last_error = str(e)
                self._log(f"La cámara virtual «{DEVICE_NAME}» no pudo iniciarse: {e}", "WARN")
                return False
            self.last_error = ""
            self._log(f"Cámara «{DEVICE_NAME}» lista en Windows para cualquier programa.", "VCAM")
            return True

    def acquire(self) -> Optional[vcam_driver.SharedFrameWriter]:
        """Enlace listo para recibir cuadros de una fuente (lo abre si hace falta)."""
        with self._lock:
            if not self.writer:
                self.start()
            return self.writer

    def hold_last_frame(self, seconds: float):
        """Mantiene el último cuadro durante un cambio de fuente (ver SharedFrameWriter)."""
        with self._lock:
            if self.writer:
                self.writer.hold_last_frame(seconds)

    @property
    def running(self) -> bool:
        return self.writer is not None

    def status(self) -> Dict:
        with self._lock:
            return {
                "available": available(),
                "registered": vcam_driver.registered_name() is not None,
                "running": self.running,
                "size": OUTPUT_SIZE,
                "error": self.last_error,
            }

    def stop(self):
        """Cierra el enlace: el driver pasa al cartel «UltraCam Studio está cerrado»."""
        with self._lock:
            writer, self.writer = self.writer, None
        if writer:
            writer.close()


# Instancia única: se abre al arrancar el programa y se cierra al salir.
SERVICE = VirtualCamService()


class VirtualCamBridge:
    """
    Reparte el video a la cámara virtual y/o grabación en archivo local.
    mode="encoded" (Android): el pipe recibe MKV de scrcpy; un ffmpeg lo reparte a
        grabación (copia directa), a la cámara virtual (decodificado a NV12) y, si se
        pide `preview`, al monitor: con fuentes mayores que Full HD scrcpy no dibuja
        ventana y el mismo decodificador (por GPU) le entrega al monitor la imagen reducida.
    mode="raw" (PC): el pipe recibe cuadros NV12 crudos para la cámara virtual.

    El enlace con el driver (`sink`) lo presta el servicio y le sobrevive al
    puente: al terminar, el driver retiene el último cuadro y luego muestra «Sin señal».
    """

    def __init__(self, mode: str, width: int, height: int, fps: int, ffmpeg_path: Optional[str] = None,
                 log: Optional[Callable[[str, str], None]] = None, sink=None,
                 preview: Optional[Dict] = None):
        self.mode = mode
        self.width, self.height = int(width), int(height)
        self.fps = max(1, int(fps or 30))
        self.ffmpeg_path = ffmpeg_path
        self.record_path: Optional[str] = None
        self._log = _guard(log or (lambda m, c="VCAM": print(f"[{c}] {m}")))
        self.pipe_path = unique_name("video")
        self.sink = sink
        # {"cmd": reproductor que lee nut por stdin, "vf": filtro del monitor, "fps": tope}
        self.preview = preview
        self.on_first_frame: Optional[Callable[[], None]] = None
        self._pipe: Optional[NamedPipeServer] = None
        # Con monitor, la salida estándar es para él y la cámara virtual va por otro pipe.
        self._vc_pipe: Optional[NamedPipeServer] = None
        self._decoder: Optional[subprocess.Popen] = None
        self._player: Optional[subprocess.Popen] = None
        self._threads = []
        self._lock = threading.Lock()
        self._stopped = False
        self._done = threading.Event()

    @property
    def frames_sent(self) -> int:
        return self.sink.frames_sent if self.sink else 0

    @property
    def frame_bytes(self) -> int:
        return self.width * self.height * 3 // 2

    def start(self):
        if self.mode == "encoded" and not self.ffmpeg_path:
            raise RuntimeError("Se necesita ffmpeg para decodificar el video del teléfono.")
        self._pipe = NamedPipeServer(self.pipe_path)
        if self.mode == "encoded" and self.preview and self.sink:
            self._vc_pipe = NamedPipeServer(unique_name("vcam"))
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        self._threads.append(t)

    def _run(self):
        if not self._pipe.wait_client() or self._stopped:
            return
        if self.mode == "raw":
            self._pump_raw(self._pipe)
        else:
            self._pump_encoded()

    def _pump_raw(self, pipe: NamedPipeServer):
        """Lee cuadros NV12 enteros del pipe directamente sobre la memoria del driver.

        Sin copias intermedias: el pipe solo guarda un par de cuadros, y si Python
        se retrasa vaciándolo, ffmpeg se queda bloqueado escribiendo y la captura
        (y con ella la grabación) se vuelve lenta.
        """
        if not self.sink:
            while not self._stopped and pipe.read():
                pass
            return
        while not self._stopped:
            if not pipe.read_exact(self.sink.back_buffer()):
                break
            self.sink.publish()
        self.sink.idle()

    def _decoder_cmd(self) -> list:
        w, h = self.width, self.height
        cmd = [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostats", "-y",
               # El avance (frame=…) sale por stderr: el primer cuadro marca el inicio de la toma
               "-progress", "pipe:2", "-stats_period", "0.5",
               # Sin «nobuffer»: descarta los paquetes leídos al analizar el inicio y se perdía
               # el primer segundo (hasta el siguiente cuadro clave) en monitor, cámara y grabación.
               "-fflags", "discardcorrupt", "-flags", "low_delay",
               "-hwaccel", "auto",
               "-probesize", "512k", "-analyzeduration", "0",
               "-f", "matroska", "-i", "pipe:0"]
        if self.record_path:
            # «0:a?»: la pista guía del teléfono, si viene, para alinear el audio al unir la toma
            cmd += ["-map", "0:v", "-map", "0:a?", "-c", "copy", "-f", "matroska", self.record_path]
        if self.sink:
            # La cámara virtual se limita a VCAM_FPS: el archivo conserva los fps del
            # teléfono (va por copia directa) y el reparto no compite con la grabación.
            vf = (f"fps={min(self.fps, VCAM_FPS)},"
                  f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=fast_bilinear,"
                  f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=nv12")
            out = self._vc_pipe.path if self._vc_pipe else "pipe:1"
            cmd += ["-map", "0:v", "-vf", vf, "-fps_mode", "passthrough", "-f", "rawvideo", out]
        if self.preview:
            # El monitor sale del mismo cuadro ya decodificado: nada se decodifica dos veces.
            vf = f"fps={self.preview['fps']},{self.preview['vf']}"
            cmd += ["-map", "0:v", "-vf", vf, "-fps_mode", "passthrough",
                    "-c:v", "rawvideo", "-pix_fmt", "yuv420p", "-an", "-f", "nut", "pipe:1"]
        return cmd

    def _pump_encoded(self):
        no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._decoder = subprocess.Popen(self._decoder_cmd(), stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE if self.sink or self.preview else subprocess.DEVNULL,
                                             stderr=subprocess.PIPE, creationflags=no_window)
            if self.preview:
                self._player = subprocess.Popen(self.preview["cmd"], stdin=self._decoder.stdout,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                creationflags=no_window)
                self._decoder.stdout.close()
        except Exception as e:
            self._log(f"No se pudo iniciar el reparto de video: {e}", "ERROR")
            return
        dec = self._decoder

        def read_vcam_pipe():
            if self._vc_pipe.wait_client() and not self._stopped:
                self._pump_raw(self._vc_pipe)

        def read_frames():
            sink = self.sink
            while True:
                view = memoryview(sink.back_buffer()).cast("B")
                got = 0
                while got < view.nbytes:
                    n = dec.stdout.readinto(view[got:])
                    if not n:
                        sink.idle()
                        return
                    got += n
                sink.publish()

        def read_errors():
            started = False
            for raw in iter(dec.stderr.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith(PROGRESS_KEYS):
                    if not started and line.startswith("frame=") and line[6:].strip() not in ("", "0"):
                        started = True
                        if self.on_first_frame:
                            self.on_first_frame()
                    continue
                self._log(line, "VCAM")

        workers = [read_errors]
        if self._vc_pipe:
            workers.append(read_vcam_pipe)
        elif self.sink:
            workers.append(read_frames)
        for fn in workers:
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self._threads.append(t)

        # Se lee hasta que scrcpy cierre el pipe, aunque se pida parar: así la copia
        # al archivo de grabación recibe todos los datos.
        try:
            while True:
                data = self._pipe.read()
                if not data:
                    break
                dec.stdin.write(data)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                dec.stdin.close()
            except (BrokenPipeError, OSError):
                pass

    def stop(self, timeout: float = 8.0):
        """Llamar después de cerrar el productor: espera a que ffmpeg termine (y cierre la
        grabación). El enlace con el driver sigue abierto para la próxima fuente."""
        with self._lock:
            if self._stopped:
                self._done.wait(timeout + 3)
                return
            self._stopped = True
        for pipe in (self._pipe, self._vc_pipe):
            if pipe:
                pipe.unblock()
        dec = self._decoder
        if dec:
            try:
                dec.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                dec.kill()
        player = self._player
        if player and player.poll() is None:
            player.kill()
        for t in self._threads:
            t.join(timeout=2.0)
        for pipe in (self._pipe, self._vc_pipe):
            if pipe:
                pipe.close()
        if self.sink:
            self.sink.idle()
        self._done.set()
