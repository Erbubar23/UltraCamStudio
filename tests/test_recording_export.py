"""Pruebas del módulo Grabación › exportación: codificador elegido, compresión en el mismo paso
de la unión, verificación antes de borrar los originales y caídas seguras a «copiar»."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = os.path.join(ROOT, "build", "vendor", "ffmpeg", "ffmpeg.exe")


class TestEncoderChoice(unittest.TestCase):
    def test_hardware_first_same_family(self):
        from modules.recording.export.encoders import choose
        avail = ["hevc_nvenc", "h264_nvenc", "libx265", "libx264"]
        self.assertEqual(choose("hevc", 2160, avail).name, "hevc_nvenc")
        self.assertEqual(choose("h264", 1080, avail).name, "h264_nvenc")     # H.264 sigue siendo H.264
        self.assertEqual(choose("mjpeg", 1080, avail).name, "h264_nvenc")    # lo desconocido, al más compatible
        self.assertEqual(choose("hevc", 2160, ["hevc_qsv", "hevc_amf"]).name, "hevc_qsv")
        self.assertEqual(choose("hevc", 2160, ["hevc_amf"]).label, "GPU AMD")

    def test_cpu_only_up_to_1080p(self):
        """Decisión del usuario: con solo CPU, el 4K se guarda como siempre (no ocupar la PC horas)."""
        from modules.recording.export.encoders import choose
        cpu = ["libx265", "libx264"]
        self.assertEqual(choose("hevc", 1080, cpu).name, "libx265")
        self.assertEqual(choose("h264", 720, cpu).name, "libx264")
        self.assertIsNone(choose("hevc", 2160, cpu))
        self.assertIsNone(choose("hevc", 1440, cpu))
        self.assertIsNone(choose("hevc", 1080, []))

    def test_light_videos_are_not_recompressed(self):
        from modules.recording.export.encoders import choose
        avail = ["hevc_nvenc", "h264_nvenc"]
        self.assertIsNotNone(choose("hevc", 2160, avail, bitrate_bps=63e6))     # el teléfono: 63 Mbps
        self.assertIsNone(choose("hevc", 1080, avail, bitrate_bps=6e6))         # ya liviano
        self.assertIsNotNone(choose("h264", 1080, avail, bitrate_bps=40e6))
        self.assertIsNone(choose("hevc", 0, avail))                             # tamaño desconocido

    def test_profiles(self):
        from modules.recording.export.encoders import profile
        p = profile("hevc_nvenc", 2160)
        self.assertEqual(p[:2], ["-c:v", "hevc_nvenc"])
        self.assertEqual(p[p.index("-maxrate") + 1], "45M")
        self.assertEqual(p[-2:], ["-tag:v", "hvc1"])                            # se abre en QuickTime / iPhone
        self.assertEqual(profile("h264_nvenc", 1080)[profile("h264_nvenc", 1080).index("-maxrate") + 1], "25M")
        self.assertNotIn("-tag:v", profile("libx264", 1080))
        with self.assertRaises(ValueError):
            profile("mpeg2video", 1080)

    def test_probe_keeps_only_what_runs(self):
        from modules.recording.export.encoders import probe_available
        ok = {"hevc_nvenc", "libx264"}
        found = probe_available(lambda cmd: 0 if cmd[cmd.index("-c:v") + 1] in ok else 1, "ffmpeg")
        self.assertEqual(sorted(found), ["hevc_nvenc", "libx264"])
        self.assertEqual(probe_available(lambda cmd: 1 / 0, "ffmpeg"), [])


class TestMediaParsing(unittest.TestCase):
    HEAD = ("Input #0, matroska,webm, from 'v.mkv':\n  Duration: 01:00:25.00, start: 0.000000, bitrate: 63106 kb/s\n"
            "  Stream #0:0: Video: hevc (Main), yuvj420p(pc), 3840x2160, 62264 kb/s, 29.99 fps\n"
            "  Stream #0:1: Audio: opus, 48000 Hz, mono\n  Stream #0:2(und): Audio: aac (LC), 48000 Hz, stereo\n")

    def test_parse(self):
        from engine import parse_media_info, last_frames
        info = parse_media_info(self.HEAD)
        self.assertEqual((info["codec"], info["width"], info["height"]), ("hevc", 3840, 2160))
        self.assertAlmostEqual(info["duration"], 3625.0)
        self.assertEqual(info["bitrate"], 62264000)
        self.assertEqual(info["audio_streams"], 2)
        no_rate = parse_media_info("  Duration: 00:00:10.00, start\n  Stream #0:0: Video: h264, yuv420p, 1920x1080\n",
                                   size_bytes=10_000_000)
        self.assertAlmostEqual(no_rate["bitrate"], 8e6)                         # estimado por el tamaño
        self.assertEqual(last_frames("frame=  10 fps\rframe= 958 fps=0"), 958)
        self.assertIsNone(last_frames(""))


class TestExportFlow(unittest.TestCase):
    """El flujo con ffmpeg simulado: qué se intenta, en qué orden y qué se borra."""

    def setUp(self):
        from engine import CameraEngine
        self.e = CameraEngine()
        self.e.ffmpeg_path = sys.executable
        self.dir = tempfile.mkdtemp()
        self.video = os.path.join(self.dir, "v.mkv")
        self.master = os.path.join(self.dir, "m.wav")
        for p in (self.video, self.master):
            with open(p, "wb") as f:
                f.write(b"x" * 1000)
        self.audio = {"master_wav": self.master, "tracks": []}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _export(self, outcomes, verify=(True, ""), **options):
        """outcomes: lista de (returncode, escribe_archivo, lento) por cada ffmpeg de la unión."""
        calls = []

        def run(cmd, progress, duration, min_speed):
            calls.append(cmd)
            code, writes, slow = outcomes[len(calls) - 1]
            if writes:
                with open(cmd[-1], "wb") as f:
                    f.write(b"y" * 100)
            return {"returncode": code, "stderr": "", "slow": slow, "frames": 10}
        verify_calls = []

        def ver(path, n, frames):
            verify_calls.append(path)
            return verify(path) if callable(verify) else verify
        self.e._run_export = run
        self.e._verify_export = ver
        res = self.e.post_process_session(self.video, self.audio, dict(
            {"output_dir": self.dir, "prefix": "T", "guide_sync": False, "normalize": "off",
             "reveal_in_explorer": False, "timestamp": "20261004_120000"}, **options))
        return res, calls, verify_calls

    def test_compresses_in_the_same_join(self):
        args = ["-c:v", "hevc_nvenc", "-cq", "26"]
        res, calls, ver = self._export([(0, True, False)], video_args=args)
        self.assertTrue(res["success"])
        self.assertTrue(res["compressed"])
        cmd = calls[0]
        self.assertEqual(cmd[cmd.index("-hwaccel") + 1], "auto")
        self.assertLess(cmd.index("-hwaccel"), cmd.index(self.video))           # va antes del video
        self.assertIn("hevc_nvenc", cmd)
        self.assertNotIn("copy", cmd[cmd.index("-c:v"):cmd.index("-c:a")])
        # las marcas de tiempo pasan tal cual: la sincronía no cambia
        self.assertEqual(cmd[cmd.index("-fps_mode") + 1], "passthrough")
        self.assertEqual(cmd[cmd.index("-enc_time_base") + 1], "demux")
        self.assertTrue(cmd[-1].endswith(".mp4.part"))
        self.assertEqual(cmd[-3:-1], ["-f", "mp4"])
        final = os.path.join(self.dir, "T_20261004_120000_4K.mp4")
        self.assertEqual(res["final_path"], final)
        self.assertTrue(os.path.exists(final), "el .part pasó a ser el MP4")
        self.assertFalse(os.path.exists(final + ".part"))
        self.assertFalse(os.path.exists(self.video), "verificado: se borran los originales")
        self.assertEqual(ver, [final + ".part"])

    def test_without_encoder_it_copies_as_always(self):
        res, calls, _ = self._export([(0, True, False)])
        self.assertTrue(res["success"])
        self.assertFalse(res["compressed"])
        self.assertIn("copy", calls[0])
        self.assertNotIn("-hwaccel", calls[0])

    def test_encoder_failure_falls_back_to_copy(self):
        res, calls, _ = self._export([(1, False, False), (0, True, False)], video_args=["-c:v", "hevc_amf"])
        self.assertTrue(res["success"])
        self.assertFalse(res["compressed"])
        self.assertIn("hevc_amf", calls[0])
        self.assertIn("copy", calls[1])

    def test_too_slow_falls_back_to_copy(self):
        res, calls, _ = self._export([(1, False, True), (0, True, False)], video_args=["-c:v", "libx265"])
        self.assertTrue(res["success"])
        self.assertEqual(len(calls), 2)
        self.assertIn("copy", calls[1])

    def test_bad_compressed_file_falls_back_to_copy(self):
        seen = []

        def verify(path):
            seen.append(path)
            return (len(seen) > 1, "faltan cuadros")     # el comprimido falla, la copia no
        res, calls, _ = self._export([(0, True, False), (0, True, False)], video_args=["-c:v", "hevc_nvenc"],
                                     verify=verify)
        self.assertTrue(res["success"])
        self.assertFalse(res["compressed"])
        self.assertEqual(len(calls), 2)
        self.assertIn("copy", calls[1])

    def test_compression_that_saves_nothing_is_discarded(self):
        def run_big(cmd, progress, duration, min_speed):
            with open(cmd[-1], "wb") as f:
                f.write(b"y" * 5000)                    # más grande que el original (1000)
            return {"returncode": 0, "stderr": "", "slow": False, "frames": 1}
        self.e._run_export = run_big
        self.e._verify_export = lambda *a: (True, "")
        res = self.e.post_process_session(self.video, self.audio, {
            "output_dir": self.dir, "prefix": "T", "guide_sync": False, "normalize": "off",
            "reveal_in_explorer": False, "video_args": ["-c:v", "hevc_nvenc"]})
        self.assertTrue(res["success"])
        self.assertFalse(res["compressed"])

    def test_unverified_copy_keeps_originals(self):
        res, calls, _ = self._export([(0, True, False)], verify=(False, "no se puede leer completo"))
        self.assertFalse(res["success"])
        self.assertTrue(os.path.exists(self.video), "los originales se conservan")
        self.assertTrue(os.path.exists(self.master))
        self.assertEqual([f for f in os.listdir(self.dir) if ".mp4" in f], [], "ni MP4 ni .part a medias")

    def test_progress_steps(self):
        steps = []
        self._export([(0, True, False)], video_args=["-c:v", "hevc_nvenc"],
                     progress=lambda s, f, sp, eta: steps.append(s))
        self.assertEqual(steps, ["encode", "verify", "done"])




@unittest.skipUnless(os.path.exists(FFMPEG), "ffmpeg del proyecto no disponible")
class TestExportRealFfmpeg(unittest.TestCase):
    """De punta a punta con el ffmpeg real: comprime, verifica, conserva sincronía y borra."""

    def test_real_compressed_join(self):
        from engine import CameraEngine
        d = tempfile.mkdtemp()
        try:
            video = os.path.join(d, "v.mkv")
            wav = os.path.join(d, "m.wav")
            subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                            "-t", "3", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "1", video], check=True)
            with wave.open(wav, "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(48000)
                w.writeframes(b"\x00\x00" * 2 * 48000 * 3)
            e = CameraEngine()
            e.ffmpeg_path = FFMPEG
            info = e.probe_media(video)
            self.assertEqual((info["codec"], info["height"]), ("h264", 720))
            steps = []
            res = e.post_process_session(video, {"master_wav": wav, "tracks": [], "duration": 3.0}, {
                "output_dir": d, "prefix": "T", "guide_sync": False, "normalize": "off", "reveal_in_explorer": False,
                "video_args": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"], "source_info": info,
                "progress": lambda s, f, sp, eta: steps.append(s)})
            self.assertTrue(res["success"], res.get("message", "")[-500:])
            self.assertTrue(res["compressed"])
            self.assertIn("verify", steps)
            out = e.probe_media(res["final_path"])
            self.assertEqual(out["audio_streams"], 1)
            self.assertFalse(os.path.exists(video))
            self.assertLess(os.path.getsize(res["final_path"]), info["bitrate"] * 3 / 8)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
