"""
Utilidades para gestión segura de procesos y terminación de árboles de procesos en Windows.
Garantiza que ningún subproceso (ffmpeg, ffplay, scrcpy) quede huérfano reteniendo la cámara web.
"""

import sys
import subprocess
import time
from typing import Optional, List
from core.interfaces import IProcessManager
from infrastructure.logging.app_logger import GLOBAL_LOGGER


class ProcessManager(IProcessManager):
    """Implementación de IProcessManager con soporte para árbol de procesos en Windows."""

    def start_process(self, cmd: List[str], stdin_pipe: bool = False, stdout_pipe: bool = False,
                      stderr_pipe: bool = True, no_window: bool = True) -> subprocess.Popen:
        flags = subprocess.CREATE_NO_WINDOW if (sys.platform == "win32" and no_window) else 0
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            stdout=subprocess.PIPE if stdout_pipe else subprocess.DEVNULL,
            stderr=subprocess.PIPE if stderr_pipe else subprocess.DEVNULL,
            creationflags=flags
        )

    def stop_process(self, proc: Optional[subprocess.Popen], graceful: bool = False, timeout: float = 3.0) -> None:
        """Detiene un proceso de forma limpia si es posible, o forzosa si no responde."""
        if not proc or proc.poll() is not None:
            return

        if graceful and proc.stdin:
            try:
                proc.stdin.write(b"q\n")
                proc.stdin.flush()
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                proc.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                GLOBAL_LOGGER.log(f"El proceso {proc.pid} no respondió a parada limpia. Forzando cierre...", "WARN")

        # Intentar terminación normal
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            self.kill_process_tree(proc)
        except Exception:
            self.kill_process_tree(proc)

    def kill_process_tree(self, proc: Optional[subprocess.Popen]) -> None:
        """Termina forzosamente un proceso y todos sus procesos hijos en Windows."""
        if not proc or proc.poll() is not None:
            return

        pid = proc.pid
        if sys.platform == "win32":
            try:
                # taskkill /F /T /PID mata de forma atómica el árbol completo del proceso
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=3.0
                )
            except Exception as e:
                GLOBAL_LOGGER.log(f"Error ejecutando taskkill sobre PID {pid}: {e}", "WARN")
                try:
                    proc.kill()
                except Exception:
                    pass
        else:
            try:
                proc.kill()
            except Exception:
                pass

        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass


GLOBAL_PROCESS_MANAGER = ProcessManager()


# Job de Windows con «matar al cerrar»: su handle solo lo tiene la app, así que al terminar ella
# (cierre normal, cuelgue o Administrador de tareas) Windows cierra el job y mata lo que haya dentro.
# Sin esto, un ffplay/ffmpeg lanzado justo mientras la app se cerraba seguía vivo con la cámara
# tomada. Solo entran los procesos de video: lo que se abre con el shell (navegador, reproductor,
# Explorador) no debe cerrarse junto con la app.
_app_job = None


def _create_app_job():
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # ExtendedLimitInformation
        raise ctypes.WinError(ctypes.get_last_error())
    return k32, job


def bind_to_app(proc: Optional[subprocess.Popen]) -> Optional[subprocess.Popen]:
    """Hace que el proceso muera con la app aunque esta no llegue a detenerlo."""
    global _app_job
    if sys.platform != "win32" or proc is None:
        return proc
    try:
        if _app_job is None:
            _app_job = _create_app_job()
        k32, job = _app_job
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):
            GLOBAL_LOGGER.log(f"No se pudo atar el PID {proc.pid} al cierre de la app.", "WARN")
    except Exception as e:
        GLOBAL_LOGGER.log(f"No se pudo atar el PID {proc.pid} al cierre de la app: {e}", "WARN")
    return proc
