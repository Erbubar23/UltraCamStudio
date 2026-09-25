"""
Pruebas del driver de cámara virtual UltraCam.

Hacen de «programa que usa la cámara» con ffmpeg (DirectShow, igual que Zoom u
OBS) y de «app» con SharedFrameWriter. Necesitan el driver compilado
(vcam_driver\\build.ps1) y ffmpeg. Registran la cámara temporalmente con el
nombre «UltraCam Test» y al terminar dejan el registro como estaba.

    py vcam_driver\\tests\\test_vcam_driver.py
"""

import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from infrastructure.video import vcam_driver as vd   # noqa: E402

TEST_NAME = "UltraCam Test"
PREVIEW = (160, 90)   # el consumidor reduce cada cuadro a esto para analizarlo


def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        from engine import CameraEngine
        return CameraEngine().ffmpeg_path
    except Exception:
        return None


FFMPEG = find_ffmpeg()


def pattern(bright_left: bool) -> np.ndarray:
    """Cuadro NV12 1080p: una mitad blanca y la otra negra (fácil de reconocer escalado)."""
    y = np.full((vd.HEIGHT, vd.WIDTH), 16, dtype=np.uint8)
    if bright_left:
        y[:, : vd.WIDTH // 2] = 235
    else:
        y[:, vd.WIDTH // 2:] = 235
    uv = np.full(vd.WIDTH * vd.HEIGHT // 2, 128, dtype=np.uint8)
    return np.concatenate([y.reshape(-1), uv])


FRAME_A, FRAME_B = pattern(True), pattern(False)


def classify(frame: np.ndarray) -> str:
    """'A' / 'B' si es uno de los patrones, 'slate' si es un cartel, 'black' si es negro."""
    w = frame.shape[1]
    left, right = frame[:, : w // 2 - 4].mean(), frame[:, w // 2 + 4:].mean()
    if left - right > 120:
        return "A"
    if right - left > 120:
        return "B"
    if frame.mean() < 8 and frame.std() < 2:
        return "black"
    return "slate"


def text_band_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Diferencia en la franja del mensaje del cartel (58–72 % de la altura): los dos
    carteles solo cambian ahí, y en la imagen completa la diferencia se diluye."""
    h = a.shape[0]
    band = slice(int(0.58 * h), int(0.72 * h))
    return float(np.abs(a[band].astype(float) - b[band].astype(float)).mean())


def consumer_cmd(seconds, size="1280x720", fps=30, pix="nv12"):
    return [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "dshow", "-video_size", size,
            "-framerate", str(fps), "-pixel_format", pix, "-i", f"video={TEST_NAME}",
            "-t", str(seconds), "-vf", f"scale={PREVIEW[0]}:{PREVIEW[1]}", "-pix_fmt", "gray",
            "-f", "rawvideo", "pipe:1"]


def frames_from(stdout: bytes) -> np.ndarray:
    data = np.frombuffer(stdout, dtype=np.uint8)
    n = data.size // (PREVIEW[0] * PREVIEW[1])
    return data[: n * PREVIEW[0] * PREVIEW[1]].reshape(n, PREVIEW[1], PREVIEW[0])


def capture(seconds, **kw) -> np.ndarray:
    done = subprocess.run(consumer_cmd(seconds, **kw), capture_output=True, timeout=seconds + 20)
    if done.returncode != 0:
        raise AssertionError(done.stderr.decode(errors="replace"))
    return frames_from(done.stdout)


class Sender:
    """Envía un patrón a ~30 fps en segundo plano, como la app con una cámara."""

    def __init__(self, writer):
        self.writer = writer
        self.frame = None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        while not self._stop.wait(1 / 30):
            if self.frame is not None:
                self.writer.send(self.frame)

    def stop(self):
        self._stop.set()
        self._t.join(timeout=2)


class TestProtocol(unittest.TestCase):
    """El encabezado que escribe la app coincide con protocol.h (sin driver ni ffmpeg)."""

    def test_header_and_publish(self):
        w = vd.SharedFrameWriter()
        try:
            def field(name):
                return struct.unpack_from("<I", w._mm, vd._OFFSET[name])[0]
            self.assertEqual(field("magic"), vd.MAGIC)
            self.assertEqual((field("width"), field("height")), (1920, 1080))
            self.assertEqual(field("slot_size"), 1920 * 1080 * 3 // 2)
            self.assertEqual(field("data_offset"), vd.DATA_OFFSET)
            seq0 = field("frame_seq")
            buf = w.back_buffer()
            slot = (field("latest_slot") + 1) % vd.SLOT_COUNT
            self.assertEqual(field(f"slot_seq{slot}"), 0, "el slot en obras debe marcarse con 0")
            buf[:] = FRAME_A
            w.publish()
            self.assertEqual(field("latest_slot"), slot)
            self.assertEqual(field("frame_seq"), seq0 + 1)
            self.assertEqual(field(f"slot_seq{slot}"), seq0 + 1)
            self.assertFalse(w.send(b"corto"), "un cuadro de otro tamaño se rechaza")
        finally:
            w.close()


@unittest.skipUnless(sys.platform == "win32", "solo Windows")
class TestDriver(unittest.TestCase):
    """De punta a punta: app → memoria compartida → driver → programa consumidor."""

    @classmethod
    def setUpClass(cls):
        if not FFMPEG:
            raise unittest.SkipTest("ffmpeg no disponible")
        if not vd.dll_path(64):
            raise unittest.SkipTest("driver sin compilar: ejecuta vcam_driver\\build.ps1")
        cls.previous = vd.registered_name()
        vd.register(TEST_NAME)
        # Referencias de los dos carteles, capturadas una vez para comparar.
        cls.closed_slate = capture(1.5)[-5:].mean(axis=0)
        w = vd.SharedFrameWriter()
        try:
            cls.nosignal_slate = capture(1.5)[-5:].mean(axis=0)
        finally:
            w.close()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "previous", None):
            vd.register(cls.previous)
        else:
            vd.unregister()

    def assertSlate(self, frame, reference, msg):
        self.assertEqual(classify(frame), "slate", msg)
        self.assertLess(text_band_diff(frame, reference), 1.5, msg)

    def test_slates_are_visible_and_distinct(self):
        """Sin app: cartel (nunca negro). App abierta sin imagen: otro cartel distinto."""
        for name, ref in (("app cerrada", self.closed_slate), ("sin señal", self.nosignal_slate)):
            self.assertEqual(classify(ref), "slate", f"el cartel «{name}» no debe ser negro")
            self.assertGreater(ref.std(), 3.0, f"el cartel «{name}» debe tener logo y texto")
        diff = text_band_diff(self.closed_slate, self.nosignal_slate)
        self.assertGreater(diff, 3.0, "los dos carteles deben distinguirse")

    def test_live_frames_reach_consumer(self):
        w = vd.SharedFrameWriter()
        s = Sender(w)
        s.frame = FRAME_A
        try:
            time.sleep(0.3)
            frames = capture(2)
        finally:
            s.stop()
            w.close()
        kinds = [classify(f) for f in frames]
        self.assertGreaterEqual(len(frames), 50, "a 30 fps, 2 s deben dar ~60 cuadros")
        self.assertGreaterEqual(kinds.count("A") / len(kinds), 0.9, kinds)

    def test_ten_source_switches_without_disconnect_or_slate(self):
        """Criterio de aceptación: 10 cambios de fuente seguidos con otro programa usando
        la cámara. Cada cambio deja 0,3 s sin imagen (lo que tarda en reiniciar la
        fuente): el driver retiene el último cuadro, así que nunca aparece el cartel."""
        w = vd.SharedFrameWriter()
        s = Sender(w)
        consumer = subprocess.Popen(consumer_cmd(16), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = {}
        reader = threading.Thread(target=lambda: out.update(zip(("o", "e"), consumer.communicate())))
        reader.start()
        try:
            time.sleep(2.0)
            for i in range(10):
                s.frame = FRAME_A if i % 2 == 0 else FRAME_B
                time.sleep(0.9)
                s.frame = None          # la fuente se reinicia: no llegan cuadros
                time.sleep(0.3)
            time.sleep(3.0)             # sin fuente de verdad: debe aparecer «Sin señal»
        finally:
            reader.join(timeout=30)
            s.stop()
            w.close()
        self.assertEqual(consumer.returncode, 0, out.get("e", b"").decode(errors="replace"))
        frames = frames_from(out["o"])
        kinds = [classify(f) for f in frames]
        self.assertGreaterEqual(len(frames), 16 * 30 * 0.9, "no deben perderse cuadros")
        live = [i for i, k in enumerate(kinds) if k in ("A", "B")]
        self.assertTrue(live, "debe llegar imagen")
        window = kinds[live[0]: live[-1] + 1]
        self.assertNotIn("slate", window, "durante los cambios de fuente no debe verse el cartel")
        self.assertNotIn("black", window)
        switches = sum(1 for a, b in zip(window, window[1:]) if a != b)
        self.assertGreaterEqual(switches, 9, "deben verse los 10 cambios de fuente")
        self.assertSlate(frames[-3], self.nosignal_slate, "tras 3 s sin fuente debe verse «Sin señal»")

    def test_hold_last_frame_during_slow_switch(self):
        """Un cambio de fuente que tarda 3 s (lo que tarda en abrir una webcam) no debe
        mostrar el cartel si la app pidió mantener el último cuadro."""
        w = vd.SharedFrameWriter()
        s = Sender(w)
        s.frame = FRAME_A
        consumer = subprocess.Popen(consumer_cmd(7), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = {}
        reader = threading.Thread(target=lambda: out.update(zip(("o", "e"), consumer.communicate())))
        reader.start()
        try:
            time.sleep(2.0)
            w.hold_last_frame(5.0)
            s.frame = None              # la nueva fuente tarda 3 s en dar imagen
            time.sleep(3.0)
            s.frame = FRAME_B
            time.sleep(1.5)
        finally:
            reader.join(timeout=30)
            s.stop()
            w.close()
        kinds = [classify(f) for f in frames_from(out["o"])]
        live = [i for i, k in enumerate(kinds) if k in ("A", "B")]
        window = kinds[live[0]: live[-1] + 1]
        self.assertNotIn("slate", window, "con retención, el cambio lento no debe mostrar el cartel")
        self.assertIn("B", window)

    def test_update_while_camera_in_use(self):
        """Actualizar la app con Zoom u OBS usando la cámara: la DLL en uso está bloqueada.
        La versión nueva se registra desde otra carpeta, el programa abierto no se corta, uno
        nuevo usa la versión nueva, y la vieja se borra cuando nadie la usa."""
        import tempfile
        from unittest.mock import patch
        real = vd.dll_path(64)
        with tempfile.TemporaryDirectory() as tmp:
            src_a = os.path.join(tmp, "a", "ultracam-vcam64.dll")
            src_b = os.path.join(tmp, "b", "ultracam-vcam64.dll")
            for p, extra in ((src_a, b""), (src_b, b"\0" * 16)):   # B: mismo código, otro contenido
                os.makedirs(os.path.dirname(p))
                with open(real, "rb") as f, open(p, "wb") as g:
                    g.write(f.read() + extra)
            current = {"src": src_a}
            with patch.object(vd, "_install_root", return_value=os.path.join(tmp, "installed")), \
                    patch.object(vd, "dll_path", side_effect=lambda bits: current["src"] if bits == 64 else None):
                w = vd.SharedFrameWriter()
                s = Sender(w)
                s.frame = FRAME_A
                try:
                    vd.register(TEST_NAME)
                    installed_a = vd.installed_copy(src_a)
                    consumer = subprocess.Popen(consumer_cmd(6), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    time.sleep(2.5)                       # «Zoom» ya cargó la versión A
                    current["src"] = src_b
                    vd.register(TEST_NAME)                # «actualización»
                    installed_b = vd.installed_copy(src_b)
                    self.assertNotEqual(os.path.dirname(installed_a), os.path.dirname(installed_b))
                    self.assertTrue(os.path.exists(installed_a), "la versión en uso no se puede ni debe borrar")
                    fresh = capture(1.5)                  # un programa nuevo abre la versión B
                    self.assertGreaterEqual([classify(f) for f in fresh].count("A") / len(fresh), 0.9)
                    stdout, stderr = consumer.communicate(timeout=30)
                    self.assertEqual(consumer.returncode, 0, stderr.decode(errors="replace"))
                    kinds = [classify(f) for f in frames_from(stdout)]
                    self.assertGreaterEqual(len(kinds), 6 * 30 * 0.9, "el programa abierto no se cortó")
                    self.assertGreaterEqual(kinds.count("A") / len(kinds), 0.9)
                    vd.register(TEST_NAME)                # siguiente arranque: ya nadie usa A
                    self.assertFalse(os.path.exists(os.path.dirname(installed_a)), "la versión vieja se limpia")
                    self.assertTrue(os.path.exists(installed_b))
                finally:
                    s.stop()
                    w.close()
        vd.register(TEST_NAME)    # vuelve a la DLL real para el resto de pruebas

    def test_32_and_64_bit_programs(self):
        """Los programas de 32 bits leen otra vista del registro y cargan la DLL de 32 bits:
        se prueban los dos con una herramienta que abre la cámara como lo haría Zoom."""
        probes = {bits: os.path.join(ROOT, "vcam_driver", "tests", "bin", f"vcam_probe{bits}.exe") for bits in (32, 64)}
        if not all(os.path.isfile(p) for p in probes.values()):
            self.skipTest("herramienta de prueba sin compilar: ejecuta vcam_driver\\build.ps1")
        w = vd.SharedFrameWriter()
        s = Sender(w)
        s.frame = FRAME_A
        try:
            time.sleep(0.3)
            for bits, exe in probes.items():
                with self.subTest(bits=bits):
                    done = subprocess.run([exe, TEST_NAME, "2"], capture_output=True, text=True, timeout=30)
                    info = dict(kv.split("=", 1) for kv in done.stdout.split())
                    self.assertEqual(info.get("found"), "1", f"{bits} bits: la cámara no aparece en la lista")
                    self.assertEqual(done.returncode, 0, done.stdout)
                    self.assertGreaterEqual(int(info["frames"]), 45, "a 30 fps, 2 s dan ~60 cuadros")
                    self.assertEqual((info["width"], info["height"]), ("1920", "1080"), "modo por omisión")
                    self.assertGreater(float(info["left"]), 200, "llega el patrón enviado, no el cartel")
                    self.assertLess(float(info["right"]), 40)
        finally:
            s.stop()
            w.close()

    def test_modes(self):
        """Cada programa elige un modo al abrir la cámara, como con una webcam real."""
        w = vd.SharedFrameWriter()
        s = Sender(w)
        s.frame = FRAME_A
        try:
            time.sleep(0.3)
            for size, fps, pix in (("1920x1080", 30, "nv12"), ("1280x720", 60, "nv12"),
                                   ("640x360", 30, "yuyv422"), ("1280x720", 30, "yuyv422")):
                with self.subTest(size=size, fps=fps, pix=pix):
                    frames = capture(1.5, size=size, fps=fps, pix=pix)
                    self.assertGreaterEqual(len(frames), int(1.5 * fps * 0.8))
                    kinds = [classify(f) for f in frames]
                    self.assertGreaterEqual(kinds.count("A") / len(kinds), 0.9, kinds)
            bad = subprocess.run(consumer_cmd(1, size="800x600"), capture_output=True, timeout=20)
            self.assertNotEqual(bad.returncode, 0, "un modo que no existe debe rechazarse")
        finally:
            s.stop()
            w.close()

    def test_closing_app_shows_closed_slate(self):
        w = vd.SharedFrameWriter()
        s = Sender(w)
        s.frame = FRAME_A
        consumer = subprocess.Popen(consumer_cmd(4), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = {}
        reader = threading.Thread(target=lambda: out.update(zip(("o", "e"), consumer.communicate())))
        reader.start()
        time.sleep(2.0)
        s.stop()
        w.close()
        reader.join(timeout=30)
        self.assertEqual(consumer.returncode, 0, out.get("e", b"").decode(errors="replace"))
        frames = frames_from(out["o"])
        self.assertIn("A", [classify(f) for f in frames[:40]])
        self.assertSlate(frames[-3], self.closed_slate, "al cerrar la app debe verse su cartel")


if __name__ == "__main__":
    unittest.main(verbosity=2)
