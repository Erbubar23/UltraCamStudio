"""
UltraCam Studio - Entrada MIDI (Windows, winmm)

Teclados y controladores MIDI por la API multimedia de Windows (winmm) con ctypes:
sin dependencias extra y sin driver propio. Cada mensaje llega en un hilo de winmm;
aquí solo se decodifica y se entrega al callback (que debe ser rápido: en UltraCam
encola el mensaje para el callback de audio).

Solo mensajes cortos (notas, CC, pitch bend, aftertouch, program change). Los SysEx
se ignoran: los instrumentos VST3 no los necesitan para tocar.
"""

import ctypes
from ctypes import wintypes
from typing import Callable, Dict, List, Optional

MIM_DATA = 0x3C3
CALLBACK_FUNCTION = 0x00030000

# Bytes de datos que sigue a cada tipo de mensaje de canal (nibble alto del status)
_DATA_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}


class _MIDIINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * 32), ("dwSupport", wintypes.DWORD)]


_MidiInProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t,
                                 ctypes.c_size_t, ctypes.c_size_t)


def _winmm():
    return ctypes.windll.winmm


def list_inputs() -> List[str]:
    """Nombres de las entradas MIDI, en el orden de winmm. Nombres repetidos (dos
    teclados iguales) llevan « #2», « #3»… para poder elegirlos por separado."""
    try:
        w = _winmm()
        n = w.midiInGetNumDevs()
    except (OSError, AttributeError):
        return []
    names, seen = [], {}
    for i in range(n):
        caps = _MIDIINCAPSW()
        if w.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) != 0:
            continue
        base = caps.szPname or f"MIDI {i + 1}"
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base} #{seen[base]}")
    return names


def decode(packed: int) -> Optional[bytes]:
    """Mensaje corto de winmm (status | d1 << 8 | d2 << 16) → bytes MIDI, o None si
    no es un mensaje de canal (reloj, active sensing, SysEx…)."""
    status = packed & 0xFF
    kind = status & 0xF0
    n = _DATA_LEN.get(kind)
    if n is None:
        return None
    d1 = (packed >> 8) & 0x7F
    d2 = (packed >> 16) & 0x7F
    # Note On con velocidad 0 es un Note Off (muchos teclados lo mandan así)
    if kind == 0x90 and d2 == 0:
        return bytes((0x80 | (status & 0x0F), d1, 0))
    return bytes((status, d1, d2)) if n == 2 else bytes((status, d1))


class MidiInput:
    """Una entrada MIDI abierta. `on_message(nombre, bytes)` se llama desde el hilo de winmm."""

    def __init__(self, name: str, on_message: Callable[[str, bytes], None]):
        self.name = name
        self.on_message = on_message
        self.handle = wintypes.HANDLE()
        self._proc = _MidiInProc(self._callback)     # guardar la referencia: winmm la llama después
        self.opened = False

    def _callback(self, _h, msg, _inst, param1, _param2):
        if msg != MIM_DATA:
            return
        data = decode(int(param1))
        if data is not None:
            try:
                self.on_message(self.name, data)
            except Exception:
                pass

    def open(self) -> bool:
        names = list_inputs()
        if self.name not in names:
            raise OSError(f"No se encontró la entrada MIDI «{self.name}».")
        w = _winmm()
        err = w.midiInOpen(ctypes.byref(self.handle), names.index(self.name),
                           ctypes.cast(self._proc, ctypes.c_void_p), 0, CALLBACK_FUNCTION)
        if err != 0:
            raise OSError(f"«{self.name}» está ocupada por otro programa (código {err}).")
        w.midiInStart(self.handle)
        self.opened = True
        return True

    def close(self):
        if not self.opened:
            return
        self.opened = False
        w = _winmm()
        try:
            w.midiInStop(self.handle)
            w.midiInReset(self.handle)
            w.midiInClose(self.handle)
        except OSError:
            pass


class MidiRouter:
    """Abre las entradas MIDI que piden los canales y reparte cada mensaje a los canales
    que escuchan esa entrada y ese canal MIDI (1–16, u Omni = todos)."""

    ALL = "*"

    def __init__(self, log: Callable[[str, str], None]):
        self.log = log
        self.inputs: Dict[str, MidiInput] = {}
        self.routes: tuple = ()            # ((entrada o "*", canal MIDI 0=omni, destino), ...)
        # «Toca una tecla para asignar»: con learning, todas las entradas quedan abiertas y la
        # primera nota que llegue se informa con on_learn(entrada, canal MIDI 1–16).
        self.learning = False
        self.on_learn: Optional[Callable[[str, int], None]] = None

    def set_learning(self, on: bool):
        self.learning = on
        self.set_routes(list(self.routes))       # abre (o vuelve a cerrar) las entradas sin canal

    def set_routes(self, routes: List[tuple]):
        """routes: [(entrada, canal_midi, destino)], donde destino tiene .midi_push(bytes).
        Abre las entradas nuevas y cierra las que ya nadie usa."""
        wanted = set()
        available = list_inputs()
        if self.learning:
            wanted.update(available)
        for dev, _mch, _dst in routes:
            if dev == self.ALL:
                wanted.update(available)
            elif dev:
                wanted.add(dev)
        for name in list(self.inputs):
            if name not in wanted:
                self.inputs.pop(name).close()
        for name in wanted:
            if name in self.inputs:
                continue
            mi = MidiInput(name, self._on_message)
            try:
                mi.open()
                self.inputs[name] = mi
                self.log(f"Entrada MIDI abierta: {name}", "MIDI")
            except OSError as e:
                self.log(str(e), "WARN")
        self.routes = tuple(routes)

    def failed(self, dev: str) -> bool:
        """True si el canal pidió esa entrada concreta y no se pudo abrir."""
        return bool(dev) and dev != self.ALL and dev not in self.inputs

    def _on_message(self, dev: str, data: bytes):
        mch = (data[0] & 0x0F) + 1
        if self.learning and data[0] & 0xF0 == 0x90:
            self.learning = False                # solo la primera nota; las entradas se cierran al aplicar
            if self.on_learn:
                self.on_learn(dev, mch)
        for want_dev, want_ch, dst in self.routes:
            if want_dev != self.ALL and want_dev != dev:
                continue
            if want_ch and want_ch != mch:
                continue
            dst.midi_push(data)

    def close(self):
        for mi in self.inputs.values():
            mi.close()
        self.inputs = {}
        self.routes = ()
