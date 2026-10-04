"""Pruebas del módulo Transmisión: plataformas, cuentas cifradas, medidor, plan de calidad,
registro de MediaMTX y una transmisión real de punta a punta con destinos simulados."""
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = os.path.join(ROOT, "build", "vendor", "ffmpeg", "ffmpeg.exe")
MTX = os.path.join(ROOT, "build", "vendor", "mediamtx", "mediamtx.exe")


class TestPlatforms(unittest.TestCase):
    def test_ingest_url_keeps_key_out_of_logs(self):
        from modules.streaming.platforms import ingest_url, redact, get
        url = ingest_url("rtmps://a.rtmps.youtube.com/live2/", " abcd-1234 ")
        self.assertEqual(url, "rtmps://a.rtmps.youtube.com/live2#abcd-1234")
        self.assertEqual(redact(url), "rtmps://a.rtmps.youtube.com/live2#•••")
        self.assertIsNone(ingest_url("https://youtube.com", "k"), "solo RTMP/RTMPS")
        self.assertIsNone(ingest_url("rtmp://x/app", ""), "sin clave no hay destino")
        self.assertTrue(get("facebook").server.startswith("rtmps://"), "Facebook exige RTMPS")
        self.assertEqual(get("tiktok").orientation, "v")
        self.assertTrue(get("instagram").key_per_session)
        self.assertEqual(get("desconocida").key, "custom")


@unittest.skipUnless(sys.platform == "win32", "DPAPI es de Windows")
class TestAccounts(unittest.TestCase):
    def test_keys_are_encrypted_at_rest(self):
        from modules.streaming.accounts import Accounts, protect, unprotect
        store = {}
        acc = Accounts(store)
        d = acc.save("youtube", "Mi canal", "rtmps://a.rtmps.youtube.com/live2", "clave-super-secreta")
        raw = json.dumps(store)
        self.assertNotIn("clave-super-secreta", raw, "la clave no se guarda en texto plano")
        self.assertTrue(d["key"].startswith("dpapi:"))
        self.assertEqual(acc.key_of(d["id"]), "clave-super-secreta")
        acc.save("youtube", "Mi canal 2", "rtmps://x/live2", None, did=d["id"])     # editar sin tocar la clave
        self.assertEqual(acc.key_of(d["id"]), "clave-super-secreta")
        acc.set_enabled(d["id"], False)
        self.assertEqual(acc.enabled(), [])
        acc.remove(d["id"])
        self.assertEqual(acc.items, [])
        self.assertEqual(unprotect(protect("")), "")
        self.assertEqual(unprotect("dpapi:AAAA"), "", "de otra PC o usuario: hay que volver a pegarla")


class TestBandwidth(unittest.TestCase):
    def test_summary_uses_the_bad_moments(self):
        from modules.streaming.bandwidth import summarize
        # la medición real de esta PC (Mbps por segundo)
        s = summarize([121, 86, 36, 23, 61, 48, 65, 38, 117, 75, 36, 59])
        self.assertEqual(s["median"], 59)
        self.assertEqual(s["stable"], 36)
        self.assertEqual(s["budget_kbps"], 25200)          # 70 % de lo estable
        self.assertEqual(summarize([])["budget_kbps"], 0)

    def test_measure_counts_what_was_sent(self):
        from modules.streaming import bandwidth

        class FakeConn:
            def __init__(self):
                pass

            def request(self, *a):
                pass

            def putrequest(self, *a):
                pass

            def putheader(self, *a):
                pass

            def endheaders(self):
                pass

            def send(self, data):
                time.sleep(0.01)

            def getresponse(self):
                class R:
                    def read(self):
                        return b""
                return R()

            def close(self):
                pass
        seen = []
        out = bandwidth.measure(duration=2.2, conns=2, progress=seen.append, connect=FakeConn)
        self.assertGreaterEqual(len(out["samples"]), 2)
        self.assertGreater(out["samples"][0], 1)            # ~2 × 256 KB cada 10 ms
        self.assertTrue(seen and seen[-1] <= 1.0)


class TestPlanner(unittest.TestCase):
    def test_this_pc_with_six_platforms(self):
        """Con 25 Mbps estables y 4 horizontales + 2 verticales: 1080p a 4,5 Mbps y vertical a 3 Mbps."""
        from modules.streaming.planner import plan
        p = plan(25200, 4, 2, max_h=6000, max_v=6000)
        self.assertTrue(p.fits)
        self.assertEqual((p.h.height, p.h.kbps), (1080, 4500))
        self.assertEqual((p.v.height, p.v.kbps), (1280, 3000))
        self.assertLessEqual(p.total_kbps, 25200)

    def test_platform_limits_and_not_enough(self):
        from modules.streaming.planner import plan
        self.assertEqual(plan(50000, 1, 0, max_h=6000).h.kbps, 6000)
        self.assertIsNone(plan(50000, 1, 0).v)
        tight = plan(3000, 4, 2)
        self.assertFalse(tight.fits)
        self.assertLess(tight.relay_kbps, tight.total_kbps, "un servicio que reparte necesita una sola subida")
        self.assertEqual(plan(None, 1, 0).h.kbps, 6000, "sin medir: presupuesto prudente")


class TestMediaMtxLog(unittest.TestCase):
    def test_parse(self):
        from modules.streaming.mediamtx import parse_line
        self.assertEqual(parse_line("2026/10/04 08:46:14 INF [path live] [RTMP dest 2 fd1a80f7] forwarding to 'rtmp://x/b'"),
                         ("live", 2, "connecting", ""))
        ev = parse_line("2026/10/04 08:46:20 ERR [path vertical] [RTMP dest 1 aa] dial tcp: refused")
        self.assertEqual(ev[:3], ("vertical", 1, "error"))
        self.assertIsNone(parse_line("INF [RTMP] listener opened on 127.0.0.1:1935"))


@unittest.skipUnless(os.path.exists(FFMPEG) and os.path.exists(MTX), "ffmpeg o MediaMTX del proyecto no disponibles")
class TestLiveEndToEnd(unittest.TestCase):
    """Transmisión real: el codificador publica en el repartidor local, que reenvía a dos
    «plataformas» simuladas (otros MediaMTX): una horizontal y una vertical."""

    def _dest(self, rtmp, api):
        import tempfile
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "d.yml")
        with open(cfg, "w") as f:
            f.write(f"rtsp: no\nhls: no\nwebrtc: no\nsrt: no\nmoq: no\nrtmpAddress: 127.0.0.1:{rtmp}\n"
                    f"api: yes\napiAddress: 127.0.0.1:{api}\npaths:\n  all_others:\n")
        return subprocess.Popen([MTX, cfg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)

    def _info(self, api, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{api}/v3/paths/get/{path}", timeout=2) as r:
                return json.load(r)
        except Exception:
            return None

    def test_one_encode_two_orientations(self):
        from modules.streaming.mediamtx import free_port
        from modules.streaming.planner import plan
        from modules.streaming.session import LiveSession, Target
        ports = [free_port() for _ in range(4)]
        A, B = self._dest(ports[0], ports[1]), self._dest(ports[2], ports[3])
        logs = []
        s = LiveSession(FFMPEG, MTX, log=lambda m, c="": logs.append(m))
        try:
            time.sleep(1.5)
            targets = [Target("a", "Horizontal", f"rtmp://127.0.0.1:{ports[0]}/live2#CLAVE_A", False),
                       Target("b", "Vertical", f"rtmp://127.0.0.1:{ports[2]}/rtmp#CLAVE_B", True)]
            ok = s.start(targets, plan(20000, 1, 1), "libx264", "x", 48000, lambda p: None, lambda: None,
                         keys=["CLAVE_A", "CLAVE_B"],
                         video_input=["-re", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30"],
                         audio_input=["-re", "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000"])
            self.assertTrue(ok, logs)
            time.sleep(9)
            a = self._info(ports[1], "live2/CLAVE_A")
            b = self._info(ports[3], "rtmp/CLAVE_B")
            self.assertTrue(a and a["ready"], logs)
            self.assertTrue(b and b["ready"], logs)
            wa = {t["codec"]: t.get("codecProps", {}) for t in a["tracks2"]}
            wb = {t["codec"]: t.get("codecProps", {}) for t in b["tracks2"]}
            self.assertEqual((wa["H264"]["width"], wa["H264"]["height"]), (1920, 1080))
            self.assertEqual((wb["H264"]["width"], wb["H264"]["height"]), (720, 1280), "vertical 9:16")
            self.assertIn("MPEG-4 Audio", wa)
            self.assertEqual([x["state"] for x in s.status()], ["live", "live"])
            self.assertFalse(any("CLAVE_" in m for m in logs), "las claves no van al registro")
        finally:
            s.stop()
            for p in (A, B):
                p.kill()
        self.assertFalse(s.running)

    def test_each_destination_turns_on_and_off_alone(self):
        """Cada plataforma se enciende y apaga sola: apagar una no corta a la otra ni al codificador."""
        from modules.streaming.mediamtx import free_port
        from modules.streaming.planner import plan
        from modules.streaming.session import LiveSession, Target
        ports = [free_port() for _ in range(4)]
        A, B = self._dest(ports[0], ports[1]), self._dest(ports[2], ports[3])
        s = LiveSession(FFMPEG, MTX, log=lambda m, c="": None)
        try:
            time.sleep(1.5)
            ok = s.open(plan(20000, 2, 0), "libx264", "x", 48000, True, False, lambda p: None, lambda: None,
                        video_input=["-re", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30"],
                        audio_input=["-re", "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000"])
            self.assertTrue(ok)
            ta = Target("a", "A", f"rtmp://127.0.0.1:{ports[0]}/live#KA", False)
            tb = Target("b", "B", f"rtmp://127.0.0.1:{ports[2]}/live#KB", False)
            self.assertTrue(s.add(ta))
            self.assertFalse(s.add(Target("v", "V", "rtmp://x/y#k", True)), "sin salida vertical abierta")
            time.sleep(5)
            self.assertTrue(s.add(tb))
            time.sleep(6)
            self.assertTrue(self._info(ports[1], "live/KA")["ready"])
            b1 = self._info(ports[3], "live/KB")["bytesReceived"]
            self.assertTrue(s.remove("a"))
            self.assertEqual(s.state_of("a")["state"], "off")
            time.sleep(4)
            self.assertIsNone(self._info(ports[1], "live/KA"), "A se apagó")
            b2 = self._info(ports[3], "live/KB")["bytesReceived"]
            self.assertGreater(b2, b1, "B siguió recibiendo")
            self.assertTrue(s.running, "el codificador no se cortó")
            self.assertEqual([x["id"] for x in s.status()], ["b"])
        finally:
            s.close()
            for p in (A, B):
                p.kill()


class TestCapacity(unittest.TestCase):
    def test_how_many_at_once(self):
        from modules.streaming.planner import capacity
        c = capacity(25200)                    # tu conexión: ~25 Mbps de presupuesto
        self.assertEqual(c["1080p"], 5)        # 4,5 Mbps + audio cada una
        self.assertEqual(c["720p"], 9)
        self.assertEqual(capacity(None), {"1080p": 0, "720p": 0, "vertical": 0})


if __name__ == "__main__":
    unittest.main()
