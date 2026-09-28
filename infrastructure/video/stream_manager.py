"""
Gestor de ciclo de vida de streams y subprocesos de video.
Garantiza sincronización segura entre hilos, liberación de cámaras y prevención de procesos huérfanos.
"""

import re
import sys
import time
import threading
import subprocess
from typing import Optional, Callable, Dict, Any, List
from infrastructure.logging.app_logger import GLOBAL_LOGGER
from infrastructure.system.process_utils import GLOBAL_PROCESS_MANAGER, bind_to_app
from infrastructure.system.win32_window import GLOBAL_WINDOW_EMBEDDER
from infrastructure.video.command_builder import preview_player_command


class StreamManager:
    """Administra la ejecución de procesos de streaming (scrcpy / ffmpeg / ffplay)."""

    def __init__(self):
        self._lock = threading.RLock()
        self.process: Optional[subprocess.Popen] = None
        self.preview_process: Optional[subprocess.Popen] = None
        self.hw_dialog_process: Optional[subprocess.Popen] = None
        self.vcam = None
        self.is_running: bool = False
        self._graceful_stop: bool = False
        # scrcpy grabando: se le cierra la ventana (como el botón X) para que escriba el final
        # del .mkv; matarlo pierde el último bloque del archivo (hasta ~5 MB o 5 s de video).
        self._close_window_title: Optional[str] = None
        self.recording_started: threading.Event = threading.Event()
        self.current_recording_file: Optional[str] = None
        # Momento del primer cuadro, en el reloj de time.monotonic(): ffmpeg (dshow) lo informa
        # como «start:»; si no, se usa cuando se detecta que el archivo empezó a grabarse.
        # Sirve para alinear el audio al unir la toma.
        self.video_start_ts: Optional[float] = None
        self.recording_started_at: Optional[float] = None
        self.embedded_hwnd: Optional[int] = None

    def start_stream(self, cmd: List[str], is_ffmpeg_rec: bool, piped_preview: bool,
                     ffplay_path: Optional[str], window_title: str, vcam_bridge=None,
                     on_exit: Optional[Callable[[int], None]] = None) -> bool:
        with self._lock:
            if self.is_running:
                return True

            self.vcam = vcam_bridge
            self._graceful_stop = is_ffmpeg_rec
            records = any(str(a).startswith("--record=") for a in cmd)
            # Con --no-window el monitor es un ffplay con el mismo título: no hay que cerrarle nada.
            has_window = "--no-window" not in cmd
            self._close_window_title = window_title if records and not is_ffmpeg_rec and has_window else None
            no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

            try:
                # stdout se lee siempre: scrcpy escribe ahí sus INFO, entre ellos «Texture:», que
                # sale al decodificar el primer cuadro. El tamaño del .mkv no sirve (el muxer retiene
                # los datos hasta juntar ~5 MB o 5 s) y «Recording started» sale antes de abrir la cámara.
                self.process = bind_to_app(subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=no_window
                ))
                proc = self.process

                if piped_preview and ffplay_path:
                    self.preview_process = bind_to_app(subprocess.Popen(
                        preview_player_command(ffplay_path, window_title),
                        stdin=proc.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=no_window
                    ))
                    proc.stdout.close()

                self.is_running = True
                self.recording_started.clear()
                self.video_start_ts = None
                self.recording_started_at = None
                started_evt = self.recording_started
                if vcam_bridge is not None:
                    # Sin ventana, scrcpy no escribe «Texture:»: el primer cuadro lo avisa el reparto.
                    vcam_bridge.on_first_frame = lambda: self._mark_started(started_evt)
                GLOBAL_LOGGER.log(f"Proceso de streaming iniciado con PID {proc.pid}", "PROCESS")

                progress_keys = ("frame=", "fps=", "stream_", "bitrate=", "total_size=", "out_time",
                                 "dup_frames=", "drop_frames=", "speed=", "progress=")

                def monitor_output(stream, prefix: str):
                    for raw in iter(stream.readline, b""):
                        clean_l = raw.decode("utf-8", errors="replace").strip()
                        if not clean_l:
                            continue
                        if clean_l.startswith(progress_keys):
                            if clean_l.startswith("frame=") and clean_l[6:].strip() not in ("", "0"):
                                self._mark_started(started_evt)
                            continue
                        if clean_l.startswith("INFO: Texture:"):
                            self._mark_started(started_evt)
                        if self.video_start_ts is None and clean_l.startswith("Duration:"):
                            m = re.search(r"start: (-?[\d.]+)", clean_l)
                            if m:
                                self.video_start_ts = float(m.group(1))
                        GLOBAL_LOGGER.log(clean_l, prefix)
                    stream.close()

                threading.Thread(target=monitor_output, args=(proc.stderr, "STREAM-ERR"), daemon=True).start()
                if not piped_preview:
                    threading.Thread(target=monitor_output, args=(proc.stdout, "STREAM-OUT"), daemon=True).start()

                def wait_for_exit():
                    code = proc.wait()
                    with self._lock:
                        if self.process is proc:
                            self.is_running = False
                            self._cleanup_preview()
                            self._cleanup_vcam()
                            self.process = None
                    GLOBAL_LOGGER.log(f"Streaming finalizó con código {code}", "PROCESS")
                    if on_exit:
                        on_exit(code)

                threading.Thread(target=wait_for_exit, daemon=True).start()
                return True

            except Exception as e:
                GLOBAL_LOGGER.error(f"Error iniciando streaming: {e}", e, "ERROR")
                self.is_running = False
                self._cleanup_vcam()
                self._cleanup_preview()
                if self.process:
                    GLOBAL_PROCESS_MANAGER.kill_process_tree(self.process)
                    self.process = None
                return False

    def _mark_started(self, evt: threading.Event):
        if self.recording_started_at is None:
            self.recording_started_at = time.monotonic()
        evt.set()

    def stop_stream(self) -> None:
        """
        Detiene la transmisión de forma segura.
        Desvincula la ventana incrustada, termina el árbol de procesos de video
        y garantiza que la cámara web DirectShow quede libre.
        """
        with self._lock:
            # 1. Desvincular ventana incrustada antes de matar procesos
            if self.embedded_hwnd:
                GLOBAL_WINDOW_EMBEDDER.detach_window(self.embedded_hwnd)
                self.embedded_hwnd = None

            # 2. Detener proceso principal de video
            proc = self.process
            self.process = None
            self.is_running = False

            if proc and proc.poll() is None and self._close_window_title:
                self._close_window(proc, self._close_window_title)
            if proc and proc.poll() is None:
                GLOBAL_PROCESS_MANAGER.stop_process(proc, graceful=self._graceful_stop, timeout=4.0)

            # 3. Limpiar proceso monitor de vista previa
            self._cleanup_preview()

            # 4. Detener diálogo de hardware si estuviera abierto
            if self.hw_dialog_process and self.hw_dialog_process.poll() is None:
                GLOBAL_PROCESS_MANAGER.kill_process_tree(self.hw_dialog_process)
                self.hw_dialog_process = None

            # 5. Cerrar puente hacia cámara virtual
            self._cleanup_vcam()

            GLOBAL_LOGGER.log("Streaming y procesos de cámara detenidos limpiamente.", "PROCESS")

    @staticmethod
    def _close_window(proc: subprocess.Popen, title: str, timeout: float = 5.0) -> None:
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        # El monitor suele seguir incrustado en la interfaz (ventana hija): FindWindow no lo ve.
        found = []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def match(h, _l):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, buf, 256)
            if buf.value == title:
                found.append(h)
                return False
            return True

        user32.EnumChildWindows(user32.GetDesktopWindow(), proto(match), 0)   # recorre también las hijas
        if not found:
            return
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW(found[0], 0x0010, 0, 0)       # WM_CLOSE
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            GLOBAL_LOGGER.log(f"scrcpy no cerró solo en {timeout:.0f} s; se fuerza el cierre.", "WARN")

    def _cleanup_preview(self):
        pv = self.preview_process
        self.preview_process = None
        if pv and pv.poll() is None:
            GLOBAL_PROCESS_MANAGER.kill_process_tree(pv)

    def _cleanup_vcam(self):
        bridge = self.vcam
        self.vcam = None
        if bridge:
            try:
                bridge.stop()
            except Exception as e:
                GLOBAL_LOGGER.log(f"Aviso al detener puente de cámara virtual: {e}", "WARN")
