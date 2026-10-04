"""
Pruebas Unitarias para GalaxyCamPro - Backend Engine (engine.py)
Verifica la compatibilidad con Android 16, construcción de comandos 4K, parsing de ADB,
detección de dispositivos, benchmark de cable y manejo de errores.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock
import tempfile
import numpy as np

# Asegurar importación del backend
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as engine_mod
from engine import CameraEngine
import virtualcam


class TestCommandBuilding(unittest.TestCase):
    """Pruebas para la generación correcta de argumentos para scrcpy"""

    def setUp(self):
        self.engine = CameraEngine()
        # Usar un archivo existente para pasar la validación os.path.exists
        self.engine.scrcpy_path = sys.executable
        self.engine.adb_path = sys.executable

    def test_android_16_compatibility(self):
        """CRÍTICO: Verifica que --no-control esté siempre presente y que no existan flags de control incompatibles"""
        config = {
            "serial": "TESTSERIAL001",
            "size": "3840x2160",
            "fps": 30,
            "codec": "h265",
            "bitrate": "50M"
        }
        cmd = self.engine.build_command(config)

        # 1. Debe incluir --no-control obligatoriamente
        self.assertIn("--no-control", cmd, "Falta --no-control, necesario para evitar el error de AssertionError en Android 16")

        # 2. NO debe incluir flags de control que causen AssertionError: Unexpected message type: 10
        self.assertNotIn("--turn-screen-off", cmd, "--turn-screen-off no debe estar presente porque rompe en Android 16 con no-control")
        self.assertNotIn("--stay-awake", cmd, "--stay-awake no debe estar presente porque requiere control")

    def test_guide_track_only_when_recording_and_never_played(self):
        """La pista guía (micrófono del teléfono) va al .mkv al grabar, sin sonar en el PC."""
        rec_dir = tempfile.mkdtemp()
        cmd = self.engine.build_command({"serial": "X", "record_video": True, "record_dir": rec_dir})
        self.assertIn("--audio-source=mic-camcorder", cmd)
        self.assertIn("--no-audio-playback", cmd)
        self.assertNotIn("--no-audio", cmd)
        preview = self.engine.build_command({"serial": "X"})
        self.assertIn("--no-audio", preview)
        off = self.engine.build_command({"serial": "X", "record_video": True, "record_dir": rec_dir, "guide_audio": False})
        self.assertIn("--no-audio", off)

    def test_4k_command_configuration(self):
        """Verifica la configuración para streaming 4K UHD a 50M H.265"""
        config = {
            "serial": "TESTSERIAL001",
            "size": "3840x2160",
            "fps": 60,
            "codec": "h265",
            "bitrate": "50M",
            "camera_facing": "back",
            "low_latency": True
        }
        cmd = self.engine.build_command(config)

        self.assertIn("--video-source=camera", cmd)
        self.assertIn("-s", cmd)
        self.assertIn("TESTSERIAL001", cmd)
        self.assertIn("--camera-size=3840x2160", cmd)
        self.assertIn("--camera-fps=60", cmd)
        self.assertIn("--video-codec=h265", cmd)
        self.assertIn("-b", cmd)
        self.assertIn("50M", cmd)
        self.assertIn("--video-buffer=0", cmd)

    def test_lens_mapping(self):
        """Verifica que los sensores del S23 Ultra se mapeen a los Camera IDs comprobados (0, 1, 2)"""
        # Cámara trasera principal (Sensor 200MP unificado con zoom 0.6x - 10x)
        config_back = {"camera_facing": "back"}
        cmd_back = self.engine.build_command(config_back)
        self.assertIn("--camera-id=0", cmd_back)

        # Cámara frontal (Selfie 12MP)
        config_front = {"camera_facing": "front"}
        cmd_front = self.engine.build_command(config_front)
        self.assertIn("--camera-id=1", cmd_front)

        # Cámara específica solicitada directamente
        config_custom = {"camera_id": "2"}
        cmd_custom = self.engine.build_command(config_custom)
        self.assertIn("--camera-id=2", cmd_custom)

    def test_audio_and_recording_options(self):
        """Verifica la configuración de audio estéreo y grabación MP4"""
        temp_dir = tempfile.gettempdir()
        config = {
            "audio_mic": True,
            "record_video": True,
            "record_dir": temp_dir,
            "zoom": 2.5
        }
        cmd = self.engine.build_command(config)

        self.assertIn("--audio-source=mic-camcorder", cmd)
        self.assertIn("--audio-codec=opus", cmd)
        self.assertIn("--record-format=mkv", cmd)
        self.assertTrue(any(arg.startswith("--record=") for arg in cmd))
        self.assertIn("--camera-zoom=2.5", cmd)

    def test_video_buffer_options(self):
        """Verifica la configuración del búfer de video para estabilizar la transmisión contra el jitter y lag"""
        # 1. Búfer predeterminado de fluidez (100 ms) cuando no se pide low_latency
        cfg_default = {"size": "3840x2160"}
        cmd_default = self.engine.build_command(cfg_default)
        self.assertIn("--video-buffer=100", cmd_default)

        # 2. Búfer explícito personalizado (ej: 200 ms)
        cfg_custom = {"size": "3840x2160", "video_buffer": 200}
        cmd_custom = self.engine.build_command(cfg_custom)
        self.assertIn("--video-buffer=200", cmd_custom)

        # 3. Modo latencia cero explícito
        cfg_zero = {"size": "1920x1080", "low_latency": True}
        cmd_zero = self.engine.build_command(cfg_zero)
        self.assertIn("--video-buffer=0", cmd_zero)

    def test_window_scaling_and_headless(self):
        """Verifica el escalado de ventana del visor (para no saturar GPU) y el modo sin visor (headless)"""
        # 1. Escalado a 720p (1280px de ancho) mientras se captura en 4K UHD
        cfg_scaled = {"size": "3840x2160", "window_width": 1280}
        cmd_scaled = self.engine.build_command(cfg_scaled)
        self.assertIn("--camera-size=3840x2160", cmd_scaled)
        self.assertIn("--window-width=1280", cmd_scaled)

        # 2. Modo headless sin visor (--no-playback) para grabar en 4K en segundo plano
        cfg_headless = {"size": "3840x2160", "no_playback": True}
        cmd_headless = self.engine.build_command(cfg_headless)
        self.assertIn("--no-playback", cmd_headless)
        self.assertNotIn("--window-title", " ".join(cmd_headless))


    def test_manual_rotation_uses_capture_orientation(self):
        """El giro lo aplica el teléfono antes de codificar: --capture-orientation."""
        base = {"serial": "TESTSERIAL001", "size": "3840x2160", "fps": 30}
        for deg in (90, 180, 270):
            cmd = self.engine.build_command(dict(base, rotation=deg))
            self.assertIn(f"--capture-orientation={deg}", cmd)
            # El giro no debe tocar la grabación sin recodificar ni el tamaño pedido
            self.assertIn("--camera-size=3840x2160", cmd)
        # Apagado por defecto y a prueba de valores inservibles de un perfil viejo
        for value in (None, 0, "", "x", 45, 720):
            cmd = self.engine.build_command(dict(base, rotation=value))
            self.assertFalse([a for a in cmd if a.startswith("--capture-orientation")],
                             f"No debería girar con rotation={value!r}")


class TestDeviceParsing(unittest.TestCase):
    """Pruebas para detección y análisis de estados de ADB"""

    def setUp(self):
        self.engine = CameraEngine()
        self.engine.adb_path = sys.executable

    @patch("subprocess.run")
    def test_device_connected_parsing(self, mock_run):
        """Verifica la detección de un dispositivo online"""
        mock_output = (
            "List of devices attached\n"
            "TESTSERIAL001            device product:dm3qxxx model:SM_S918B device:dm3q transport_id:1\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

        devices = self.engine.check_device_changes()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["serial"], "TESTSERIAL001")
        self.assertEqual(devices[0]["state"], "device")
        self.assertEqual(devices[0]["model"], "SM S918B")
        self.assertFalse(devices[0]["is_wifi"])

    @patch("subprocess.run")
    def test_wifi_device_parsing(self, mock_run):
        """Verifica la detección de conexión inalámbrica por IP"""
        mock_output = (
            "List of devices attached\n"
            "192.168.1.105:5555     device product:dm3qxxx model:SM_S918B device:dm3q transport_id:2\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")

        devices = self.engine.check_device_changes()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["serial"], "192.168.1.105:5555")
        self.assertTrue(devices[0]["is_wifi"])

    @patch("subprocess.run")
    def test_device_state_transitions(self, mock_run):
        """Verifica que el motor detecte cambios de estado (online -> offline -> desconectado)"""
        # 1. Conecta
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="List of devices attached\nTESTSERIAL001 device model:SM_S918B\n"
        )
        devs1 = self.engine.check_device_changes()
        self.assertEqual(devs1[0]["state"], "device")
        self.assertEqual(self.engine.last_device_states["TESTSERIAL001"], "device")

        # 2. Pasa a Offline
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="List of devices attached\nTESTSERIAL001 offline model:SM_S918B\n"
        )
        devs2 = self.engine.check_device_changes()
        self.assertEqual(devs2[0]["state"], "offline")
        self.assertEqual(self.engine.last_device_states["TESTSERIAL001"], "offline")

        # 3. Se desconecta físicamente
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="List of devices attached\n"
        )
        devs3 = self.engine.check_device_changes()
        self.assertEqual(len(devs3), 0)
        self.assertNotIn("TESTSERIAL001", self.engine.last_device_states)


class TestBatteryAndNetwork(unittest.TestCase):
    """Pruebas de extracción y caché de batería e IP"""

    def setUp(self):
        self.engine = CameraEngine()
        self.engine.adb_path = sys.executable

    @patch("subprocess.run")
    def test_battery_parsing_and_cache(self, mock_run):
        """Verifica extracción del nivel de batería y uso de memoria caché"""
        dumpsys_output = (
            "Current Battery Service state:\n"
            "  AC powered: false\n"
            "  USB powered: true\n"
            "  level: 84\n"
            "  scale: 100\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=dumpsys_output)

        # Primera consulta (ejecuta subprocess)
        bat1 = self.engine.get_device_battery("TESTSERIAL001")
        self.assertEqual(bat1, 84)
        self.assertEqual(mock_run.call_count, 1)

        # Segunda consulta (debe retornar de caché sin llamar de nuevo a subprocess)
        bat2 = self.engine.get_device_battery("TESTSERIAL001")
        self.assertEqual(bat2, 84)
        self.assertEqual(mock_run.call_count, 1)

    @patch("subprocess.run")
    def test_wifi_ip_extraction(self, mock_run):
        """Verifica extracción de la IP de la interfaz wlan0"""
        ip_output = (
            "33: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 3000\n"
            "    inet 192.168.1.120/24 brd 192.168.1.255 scope global wlan0\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=ip_output)

        ip = self.engine.get_device_wifi_ip("TESTSERIAL001")
        self.assertEqual(ip, "192.168.1.120")


class TestCableSpeedBenchmark(unittest.TestCase):
    """Pruebas de la lógica de calibración y clasificación de velocidad del cable USB"""

    def setUp(self):
        self.engine = CameraEngine()
        self.engine.adb_path = sys.executable

    @patch("subprocess.run")
    def test_usb_3_classification(self, mock_run):
        """Verifica que velocidades >= 20 MB/s clasifiquen como USB 3.0 con 4K habilitado"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="1 file pushed, 0 skipped. 38.5 MB/s (3145728 bytes in 0.081s)\n",
            stderr=""
        )
        res = self.engine.test_cable_speed("TESTSERIAL001", size_mb=1)

        self.assertTrue(res["success"])
        self.assertEqual(res["speed_mb_s"], 38.5)
        self.assertIn("USB 3.0", res["classification"])
        self.assertIn("4K UHD", res["max_res"])

    @patch("subprocess.run")
    def test_usb_2_classification(self, mock_run):
        """Verifica que velocidades entre 8 y 20 MB/s limiten a 1080p y bloqueen 4K"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="1 file pushed, 0 skipped. 14.2 MB/s (3145728 bytes in 0.221s)\n",
            stderr=""
        )
        res = self.engine.test_cable_speed("TESTSERIAL001", size_mb=1)

        self.assertTrue(res["success"])
        self.assertEqual(res["speed_mb_s"], 14.2)
        self.assertIn("USB 2.0", res["classification"])
        self.assertIn("1080p", res["max_res"])

    @patch("subprocess.run")
    def test_slow_cable_classification(self, mock_run):
        """Verifica que cables lentos (< 8 MB/s) clasifiquen con advertencia y bloqueen 4K y 2K"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="1 file pushed, 0 skipped. 1.2 MB/s (3145728 bytes in 2.621s)\n",
            stderr=""
        )
        res = self.engine.test_cable_speed("TESTSERIAL001", size_mb=1)

        self.assertTrue(res["success"])
        self.assertEqual(res["speed_mb_s"], 1.2)
        self.assertIn("Cable Lento", res["classification"])
        self.assertIn("720p", res["max_res"])

    @patch("subprocess.run")
    def test_cable_failure_handling(self, mock_run):
        """Verifica que fallos de conexión (EOF / reset) no rompan el programa y retornen error estructurado"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="adb: error: failed to read copy response: EOF\n"
        )
        res = self.engine.test_cable_speed("TESTSERIAL001", size_mb=1)

        self.assertFalse(res["success"])
        self.assertIn("Fallo al transferir datos", res["message"])


class TestRealDeviceIntegration(unittest.TestCase):
    """Pruebas de integración directa contra el S23 Ultra conectado en el sistema"""

    def setUp(self):
        self.engine = CameraEngine()

    def test_binaries_present(self):
        """Verifica que scrcpy y adb estén instalados y accesibles en Windows"""
        self.assertIsNotNone(self.engine.scrcpy_path, "scrcpy.exe no fue encontrado")
        self.assertIsNotNone(self.engine.adb_path, "adb.exe no fue encontrado")
        self.assertTrue(os.path.exists(self.engine.scrcpy_path))
        self.assertTrue(os.path.exists(self.engine.adb_path))

    def test_real_device_detection(self):
        """Verifica la detección en vivo del Galaxy S23 Ultra"""
        devices = self.engine.check_device_changes()
        if not devices:
            self.skipTest("No hay teléfono conectado físicamente en este momento para la prueba en vivo.")

        dev = devices[0]
        self.assertEqual(dev["state"], "device", "El dispositivo debe estar en estado 'device'")
        self.assertTrue("S918" in dev["model"] or "Galaxy" in dev["model"] or "TESTSERIAL001" == dev["serial"])

    def test_real_battery_read(self):
        """Verifica la lectura real del nivel de batería del móvil conectado"""
        devices = self.engine.check_device_changes()
        if not devices:
            self.skipTest("No hay teléfono conectado físicamente.")

        serial = devices[0]["serial"]
        bat = self.engine.get_device_battery(serial)
        self.assertIsNotNone(bat)
        self.assertGreaterEqual(bat, 0)
        self.assertLessEqual(bat, 100)


class TestUniversalAndReporting(unittest.TestCase):
    """Pruebas para compatibilidad universal con cualquier móvil Android y el sistema de reporte con IA"""

    def setUp(self):
        self.engine = CameraEngine()
        self.engine.scrcpy_path = sys.executable
        self.engine.adb_path = sys.executable

    @patch("subprocess.run")
    def test_get_device_info_pixel(self, mock_run):
        """Verifica la detección universal de un dispositivo no-Samsung (ej: Google Pixel 8 Pro)"""
        mock_output = "google\nPixel 8 Pro\n14\nGoogle Pixel 8 Pro\n"
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)

        info = self.engine.get_device_info("PIXEL123")
        self.assertEqual(info["brand"], "Google")
        self.assertIn("Pixel", info["friendly_name"])
        self.assertEqual(info["android_version"], "14")
        self.assertTrue(info["camera_supported"])

    @patch("subprocess.run")
    def test_get_device_info_android_below_12(self, mock_run):
        """Verifica que dispositivos con Android < 12 se identifiquen como no compatibles con webcam directa"""
        mock_output = "motorola\nmoto g(9) play\n11\n\n"
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)

        info = self.engine.get_device_info("MOTO456")
        self.assertEqual(info["android_version"], "11")
        self.assertFalse(info["camera_supported"])

    @patch("subprocess.run")
    def test_dynamic_camera_discovery(self, mock_run):
        """Verifica el descubrimiento dinámico de lentes de cámara mediante scrcpy --list-cameras"""
        mock_output = (
            "[server] INFO: List of cameras:\n"
            "    --camera-id=0    (back, 4080x3060, fps={10, 15, 30})\n"
            "    --camera-id=1    (front, 4000x3000, fps={10, 15, 30})\n"
            "    --camera-id=2    (back, 4000x3000, fps={10, 30})\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)

        cams = self.engine.get_device_cameras("TEST_SERIAL")
        self.assertEqual(len(cams), 3)
        self.assertEqual(cams[0]["id"], "0")
        self.assertEqual(cams[0]["facing"], "back")
        self.assertEqual(cams[1]["id"], "1")
        self.assertEqual(cams[1]["facing"], "front")
        self.assertEqual(cams[0]["fps"], [10, 15, 30])

    @patch("subprocess.run")
    def test_camera_discovery_zoom_range(self, mock_run):
        """scrcpy 4.x informa el rango de zoom: en el S23 Ultra 0.6× (gran angular) a 10× (tele)"""
        mock_output = (
            "[server] INFO: List of cameras:\n"
            "    --camera-id=0    (back, 4080x3060, fps={10, 11, 15, 24, 30}, zoom-range=[0.6, 10])\n"
            "        - 4080x3060\n"
            "    --camera-id=1    (front, 4000x3000, fps={10, 15, 24, 30}, zoom-range=[1, 8])\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)

        cams = self.engine.get_device_cameras("ZOOM_SERIAL")
        self.assertEqual(len(cams), 2)
        self.assertEqual((cams[0]["zoom_min"], cams[0]["zoom_max"]), (0.6, 10.0))
        self.assertEqual(cams[0]["fps"], [10, 11, 15, 24, 30])
        self.assertEqual(cams[0]["resolution"], "4080x3060")

    @patch("subprocess.run")
    def test_camera_discovery_high_speed(self, mock_run):
        """El S23 Ultra da 30 fps en modo normal y 120/240 en alta velocidad (1080p/720p)"""
        mock_output = (
            "[server] INFO: List of cameras:\n"
            "    --camera-id=0    (back, 4080x3060, fps={10, 11, 15, 24, 30}, zoom-range=[0.6, 10])\n"
            "        - 4080x3060\n"
            "        - 1920x1080\n"
            "      High speed capture (--camera-high-speed):\n"
            "        - 1280x720 (fps={120, 240})\n"
            "        - 1920x1080 (fps={120, 240})\n"
            "    --camera-id=1    (front, 4000x3000, fps={10, 15, 24, 30}, zoom-range=[1, 8])\n"
            "        - 4000x3000\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
        cams = self.engine.get_device_cameras("HS_SERIAL")
        self.assertIn("--list-camera-sizes", mock_run.call_args[0][0])
        self.assertEqual(cams[0]["high_speed"], {"1280x720": [120, 240], "1920x1080": [120, 240]})
        self.assertEqual(cams[1]["high_speed"], {})

        from infrastructure.video.command_builder import high_speed_rate, high_speed_sizes_for
        self.assertEqual(high_speed_rate(cams[0], "1920x1080", 60), 120)
        self.assertIsNone(high_speed_rate(cams[0], "3840x2160", 60), "4K no tiene alta velocidad")
        self.assertIsNone(high_speed_rate(cams[0], "1920x1080", 30), "30 fps sale en modo normal")
        self.assertIsNone(high_speed_rate(cams[1], "1920x1080", 60))
        self.assertEqual(sorted(high_speed_sizes_for(cams[0], 60)), ["1280x720", "1920x1080"])

    def test_high_speed_command(self):
        """60 fps por alta velocidad: el sensor a 120 y el teléfono deja pasar 60"""
        cmd = self.engine.build_command({"camera_id": "0", "size": "1920x1080", "fps": 60, "high_speed_fps": 120})
        self.assertIn("--camera-high-speed", cmd)
        self.assertIn("--camera-fps=120", cmd)
        self.assertIn("--max-fps=60", cmd)
        normal = self.engine.build_command({"camera_id": "0", "size": "1920x1080", "fps": 30})
        self.assertIn("--camera-fps=30", normal)
        self.assertNotIn("--camera-high-speed", normal)
        self.assertFalse(any(a.startswith("--max-fps") for a in normal))

    def test_lens_zoom_in_command(self):
        """El objetivo gran angular (0.6×) viaja como zoom inicial de la cámara principal"""
        cmd = self.engine.build_command({"camera_id": "0", "camera_facing": "back", "zoom": 0.6})
        self.assertIn("--camera-id=0", cmd)
        self.assertIn("--camera-zoom=0.6", cmd)
        cmd_main = self.engine.build_command({"camera_id": "0", "camera_facing": "back", "zoom": None})
        self.assertFalse(any(a.startswith("--camera-zoom") for a in cmd_main))

    def test_ai_report_structure(self):
        """Verifica que el reporte para IA incluya los metadatos requeridos"""
        user_notes = "La transmisión se congeló a los 30 segundos"
        active_cfg = {"size": "3840x2160", "fps": 30, "video_buffer": 100}

        report = self.engine.generate_ai_report(user_notes, active_cfg)
        self.assertNotIn("target_email", report)
        self.assertEqual(report["user_notes"], user_notes)
        self.assertIn("host_environment", report)
        self.assertIn("connected_device", report)
        self.assertIn("session_log_trace", report)
        self.assertEqual(report["active_stream_config"]["video_buffer"], 100)

    @patch("urllib.request.urlopen")
    def test_save_problem_report_stays_local(self, mock_urlopen):
        """El reporte se guarda en la PC y nunca se envía por internet"""
        res = self.engine.save_problem_report("Test de fallo de cámara", {"size": "1920x1080"})
        self.assertTrue(res["success"])
        mock_urlopen.assert_not_called()
        self.assertNotIn("mailto_url", res)
        self.assertTrue(os.path.exists(res["file_path"]))
        self.assertIn("=== DIAGNÓSTICO DE ERROR ULTRACAM PRO ===", res["clipboard_text"])

        # Limpieza de archivo de prueba
        try:
            os.remove(res["file_path"])
        except Exception:
            pass


class _FakeConn:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


class TestAudioEngineServer(unittest.TestCase):
    """Motor de audio: mezcla en tiempo real, monitor, deriva entre relojes y grabación"""

    def _server(self, channels):
        from audio_server import AudioServer, Channel
        srv = AudioServer(_FakeConn())
        srv.sr, srv.block = 48000, 64
        srv.out_pair = [0, 1]
        chans = []
        for cfg in channels:
            ch = Channel(cfg)
            ch.cols = cfg.get("cols")
            chans.append(ch)
        srv.channels = chans
        srv.rt_channels = tuple(chans)
        return srv

    def test_mono_input_goes_to_both_sides_and_monitor(self):
        import numpy as np
        srv = self._server([{"id": "g", "source": {"kind": "main", "ch": [0]}, "mode": "mono", "monitor": True,
                             "cols": [0]}])
        indata = np.zeros((64, 2), dtype=np.float32)
        indata[:, 0] = 0.5                      # guitarra en IN 1, nada en IN 2
        out = np.zeros((64, 2), dtype=np.float32)
        srv._process(indata, out, 64)
        master, posts, peaks, mon, _ = srv.out_q.get_nowait()
        np.testing.assert_allclose(master[:, 0], 0.5)
        np.testing.assert_allclose(master[:, 1], 0.5)
        np.testing.assert_allclose(out[:, 0], 0.5)     # se escucha en el monitor
        self.assertAlmostEqual(peaks[0], 0.5, places=5)

    def test_input_only_and_output_only_callbacks(self):
        """Con solo entrada o solo salida, sounddevice llama con 4 argumentos: antes cada
        bloque fallaba («missing 1 required positional argument: 'status'»)."""
        import numpy as np
        srv = self._server([{"id": "g", "source": {"kind": "main", "ch": [0]}, "mode": "mono", "monitor": True,
                             "cols": [0]}])
        indata = np.full((64, 1), 0.5, dtype=np.float32)
        srv._input_callback(indata, 64, None, None)
        master, *_ = srv.out_q.get_nowait()
        np.testing.assert_allclose(master[:, 0], 0.5)
        out = np.ones((64, 2), dtype=np.float32)
        srv._output_callback(out, 64, None, "underflow")
        self.assertEqual(srv.xruns, 1)
        np.testing.assert_allclose(out, 0.0)   # sin entrada: el monitor queda en silencio

    def test_mute_solo_and_monitor_off(self):
        import numpy as np
        srv = self._server([
            {"id": "a", "source": {"kind": "main", "ch": [0]}, "mode": "mono", "monitor": False, "cols": [0]},
            {"id": "b", "source": {"kind": "main", "ch": [1]}, "mode": "mono", "monitor": True, "cols": [1], "solo": True},
        ])
        indata = np.full((64, 2), 0.25, dtype=np.float32)
        out = np.zeros((64, 2), dtype=np.float32)
        srv._process(indata, out, 64)
        master, posts, peaks, _, _ = srv.out_q.get_nowait()
        np.testing.assert_allclose(master[:, 0], 0.25)  # solo «b» suena (a quedó silenciado por el solo)
        self.assertEqual(peaks[0], 0.0)
        srv.rt_channels[1].mute = True
        srv._process(indata, out, 64)
        master, *_ = srv.out_q.get_nowait()
        np.testing.assert_allclose(master, 0.0)

    def test_drift_buffer_resamples_and_stays_bounded(self):
        import numpy as np
        from audio_server import DriftBuffer
        buf = DriftBuffer(channels=1, in_rate=44100, out_rate=48000, block=256)
        chunk = (np.ones(441, dtype=np.int16) * 16384).tobytes()   # 10 ms a 44.1 kHz
        for _ in range(20):
            buf.push(chunk)
        out = buf.pull(480)
        self.assertEqual(out.shape, (480, 2))
        self.assertAlmostEqual(float(out[-1, 0]), 0.5, places=2)
        for _ in range(500):                    # la fuente va más rápido: no debe crecer sin límite
            buf.push(chunk)
        self.assertLessEqual(buf.count, buf.max_frames)

    def test_recording_writes_master_and_one_track_per_channel(self):
        import wave
        import numpy as np
        srv = self._server([
            {"id": "g", "name": "Guitarra", "source": {"kind": "main", "ch": [0]}, "cols": [0]},
            {"id": "s", "name": "Sistema", "source": {"kind": "device", "device": "x", "loopback": True}},
        ])
        with tempfile.TemporaryDirectory() as d:
            srv.start_recording(d)
            master = np.full((480, 2), 0.1, dtype=np.float32)
            srv.out_q.put((master, [master, None], [0.1, 0.0], 0.0, None))
            import threading
            srv.running = True
            t = threading.Thread(target=srv._writer_loop, daemon=True)
            t.start()
            import time
            time.sleep(0.4)
            srv.running = False
            t.join(2)
            res = srv.stop_recording()
            self.assertEqual([tr["name"] for tr in res["tracks"]], ["Guitarra", "Sistema"])
            for p in [res["master_wav"]] + [tr["wav"] for tr in res["tracks"]]:
                with wave.open(p) as w:
                    self.assertEqual(w.getnframes(), 480)

    def test_scan_vst3_finds_plugins_in_extra_folder(self):
        from audio_engine import scan_vst3
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "MiAmp.vst3", "Contents", "x86_64-win"))
            open(os.path.join(d, "MiAmp.vst3", "Contents", "x86_64-win", "MiAmp.vst3"), "w").close()
            names = [p["name"] for p in scan_vst3([d]) if p["path"].startswith(d)]
            self.assertEqual(names, ["MiAmp"])   # el .vst3 interno del bundle no se cuenta dos veces

    def test_vst3_bundle_resolves_to_inner_binary(self):
        """pedalboard en Windows no carga la carpeta de un bundle .vst3 (Amp Locker, Decent
        Sampler…): hay que pasarle el binario de Contents/x86_64-win."""
        from vst_probe import plugin_binary
        with tempfile.TemporaryDirectory() as d:
            inner = os.path.join(d, "MiSynth.vst3", "Contents", "x86_64-win", "MiSynth.vst3")
            os.makedirs(os.path.dirname(inner))
            open(inner, "w").close()
            self.assertEqual(plugin_binary(os.path.join(d, "MiSynth.vst3")), inner)
            single = os.path.join(d, "Plano.vst3")
            open(single, "w").close()
            self.assertEqual(plugin_binary(single), single)

    def test_probe_cache_skips_known_plugins(self):
        import vst_probe
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Synth.vst3")
            open(p, "w").close()
            plugins = [{"name": "Synth", "path": p}]
            cache = {os.path.normcase(p): {"sig": vst_probe._signature(p), "v": vst_probe.CACHE_VERSION,
                                           "kind": "instrument"}}
            with patch.object(vst_probe, "_run_batch", side_effect=AssertionError("no debía cargarse")):
                self.assertFalse(vst_probe.classify(plugins, cache))
            self.assertEqual(plugins[0]["kind"], "instrument")
            # Si el plugin cambió (otro tamaño), se vuelve a revisar
            with open(p, "w") as f:
                f.write("v2")
            meta = {"name": "Synth Pro", "vendor": "ACME", "category": "Fx|Reverb", "version": "1.2"}
            with patch.object(vst_probe, "_run_batch", return_value={p: ("effect", meta)}):
                self.assertTrue(vst_probe.classify(plugins, cache))
            self.assertEqual(plugins[0]["kind"], "effect")
            entry = cache[os.path.normcase(p)]
            self.assertEqual((entry["vendor"], entry["category"], entry["name"]), ("ACME", "Fx|Reverb", "Synth Pro"))
            # Una caché de la versión anterior (sin fabricante ni categoría) se vuelve a revisar
            entry["v"] = 1
            with patch.object(vst_probe, "_run_batch", return_value={p: ("effect", meta)}) as run:
                vst_probe.classify(plugins, cache)
            run.assert_called_once()

    def test_probe_reports_progress(self):
        """Mientras se revisan los plugins se avisa «3 de 5» (el selector de instrumentos lo muestra)."""
        import vst_probe
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for n in range(3):
                p = os.path.join(d, f"P{n}.vst3")
                open(p, "w").close()
                paths.append(p)

            def fake_batch(todo, on_done=None):
                for _ in todo:
                    on_done()
                return {p: ("effect", {}) for p in todo}
            seen = []
            with patch.object(vst_probe, "_run_batch", side_effect=fake_batch):
                vst_probe.classify([{"name": "P", "path": p} for p in paths], {},
                                   progress=lambda done, total: seen.append((done, total)))
            self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_instrument_groups_and_quick_picks(self):
        from plugin_library import PluginLibrary, instrument_group
        self.assertEqual(instrument_group({"category": "Instrument|Piano", "name": "Keys"}), "piano")
        self.assertEqual(instrument_group({"category": "Instrument|Sampler|Synth", "name": "Kontakt"}), "sampler")
        self.assertEqual(instrument_group({"category": "Instrument", "name": "Addictive Drums 2"}), "drums")
        self.assertEqual(instrument_group({"category": "Instrument", "name": "Raro"}), "other")
        plugins = [{"name": n, "path": rf"C:\VST3\{n}.vst3"} for n in ("Vital", "Keyscape", "Reverb")]
        probe = {os.path.normcase(r"C:\VST3\Vital.vst3"): {"kind": "instrument", "category": "Instrument|Synth"},
                 os.path.normcase(r"C:\VST3\Keyscape.vst3"): {"kind": "instrument", "category": "Instrument|Piano"},
                 os.path.normcase(r"C:\VST3\Reverb.vst3"): {"kind": "effect", "category": "Fx|Reverb"}}
        lib = PluginLibrary(plugins, probe, {})
        self.assertEqual([i["name"] for i in lib.instruments()], ["Keyscape", "Vital"])
        self.assertEqual([i["name"] for i in lib.instruments(group="piano")], ["Keyscape"])
        self.assertEqual([i["name"] for i in lib.instruments("synth")], ["Vital"])
        lib.touch_recent(r"C:\VST3\Reverb.vst3")
        lib.touch_recent(r"C:\VST3\Vital.vst3")
        self.assertEqual([i["name"] for i in lib.quick(("recent",), "instrument")], ["Vital"])

    def _library(self, org=None):
        from plugin_library import PluginLibrary
        plugins = [{"name": n, "path": rf"C:\VST3\{n}.vst3"} for n in ("Vital", "Decent", "Tonocracy", "ValhallaRoom", "Roto")]
        probe = {
            os.path.normcase(r"C:\VST3\Vital.vst3"): {"kind": "instrument", "name": "Vital", "vendor": "Vital Audio",
                                                       "category": "Instrument|Synth"},
            os.path.normcase(r"C:\VST3\Decent.vst3"): {"kind": "instrument", "name": "DecentSampler",
                                                        "vendor": "Decidedly", "category": "Instrument|Sampler"},
            os.path.normcase(r"C:\VST3\Tonocracy.vst3"): {"kind": "effect", "vendor": "TMT", "category": "Fx"},
            os.path.normcase(r"C:\VST3\ValhallaRoom.vst3"): {"kind": "effect", "vendor": "Valhalla DSP",
                                                              "category": "Fx|Reverb"},
            os.path.normcase(r"C:\VST3\Roto.vst3"): {"kind": "error"},
        }
        return PluginLibrary(plugins, probe, org if org is not None else {})

    def test_plugin_library_tree_nodes(self):
        lib = self._library()
        names = lambda node: [i["name"] for i in lib.in_node(node)]
        self.assertEqual(names(("kind", "instrument")), ["DecentSampler", "Vital"])
        self.assertEqual(names(("vendor", "TMT")), ["Tonocracy"])
        self.assertEqual(names(("cat", "Reverb")), ["ValhallaRoom"])
        self.assertEqual(names(("cat", "Sintetizador")), ["Vital"])
        self.assertEqual(names(("errors",)), ["Roto"])
        self.assertIn("Valhalla DSP", lib.vendors())
        self.assertEqual(lib.category_names(), ["Reverb", "Sampler", "Sintetizador"])

    def test_plugin_library_search_like_reaper(self):
        lib = self._library()
        find = lambda q, node=("all",): [i["name"] for i in lib.search(node, q)]
        self.assertEqual(find("vital synth"), ["Vital"])                  # varias palabras, cualquier orden
        self.assertEqual(find("SINTETIZADOR"), ["Vital"])                 # categoría en español, sin mayúsculas
        self.assertEqual(find("decidedly"), ["DecentSampler"])            # por fabricante
        self.assertEqual(find("instrumento -sampler"), ["Vital"])         # «-» excluye
        self.assertEqual(find("valhalla", ("kind", "instrument")), [])    # solo dentro del nodo elegido
        self.assertEqual(find("distorsion"), [])

    def test_plugin_library_favorites_folders_and_recent(self):
        org = {}
        lib = self._library(org)
        vital = r"C:\VST3\Vital.vst3"
        self.assertTrue(lib.toggle_favorite(vital))
        self.assertEqual([i["name"] for i in lib.in_node(("fav",))], ["Vital"])
        self.assertEqual(lib.new_folder("Sintes"), "Sintes")
        self.assertIsNone(lib.new_folder("Sintes"))                       # sin carpetas repetidas
        lib.add_to_folder("Sintes", vital)
        lib.add_to_folder("Sintes", vital.upper())                        # misma ruta con otras mayúsculas
        self.assertEqual(len(org["folders"]["Sintes"]), 1)
        self.assertTrue(lib.rename_folder("Sintes", "Teclados"))
        self.assertEqual(lib.folders_of(vital), ["Teclados"])
        for n in ("Vital", "Decent", "Vital"):
            lib.touch_recent(rf"C:\VST3\{n}.vst3")
        self.assertEqual([i["name"] for i in lib.in_node(("recent",))], ["Vital", "DecentSampler"])
        # La organización vive en el dict que se guarda en la configuración
        lib2 = self._library(org)
        self.assertTrue(lib2.is_favorite(vital))
        lib2.remove_from_folder("Teclados", vital)
        lib2.delete_folder("Teclados")
        self.assertEqual(org["folders"], {})

    def test_midi_decode(self):
        from midi_input import decode
        self.assertEqual(decode(0x90 | (60 << 8) | (100 << 16)), bytes((0x90, 60, 100)))
        self.assertEqual(decode(0x91 | (60 << 8)), bytes((0x81, 60, 0)))   # Note On vel 0 = Note Off
        self.assertEqual(decode(0xC2 | (5 << 8)), bytes((0xC2, 5)))        # program change: 1 byte de datos
        self.assertIsNone(decode(0xF8))                                    # reloj MIDI: se ignora
        self.assertIsNone(decode(0xFE))                                    # active sensing

    def test_midi_router_filters_by_input_and_channel(self):
        from midi_input import MidiRouter
        from audio_server import Channel
        omni = Channel({"id": "a", "source": {"kind": "instrument"}})
        ch2 = Channel({"id": "b", "source": {"kind": "instrument"}})
        other = Channel({"id": "c", "source": {"kind": "instrument"}})
        r = MidiRouter(lambda m, c: None)
        r.routes = (("*", 0, omni), ("Teclado", 2, ch2), ("Pads", 0, other))
        r._on_message("Teclado", bytes((0x90, 60, 100)))     # canal MIDI 1
        r._on_message("Teclado", bytes((0x91, 64, 100)))     # canal MIDI 2
        self.assertEqual(len(omni.midi_q), 2)
        self.assertEqual(list(ch2.midi_q), [bytes((0x91, 64, 100))])
        self.assertEqual(len(other.midi_q), 0)

    def test_midi_learn_reports_first_note_only(self):
        """«Toca una tecla para asignar»: la primera nota (no un CC ni un Note Off) dice qué
        teclado y canal MIDI usar, una sola vez; las notas siguen llegando a los canales."""
        from midi_input import MidiRouter
        from audio_server import Channel
        omni = Channel({"id": "a", "source": {"kind": "instrument"}})
        r = MidiRouter(lambda m, c: None)
        r.routes = (("*", 0, omni),)
        learned = []
        r.on_learn = lambda dev, mch: learned.append((dev, mch))
        r.learning = True
        r._on_message("Pads", bytes((0xB0, 1, 64)))           # perilla: no cuenta
        r._on_message("Pads", bytes((0x82, 60, 0)))           # Note Off: no cuenta
        r._on_message("Teclado", bytes((0x92, 60, 100)))      # Note On, canal MIDI 3
        r._on_message("Pads", bytes((0x90, 36, 100)))
        self.assertEqual(learned, [("Teclado", 3)])
        self.assertFalse(r.learning)
        self.assertEqual(len(omni.midi_q), 4)

    def test_input_meters_measure_every_open_input(self):
        """Con meter_inputs, cada entrada del dispositivo trae su pico aunque ningún canal la use."""
        import numpy as np
        srv = self._server([{"id": "g", "source": {"kind": "main", "ch": [0]}, "mode": "mono", "cols": [0]}])
        indata = np.zeros((64, 4), dtype=np.float32)
        indata[:, 2] = 0.5                                     # algo suena en IN 3, sin canal
        out = np.zeros((64, 2), dtype=np.float32)
        srv._process(indata, out, 64)
        self.assertIsNone(srv.out_q.get_nowait()[4])           # apagado: no se mide nada de más
        srv.meter_inputs = True
        srv._process(indata, out, 64)
        np.testing.assert_allclose(srv.out_q.get_nowait()[4], [0.0, 0.0, 0.5, 0.0])

    def test_meter_inputs_reopens_only_when_needed(self):
        srv = self._server([{"id": "g", "source": {"kind": "main", "ch": [0]}, "mode": "mono", "cols": [0]}])
        srv.cfg = {"channels": []}
        srv.apply_config = MagicMock()
        srv._open_meter_streams = MagicMock()
        fresh = {"channels": [{"id": "g"}]}
        srv.device_info = {"n_in": 1, "max_in": 8}
        srv._set_meter_inputs(True, fresh)
        srv.apply_config.assert_called_once_with(fresh)        # abre las 8 entradas, con la config al día
        srv.apply_config.reset_mock()
        srv.device_info = {"n_in": 8, "max_in": 8}
        srv._set_meter_inputs(False, fresh)
        srv.apply_config.assert_not_called()                   # un canal usa la entrada: se cierra después
        srv.meter_inputs = False
        srv.device_info = {"n_in": 2, "max_in": 2}
        srv._set_meter_inputs(True, fresh)
        srv.apply_config.assert_not_called()                   # ya estaban todas abiertas
        srv.meter_inputs = False
        srv.device_info = {"n_in": 1, "max_in": 8}
        srv.rec_files = {"master": None}
        srv._open_meter_streams.reset_mock()
        srv._set_meter_inputs(True, fresh)
        srv.apply_config.assert_not_called()                   # grabando: nunca se reabre
        srv._open_meter_streams.assert_not_called()            # ni se abren micrófonos de más
        self.assertTrue(srv.meter_inputs)

    def test_meter_off_closes_input_nobody_uses(self):
        """Si se midió el micrófono solo para el diálogo, al cerrarlo no queda abierto."""
        srv = self._server([{"id": "k", "source": {"kind": "instrument"}}])
        srv.cfg = {"channels": []}
        srv.apply_config = MagicMock()
        srv._open_meter_streams = MagicMock()
        srv.meter_inputs = True
        srv.device_info = {"n_in": 2, "max_in": 2}
        srv._set_meter_inputs(False, None)
        srv.apply_config.assert_called_once_with(srv.cfg)

    def test_default_channel_names(self):
        from audio_engine import default_channel_name as name
        chans = [{"name": "Entrada 1"}]
        self.assertEqual(name({"kind": "main", "ch": [0]}, chans), "Entrada 1 2")
        self.assertEqual(name({"kind": "main", "ch": [2]}, chans), "Entrada 3")
        self.assertEqual(name({"kind": "main", "ch": [0, 1]}, chans), "Entradas 1-2")
        self.assertEqual(name({"kind": "device", "device": "Altavoces (Realtek(R) Audio)", "loopback": True}, [],
                              default_out="Altavoces (Realtek(R) Audio)"), "Sonido del PC")
        self.assertEqual(name({"kind": "device", "device": "Auriculares (USB Headset)", "loopback": True}, [],
                              default_out="Altavoces"), "Sonido · Auriculares")
        self.assertEqual(name({"kind": "device", "device": "Micrófono (C505 HD Webcam)", "loopback": False}, []),
                         "Micrófono")
        self.assertEqual(name({"kind": "instrument", "path": r"C:\VST3\Vital.vst3"}, []), "Vital")
        self.assertEqual(name({"kind": "instrument", "path": r"C:\VST3\v.vst3"}, [], label="Keyscape"), "Keyscape")

    def test_add_dialog_input_helpers(self):
        from modules.audio.ui.add_channel import main_inputs, used_inputs
        devs = {"asio": [{"name": "Focusrite USB ASIO", "in": 8}], "wasapi_in": [{"name": "Mic", "in": 2}]}
        self.assertEqual(main_inputs({"driver": "asio", "asio_device": "Focusrite USB ASIO"}, devs),
                         ("Focusrite USB ASIO", 8))
        self.assertEqual(main_inputs({"driver": "wasapi", "input_device": "Mic"}, devs), ("Mic", 2))
        self.assertEqual(main_inputs({"driver": "wasapi", "input_device": "Otro"}, devs), ("Otro", 0))
        chans = [{"name": "Voz", "source": {"kind": "main", "ch": [0]}},
                 {"name": "Teclado", "source": {"kind": "main", "ch": [2, 3]}},
                 {"name": "PC", "source": {"kind": "device"}}]
        self.assertEqual(used_inputs(chans), {0: "Voz", 2: "Teclado", 3: "Teclado"})

    def test_add_dialog_rows_follow_how_windows_names_inputs(self):
        """Una interfaz que Windows parte en «IN 1», «IN 2»…: la fila (y el canal) se llaman
        «IN 2», no «Entrada 1»; con ASIO o un dispositivo de varias entradas, «Entrada N»."""
        from modules.audio.ui.add_channel import input_rows
        self.assertEqual(input_rows("IN 2 (2- BEHRINGER UMC 202HD 192k)", 1), [([0], "IN 2", "IN 2")])
        rows = input_rows("Focusrite USB ASIO", 4)
        self.assertEqual([r[1] for r in rows], ["Entrada 1", "Entrada 2", "Entrada 3", "Entrada 4",
                                                "Entradas 1 + 2", "Entradas 3 + 4"])
        self.assertEqual(rows[4][0], [0, 1])
        self.assertTrue(all(r[2] is None for r in rows))

    def test_instrument_channel_plays_midi_through_fx(self):
        """Un canal de instrumento: el MIDI encolado llega al plugin al inicio del bloque
        y su salida estéreo pasa por la mezcla y el monitor como cualquier canal."""
        import numpy as np

        class FakeSynth:
            def __init__(self):
                self.got = []

            def process(self, msgs, duration, sr, num_channels, buffer_size, reset):
                self.got.append((list(msgs), round(duration * sr), reset))
                n = round(duration * sr)
                on = any(m[0][0] & 0xF0 == 0x90 for m in msgs) or getattr(self, "held", False)
                self.held = on
                return np.full((2, n), 0.3 if on else 0.0, dtype=np.float32)

        srv = self._server([{"id": "k", "source": {"kind": "instrument"}, "monitor": True}])
        ch = srv.rt_channels[0]
        synth = FakeSynth()
        ch.inst_plugin = synth
        ch.midi_push(bytes((0x90, 60, 100)))
        out = np.zeros((64, 2), dtype=np.float32)
        srv._process(np.zeros((64, 2), dtype=np.float32), out, 64)
        master, posts, peaks, _, _ = srv.out_q.get_nowait()
        self.assertEqual(synth.got[0], ([(bytes((0x90, 60, 100)), 0.0)], 64, False))
        np.testing.assert_allclose(master, 0.3)
        np.testing.assert_allclose(out, 0.3)
        self.assertEqual(len(ch.midi_q), 0)
        srv._process(None, out, 64)                        # siguiente bloque: sin MIDI nuevo, la nota sigue
        self.assertEqual(synth.got[1][0], [])
        self.assertEqual(ch.midi_hits, 1)

    def test_instrument_panic_releases_all_channels(self):
        from audio_server import Channel
        ch = Channel({"id": "k", "source": {"kind": "instrument"}})
        ch.panic()
        msgs = [m for m, _t in ch.drain_midi()]
        self.assertIn(bytes((0xB0, 123, 0)), msgs)          # All Notes Off, canal 1
        self.assertIn(bytes((0xBF, 64, 0)), msgs)           # pedal suelto, canal 16
        self.assertEqual(len(msgs), 32)

    def test_instrument_state_is_stored_in_source(self):
        from audio_engine import AudioEngine, new_channel, new_instrument_source, source_label
        ae = AudioEngine()
        src = new_instrument_source(r"C:\VST3\Vital.vst3")
        ch = new_channel("Vital", src, "stereo")
        ae.config = {"channels": [ch]}
        ae._store_fx_state(ch["id"], src["id"], "QUJD")
        self.assertEqual(ch["source"]["state"], "QUJD")
        self.assertEqual(source_label(src, {}), "🎹 Vital · todo MIDI")
        src["midi_in"], src["midi_ch"] = "Teclado", 3
        self.assertEqual(source_label(src, {}), "🎹 Vital · Teclado · canal 3")

    def test_migrates_old_fixed_channels(self):
        from types import SimpleNamespace
        from gui import GalaxyCamApp
        old = {"audio_dev": {"sys": "OUT 1-2 (UMC)", "in1": "IN 2 (UMC)", "in2": "Desactivada"}, "vol": {"sys": 0.97}}
        cfg = GalaxyCamApp._load_audio_config(SimpleNamespace(settings=old))
        self.assertEqual([c["name"] for c in cfg["channels"]], ["Sistema", "Entrada 1"])
        self.assertEqual(cfg["channels"][0]["source"], {"kind": "device", "device": "OUT 1-2 (UMC)", "loopback": True})
        self.assertEqual(cfg["channels"][0]["volume"], 0.97)
        self.assertEqual(cfg["channels"][1]["source"]["loopback"], False)


class TestPortableAndObs(unittest.TestCase):
    """Datos portables, enlace con OBS y salidas hacia otros programas"""

    def test_save_json_is_atomic_and_roundtrips(self):
        import paths
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            self.assertTrue(paths.save_json(p, {"a": "ñ"}))
            self.assertEqual(paths.load_json(p), {"a": "ñ"})
            self.assertFalse(os.path.exists(p + ".tmp"))
            self.assertEqual(paths.load_json(os.path.join(d, "no.json")), {})

    def test_virtualcam_status(self):
        info = virtualcam.SERVICE.status()
        for key in ("available", "registered", "running", "size", "error"):
            self.assertIn(key, info)
        self.assertEqual(info["size"], (1920, 1080))

    def test_pc_command_routes_to_vcam_pipe(self):
        e = CameraEngine()
        e.ffmpeg_path = sys.executable
        cmd = e.build_pc_camera_command({"pc_device": "C505 HD Webcam", "size": "1280x960", "fps": 30,
                                         "vcam_pipe": r"\\.\pipe\v", "live_preview": True})
        s = " ".join(cmd)
        self.assertIn("-map [vcout]", s)
        self.assertIn(r"\\.\pipe\v", cmd)
        self.assertIn("format=nv12", s)

    def test_android_vcam_requests_frequent_keyframes(self):
        e = CameraEngine()
        e.scrcpy_path = sys.executable
        cmd = e.build_command({"serial": "X", "vcam_pipe": r"\\.\pipe\v"})
        self.assertIn("--video-codec-options=i-frame-interval:int=1", cmd)
        self.assertIn(r"--record=\\.\pipe\v", cmd)

    @patch("subprocess.run")
    def test_finalize_recording_with_free_channels(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        e = CameraEngine()
        e.ffmpeg_path = sys.executable
        e._verify_export = lambda *a: (True, "")          # ffmpeg simulado: no hay archivo que verificar
        with tempfile.TemporaryDirectory() as d:
            files = {}
            for n in ("video.mkv", "master.wav", "g.wav", "s.wav"):
                files[n] = os.path.join(d, n)
                open(files[n], "wb").close()
            info = {"master_wav": files["master.wav"], "clipping": False,
                    "tracks": [{"name": "Guitarra", "wav": files["g.wav"]}, {"name": "Sistema", "wav": files["s.wav"]}]}
            res = e.finalize_recording(files["video.mkv"], info, {"output_dir": d, "prefix": "T", "embed_multitrack": True,
                                                                  "reveal_in_explorer": False})
            self.assertTrue(res["success"])
            s = " ".join(mock_run.call_args[0][0])
            self.assertIn("title=Guitarra", s)
            self.assertIn("title=Sistema", s)
            self.assertEqual([t["name"] for t in res["tracks"]], ["Guitarra", "Sistema"])


class TestPostRecordingAndIos(unittest.TestCase):
    """Pruebas para compatibilidad con iPhone y pipeline de post-grabación FFmpeg"""

    def setUp(self):
        self.engine = CameraEngine()
        self.engine.ffmpeg_path = sys.executable
        self.engine.ffplay_path = sys.executable
        self.engine._verify_export = lambda *a: (True, "")     # ffmpeg simulado: no hay archivo que verificar

    def test_ios_devices_discovery(self):
        """Verifica la detección de fuentes de iPhone (DirectShow / Red)"""
        ios_cams = self.engine.get_ios_cameras()
        self.assertIsInstance(ios_cams, list)
        self.assertGreater(len(ios_cams), 0)
        labels = [c["label"] for c in ios_cams]
        self.assertTrue(any("iPhone" in l for l in labels))

    def test_build_ios_command(self):
        """Verifica la construcción del comando de streaming para iPhone"""
        config = {
            "ios_device": "Iriun Webcam",
            "size": "1920x1080",
            "fps": 60
        }
        cmd = self.engine.build_ios_command(config)
        self.assertIn("-f", cmd)
        self.assertIn("dshow", cmd)
        self.assertIn("video=Iriun Webcam", cmd)
        self.assertIn("1920x1080", cmd)

    @patch("subprocess.run")
    def test_finalize_recording_multitrack_ffmpeg(self, mock_run):
        """Verifica que el pipeline de post-grabación use -c:v copy y mapeo multipista"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f_vid, \
             tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_mst, \
             tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_sys, \
             tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_mic:
            vid_path = f_vid.name
            mst_path = f_mst.name
            sys_path = f_sys.name
            mic_path = f_mic.name

        try:
            audio_info = {
                "master_wav": mst_path,
                "system_wav": sys_path,
                "mic_wav": mic_path,
                "duration": 5.0,
                "clipping": False
            }
            options = {
                "output_dir": tempfile.gettempdir(),
                "prefix": "TestSession",
                "embed_multitrack": True,
                "normalize": "ebu_r128",
                "reveal_in_explorer": False,
                "auto_play": False
            }

            res = self.engine.finalize_recording(vid_path, audio_info, options)
            self.assertTrue(res["success"])

            # Comprobar llamada FFmpeg
            ffmpeg_cmd = mock_run.call_args[0][0]
            self.assertIn("-c:v", ffmpeg_cmd)
            self.assertIn("copy", ffmpeg_cmd)
            # La normalización va solo en la mezcla final (pista 1): las pistas por canal quedan tal cual
            self.assertNotIn("-af", ffmpeg_cmd)
            self.assertEqual(ffmpeg_cmd[ffmpeg_cmd.index("-filter:a:0") + 1], "loudnorm=I=-14:TP=-1.0:LRA=11")
            self.assertIn("-map", ffmpeg_cmd)
        finally:
            for p in [vid_path, mst_path, sys_path, mic_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    @patch("subprocess.run")
    def test_finalize_recording_multitrack_with_in1_and_in2(self, mock_run):
        """Verifica que FFmpeg mapee y etiquete Audio del Sistema, Entrada 1 y Entrada 2"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f_vid, \
             tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_mst, \
             tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_sys, \
             tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_in1, \
             tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_in2:
            vid_path = f_vid.name
            mst_path = f_mst.name
            sys_path = f_sys.name
            in1_path = f_in1.name
            in2_path = f_in2.name

        try:
            audio_info = {
                "master_wav": mst_path,
                "system_wav": sys_path,
                "in1_wav": in1_path,
                "in2_wav": in2_path,
                "duration": 10.0,
                "clipping": False
            }
            options = {
                "output_dir": tempfile.gettempdir(),
                "prefix": "DualInputTest",
                "embed_multitrack": True,
                "normalize": "ebu_r128"
            }

            res = self.engine.finalize_recording(vid_path, audio_info, options)
            self.assertTrue(res["success"])

            ffmpeg_cmd = mock_run.call_args[0][0]
            cmd_str = " ".join(ffmpeg_cmd)
            self.assertIn("title=Mezcla Master (Stereo)", cmd_str)
            self.assertIn("title=Audio del Sistema (Salida General)", cmd_str)
            self.assertIn("title=Entrada 1", cmd_str)
            self.assertIn("title=Entrada 2", cmd_str)
            self.assertNotIn("Tonocracy", cmd_str)
        finally:
            for p in [vid_path, mst_path, sys_path, in1_path, in2_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    def test_embed_window_into_hwnd_mock(self):
        """Verifica la lógica Win32 de incrustación de monitor SetParent sin errores"""
        if sys.platform != "win32":
            return

        with patch("ctypes.windll.user32") as mock_user32:
            mock_user32.FindWindowW.return_value = 12345
            mock_user32.IsWindowVisible.return_value = 1
            mock_user32.GetWindowLongW.return_value = 0x14CF0000
            mock_user32.SetParent.return_value = 1
            mock_user32.SetWindowLongW.return_value = 1
            mock_user32.MoveWindow.return_value = 1
            mock_user32.ShowWindow.return_value = 1

            success = CameraEngine.embed_window_into_hwnd("UltraCam_Studio_Monitor", 9999, 800, 450, timeout=0.1)
            self.assertTrue(success)
            mock_user32.FindWindowW.assert_called_with(None, "UltraCam_Studio_Monitor")
            mock_user32.SetParent.assert_called_with(12345, 9999)
            mock_user32.MoveWindow.assert_called_with(12345, 0, 0, 800, 450, True)

    def test_embed_window_into_hwnd_timeout(self):
        """Verifica que embed_window devuelva False si la ventana no aparece"""
        if sys.platform != "win32":
            return

        with patch("ctypes.windll.user32") as mock_user32:
            mock_user32.FindWindowW.return_value = 0
            success = CameraEngine.embed_window_into_hwnd("NonExistentWindow", 9999, 800, 450, timeout=0.1)
            self.assertFalse(success)

    def test_embed_window_waits_until_visible(self):
        """Una ventana de scrcpy aún oculta no debe tocarse (crash 0xC0000094)"""
        if sys.platform != "win32":
            return

        with patch("ctypes.windll.user32") as mock_user32:
            mock_user32.FindWindowW.return_value = 12345
            mock_user32.IsWindowVisible.return_value = 0
            success = CameraEngine.embed_window_into_hwnd("UltraCam_Monitor_1", 9999, 800, 450, timeout=0.2)
            self.assertFalse(success)
            mock_user32.SetParent.assert_not_called()
            mock_user32.MoveWindow.assert_not_called()
            mock_user32.ShowWindow.assert_not_called()


class TestVirtualCamera(unittest.TestCase):
    """Salida a cámara virtual: comandos con pipe y tamaños de salida"""

    PIPE = r"\\.\pipe\ultracam_vcam_test"

    def setUp(self):
        self.engine = CameraEngine()
        self.engine.scrcpy_path = sys.executable
        self.engine.ffmpeg_path = sys.executable

    def test_android_preview_records_to_pipe(self):
        cmd = self.engine.build_command({"serial": "X", "vcam_pipe": self.PIPE})
        self.assertIn(f"--record={self.PIPE}", cmd)
        self.assertIn("--record-format=mkv", cmd)
        self.assertIsNone(self.engine.current_recording_file)

    def test_android_recording_goes_through_pipe(self):
        cmd = self.engine.build_command({"serial": "X", "vcam_pipe": self.PIPE, "record_video": True,
                                         "record_dir": tempfile.gettempdir()})
        records = [a for a in cmd if a.startswith("--record=")]
        self.assertEqual(records, [f"--record={self.PIPE}"])
        self.assertTrue(self.engine.current_recording_file.endswith(".mkv"))

    def test_pc_preview_with_vcam_uses_ffmpeg(self):
        cmd = self.engine.build_pc_camera_command({"pc_device": "C505 HD Webcam", "size": "1280x960", "fps": 30,
                                                   "vcam_pipe": self.PIPE, "vcam_size": (1280, 960),
                                                   "live_preview": True})
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[-1], self.PIPE)
        self.assertIn("pipe:1", cmd)
        self.assertTrue(any("format=nv12" in a for a in cmd))
        self.assertFalse(any(a.endswith(".mkv") for a in cmd))
        self.assertIsNone(self.engine.current_recording_file)

    def test_android_decoded_monitor_has_no_scrcpy_window(self):
        """Por encima de Full HD el monitor sale del reparto: scrcpy solo entrega el video."""
        cmd = self.engine.build_command({"serial": "X", "size": "3840x2160", "vcam_pipe": self.PIPE,
                                         "decoded_monitor": True, "video_buffer": 0, "window_title": "M"})
        self.assertIn("--no-window", cmd)
        self.assertIn(f"--record={self.PIPE}", cmd)
        self.assertFalse(any(a.startswith(("--window-title", "--video-buffer")) for a in cmd))
        # Sin pipe no hay de dónde sacar la imagen: scrcpy conserva su ventana
        plain = self.engine.build_command({"serial": "X", "decoded_monitor": True, "window_title": "M"})
        self.assertNotIn("--no-window", plain)
        self.assertIn("--window-title=M", plain)

    def test_monitor_window_opens_offscreen(self):
        """ffplay abre fuera de la pantalla: si la imagen tarda en llegar (vertical al grabar),
        su ventana no queda suelta en el escritorio antes de incrustarse."""
        from infrastructure.video.command_builder import preview_player_command
        cmd = preview_player_command("ffplay", "M")
        self.assertEqual(cmd[cmd.index("-left") + 1], "-32000")
        self.assertEqual(cmd[cmd.index("-top") + 1], "-32000")
        direct = self.engine.build_pc_camera_command({"pc_device": "Cam", "size": "1920x1080", "fps": 30})
        self.assertIn("-left", direct)

    def test_monitor_limited_to_full_hd(self):
        from infrastructure.video.command_builder import exceeds_full_hd
        self.assertTrue(exceeds_full_hd("3840x2160"))
        self.assertTrue(exceeds_full_hd("2560x1440"))
        self.assertTrue(exceeds_full_hd("2160x3840"))
        self.assertFalse(exceeds_full_hd("1920x1080"))
        self.assertFalse(exceeds_full_hd("1080x1920"))
        self.assertFalse(exceeds_full_hd("auto"))
        big = self.engine.build_pc_camera_command({"pc_device": "Cam", "size": "3840x2160", "fps": 30})
        self.assertTrue(any("min(iw,1280)" in a for a in big))
        small = self.engine.build_pc_camera_command({"pc_device": "Cam", "size": "1920x1080", "fps": 30})
        self.assertFalse(any("min(iw,1280)" in a for a in small))

    def test_monitor_drops_late_frames(self):
        """El monitor va con reloj externo y sin análisis inicial: tras un tirón descarta los
        cuadros atrasados en vez de mostrarlos todos a su ritmo (retraso que no se recupera)."""
        from infrastructure.video.command_builder import preview_player_command
        for cmd in (preview_player_command("ffplay", "M"),
                    self.engine.build_pc_camera_command({"pc_device": "Cam", "size": "1920x1080", "fps": 30})):
            self.assertEqual(cmd[cmd.index("-sync") + 1], "ext")
            self.assertIn("-framedrop", cmd)
        piped = preview_player_command("ffplay", "M")
        self.assertEqual(piped[piped.index("-probesize") + 1], "32")
        self.assertLess(piped.index("-probesize"), piped.index("-i"))

    def test_decoded_monitor_bridge_splits_outputs(self):
        """Monitor por stdout (hacia ffplay) y cámara virtual por su propio pipe."""
        class Sink:
            frames_sent = 0
        bridge = virtualcam.VirtualCamBridge("encoded", 1920, 1080, 30, ffmpeg_path=sys.executable, sink=Sink(),
                                             preview={"cmd": ["ffplay"], "vf": "scale=1920:1080", "fps": 30})
        bridge._vc_pipe = MagicMock(path=self.PIPE)
        cmd = bridge._decoder_cmd()
        self.assertEqual(cmd[-1], "pipe:1")
        self.assertIn("nut", cmd)
        self.assertIn(self.PIPE, cmd)
        self.assertNotIn("nobuffer+discardcorrupt", cmd)

    def test_mode_badge_tiers(self):
        from presentation.theme import res_tier
        self.assertEqual(res_tier("3840x2160"), "4K")
        self.assertEqual(res_tier("2160x3840"), "4K")
        self.assertEqual(res_tier("2560x1440"), "2K")
        self.assertEqual(res_tier("1920x1080"), "Full HD")
        self.assertEqual(res_tier("1280x960"), "HD")
        self.assertEqual(res_tier("640x480"), "480p")

    def test_vcam_output_is_independent_of_source(self):
        """La cámara virtual siempre recibe 1080p, con franjas si hace falta: cambiar de
        fuente o girarla nunca cambia el formato que ven Zoom, Teams u OBS."""
        for size in ("1280x960", "3840x2160", "1080x1920"):
            cmd = self.engine.build_pc_camera_command({"pc_device": "C505 HD Webcam", "size": size,
                                                       "fps": 30, "vcam_pipe": self.PIPE})
            joined = " ".join(cmd)
            self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease", joined, size)
            self.assertIn("pad=1920:1080", joined, size)

    def test_vcam_disabled_leaves_config_untouched(self):
        cfg = {"serial": "X"}
        self.assertIs(self.engine._setup_vcam(cfg, "android"), cfg)
        self.assertIsNone(self.engine.vcam)

    def test_vcam_enabled_builds_bridge_on_shared_sink(self):
        """Con la cámara virtual activa se crea el puente sobre el emisor del servicio
        (antes se pedía una clase inexistente y la vista previa no arrancaba)."""
        sink = MagicMock()
        for mode, platform in (("raw", "pc"), ("encoded", "android")):
            with patch.object(virtualcam, "available", return_value=True), \
                    patch.object(virtualcam.SERVICE, "acquire", return_value=sink):
                cfg = self.engine._setup_vcam({"virtual_cam": True}, platform)
            bridge = self.engine.vcam
            try:
                self.assertIsInstance(bridge, virtualcam.VirtualCamBridge)
                self.assertEqual(bridge.mode, mode)
                self.assertIs(bridge.sink, sink)
                self.assertEqual(cfg["vcam_pipe"], bridge.pipe_path)
                self.assertEqual(cfg["vcam_size"], (1920, 1080))
            finally:
                self.engine._stop_vcam()
        self.assertIsNone(self.engine.vcam)

    def test_vcam_unavailable_keeps_preview_without_vcam(self):
        """Si el dispositivo de Windows no abre, la fuente se ve igual (sin cámara virtual)."""
        with patch.object(virtualcam, "available", return_value=True), \
                patch.object(virtualcam.SERVICE, "acquire", return_value=None):
            cfg = {"virtual_cam": True}
            self.assertIs(self.engine._setup_vcam(cfg, "pc"), cfg)
        self.assertIsNone(self.engine.vcam)

    def test_start_stream_reports_setup_failure(self):
        """Un fallo al preparar devuelve False (la interfaz muestra el error) y no deja
        un puente de cámara virtual colgado."""
        with patch.object(self.engine, "_setup_vcam", side_effect=RuntimeError("boom")):
            self.assertFalse(self.engine.start_stream({"platform": "pc", "pc_device": "X"}))
        self.assertIsNone(self.engine.vcam)
        self.assertFalse(self.engine.is_running)

    def test_calibration_is_computed_once_for_all_outputs(self):
        """El filtrado caro (nitidez) se calcula una vez y se reparte: es lo que
        hacía que la grabación fuera lenta con la cámara virtual encendida."""
        cmd = self.engine.build_pc_camera_command({
            "pc_device": "Logitech BRIO", "size": "1920x1080", "fps": 60, "sharpness": 1.5,
            "record_video": True, "record_dir": tempfile.gettempdir(),
            "vcam_pipe": self.PIPE, "live_preview": True})
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertEqual(graph.count("unsharp"), 1, "la nitidez no debe recalcularse por salida")
        self.assertIn("split=3", graph)
        for label in ("[rec]", "[pvout]", "[vcout]"):
            self.assertIn(label, " ".join(cmd))

    def test_preview_and_vcam_are_throttled_but_recording_is_not(self):
        """El monitor y la cámara virtual bajan de tamaño y de cuadros; la toma que
        se guarda conserva la resolución y los fps de la cámara."""
        cmd = self.engine.build_pc_camera_command({
            "pc_device": "Logitech BRIO", "size": "1920x1080", "fps": 60,
            "record_video": True, "record_dir": tempfile.gettempdir(),
            "vcam_pipe": self.PIPE, "live_preview": True})
        graph = cmd[cmd.index("-filter_complex") + 1]
        pv = next(p for p in graph.split(";") if p.startswith("[pv]"))
        vc = next(p for p in graph.split(";") if p.startswith("[vc]"))
        self.assertIn(f"fps={engine_mod.PREVIEW_MAX_FPS}", pv)
        self.assertIn(f"scale=-2:{engine_mod.PREVIEW_HEIGHT}", pv)
        self.assertIn(f"fps={virtualcam.VCAM_FPS}", vc)
        # La rama de grabación sale del split sin filtros añadidos
        self.assertIn("-map [rec]", " ".join(cmd))
        self.assertNotIn("[recout]", " ".join(cmd))

    def test_vertical_goes_first_for_every_output(self):
        """El recorte/giro vertical va antes del reparto: grabación, monitor y cámara
        virtual salen iguales, y la calibración trabaja ya sobre la imagen vertical."""
        for mode, expected in (("crop", "crop=trunc(ih*9/32)*2:ih"), ("cw", "transpose=1"), ("ccw", "transpose=2")):
            cmd = self.engine.build_pc_camera_command({
                "pc_device": "Logitech BRIO", "size": "1920x1080", "fps": 30, "sharpness": 1.0, "vertical": mode,
                "record_video": True, "record_dir": tempfile.gettempdir(), "vcam_pipe": self.PIPE, "live_preview": True})
            graph = cmd[cmd.index("-filter_complex") + 1]
            self.assertTrue(graph.startswith(f"[0:v]{expected},"), graph)
            self.assertLess(graph.index(expected), graph.index("split="))
        # Solo vista previa (ffplay): el mismo filtro
        cmd = self.engine.build_pc_camera_command({"pc_device": "X", "size": "1920x1080", "fps": 30, "vertical": "crop"})
        self.assertIn("crop=trunc(ih*9/32)*2:ih", cmd[cmd.index("-vf") + 1])
        # Horizontal: sin filtros de más
        cmd = self.engine.build_pc_camera_command({"pc_device": "X", "size": "1920x1080", "fps": 30})
        self.assertNotIn("-vf", cmd)

    def test_single_output_keeps_simple_filter(self):
        """Con una sola salida no hace falta filter_complex."""
        cmd = self.engine.build_pc_camera_command({
            "pc_device": "Logitech BRIO", "size": "1920x1080", "fps": 30, "sharpness": 1.0,
            "record_video": True, "record_dir": tempfile.gettempdir()})
        self.assertNotIn("-filter_complex", cmd)
        self.assertIn("-vf", cmd)
        self.assertIn("-map", cmd)

    def test_encoder_falls_back_to_cpu_without_ffmpeg(self):
        e = CameraEngine()
        e.ffmpeg_path = None
        self.assertEqual(e.video_encoder_args(), engine_mod.CPU_ENCODER)

    def test_bridge_stop_keeps_driver_link(self):
        """Al cambiar de fuente el puente se cierra, pero el enlace con el driver sigue
        abierto: el driver retiene el último cuadro y los programas no se desconectan."""
        sink = MagicMock()
        bridge = virtualcam.VirtualCamBridge("raw", 1920, 1080, 30, sink=sink)
        bridge.start()
        bridge.stop()
        sink.idle.assert_called()
        sink.close.assert_not_called()

    def test_service_without_driver_reports_error(self):
        """Sin la DLL del driver la app sigue funcionando; el motivo queda para mostrarlo."""
        service = virtualcam.VirtualCamService()
        with patch.object(virtualcam.vcam_driver, "dll_path", return_value=None):
            self.assertFalse(service.start())
        self.assertFalse(service.running)
        self.assertIn("driver", service.last_error)

    def test_service_removes_legacy_obs_registration(self):
        """La «UltraCam» de versiones anteriores dependía de OBS: se borra para que
        Windows no muestre dos cámaras con el mismo nombre."""
        service = virtualcam.VirtualCamService()
        with patch.object(virtualcam, "available", return_value=True), \
                patch("winreg.DeleteKey") as delete, \
                patch.object(virtualcam.vcam_driver, "register", return_value=True), \
                patch.object(virtualcam.vcam_driver, "SharedFrameWriter") as writer:
            self.assertTrue(service.start())
            service.stop()
        self.assertIn("{7D129774-8B8E-47C2-9E9C-A2E4B17961C4}", delete.call_args[0][1])
        writer.return_value.close.assert_called_once()


class TestUniversalPCCamerasAndControls(unittest.TestCase):
    """Pruebas para el soporte universal de cámaras de PC, sondeo de capacidades y calibración"""

    def setUp(self):
        self.engine = CameraEngine()
        self.engine.ffmpeg_path = sys.executable
        self.engine.ffplay_path = sys.executable
        self.engine._verify_export = lambda *a: (True, "")     # ffmpeg simulado: no hay archivo que verificar

    @patch("subprocess.run")
    def test_pc_camera_discovery_and_categorization(self, mock_run):
        """Verifica la detección y categorización inteligente de webcams, capturadoras y virtuales"""
        mock_output = (
            "[in#0 @ 000001] \"Logitech BRIO\" (video)\n"
            "[in#0 @ 000001] \"Elgato Cam Link 4K\" (video)\n"
            "[in#0 @ 000001] \"OBS Virtual Camera\" (video)\n"
            "[in#0 @ 000001] \"Iriun Webcam\" (video)\n"
            "[in#0 @ 000001] \"Micrófono Realtek\" (audio)\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr=mock_output)

        cams = self.engine.get_pc_cameras(force_refresh=True)
        self.assertEqual(len(cams), 4)
        
        categories = {c["name"]: c["category"] for c in cams}
        self.assertEqual(categories["Logitech BRIO"], "webcam")
        self.assertEqual(categories["Elgato Cam Link 4K"], "capture_card")
        self.assertEqual(categories["OBS Virtual Camera"], "virtual")
        self.assertEqual(categories["Iriun Webcam"], "ios")

        labels = {c["name"]: c["label"] for c in cams}
        self.assertIn("📷", labels["Logitech BRIO"])
        self.assertIn("🎥", labels["Elgato Cam Link 4K"])
        self.assertIn("🪟", labels["OBS Virtual Camera"])

    @patch("subprocess.run")
    def test_probe_camera_capabilities_mjpeg_priority(self, mock_run):
        """Verifica que el sondeo dinámico priorice MJPEG para resoluciones altas a 60/30 fps"""
        mock_output = (
            "[in#0 @ 000001]   pixel_format=yuyv422  min s=1280x720 fps=5 max s=1280x720 fps=7.5\n"
            "[in#0 @ 000001]   pixel_format=yuyv422  min s=640x480 fps=5 max s=640x480 fps=30\n"
            "[in#0 @ 000001]   vcodec=mjpeg  min s=1920x1080 fps=5 max s=1920x1080 fps=60\n"
            "[in#0 @ 000001]   vcodec=mjpeg  min s=1280x720 fps=5 max s=1280x720 fps=60\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr=mock_output)

        caps = self.engine.probe_camera_capabilities("TestWebcam", force_refresh=True)
        self.assertTrue(caps["has_mjpeg"])
        self.assertEqual(caps["best_pixel_format"], "mjpeg")
        self.assertIn("1920x1080", caps["resolutions"])
        self.assertIn("1280x720", caps["resolutions"])
        self.assertIn(60, caps["framerates"])
        self.assertEqual(caps["default_res"], "1920x1080")
        self.assertEqual(caps["default_fps"], 60)

    @patch("subprocess.Popen")
    def test_open_camera_hardware_dialog(self, mock_popen):
        """Verifica el comando para disparar el diálogo nativo DirectShow del fabricante"""
        mock_popen.return_value = MagicMock()
        ok = self.engine.open_camera_hardware_dialog("Logitech BRIO")
        self.assertTrue(ok)
        
        args = mock_popen.call_args[0][0]
        self.assertIn("-f", args)
        self.assertIn("dshow", args)
        self.assertIn("-show_video_device_dialog", args)
        self.assertIn("true", args)
        self.assertIn("video=Logitech BRIO", args)

    def test_build_pc_camera_command_preview_and_recording(self):
        """Verifica los comandos de monitoreo y grabación con filtros de calibración (ProcAmp)"""
        preview_cfg = {
            "pc_device": "Logitech BRIO",
            "size": "1920x1080",
            "fps": 60,
            "pixel_format": "mjpeg",
            "brightness": 0.1,
            "contrast": 1.1,
            "saturation": 1.2,
            "sharpness": 1.5,
            "record_video": False
        }
        cmd_prev = self.engine.build_pc_camera_command(preview_cfg)
        cmd_str = " ".join(cmd_prev)
        self.assertIn("-video_size 1920x1080", cmd_str)
        self.assertIn("-framerate 60", cmd_str)
        self.assertIn("-vcodec mjpeg", cmd_str)
        self.assertNotIn("-pixel_format mjpeg", cmd_str)
        self.assertIn("video=Logitech BRIO", cmd_str)
        self.assertIn("UltraCam_Studio_Monitor", cmd_str)
        self.assertIn("-vf", cmd_str)
        self.assertIn("eq=brightness=0.10:contrast=1.10:saturation=1.20", cmd_str)
        self.assertIn("unsharp=5:5:0.60", cmd_str)

        # Prueba con formato crudo sin compresión (YUY2)
        yuy2_cfg = {
            "pc_device": "Generic Cam",
            "size": "640x480",
            "fps": 30,
            "pixel_format": "yuyv422",
            "record_video": False
        }
        cmd_yuy2 = self.engine.build_pc_camera_command(yuy2_cfg)
        self.assertIn("-pixel_format yuyv422", " ".join(cmd_yuy2))

        rec_cfg = {
            "pc_device": "Logitech BRIO",
            "size": "1920x1080",
            "fps": 60,
            "record_video": True,
            "record_dir": tempfile.gettempdir()
        }
        cmd_rec = self.engine.build_pc_camera_command(rec_cfg)
        self.assertIn("-an", cmd_rec)
        self.assertTrue(any(rec_cfg["record_dir"] in arg for arg in cmd_rec))

    def test_camera_preset_persistence(self):
        """Verifica el guardado y carga de perfiles de cámara personalizados"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file = os.path.join(tmp_dir, "test_presets.json")
            with patch.object(self.engine, "get_presets_file_path", return_value=test_file):
                settings = {"size": "3840x2160", "fps": 60, "brightness": 0.05, "sharpness": 1.2}
                ok = self.engine.save_camera_preset("MiCamara4K", settings)
                self.assertTrue(ok)
                self.assertTrue(os.path.exists(test_file))

                loaded = self.engine.load_camera_preset("MiCamara4K")
                self.assertEqual(loaded["size"], "3840x2160")
                self.assertEqual(loaded["fps"], 60)
                self.assertEqual(loaded["brightness"], 0.05)


class TestRecordingJoin(unittest.TestCase):
    """Unión de video y audio al terminar la toma: alineación, normalización y fallos."""

    def setUp(self):
        self.engine = CameraEngine()
        self.engine.ffmpeg_path = sys.executable
        self.engine._verify_export = lambda *a: (True, "")     # ffmpeg simulado: no hay archivo que verificar
        self.dir = tempfile.mkdtemp()
        self.video = os.path.join(self.dir, "v.mkv")
        self.master = os.path.join(self.dir, "m.wav")
        self.track = os.path.join(self.dir, "t.wav")
        self.audio = {"master_wav": self.master, "tracks": [{"wav": self.track, "name": "Guitarra"}]}

    def _join(self, returncodes=(0,), **options):
        for p in (self.video, self.master, self.track):   # una unión exitosa borra los temporales
            open(p, "wb").close()
        results = [MagicMock(returncode=rc, stdout="", stderr="línea\n" * 50 + "Conversion failed!") for rc in returncodes]
        with patch("subprocess.run", side_effect=results) as run:
            res = self.engine.finalize_recording(self.video, self.audio,
                                                 dict({"output_dir": self.dir, "prefix": "T", "guide_sync": False},
                                                      **options))
        return res, [c.args[0] for c in run.call_args_list]

    def _join_with_guide(self, sync, **options):
        self.audio["duration"] = 300.0
        with patch("infrastructure.video.av_sync.measure", return_value=sync) as measure:
            res, cmds = self._join(guide_sync=True, **options)
        self.assertEqual(measure.call_args.args[2], [self.master, self.track])
        return res, cmds

    def test_guide_track_sets_offset_shifts_video_and_fixes_drift(self):
        sync = {"video_start": 0.367, "offset": -2.373, "drift": 80e-6, "psr": 18.0, "ref": self.master}
        _, cmds = self._join_with_guide(sync, av_offset_s=-3.5, sync_offset_ms=20)
        cmd = cmds[0]
        # la pista guía manda sobre las horas de inicio; el ajuste manual se suma
        self.assertEqual(cmd[cmd.index(self.master) - 3: cmd.index(self.master)], ["-ss", "2.353", "-i"])
        # el .mkv empieza con la pista guía: el primer cuadro pasa a ser el tiempo 0
        self.assertEqual(cmd[cmd.index(self.video) - 3: cmd.index(self.video)], ["-itsoffset", "-0.367", "-i"])
        # 80 ppm en 300 s son 24 ms: se corrige en todas las pistas
        self.assertIn("asetrate=48004,aresample=48000", cmd[cmd.index("-filter:a:0") + 1])
        self.assertEqual(cmd[cmd.index("-filter:a:1") + 1], "asetrate=48004,aresample=48000")

    def test_phone_clock_gap_from_dumpsys(self):
        from infrastructure.video import av_sync
        out = (b"  Runtime uptime (elapsed): +3d13h26m47s229ms\n"
               b"  Runtime uptime (uptime): +2d4h32m53s733ms\n")
        with patch.object(av_sync, "_run", return_value=MagicMock(returncode=0, stdout=out)):
            self.assertAlmostEqual(av_sync.phone_clock_gap("adb", "X"), 118433.496, places=3)
        with patch.object(av_sync, "_run", return_value=MagicMock(returncode=1, stdout=b"")):
            self.assertIsNone(av_sync.phone_clock_gap("adb", "X"))

    def test_video_on_other_phone_clock_needs_the_gap(self):
        # con --capture-orientation la imagen viene horas «después» que la pista guía
        from infrastructure.video import av_sync
        with patch.object(av_sync, "_decode", return_value=np.ones(10 * av_sync.FS, np.float32)), \
                patch.object(av_sync, "first_video_time", return_value=118434.004), \
                patch.object(av_sync, "_measure_at", return_value=(2.0, 20.0)):
            res = av_sync.measure("ffmpeg", "v.mkv", ["m.wav"], clock_gap=lambda: 118433.496)
            self.assertAlmostEqual(res["offset"], -(0.508 + 2.0), places=3)
            self.assertEqual(res["video_start"], 118434.004)
            res = av_sync.measure("ffmpeg", "v.mkv", ["m.wav"], clock_gap=lambda: None)
            self.assertIsNone(res["offset"], "sin la diferencia de relojes no se adivina")

    def test_unreliable_guide_falls_back_to_start_times(self):
        sync = {"video_start": 0.367, "offset": None, "drift": 0.0, "psr": 0.0, "ref": None}
        _, cmds = self._join_with_guide(sync, av_offset_s=-2.5, normalize="off")
        cmd = cmds[0]
        self.assertEqual(cmd[cmd.index(self.master) - 3: cmd.index(self.master)], ["-ss", "2.500", "-i"])
        self.assertIn("-itsoffset", cmd[: cmd.index(self.video)])
        self.assertNotIn("-filter:a:0", cmd)

    def test_audio_that_started_early_is_trimmed_and_late_is_delayed(self):
        _, cmds = self._join(av_offset_s=-2.5)
        cmd = cmds[0]
        self.assertEqual(cmd[cmd.index(self.master) - 3: cmd.index(self.master)], ["-ss", "2.500", "-i"])
        _, cmds = self._join(av_offset_s=0.4, sync_offset_ms=100)
        cmd = cmds[0]
        self.assertEqual(cmd[cmd.index(self.track) - 3: cmd.index(self.track)], ["-itsoffset", "0.500", "-i"])

    def test_peak_mode_really_limits(self):
        _, cmds = self._join(normalize="peak")
        self.assertIn("alimiter=limit=0.891:level=disabled", cmds[0])

    def test_failed_normalization_retries_without_it(self):
        res, cmds = self._join(returncodes=(1, 0))
        self.assertTrue(res["success"], "sin normalizar, pero la toma se guarda")
        self.assertIn("-filter:a:0", cmds[0])
        self.assertNotIn("-filter:a:0", cmds[1])

    def test_failed_join_leaves_no_half_file(self):
        def fail(cmd, **kw):
            open(cmd[-1], "wb").close()          # ffmpeg dejó un MP4 a medias
            return MagicMock(returncode=1, stdout="", stderr="Conversion failed!")
        for p in (self.video, self.master, self.track):
            open(p, "wb").close()
        with patch("subprocess.run", side_effect=fail):
            res = self.engine.finalize_recording(self.video, self.audio,
                                                 {"output_dir": self.dir, "prefix": "T", "guide_sync": False})
        self.assertFalse(res["success"])
        self.assertEqual([f for f in os.listdir(self.dir) if f.endswith(".mp4")], [])
        self.assertTrue(os.path.exists(self.video), "los originales se conservan")

    def test_stream_manager_reads_first_frame_time(self):
        from infrastructure.video.stream_manager import StreamManager
        sm = StreamManager()
        script = ("import sys; sys.stderr.write('Input #0, dshow\\n  Duration: N/A, start: 56237.628313, bitrate: N/A\\n"
                  "frame=12\\n'); sys.stderr.flush()")
        sm.start_stream([sys.executable, "-c", script], is_ffmpeg_rec=False, piped_preview=False,
                        ffplay_path=None, window_title="t")
        self.assertTrue(sm.recording_started.wait(5))
        time.sleep(0.2)
        self.assertAlmostEqual(sm.video_start_ts, 56237.628313, places=4)
        self.assertIsNotNone(sm.recording_started_at)
        sm.stop_stream()

    def test_stream_manager_scrcpy_first_frame_from_stdout(self):
        # scrcpy da sus INFO por stdout: «Recording started» sale antes de abrir la cámara
        # y no cuenta; el primer cuadro es «Texture:».
        from infrastructure.video.stream_manager import StreamManager
        sm = StreamManager()
        script = ("import sys, time; print('INFO: Recording started to matroska file: x.mkv', flush=True); "
                  "time.sleep(0.6); print('INFO: Texture: 1920x1080', flush=True); time.sleep(0.2)")
        t0 = time.monotonic()
        sm.start_stream([sys.executable, "-c", script], is_ffmpeg_rec=False, piped_preview=False,
                        ffplay_path=None, window_title="t")
        self.assertTrue(sm.recording_started.wait(5))
        self.assertGreater(sm.recording_started_at - t0, 0.5)
        sm.stop_stream()


class TestWifiPhone(unittest.TestCase):
    """Pasar el teléfono a Wi‑Fi: cada fallo trae un motivo que la interfaz sabe explicar."""

    def setUp(self):
        self.engine = CameraEngine()
        self.engine.adb_path = sys.executable

    def test_same_network_heuristic(self):
        self.assertTrue(CameraEngine.same_network("192.168.1.35", ["10.0.0.4", "192.168.1.20"]))
        self.assertFalse(CameraEngine.same_network("192.168.0.35", ["192.168.1.20"]))

    def _run(self, connect_out):
        def fake_run(cmd, **kw):
            out = connect_out if "connect" in cmd else ""
            return MagicMock(returncode=0, stdout=out, stderr="")
        return patch("subprocess.run", side_effect=fake_run)

    def test_reasons(self):
        with patch.object(self.engine, "get_device_wifi_ip", return_value=None):
            self.assertEqual(self.engine.setup_wireless_mode("R5C")["reason"], "no_ip")
        with patch.object(self.engine, "get_device_wifi_ip", return_value="192.168.1.35"), \
                patch.object(CameraEngine, "local_ipv4", return_value=["192.168.0.10"]), \
                self._run("failed to connect to 192.168.1.35:5555"), patch("time.sleep"):
            res = self.engine.setup_wireless_mode("R5C")
        self.assertEqual((res["success"], res["reason"]), (False, "other_network"))
        with patch.object(self.engine, "get_device_wifi_ip", return_value="192.168.1.35"), \
                patch.object(CameraEngine, "local_ipv4", return_value=["192.168.1.10"]), \
                self._run("failed to connect to 192.168.1.35:5555"), patch("time.sleep"):
            self.assertEqual(self.engine.setup_wireless_mode("R5C")["reason"], "unreachable")
        with patch.object(self.engine, "get_device_wifi_ip", return_value="192.168.1.35"), \
                patch.object(CameraEngine, "local_ipv4", return_value=["192.168.1.10"]), \
                self._run("connected to 192.168.1.35:5555"), patch("time.sleep"):
            res = self.engine.setup_wireless_mode("R5C")
        self.assertTrue(res["success"])
        self.assertEqual(res["endpoint"], "192.168.1.35:5555")


class TestAdbHealth(unittest.TestCase):
    """Conflictos entre versiones de adb (Iriun, DroidCam…) y adb sin respuesta."""

    def setUp(self):
        from infrastructure.video.device_scanner import DeviceScanner
        self.scanner = DeviceScanner(adb_path=sys.executable)
        self.ok = MagicMock(returncode=0, stdout="List of devices attached\nR5C\tdevice model:SM_S918B\n", stderr="")
        self.clash = MagicMock(returncode=0, stdout="List of devices attached\n",
                               stderr="adb server version (41) doesn't match this client (39); killing...\n")

    def test_single_clash_is_not_reported_but_repeated_is(self):
        with patch("subprocess.run", return_value=self.clash):
            self.scanner.scan_adb_devices()
            self.assertIsNone(self.scanner.adb_problem, "un choque suelto al arrancar es normal")
            self.scanner.scan_adb_devices()
        self.assertEqual(self.scanner.adb_problem, "conflict")

    def test_timeouts_are_reported_and_recover(self):
        import subprocess as sp
        with patch("subprocess.run", side_effect=sp.TimeoutExpired("adb", 8)):
            self.assertEqual(self.scanner.scan_adb_devices(), [])
            self.assertIsNone(self.scanner.adb_problem)
            self.scanner.scan_adb_devices()
        self.assertEqual(self.scanner.adb_problem, "timeout")
        with patch("subprocess.run", return_value=self.ok):
            devices = self.scanner.scan_adb_devices()
        self.assertIsNone(self.scanner.adb_problem)
        self.assertEqual(devices[0]["serial"], "R5C")

    def test_first_scan_starts_server_with_more_time(self):
        with patch("subprocess.run", return_value=self.ok) as run:
            self.scanner.scan_adb_devices()
            self.scanner.scan_adb_devices()
        calls = [c.args[0][1:] for c in run.call_args_list]
        self.assertEqual(calls[0], ["start-server"], "la primera vez arranca el servidor")
        self.assertGreaterEqual(run.call_args_list[0].kwargs["timeout"], 15)
        self.assertEqual(calls.count(["start-server"]), 1, "solo una vez")


def _ui_sources(root):
    """Archivos de la interfaz: gui.py, el marco (app/), los módulos y presentation/."""
    names = ["gui.py"]
    for folder in ("app", "modules", "presentation"):
        for base, _dirs, files in os.walk(os.path.join(root, folder)):
            names += [os.path.relpath(os.path.join(base, n), root) for n in files if n.endswith(".py")]
    return names


class TestMessagesAndDisk(unittest.TestCase):
    """Catálogo de textos, avisos sin repeticiones y cálculo de espacio para grabar."""

    def test_every_key_used_in_the_ui_exists(self):
        """Una errata en una clave mostraría la clave en pantalla: aquí falla antes."""
        import re
        from presentation import strings
        root = os.path.dirname(os.path.abspath(__file__))
        used = set()
        for name in _ui_sources(root):
            with open(os.path.join(root, name), encoding="utf-8") as f:
                used |= set(re.findall(r'\bt\(\s*"([a-z0-9_.]+)"', f.read()))
        self.assertGreater(len(used), 300)
        missing = sorted(k for k in used if k not in strings.ES)
        self.assertEqual(missing, [])

    def test_nothing_shadows_the_catalog_function(self):
        """Un parámetro o variable llamado «t» taparía t() y esa pantalla fallaría al abrirse
        (pasó con Configuración › Video): ninguna función de la interfaz puede usar ese nombre."""
        import ast
        root = os.path.dirname(os.path.abspath(__file__))
        offenders = []
        for name in _ui_sources(root):
            with open(os.path.join(root, name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.Lambda)):
                    params = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
                    stores = [n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)]
                    if "t" in params + stores:
                        offenders.append(f"{name}:{fn.lineno}")
        self.assertEqual(offenders, [])

    def test_translation_falls_back_to_spanish(self):
        from presentation import strings
        strings.CATALOGS["xx"] = {"rec.saved": "Take saved: {file}"}
        old = strings.LANG
        try:
            strings.LANG = "xx"
            self.assertEqual(strings.t("rec.saved", file="a.mp4"), "Take saved: a.mp4")
            self.assertEqual(strings.t("log.copied"), strings.ES["log.copied"])   # sin traducir: español
        finally:
            strings.LANG = old
            del strings.CATALOGS["xx"]

    def test_disk_verdict(self):
        import gui
        GB = gui.GB
        self.assertEqual(gui.disk_verdict(None), "ok")                    # desconocido: no bloquear
        self.assertEqual(gui.disk_verdict(100 * GB, 10 * GB), "ok")
        self.assertEqual(gui.disk_verdict(8 * GB, 4 * GB), "low")        # quedan 8, harían falta 4 + margen
        self.assertEqual(gui.disk_verdict(4 * GB, 3.5 * GB), "stop")     # no cabría el MP4 final
        self.assertEqual(gui.fmt_bytes(int(45.24 * GB)), "45,2 GB")
        self.assertEqual(gui.fmt_bytes(820 * 1024 ** 2), "820 MB")
        free, drive = gui.disk_free(os.path.join(tempfile.gettempdir(), "no", "existe", "aun"))
        self.assertIsNotNone(free, "una carpeta que aún no existe se mide por su unidad")
        self.assertTrue(drive)

    def test_notifier_does_not_repeat_banners(self):
        import customtkinter as ctk
        from presentation.notifier import Notifier
        root = ctk.CTk()
        root.withdraw()
        try:
            host = ctk.CTkFrame(root)
            host.grid(row=0, column=0)
            footer = []
            n = Notifier(host, lambda *a, **k: ctk.CTkFont(size=12), lambda *a, **k: ctk.CTkFont(size=12),
                         on_footer=lambda text, level: footer.append(text))
            for _ in range(5):
                n.banner("disk", "Queda poco espacio", "warn")
            self.assertEqual(len(host.winfo_children()), 1, "el mismo aviso no se apila")
            self.assertEqual(footer, ["Queda poco espacio"])
            n.banner("disk", "Queda menos espacio", "warn")
            self.assertEqual(len([w for w in host.winfo_children() if w.winfo_exists()]), 1, "misma clave: se reemplaza")
            n.toast("Toma guardada")
            n.toast("Toma guardada")
            self.assertEqual(len(host.winfo_children()), 2)
            n.clear("disk")
            self.assertFalse(n.has("disk"))
        finally:
            root.destroy()


class TestAppLogger(unittest.TestCase):
    def test_warn_and_debug(self):
        """La app llama a warn() y debug(): deben existir (antes fallaban al cerrar la app)
        y los detalles de depuración no deben llegar a la interfaz."""
        from infrastructure.logging.app_logger import GLOBAL_LOGGER
        seen = []
        listener = lambda _m, category: seen.append(category)
        GLOBAL_LOGGER.add_listener(listener)
        try:
            GLOBAL_LOGGER.warn("aviso de prueba")
            GLOBAL_LOGGER.debug("detalle de prueba")
        finally:
            GLOBAL_LOGGER.remove_listener(listener)
        self.assertEqual(seen, ["WARN"])


class TestSourceSelection(unittest.TestCase):
    """Qué pasa con la cámara elegida cuando se desconecta y vuelve (sin abrir ventanas)."""

    def setUp(self):
        import gui
        self.gui = gui
        self.app = MagicMock()
        self.app.sources, self.app.sources_sig = [], ""
        self.app.rec_state, self.app.camera_paused = "idle", False
        self.app.connect_dialog, self.app.settings = None, {}
        self.app.engine.is_running = False
        self.app._selected = lambda: gui.GalaxyCamApp._selected(self.app)
        self.phone = gui.Source(id="adb:R5C", kind="android", name="Galaxy S23", meta="USB · 80 %", serial="R5C")
        self.webcam = gui.Source(id="dshow:C505", kind="webcam", name="C505 HD Webcam", device_name="C505 HD Webcam")
        self.app.sources = [self.phone, self.webcam]
        self.app.selected_id = self.phone.id

    def scan(self, *srcs):
        self.gui.GalaxyCamApp._apply_sources(self.app, list(srcs))

    def test_disconnected_source_stays_selected_and_waits(self):
        """Criterio de aceptación: al desconectar el teléfono no se salta a otra cámara."""
        self.scan(self.webcam)
        self.assertEqual(self.app.selected_id, self.phone.id)
        waiting = self.app._selected()
        self.assertTrue(waiting.waiting)
        self.assertFalse(waiting.ready)
        self.assertEqual(waiting.meta, "Desconectada")
        self.assertIn("Galaxy S23", waiting.hint_title)
        self.app._stop_preview.assert_called_once()
        self.app.select_source.assert_not_called()

    def test_disconnection_is_announced_once(self):
        """Sin spam: los escaneos siguientes (cada 3 s) no repiten el aviso."""
        for _ in range(4):
            self.scan(self.webcam)
        warns = [c for c in self.app._on_engine_log.call_args_list if c.args[1] == "WARN"]
        self.assertEqual(len(warns), 1)
        self.assertEqual(sum(1 for s in self.app.sources if s.id == self.phone.id), 1)

    def test_source_resumes_by_itself_when_back(self):
        self.scan(self.webcam)
        self.scan(self.phone, self.webcam)
        self.app.select_source.assert_called_once_with(self.phone.id)

    def test_authorizing_usb_debugging_starts_the_image(self):
        """Un teléfono «Falta autorizar» empieza solo en cuanto se acepta el aviso."""
        pending = self.gui.Source(id=self.phone.id, kind="android", name="Galaxy S23", ready=False,
                                  meta="Falta autorizar", serial="R5C")
        self.app.sources = [pending, self.webcam]
        self.scan(self.phone, self.webcam)
        self.app.select_source.assert_called_once_with(self.phone.id)

    def test_paused_camera_is_not_resumed(self):
        self.scan(self.webcam)
        self.app.camera_paused = True
        self.scan(self.phone, self.webcam)
        self.app.select_source.assert_not_called()

    def test_waiting_source_hints_match_connection(self):
        wifi = self.gui.waiting_source(self.gui.Source(id="adb:1.2.3.4:5555", kind="android", name="Pixel",
                                                       is_wifi=True))
        self.assertTrue(any("Wi‑Fi" in step for step in wifi.hint_steps))
        cam = self.gui.waiting_source(self.webcam)
        self.assertTrue(any("cable USB" in step for step in cam.hint_steps))

    def test_cancel_recording_while_starting(self):
        """Mientras la cámara tarda en dar imagen, «Cancelar» vuelve a la vista previa y
        borra el archivo a medio empezar (detrás de la parada, en la cola de trabajos)."""
        self.app.rec_state = "starting"
        self.app.engine.current_recording_file = "C:/tmp/parcial.mkv"
        self.app._cancel_recording_start = lambda: self.gui.GalaxyCamApp._cancel_recording_start(self.app)
        self.gui.GalaxyCamApp.toggle_recording(self.app)
        self.assertEqual(self.app.rec_state, "idle")
        self.app._stop_preview.assert_called_once()
        self.app._stream_jobs.submit.assert_called_once()
        self.app._start_preview.assert_called_once()

    def _channel_app(self):
        app = self.app
        app.audio_engine.config = {"channels": [{"id": "x", "name": "Entrada 1", "source": {"kind": "main", "ch": [0]}}]}
        app.audio_devices = {"default_out": "Altavoces"}
        app._chord_pending = set()
        app.add_channel = lambda *a, **k: self.gui.GalaxyCamApp.add_channel(app, *a, **k)
        return app

    def test_add_channel_picks_name_and_mode(self):
        """Cada canal nuevo nace con un nombre útil y mono/estéreo según la fuente."""
        app = self._channel_app()
        mono = self.gui.GalaxyCamApp.add_channel_from(app, {"kind": "main", "ch": [1]})
        self.assertEqual((mono["name"], mono["mode"], mono["monitor"]), ("Entrada 2", "mono", False))
        pair = self.gui.GalaxyCamApp.add_channel_from(app, {"kind": "main", "ch": [2, 3]})
        self.assertEqual((pair["name"], pair["mode"]), ("Entradas 3-4", "stereo"))
        pc = self.gui.GalaxyCamApp.add_channel_from(app, {"kind": "device", "device": "Altavoces", "loopback": True})
        self.assertEqual((pc["name"], pc["mode"]), ("Sonido del PC", "stereo"))
        self.assertEqual(len(app.audio_engine.config["channels"]), 4)
        self.assertEqual(app.apply_audio_config.call_count, 3)

    def test_new_instrument_is_ready_to_play(self):
        """Instrumento nuevo: monitor encendido, cualquier teclado MIDI y un acorde al cargar."""
        app = self._channel_app()
        ch = self.gui.GalaxyCamApp.add_instrument_channel(app, r"C:\VST3\vital.vst3", "Vital")
        self.assertEqual((ch["name"], ch["mode"], ch["monitor"]), ("Vital", "stereo", True))
        self.assertEqual((ch["source"]["midi_in"], ch["source"]["midi_ch"]), ("*", 0))
        self.assertIn(ch["id"], app._chord_pending)
        app.audio_engine.inst_status = {}
        self.gui.GalaxyCamApp._after_audio_applied(app)          # todavía cargando
        app.audio_engine.test_chord.assert_not_called()
        app.audio_engine.inst_status = {ch["id"]: {"name": "Vital", "error": None}}
        self.gui.GalaxyCamApp._after_audio_applied(app)
        app.audio_engine.test_chord.assert_called_once_with(ch["id"])
        self.gui.GalaxyCamApp._after_audio_applied(app)          # una sola vez
        app.audio_engine.test_chord.assert_called_once()

    def test_failed_instrument_does_not_play(self):
        app = self._channel_app()
        ch = self.gui.GalaxyCamApp.add_instrument_channel(app, r"C:\VST3\roto.vst3")
        app.audio_engine.inst_status = {ch["id"]: {"name": "Roto", "error": "no carga"}}
        self.gui.GalaxyCamApp._after_audio_applied(app)
        app.audio_engine.test_chord.assert_not_called()
        self.assertEqual(app._chord_pending, set())

    def test_vertical_size(self):
        self.assertEqual(self.gui.vertical_size("1920x1080", "crop"), (606, 1080))
        self.assertEqual(self.gui.vertical_size("1920x1080", "cw"), (1080, 1920))
        self.assertEqual(self.gui.vertical_size("3840x2160", "phone"), (2160, 3840))
        self.assertIsNone(self.gui.vertical_size("1920x1080", None))

    def test_vertical_pick_phone_rotates_webcam_crops(self):
        """Vertical en el teléfono = captura girada (resolución completa); en una webcam, por
        omisión se recorta el centro y al volver a vertical se recupera el último modo."""
        app = self.app
        app._rotation = lambda s: self.gui.GalaxyCamApp._rotation(app, s)
        app.fmt_by_src = {}
        app.selected_id = self.phone.id
        self.gui.GalaxyCamApp._on_orient_pick(app, "v")
        self.assertEqual(app.fmt_by_src[self.phone.id]["rotation"], 90)
        self.gui.GalaxyCamApp._on_orient_pick(app, "h")
        self.assertEqual(app.fmt_by_src[self.phone.id]["rotation"], 0)
        app.selected_id = self.webcam.id
        self.gui.GalaxyCamApp._on_orient_pick(app, "v")
        self.assertEqual(app.fmt_by_src[self.webcam.id]["vertical"], "crop")
        self.gui.GalaxyCamApp._on_vmode_pick(app, "cw")
        self.gui.GalaxyCamApp._on_orient_pick(app, "h")
        self.assertIsNone(app.fmt_by_src[self.webcam.id]["vertical"])
        self.gui.GalaxyCamApp._on_orient_pick(app, "v")
        self.assertEqual(app.fmt_by_src[self.webcam.id]["vertical"], "cw", "recuerda el último modo")

    def test_own_virtual_camera_is_not_a_source(self):
        self.assertTrue(self.gui.is_own_virtual_camera("UltraCam"))
        self.assertTrue(self.gui.is_own_virtual_camera(" ultracam "))
        self.assertFalse(self.gui.is_own_virtual_camera("OBS Virtual Camera"))
        self.assertFalse(self.gui.is_own_virtual_camera("UltraCam Test"))


@unittest.skipUnless(sys.platform == "win32", "Job Objects de Windows")
class TestProcessesDieWithApp(unittest.TestCase):
    def test_bound_process_dies_when_app_exits_abruptly(self):
        """Un ffplay atado a la app muere aunque ella termine sin detenerlo (os._exit)."""
        import subprocess
        app = ("import os, subprocess, sys; sys.path.insert(0, {root!r});"
               "from infrastructure.system.process_utils import bind_to_app;"
               "p = bind_to_app(subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],"
               " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL));"
               "print(p.pid, flush=True); os._exit(0)").format(root=os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-c", app], capture_output=True, text=True, timeout=30)
        pid = int(out.stdout.split()[0])
        import ctypes
        k32 = ctypes.windll.kernel32
        deadline = time.time() + 5
        alive = True
        while alive and time.time() < deadline:
            h = k32.OpenProcess(0x00100000, False, pid)          # SYNCHRONIZE
            alive = bool(h) and k32.WaitForSingleObject(h, 0) == 0x102   # WAIT_TIMEOUT: sigue vivo
            if h:
                k32.CloseHandle(h)
            if alive:
                time.sleep(0.1)
        self.assertFalse(alive, "el proceso hijo sobrevivió al cierre de la app")


if __name__ == "__main__":
    unittest.main(verbosity=2)


