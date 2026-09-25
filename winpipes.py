"""
Pipes con nombre de Win32 (\\\\.\\pipe\\...) para pasar video y audio entre procesos
(scrcpy/ffmpeg <-> UltraCam) sin archivos intermedios.
"""

import os
import itertools

_counter = itertools.count(1)


def unique_name(tag: str) -> str:
    return rf"\\.\pipe\ultracam_{tag}_{os.getpid()}_{next(_counter)}"


class NamedPipeServer:
    """Lado servidor de un pipe de un solo sentido. El otro proceso lo abre como un archivo."""

    INBOUND, OUTBOUND = 0x1, 0x2

    def __init__(self, name: str, direction: int = INBOUND, buffer: int = 4 * 1024 * 1024):
        import ctypes
        from ctypes import wintypes
        self._ct = ctypes
        self._wt = wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateNamedPipeW.restype = wintypes.HANDLE
        k32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                         wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        k32.ConnectNamedPipe.restype = wintypes.BOOL
        k32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        k32.ReadFile.restype = wintypes.BOOL
        k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        k32.WriteFile.restype = wintypes.BOOL
        k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self._k32 = k32
        self.path = name
        self.direction = direction
        in_buf = buffer if direction == self.INBOUND else 0
        out_buf = buffer if direction == self.OUTBOUND else 0
        # PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT, una sola instancia
        h = k32.CreateNamedPipeW(name, direction, 0x0, 1, out_buf, in_buf, 0, None)
        if not h or h == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), f"No se pudo crear el pipe {name}")
        self._h = h
        self._closed = False

    def wait_client(self) -> bool:
        ok = self._k32.ConnectNamedPipe(self._h, None)
        return bool(ok) or self._ct.get_last_error() == 535  # ERROR_PIPE_CONNECTED

    def read(self, size: int = 1024 * 1024) -> bytes:
        buf = self._ct.create_string_buffer(size)
        n = self._wt.DWORD(0)
        if not self._k32.ReadFile(self._h, buf, size, self._ct.byref(n), None) or n.value == 0:
            return b""  # ERROR_BROKEN_PIPE: el otro extremo cerró
        return buf.raw[:n.value]

    def readinto(self, view) -> int:
        """Lee sobre un búfer ya reservado, sin copias intermedias.

        Es el camino del video crudo: un cuadro de 1080p en NV12 pesa 3 MB, así que
        copiarlo de más (una vez al leerlo y otra al guardarlo) cuesta decenas de MB
        por segundo de memoria y, sobre todo, frena a quien escribe en el pipe: si
        Python no vacía el pipe a tiempo, ffmpeg se bloquea y la grabación se ralentiza.
        """
        mv = memoryview(view).cast("B")
        size = mv.nbytes
        if size <= 0:
            return 0
        buf = (self._ct.c_char * size).from_buffer(mv)
        n = self._wt.DWORD(0)
        ok = self._k32.ReadFile(self._h, buf, size, self._ct.byref(n), None)
        del buf          # libera la exportación del búfer antes de devolverlo
        return n.value if ok else 0

    def read_exact(self, view) -> bool:
        """Llena el búfer completo (varias lecturas si hace falta). False si el pipe cerró."""
        mv = memoryview(view).cast("B")
        got = 0
        total = mv.nbytes
        while got < total:
            n = self.readinto(mv[got:])
            if n <= 0:
                return False
            got += n
        return True

    def write(self, data: bytes) -> bool:
        n = self._wt.DWORD(0)
        return bool(self._k32.WriteFile(self._h, data, len(data), self._ct.byref(n), None))

    def unblock(self):
        """Desbloquea un ConnectNamedPipe pendiente conectándose como cliente."""
        access = 0x40000000 if self.direction == self.INBOUND else 0x80000000  # GENERIC_WRITE / GENERIC_READ
        h = self._k32.CreateFileW(self.path, access, 0, None, 3, 0, None)  # OPEN_EXISTING
        if h and h != self._wt.HANDLE(-1).value:
            self._k32.CloseHandle(h)

    def close(self):
        if not self._closed:
            self._closed = True
            self._k32.CloseHandle(self._h)
