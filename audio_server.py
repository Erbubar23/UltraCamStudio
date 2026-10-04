"""
UltraCam Studio - Servidor de audio (proceso separado)

Arquitectura (como JUCE / Ableton / Reaper):
  - Un DISPOSITIVO PRINCIPAL marca el reloj: ASIO (un solo driver para entrada y salida)
    o Windows Audio (WASAPI; entrada y salida pueden ser dispositivos distintos).
    Su callback de tiempo real hace: entradas -> efectos VST3 -> mezcla -> Monitor.
  - FUENTES EXTRA (otros dispositivos, loopback "lo que suena") se capturan por WASAPI
    con PyAudioWPatch y se sincronizan al reloj principal con remuestreo adaptativo
    (compensación de deriva), igual que hacen OBS y los DAW al mezclar interfaces.
  - CANALES DE INSTRUMENTO: un VST3 instrumento (sintetizador, sampler) que se toca con
    un teclado MIDI. La entrada MIDI (winmm) encola los mensajes y el callback se los
    entrega al instrumento al inicio de cada bloque.
  - Dos buses: MASTER (grabación y OBS) y MONITOR (audífonos, sin retraso extra).
  - Fuera del callback: escritura de WAV, vúmetros y envío a OBS, en otro hilo.

Corre en su propio proceso porque las ventanas de los plugins VST3 solo pueden
abrirse desde el hilo principal del proceso que los aloja (y así un plugin que
falle no tumba la interfaz). El proceso principal habla con él por un Pipe
(ver audio_engine.AudioEngine).
"""

import os
import sys
import time
import math
import wave
import base64
import queue
import threading
import collections
import traceback
from typing import Dict, List, Optional

# El PortAudio con soporte ASIO de sounddevice se elige con esta variable antes de importarlo
os.environ.setdefault("SD_ENABLE_ASIO", "1")

import numpy as np

from midi_input import MidiRouter, list_inputs

SAMPLE_RATES = (44100, 48000, 88200, 96000)
BUFFER_SIZES = (64, 128, 256, 512, 1024)
METER_MAX_INPUTS = 16        # entradas que se miden al elegir la de un canal nuevo


def _dbfs(peak: float) -> float:
    if peak <= 1e-6:
        return -90.0
    return max(-90.0, 20.0 * math.log10(peak))


# =============================================================================
# FUENTE EXTRA CON COMPENSACIÓN DE DERIVA
# =============================================================================
class DriftBuffer:
    """Recibe audio de un dispositivo con su propio reloj y lo entrega al ritmo del
    dispositivo principal. Remuestrea con interpolación lineal y ajusta la razón
    de remuestreo según el nivel de llenado (control proporcional ±0.5 %), para que
    dos relojes distintos no provoquen cortes ni retraso creciente."""

    def __init__(self, channels: int, in_rate: int, out_rate: int, block: int, mode: str = "stereo"):
        self.channels = channels
        self.base_step = in_rate / float(out_rate)
        self.step = self.base_step
        self.mode = mode
        self.lock = threading.Lock()
        self.chunks: collections.deque = collections.deque()
        self.count = 0
        self.target = max(block * 3, out_rate // 50)     # ~20 ms de colchón
        self.max_frames = self.target * 6
        self.primed = False
        self.pos = 0.0
        self.last = np.zeros((1, 2), dtype=np.float32)

    def _to_stereo(self, raw: bytes) -> np.ndarray:
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) * (1.0 / 32768.0)
        ch = self.channels
        if ch == 1:
            return np.column_stack((arr, arr))
        arr = arr.reshape(-1, ch)
        if self.mode == "mono":
            m = arr[:, 0]
            return np.column_stack((m, m))
        return arr[:, :2].copy()

    def _resample(self, x: np.ndarray) -> np.ndarray:
        step = self.step
        if abs(step - 1.0) < 1e-9 and abs(self.pos) < 1e-9:
            return x
        src = np.vstack((self.last, x))
        m = len(x)
        t = np.arange(self.pos, m, step)
        self.pos = (t[-1] + step - m) if len(t) else self.pos - m
        self.last = x[-1:].copy()
        if not len(t):
            return np.zeros((0, 2), dtype=np.float32)
        idx = np.arange(m + 1)
        return np.column_stack((np.interp(t, idx, src[:, 0]), np.interp(t, idx, src[:, 1]))).astype(np.float32)

    def push(self, raw: bytes):
        try:
            out = self._resample(self._to_stereo(raw))
        except Exception:
            return
        with self.lock:
            self.chunks.append(out)
            self.count += len(out)
            while self.count > self.max_frames and self.chunks:
                old = self.chunks.popleft()
                self.count -= len(old)

    def pull(self, n: int) -> np.ndarray:
        out = np.zeros((n, 2), dtype=np.float32)
        with self.lock:
            if not self.primed:
                if self.count < self.target:
                    return out
                self.primed = True
            filled = 0
            while filled < n and self.chunks:
                c = self.chunks[0]
                take = min(n - filled, len(c))
                out[filled:filled + take] = c[:take]
                filled += take
                if take == len(c):
                    self.chunks.popleft()
                else:
                    self.chunks[0] = c[take:]
            self.count -= filled
            if filled < n:
                self.primed = False
            # Control de deriva: si sobra audio, consumir un poco más rápido; si falta, más lento
            err = (self.count - self.target) / float(self.target)
            self.step = self.base_step * (1.0 + max(-0.005, min(0.005, 0.002 * err)))
        return out


# =============================================================================
# CANAL
# =============================================================================
class FxSlot:
    def __init__(self, fid: str, path: str, enabled: bool = True):
        self.id = fid
        self.path = path
        self.enabled = enabled
        self.plugin = None
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.error: Optional[str] = None


class Channel:
    """Estado de un canal. El callback solo LEE estos campos; los cambios se hacen
    reemplazando valores completos (asignaciones atómicas en Python)."""

    def __init__(self, cfg: Dict):
        self.id = cfg["id"]
        self.name = cfg.get("name", self.id)
        self.source = cfg.get("source", {"kind": "none"})
        self.mode = cfg.get("mode", "mono")
        self.volume = float(cfg.get("volume", 1.0))
        self.mute = bool(cfg.get("mute", False))
        self.solo = bool(cfg.get("solo", False))
        self.monitor = bool(cfg.get("monitor", False))
        self.fx: List[FxSlot] = []
        self.active_fx: tuple = ()          # plugins listos, en orden (lo que usa el callback)
        self.cols: Optional[List[int]] = None   # columnas del dispositivo principal
        self.buf: Optional[DriftBuffer] = None  # fuente extra
        self.inst: Optional[FxSlot] = None      # instrumento VST3 (fuente "instrument")
        self.inst_plugin = None                 # lo que usa el callback (None si no cargó)
        self.midi_q: collections.deque = collections.deque(maxlen=512)
        self.midi_hits = 0                      # mensajes recibidos (para el indicador de actividad)
        self.error: Optional[str] = None

    def midi_push(self, data: bytes):
        """Llamado desde el hilo de winmm (o de un comando): el callback lo toma en el próximo bloque."""
        self.midi_q.append(data)
        self.midi_hits += 1

    def drain_midi(self) -> list:
        msgs = []
        q = self.midi_q
        while q:
            try:
                msgs.append((q.popleft(), 0.0))
            except IndexError:
                break
        return msgs

    def panic(self):
        """Suelta todas las notas y el pedal en los 16 canales MIDI (tras recargar la configuración)."""
        for c in range(16):
            self.midi_q.append(bytes((0xB0 | c, 64, 0)))
            self.midi_q.append(bytes((0xB0 | c, 123, 0)))


# =============================================================================
# SERVIDOR
# =============================================================================
class AudioServer:
    def __init__(self, conn):
        self.conn = conn
        self.send_lock = threading.Lock()
        self.main_jobs: "queue.Queue" = queue.Queue()      # trabajos del hilo principal (ventanas de plugins)
        self.running = True
        self.sd = None
        self.pa = None                                     # PyAudioWPatch para fuentes extra
        self.cfg: Dict = {}
        self.sr = 48000
        self.block = 256
        self.channels: List[Channel] = []
        self.rt_channels: tuple = ()
        self.master_volume = 1.0
        self.monitor_volume = 1.0
        self.stream = None
        self.extra_streams = []
        self.clock_thread: Optional[threading.Thread] = None
        self.clock_stop = threading.Event()
        self.out_q: "queue.Queue" = queue.Queue(maxsize=400)
        self.xruns = 0
        self.dropped = 0
        self.device_info: Dict = {}
        self.last_error: Optional[str] = None
        # Grabación
        self.rec_lock = threading.Lock()
        self.rec_files: Optional[Dict] = None
        self.rec_frames = 0
        self.clipping = False
        # Envío a OBS (master como PCM s16le por un pipe con nombre)
        self.feed = None
        # Editor abierto
        self.editor_close: Optional[threading.Event] = None
        # Teclados y controladores MIDI
        self.midi = MidiRouter(self.log)
        self.midi.on_learn = lambda dev, mch: self.send("midi_learned", dev=dev, ch=mch)
        # Medir todas las entradas del dispositivo principal (al agregar un canal: se ve
        # cuál se mueve al hablar o tocar), aunque ningún canal las use todavía. Los otros
        # micrófonos de Windows se miden con flujos propios: {nombre: pico desde el último envío}.
        self.meter_inputs = False
        self.meter_streams = []
        self.dev_peaks: Dict[str, float] = {}

    # ------------------------------------------------------------------ IPC
    def send(self, kind: str, **data):
        try:
            with self.send_lock:
                self.conn.send((kind, data))
        except Exception:
            self.running = False

    def log(self, msg: str, cat: str = "AUDIO"):
        self.send("log", msg=msg, cat=cat)

    def reply(self, rid, ok=True, **data):
        if rid is not None:
            self.send("reply", rid=rid, ok=ok, **data)

    # ------------------------------------------------------------ Dispositivos
    def _import_sd(self):
        if self.sd is None:
            import sounddevice as sd
            self.sd = sd
        return self.sd

    def _import_pa(self):
        if self.pa is None:
            import pyaudiowpatch as pyaudio
            self.pa_mod = pyaudio
            self.pa = pyaudio.PyAudio()
        return self.pa

    def list_devices(self) -> Dict:
        sd = self._import_sd()
        out = {"asio": [], "wasapi_in": [], "wasapi_out": [], "extra": [], "default_in": None, "default_out": None}
        for i, d in enumerate(sd.query_devices()):
            api = sd.query_hostapis(d["hostapi"])["name"]
            item = {"name": d["name"], "in": d["max_input_channels"], "out": d["max_output_channels"],
                    "sr": int(d["default_samplerate"])}
            if api == "ASIO":
                out["asio"].append(item)
            elif api == "Windows WASAPI":
                if d["max_input_channels"] > 0:
                    out["wasapi_in"].append(item)
                if d["max_output_channels"] > 0:
                    out["wasapi_out"].append(item)
        try:
            api = sd.query_hostapis()
            wasapi = next(h for h in api if h["name"] == "Windows WASAPI")
            if wasapi["default_input_device"] >= 0:
                out["default_in"] = sd.query_devices(wasapi["default_input_device"])["name"]
            if wasapi["default_output_device"] >= 0:
                out["default_out"] = sd.query_devices(wasapi["default_output_device"])["name"]
        except Exception as e:
            self.log(f"No se pudieron obtener dispositivos WASAPI por defecto: {e}", "DEBUG")
        # Fuentes extra: entradas WASAPI y loopbacks ("lo que suena" en cada salida)
        try:
            pa = self._import_pa()
            wasapi_idx = pa.get_host_api_info_by_type(self.pa_mod.paWASAPI)["index"]
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                if d["hostApi"] != wasapi_idx or d.get("maxInputChannels", 0) <= 0:
                    continue
                loop = bool(d.get("isLoopbackDevice", False))
                out["extra"].append({"name": d["name"].replace(" [Loopback]", ""), "loopback": loop,
                                     "in": int(d["maxInputChannels"]), "sr": int(d["defaultSampleRate"])})
        except Exception as e:
            self.log(f"No se pudieron listar fuentes extra: {e}", "WARN")
        out["midi_in"] = list_inputs()
        return out

    def _find_sd_device(self, name: Optional[str], api_name: str, need_in: bool, need_out: bool) -> Optional[int]:
        if not name:
            return None
        sd = self._import_sd()
        for i, d in enumerate(sd.query_devices()):
            if d["name"] != name or sd.query_hostapis(d["hostapi"])["name"] != api_name:
                continue
            if need_in and d["max_input_channels"] <= 0:
                continue
            if need_out and d["max_output_channels"] <= 0:
                continue
            return i
        return None

    def _find_pa_device(self, name: str, loopback: bool) -> Optional[Dict]:
        pa = self._import_pa()
        wasapi_idx = pa.get_host_api_info_by_type(self.pa_mod.paWASAPI)["index"]
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d["hostApi"] != wasapi_idx or d.get("maxInputChannels", 0) <= 0:
                continue
            if bool(d.get("isLoopbackDevice", False)) != loopback:
                continue
            if d["name"].replace(" [Loopback]", "") == name:
                return d
        return None

    # --------------------------------------------------------------- Plugins
    def _load_plugin(self, path: str):
        import pedalboard
        from vst_probe import plugin_binary
        return pedalboard.load_plugin(plugin_binary(path))

    def _prepare_fx(self, ch: Channel, fx_cfg: List[Dict]):
        """Carga los plugins de un canal (en el hilo principal, como pide JUCE)."""
        slots = []
        old = {s.id: s for s in ch.fx}
        for f in fx_cfg:
            slot = old.get(f["id"])
            if slot is None or slot.path != f["path"]:
                slot = FxSlot(f["id"], f["path"], f.get("enabled", True))
                try:
                    slot.plugin = self._load_plugin(f["path"])
                    slot.name = getattr(slot.plugin, "name", slot.name) or slot.name
                    if f.get("state"):
                        try:
                            slot.plugin.raw_state = base64.b64decode(f["state"])
                        except Exception as e:
                            self.log(f"{slot.name}: no se pudo restaurar su preset ({e})", "WARN")
                except Exception as e:
                    slot.error = str(e)
                    self.log(f"No se pudo cargar el plugin {os.path.basename(f['path'])}: {e}", "ERROR")
            slot.enabled = f.get("enabled", True)
            slots.append(slot)
        ch.fx = slots
        ch.active_fx = tuple(s.plugin for s in slots if s.enabled and s.plugin is not None)
        self.send("fx_loaded", ch=ch.id, fx=[{"id": s.id, "name": s.name, "error": s.error} for s in slots])

    def _prepare_instrument(self, ch: Channel, prev: Optional[Channel]):
        """Carga (o reutiliza) el instrumento VST3 de un canal con fuente "instrument"."""
        src = ch.source
        path = src.get("path") or ""
        if not path:
            ch.error = "Elige un instrumento"
            return
        slot = prev.inst if prev is not None else None
        if slot is None or slot.path != path or slot.id != src.get("id"):
            slot = FxSlot(src.get("id") or "inst", path)
            try:
                slot.plugin = self._load_plugin(path)
                slot.name = getattr(slot.plugin, "name", slot.name) or slot.name
                if not getattr(slot.plugin, "is_instrument", False):
                    slot.error = "Este plugin es un efecto, no un instrumento"
                    slot.plugin = None
                elif src.get("state"):
                    try:
                        slot.plugin.raw_state = base64.b64decode(src["state"])
                    except Exception as e:
                        self.log(f"{slot.name}: no se pudo restaurar su preset ({e})", "WARN")
            except Exception as e:
                slot.error = str(e)
                self.log(f"No se pudo cargar el instrumento {os.path.basename(path)}: {e}", "ERROR")
        ch.inst = slot
        ch.inst_plugin = slot.plugin
        if slot.error:
            ch.error = slot.error
        ch.panic()
        self.send("inst_loaded", ch=ch.id, name=slot.name, error=slot.error)

    def _slot(self, ch_id: str, fx_id: str) -> Optional[FxSlot]:
        """Efecto o instrumento de un canal, por su id."""
        ch = self._channel(ch_id)
        if ch is None:
            return None
        if ch.inst is not None and ch.inst.id == fx_id:
            return ch.inst
        return next((s for s in ch.fx if s.id == fx_id), None)

    def _fx_state(self, ch_id: str, fx_id: str) -> Optional[str]:
        slot = self._slot(ch_id, fx_id)
        if slot and slot.plugin is not None:
            try:
                return base64.b64encode(bytes(slot.plugin.raw_state)).decode("ascii")
            except Exception as e:
                self.log(f"No se pudo guardar estado del efecto {slot.name}: {e}", "WARN")
                return None
        return None

    def _open_editor(self, ch_id: str, fx_id: str):
        ch = self._channel(ch_id)
        slot = self._slot(ch_id, fx_id)
        if not slot or slot.plugin is None:
            self.log("El plugin no está cargado.", "WARN")
            return
        ev = threading.Event()
        self.editor_close = ev
        self.send("editor", ch=ch_id, fx=fx_id, open=True, name=slot.name)
        threading.Thread(target=_retitle_editor, args=(f"{slot.name} · {ch.name} — UltraCam Studio", ev),
                         daemon=True).start()
        try:
            slot.plugin.show_editor(ev)          # bloquea este hilo (el principal) hasta cerrar la ventana
        except Exception as e:
            self.log(f"No se pudo abrir la ventana de {slot.name}: {e}", "ERROR")
        finally:
            self.editor_close = None
        self.send("editor", ch=ch_id, fx=fx_id, open=False)
        state = self._fx_state(ch_id, fx_id)
        if state:
            self.send("fx_state", ch=ch_id, fx=fx_id, state=state)

    def _channel(self, cid: str) -> Optional[Channel]:
        return next((c for c in self.channels if c.id == cid), None)

    # ----------------------------------------------------------- Configuración
    def apply_config(self, cfg: Dict):
        """Reabre el dispositivo principal y las fuentes extra con la configuración dada.
        Se ejecuta en el hilo principal (carga plugins)."""
        self._stop_streams()
        self.rt_channels = ()
        self.cfg = cfg
        self.sr = int(cfg.get("sample_rate", 48000))
        self.block = int(cfg.get("buffer", 256))
        self.master_volume = float(cfg.get("master_volume", 1.0))
        self.monitor_volume = float(cfg.get("monitor_volume", 1.0))
        old = {c.id: c for c in self.channels}
        chans = []
        for cc in cfg.get("channels", []):
            ch = Channel(cc)
            prev = old.get(ch.id)
            if prev:
                ch.fx = prev.fx                 # reutiliza plugins ya cargados
            if ch.source.get("kind") == "instrument":
                self._prepare_instrument(ch, prev)
            self._prepare_fx(ch, cc.get("fx", []))
            chans.append(ch)
        self.channels = chans
        self.xruns = 0
        self.last_error = None
        self._open_main()
        self._open_extras()
        self._open_midi()
        self.rt_channels = tuple(self.channels)
        self._send_stats()

    def _open_main(self):
        sd = self._import_sd()
        driver = self.cfg.get("driver", "wasapi")
        in_name = self.cfg.get("input_device")
        out_name = self.cfg.get("output_device")
        api = "ASIO" if driver == "asio" else "Windows WASAPI"
        if driver == "asio":
            out_name = in_name = self.cfg.get("asio_device") or in_name
        i_in = self._find_sd_device(in_name, api, True, False)
        i_out = self._find_sd_device(out_name, api, False, True)
        if in_name and i_in is None and out_name and i_out is None:
            self.last_error = f"No se encontró «{in_name}»."
        # Columnas de entrada que usan los canales del dispositivo principal
        n_in = max_in = 0
        if i_in is not None:
            max_in = sd.query_devices(i_in)["max_input_channels"]
            for ch in self.channels:
                if ch.source.get("kind") == "main":
                    cols = [c for c in ch.source.get("ch", [0]) if c < max_in]
                    ch.cols = cols or None
                    if cols:
                        n_in = max(n_in, max(cols) + 1)
                    else:
                        ch.error = "Entrada no disponible en este dispositivo"
            if self.meter_inputs:
                n_in = max(n_in, min(max_in, METER_MAX_INPUTS))
        out_pair = self.cfg.get("monitor_out", [0, 1])
        n_out = 0
        if i_out is not None:
            max_out = sd.query_devices(i_out)["max_output_channels"]
            out_pair = [c for c in out_pair if c < max_out] or [0]
            n_out = max(out_pair) + 1
        self.out_pair = out_pair
        if n_in == 0:
            i_in = None
        if n_out == 0:
            i_out = None
        self.device_info = {"driver": driver, "input": in_name if i_in is not None else None,
                            "output": out_name if i_out is not None else None, "max_in": max_in}
        if i_in is None and i_out is None:
            self._start_clock()                  # sin dispositivo principal: reloj por software
            return
        kwargs = dict(samplerate=self.sr, blocksize=self.block, dtype="float32", callback=self._callback)
        if driver == "asio":
            kwargs["latency"] = self.block / float(self.sr)   # pide al driver ASIO ese tamaño de búfer
        else:
            kwargs["latency"] = "low"
        try:
            if i_in is not None and i_out is not None:
                self.stream = sd.Stream(device=(i_in, i_out), channels=(n_in, n_out), **kwargs)
            elif i_in is not None:
                # Solo entrada o solo salida: sounddevice llama sin el búfer que falta
                # (4 argumentos en vez de 5); sin adaptarlo, cada bloque de audio fallaba.
                kwargs["callback"] = self._input_callback
                self.stream = sd.InputStream(device=i_in, channels=n_in, **kwargs)
            else:
                kwargs["callback"] = self._output_callback
                self.stream = sd.OutputStream(device=i_out, channels=n_out, **kwargs)
            self.stream.start()
            lat = self.stream.latency
            lat_in, lat_out = (lat if isinstance(lat, (tuple, list)) else (lat, lat))
            self.device_info.update({"latency_in": round(lat_in * 1000, 1) if i_in is not None else 0.0,
                                     "latency_out": round(lat_out * 1000, 1) if i_out is not None else 0.0,
                                     "n_in": n_in, "n_out": n_out})
            self.log(f"Audio principal ({'ASIO' if driver == 'asio' else 'Windows Audio'}): "
                     f"{in_name or '—'} → {out_name or '—'} · {self.sr} Hz · búfer {self.block}", "AUDIO")
        except Exception as e:
            self.stream = None
            self.last_error = f"No se pudo abrir el dispositivo: {e}"
            self.log(self.last_error, "ERROR")
            self._start_clock()

    def _open_extras(self):
        for ch in self.channels:
            src = ch.source
            if src.get("kind") != "device":
                continue
            try:
                d = self._find_pa_device(src.get("device", ""), bool(src.get("loopback")))
                if d is None:
                    ch.error = "Dispositivo no encontrado"
                    self.log(f"{ch.name}: no se encontró «{src.get('device')}».", "WARN")
                    continue
                dev_sr = int(d["defaultSampleRate"])
                dev_ch = max(1, int(d["maxInputChannels"]))
                buf = DriftBuffer(dev_ch, dev_sr, self.sr, self.block, ch.mode)

                def _cb(in_data, frame_count, time_info, status, b=buf):
                    b.push(in_data)
                    return (None, self.pa_mod.paContinue)

                st = self.pa.open(format=self.pa_mod.paInt16, channels=dev_ch, rate=dev_sr, input=True,
                                  input_device_index=d["index"], frames_per_buffer=max(256, self.block),
                                  stream_callback=_cb)
                st.start_stream()
                self.extra_streams.append(st)
                ch.buf = buf
            except Exception as e:
                ch.error = str(e)
                self.log(f"{ch.name}: no se pudo abrir «{src.get('device')}»: {e}", "ERROR")

    def _open_midi(self):
        """Conecta cada canal de instrumento a su entrada MIDI (o a todas) y a su canal MIDI."""
        routes = []
        for ch in self.channels:
            src = ch.source
            if src.get("kind") != "instrument" or ch.inst_plugin is None:
                continue
            dev = src.get("midi_in", MidiRouter.ALL)
            if dev:
                routes.append((dev, int(src.get("midi_ch", 0) or 0), ch))
        self.midi.set_routes(routes)
        for dev, _mch, ch in routes:
            if self.midi.failed(dev):
                ch.error = f"Entrada MIDI «{dev}» no disponible"

    def _stop_streams(self):
        self.clock_stop.set()
        if self.clock_thread:
            self.clock_thread.join(timeout=1.0)
            self.clock_thread = None
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                self.log(f"Aviso al cerrar stream principal: {e}", "DEBUG")
            self.stream = None
        for st in self.extra_streams:
            try:
                st.stop_stream()
                st.close()
            except Exception as e:
                self.log(f"Aviso al cerrar stream extra: {e}", "DEBUG")
        self.extra_streams = []
        for ch in self.channels:
            ch.buf = None

    def _start_clock(self):
        self.clock_stop = threading.Event()
        stop = self.clock_stop

        def run():
            t0 = time.perf_counter()
            produced = 0
            while not stop.is_set():
                target = int((time.perf_counter() - t0) * self.sr)
                if target - produced < self.block:
                    time.sleep(0.003)
                    continue
                if target - produced > self.sr:
                    produced = target - self.block
                self._process(None, None, self.block)
                produced += self.block

        self.clock_thread = threading.Thread(target=run, daemon=True)
        self.clock_thread.start()

    # --------------------------------------------------------- Tiempo real
    def _callback(self, indata, outdata, frames, time_info, status):
        if status:
            self.xruns += 1
        self._process(indata, outdata, frames)

    def _input_callback(self, indata, frames, time_info, status):
        self._callback(indata, None, frames, time_info, status)

    def _output_callback(self, outdata, frames, time_info, status):
        self._callback(None, outdata, frames, time_info, status)

    def _process(self, indata, outdata, n):
        chans = self.rt_channels
        any_solo = any(c.solo for c in chans)
        mix = np.zeros((n, 2), dtype=np.float32)
        mon = np.zeros((n, 2), dtype=np.float32)
        posts = []
        peaks = []
        for ch in chans:
            if ch.cols is not None and indata is not None:
                if len(ch.cols) == 1 or ch.mode == "mono":
                    m = indata[:, ch.cols[0]]
                    sig = np.column_stack((m, m))
                else:
                    sig = indata[:, ch.cols[:2]].copy()
            elif ch.buf is not None:
                sig = ch.buf.pull(n)
            elif ch.inst_plugin is not None:
                try:
                    y = ch.inst_plugin.process(ch.drain_midi(), n / float(self.sr), self.sr, 2, n, False)
                    sig = np.zeros((n, 2), dtype=np.float32)
                    m = min(n, y.shape[1])
                    sig[:m, 0] = y[0, :m]
                    sig[:m, 1] = y[1 if y.shape[0] > 1 else 0, :m]
                except Exception as e:
                    ch.error = f"Error del instrumento: {e}"
                    posts.append(None)
                    peaks.append(0.0)
                    continue
            else:
                posts.append(None)
                peaks.append(0.0)
                continue
            fx = ch.active_fx
            if fx:
                try:
                    y = np.ascontiguousarray(sig.T, dtype=np.float32)
                    for p in fx:
                        y = p.process(y, self.sr, buffer_size=n, reset=False)
                    sig = np.ascontiguousarray(y.T)
                except Exception as e:
                    ch.error = f"Error VST: {e}"
            g = 0.0 if ch.mute or (any_solo and not ch.solo) else ch.volume
            post = sig * g
            if ch.monitor and g > 0:
                mon += post
            mix += post
            posts.append(post)
            peaks.append(float(np.abs(post).max()) if g > 0 else 0.0)
        master = mix * self.master_volume
        if outdata is not None:
            outdata.fill(0)
            out = np.clip(mon * self.monitor_volume, -1.0, 1.0)
            pair = self.out_pair
            outdata[:, pair[0]] = out[:, 0]
            if len(pair) > 1:
                outdata[:, pair[1]] = out[:, 1]
        in_peaks = np.abs(indata).max(axis=0) if self.meter_inputs and indata is not None and n else None
        try:
            self.out_q.put_nowait((master, posts, peaks, float(np.abs(mon).max()) * self.monitor_volume, in_peaks))
        except queue.Full:
            self.dropped += 1

    # ------------------------------------------------ Hilo de salida (no RT)
    def _writer_loop(self):
        last_meter = 0.0
        last_stats = 0.0
        acc_peaks: Dict[str, float] = {}
        acc_master = 0.0
        acc_mon = 0.0
        acc_inputs = None
        midi_seen: Dict[str, int] = {}
        while self.running:
            try:
                master, posts, peaks, mon_peak, in_peaks = self.out_q.get(timeout=0.25)
            except queue.Empty:
                master = None
            now = time.perf_counter()
            if master is not None:
                chans = self.rt_channels
                mpk = float(np.abs(master).max())
                if mpk > 1.0:
                    self.clipping = True
                acc_master = max(acc_master, mpk)
                acc_mon = max(acc_mon, mon_peak)
                if in_peaks is not None:
                    acc_inputs = in_peaks if acc_inputs is None or len(acc_inputs) != len(in_peaks) \
                        else np.maximum(acc_inputs, in_peaks)
                for ch, pk in zip(chans, peaks):
                    acc_peaks[ch.id] = max(acc_peaks.get(ch.id, 0.0), pk)
                pcm_master = (np.clip(master, -1.0, 1.0) * 32767.0).astype(np.int16)
                with self.rec_lock:
                    rf = self.rec_files
                    if rf is not None:
                        try:
                            rf["master"].writeframes(pcm_master.tobytes())
                            for ch, post in zip(chans, posts):
                                wf = rf["tracks"].get(ch.id)
                                if wf is None:
                                    continue
                                data = post if post is not None else np.zeros_like(master)
                                wf.writeframes((np.clip(data, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes())
                            self.rec_frames += len(master)
                        except Exception as e:
                            self.log(f"Error escribiendo audio: {e}", "ERROR")
                feed = self.feed
                if feed is not None:
                    feed.push(pcm_master.tobytes())
            if now - last_meter >= 0.05:
                last_meter = now
                midi = []
                for ch in self.rt_channels:
                    if ch.midi_hits != midi_seen.get(ch.id, 0):
                        midi_seen[ch.id] = ch.midi_hits
                        midi.append(ch.id)
                extra = {}
                if self.meter_inputs and acc_inputs is not None:
                    extra["inputs"] = [_dbfs(float(v)) for v in acc_inputs]
                if self.meter_streams:
                    peaks, self.dev_peaks = self.dev_peaks, {}
                    extra["devices"] = {k: _dbfs(v) for k, v in peaks.items()}
                self.send("levels", ch={k: _dbfs(v) for k, v in acc_peaks.items()},
                          master=_dbfs(acc_master), monitor=_dbfs(acc_mon), midi=midi, **extra)
                acc_peaks = {}
                acc_inputs = None
                acc_master = acc_mon = 0.0
            if now - last_stats >= 1.0:
                last_stats = now
                self._send_stats()

    def _send_stats(self):
        cpu = 0.0
        try:
            if self.stream is not None:
                cpu = float(self.stream.cpu_load)
        except Exception:
            pass
        self.send("stats", sr=self.sr, buffer=self.block, cpu=round(cpu * 100, 1), xruns=self.xruns,
                  running=self.stream is not None or self.clock_thread is not None, error=self.last_error,
                  channel_errors={c.id: c.error for c in self.channels if c.error}, **self.device_info)

    # --------------------------------------------------------------- Grabación
    def start_recording(self, out_dir: str) -> Dict:
        os.makedirs(out_dir, exist_ok=True)
        ts = int(time.time() * 1000)

        def mk(path):
            wf = wave.open(path, "wb")
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(self.sr)
            return wf

        files = {"master_path": os.path.join(out_dir, f"temp_master_{ts}.wav"), "tracks": {}, "paths": {}}
        files["master"] = mk(files["master_path"])
        for i, ch in enumerate(self.channels):
            if ch.source.get("kind") in (None, "none"):
                continue
            p = os.path.join(out_dir, f"temp_track{i + 1}_{ts}.wav")
            files["tracks"][ch.id] = mk(p)
            files["paths"][ch.id] = (p, ch.name)
        with self.rec_lock:
            self.rec_frames = 0
            self.clipping = False
            self.rec_files = files
        self.log("Grabación de audio multipista iniciada.", "REC")
        return {"sample_rate": self.sr}

    def stop_recording(self) -> Dict:
        with self.rec_lock:
            files, self.rec_files = self.rec_files, None
        if not files:
            return {}
        try:
            files["master"].close()
        except Exception as e:
            self.log(f"Aviso al cerrar archivo WAV maestro: {e}", "WARN")
        for wf in files["tracks"].values():
            try:
                wf.close()
            except Exception as e:
                self.log(f"Aviso al cerrar pista WAV: {e}", "WARN")
        duration = self.rec_frames / float(self.sr)
        self.log(f"Grabación de audio finalizada ({duration:.1f} s).", "REC")
        tracks = [{"id": cid, "name": name, "wav": p} for cid, (p, name) in files["paths"].items()]
        return {"master_wav": files["master_path"], "tracks": tracks, "duration": duration, "clipping": self.clipping}

    # ------------------------------------------------------------ Comandos
    def handle(self, cmd: str, args: Dict, rid):
        """Se ejecuta en el hilo de comandos. Lo que toca plugins o dispositivos va al hilo principal."""
        # Todo lo que toca PortAudio/WASAPI (COM) o plugins corre en el hilo principal
        if cmd in ("config", "open_editor", "asio_panel", "fx", "devices", "meter_inputs", "midi_learn"):
            self.main_jobs.put((cmd, args, rid))
            if cmd == "open_editor" and self.editor_close is not None:
                self.editor_close.set()          # cierra la ventana anterior para abrir la nueva
            return
        if cmd == "param":
            ch = self._channel(args["ch"])
            if ch is not None and args["key"] in ("volume", "mute", "solo", "monitor", "mode", "name"):
                val = args["value"]
                setattr(ch, args["key"], float(val) if args["key"] == "volume" else val)
                if args["key"] == "mode" and ch.buf is not None:
                    ch.buf.mode = val
        elif cmd == "master":
            if "master_volume" in args:
                self.master_volume = float(args["master_volume"])
            if "monitor_volume" in args:
                self.monitor_volume = float(args["monitor_volume"])
        elif cmd == "rec_start":
            self.reply(rid, **self.start_recording(args["dir"]))
        elif cmd == "rec_stop":
            self.reply(rid, **self.stop_recording())
        elif cmd == "fx_states":
            states = {}
            for ch in self.channels:
                for s in ([ch.inst] if ch.inst is not None else []) + ch.fx:
                    st = self._fx_state(ch.id, s.id)
                    if st:
                        states.setdefault(ch.id, {})[s.id] = st
            self.reply(rid, states=states)
        elif cmd == "feed_start":
            self._start_feed(args["pipe"])
            self.reply(rid)
        elif cmd == "feed_stop":
            self._stop_feed()
            self.reply(rid)
        elif cmd == "test_note":
            ch = self._channel(args["ch"])
            if ch is not None and ch.inst_plugin is not None:
                note = int(args.get("note", 60))
                mc = max(0, int(ch.source.get("midi_ch", 0) or 1) - 1)
                ch.midi_push(bytes((0x90 | mc, note, 100)))
                threading.Timer(0.6, ch.midi_push, args=(bytes((0x80 | mc, note, 0)),)).start()
        elif cmd == "close_editor":
            if self.editor_close is not None:
                self.editor_close.set()
        elif cmd == "quit":
            self.running = False
            if self.editor_close is not None:
                self.editor_close.set()
            self.main_jobs.put(("quit", {}, rid))

    def run_main_job(self, cmd, args, rid):
        try:
            if cmd == "devices":
                self.reply(rid, devices=self.list_devices())
            elif cmd == "config":
                self.apply_config(args["config"])
                self.reply(rid)
            elif cmd == "fx":
                ch = self._channel(args["ch"])
                if ch is not None:
                    self._prepare_fx(ch, args["fx"])
                self.reply(rid)
            elif cmd == "open_editor":
                self._open_editor(args["ch"], args["fx"])
            elif cmd == "asio_panel":
                self._asio_panel()
            elif cmd == "meter_inputs":
                self._set_meter_inputs(bool(args.get("on")), args.get("config"))
            elif cmd == "midi_learn":
                self.midi.set_learning(bool(args.get("on")))
        except Exception as e:
            self.log(f"Error de audio: {e}", "ERROR")
            self.send("log", msg=traceback.format_exc()[-600:], cat="DEBUG")
            self.reply(rid, ok=False, error=str(e))

    def _set_meter_inputs(self, on: bool, cfg: Optional[Dict]):
        """Mide (o deja de medir) todas las entradas del dispositivo principal. Si para eso hay
        que abrir más entradas de las que usan los canales, se reabre el dispositivo con `cfg`
        (la configuración actual de la interfaz: volúmenes y efectos al día). Nunca mientras se
        graba (sería un corte en la toma): entonces se miden las entradas que ya están abiertas."""
        if on == self.meter_inputs:
            return
        self.meter_inputs = on
        if not on:
            self._close_meter_streams()
        if self.rec_files is not None or not (cfg or self.cfg):
            return
        if on:
            self._open_meter_streams()
        n_in = self.device_info.get("n_in") or 0
        in_use = any(ch.cols for ch in self.channels)
        # Al dejar de medir, las entradas de más quedan abiertas hasta la próxima configuración
        # (agregar el canal ya reabre); solo se cierra si ningún canal usa el dispositivo,
        # para no dejar el micrófono abierto sin motivo.
        if (on and n_in < min(self.device_info.get("max_in") or 0, METER_MAX_INPUTS)) or \
                (not on and n_in and not in_use):
            self.apply_config(cfg or self.cfg)

    def _open_meter_streams(self):
        """Abre cada micrófono de Windows (WASAPI compartido, sin loopbacks) solo para medirlo:
        en interfaces que Windows parte en «IN 1», «IN 2», «IN 1-2» se ve cuál es cuál."""
        self._close_meter_streams()
        try:
            pa = self._import_pa()
            wasapi = pa.get_host_api_info_by_type(self.pa_mod.paWASAPI)["index"]
            devices = [pa.get_device_info_by_index(i) for i in range(pa.get_device_count())]
        except Exception as e:
            self.log(f"No se pudieron medir los micrófonos de Windows: {e}", "DEBUG")
            return
        for d in devices:
            if d["hostApi"] != wasapi or d.get("maxInputChannels", 0) <= 0 or d.get("isLoopbackDevice"):
                continue

            def _cb(in_data, frame_count, time_info, status, name=d["name"]):
                a = np.frombuffer(in_data, dtype=np.int16)
                if a.size:
                    pk = max(int(a.max()), -int(a.min())) / 32768.0
                    if pk > self.dev_peaks.get(name, 0.0):
                        self.dev_peaks[name] = pk
                return (None, self.pa_mod.paContinue)
            try:
                st = pa.open(format=self.pa_mod.paInt16, channels=max(1, int(d["maxInputChannels"])),
                             rate=int(d["defaultSampleRate"]), input=True, input_device_index=d["index"],
                             frames_per_buffer=1024, stream_callback=_cb)
                st.start_stream()
                self.meter_streams.append(st)
            except Exception as e:
                self.log(f"No se pudo medir «{d['name']}»: {e}", "DEBUG")

    def _close_meter_streams(self):
        for st in self.meter_streams:
            try:
                st.stop_stream()
                st.close()
            except Exception as e:
                self.log(f"Aviso al cerrar la medición de un micrófono: {e}", "DEBUG")
        self.meter_streams = []
        self.dev_peaks = {}

    def _asio_panel(self):
        """Abre el panel del driver ASIO (donde muchas interfaces fijan el tamaño del búfer)."""
        import ctypes
        sd = self._import_sd()
        name = self.cfg.get("asio_device") or self.cfg.get("input_device")
        idx = self._find_sd_device(name, "ASIO", False, False)
        if idx is None:
            self.log("Elige primero un dispositivo ASIO.", "WARN")
            return
        lib = ctypes.CDLL(sd._libname)
        fn = getattr(lib, "PaAsio_ShowControlPanel", None)
        if fn is None:
            self.log("Este PortAudio no permite abrir el panel ASIO.", "WARN")
            return
        self._stop_streams()                    # el panel suele pedir que el driver esté libre
        fn.argtypes = [ctypes.c_int, ctypes.c_void_p]
        err = fn(idx, None)
        if err != 0:
            self.log(f"El driver no abrió su panel (código {err}).", "WARN")
        self.apply_config(self.cfg)             # reabrir con lo que se haya cambiado en el panel

    # ------------------------------------------------------ Envío a OBS
    def _start_feed(self, pipe_path: str):
        self._stop_feed()
        self.feed = _PcmFeed(pipe_path, self.sr)
        self.feed.start()

    def _stop_feed(self):
        feed, self.feed = self.feed, None
        if feed:
            feed.stop()

    # ------------------------------------------------------------ Ciclo
    def serve(self):
        threading.Thread(target=self._writer_loop, daemon=True).start()
        threading.Thread(target=self._command_loop, daemon=True).start()
        self.send("ready", pid=os.getpid())
        while self.running:
            try:
                cmd, args, rid = self.main_jobs.get(timeout=0.25)
            except queue.Empty:
                continue
            if cmd == "quit":
                break
            self.run_main_job(cmd, args, rid)
        self._stop_feed()
        self.midi.close()
        self._close_meter_streams()
        self._stop_streams()
        try:
            if self.pa is not None:
                self.pa.terminate()
        except Exception as e:
            self.log(f"Aviso al terminar PyAudio: {e}", "DEBUG")

    def _command_loop(self):
        while self.running:
            try:
                msg = self.conn.recv()
            except (EOFError, OSError):
                self.running = False       # la app principal se cerró
                self.main_jobs.put(("quit", {}, None))
                break
            try:
                cmd, args, rid = msg
                self.handle(cmd, args, rid)
            except Exception as e:
                self.log(f"Comando de audio inválido: {e}", "ERROR")


def _retitle_editor(title: str, closed: threading.Event):
    """La ventana del plugin nace con el título genérico «Pedalboard»: le pone el nombre
    del plugin y del canal, y la trae al frente."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        pid = os.getpid()
        for _ in range(60):
            if closed.is_set():
                return
            found = []
            cb = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

            def enum(h, _l):
                p = wintypes.DWORD()
                u.GetWindowThreadProcessId(h, ctypes.byref(p))
                if p.value == pid and u.IsWindowVisible(h):
                    b = ctypes.create_unicode_buffer(64)
                    u.GetWindowTextW(h, b, 64)
                    if b.value == "Pedalboard":
                        found.append(h)
                return True

            u.EnumWindows(cb(enum), 0)
            if found:
                u.SetWindowTextW(found[0], title)
                _fit_on_screen(found[0])
                u.SetForegroundWindow(found[0])
                return
            time.sleep(0.1)
    except Exception:
        pass


def _fit_on_screen(hwnd: int):
    """La ventana del plugin nace en (−8, −31): la barra de título queda fuera de la pantalla
    y no se puede arrastrar ni cerrar. Se centra en el área útil de su monitor, con la barra
    siempre visible aunque la ventana sea más alta que la pantalla."""
    import ctypes
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    u = ctypes.windll.user32
    u.MonitorFromWindow.restype = wintypes.HMONITOR
    u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
    r = wintypes.RECT()
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if not u.GetWindowRect(hwnd, ctypes.byref(r)):
        return
    if not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):   # 2: el monitor más cercano
        return
    wa = mi.rcWork
    w, h = r.right - r.left, r.bottom - r.top
    x = wa.left + max(0, (wa.right - wa.left - w) // 2)
    y = wa.top + max(0, (wa.bottom - wa.top - h) // 2)
    u.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)   # NOSIZE | NOZORDER | NOACTIVATE


class _PcmFeed:
    """Entrega el master como PCM s16le estéreo a un pipe con nombre que lee ffmpeg.
    Nunca bloquea al mezclador: si ffmpeg no lee, se descarta lo más viejo."""

    def __init__(self, pipe_path: str, sr: int):
        from winpipes import NamedPipeServer
        self.pipe = NamedPipeServer(pipe_path, NamedPipeServer.OUTBOUND, buffer=256 * 1024)
        self.q: collections.deque = collections.deque(maxlen=int(sr / 256))   # ~1 s
        self.ev = threading.Event()
        self.stopped = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def push(self, data: bytes):
        self.q.append(data)
        self.ev.set()

    def _run(self):
        if not self.pipe.wait_client() or self.stopped:
            return
        self.q.clear()
        while not self.stopped:
            self.ev.wait(0.5)
            self.ev.clear()
            while self.q and not self.stopped:
                if not self.pipe.write(self.q.popleft()):
                    self.stopped = True
                    break

    def stop(self):
        self.stopped = True
        self.ev.set()
        self.pipe.unblock()
        self.pipe.close()


def main(conn):
    """Punto de entrada del proceso de audio."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x80)  # HIGH_PRIORITY_CLASS
    except Exception:
        pass
    server = AudioServer(conn)
    try:
        server.serve()
    except Exception:
        server.send("log", msg=traceback.format_exc()[-800:], cat="ERROR")
