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
