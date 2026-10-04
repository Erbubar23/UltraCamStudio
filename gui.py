"""
UltraCam Studio - Interfaz de estudio unificada.

Una sola pantalla: todas las cámaras (webcams, capturadoras, Android, apps de
iPhone) aparecen juntas en la lista de la izquierda, sin "modos" de plataforma.
El monitor se integra en la ventana (Win32 SetParent) y la grabación usa un solo
botón. Los ajustes propios de cada tipo de cámara viven en el bloque
"Este dispositivo" del panel derecho.

Raíz de composición: GalaxyCamApp reúne el marco (app/) y los módulos (modules/).
"""

import os
import queue
import threading
import concurrent.futures
import webbrowser
import tkinter.font as tkfont
from typing import Dict, List, Optional

import customtkinter as ctk

from engine import CameraEngine
from audio_engine import AudioEngine
from infrastructure.logging.app_logger import GLOBAL_LOGGER
from modules.audio.ui.add_channel import AddChannelDialog
from presentation.strings import t
from presentation.theme import C
from app.bus import EventBus
from app.constants import APP_NAME, DONATE_URL
from app.shell import ShellMixin, settings_path
from app.frame import FrameMixin
from modules.cameras.mixin import CamerasMixin
from modules.cameras.model import Source, is_own_virtual_camera, vertical_size, waiting_source
from modules.audio.mixin import AudioMixin
from modules.audio.levels import vol_to_db_text
from modules.recording.mixin import RecordingMixin
from modules.recording.disk import GB, DISK_LOW, DISK_MIN_TO_START, DISK_RESERVE, disk_free, disk_verdict, fmt_bytes
from modules.general.mixin import GeneralMixin
from modules.cameras.module import CamerasModule
from modules.audio.module import AudioModule
from modules.recording.module import RecordingModule
from modules.general.module import GeneralModule
from modules.streaming.module import StreamingModule

# Lo que otros archivos y las pruebas siguen importando desde gui (antes vivía aquí)
__all__ = ["GalaxyCamApp", "APP_NAME", "APP_VERSION", "DONATE_URL", "C", "Source", "is_own_virtual_camera",
           "vertical_size", "waiting_source", "vol_to_db_text", "settings_path", "GB", "DISK_LOW",
           "DISK_MIN_TO_START", "DISK_RESERVE", "disk_free", "disk_verdict", "fmt_bytes"]

APP_VERSION = "0.21.0-beta"

ctk.set_appearance_mode("Dark")


# =============================================================================
# APLICACIÓN
# =============================================================================
class GalaxyCamApp(FrameMixin, ShellMixin, CamerasMixin, AudioMixin, RecordingMixin, GeneralMixin, ctk.CTk):
    def __init__(self):
        super().__init__()
        # Cola de tareas para la interfaz: los hilos de fondo dejan aquí lo que hay que
        # pintar y la interfaz lo ejecuta (ver _ui). Va primero: los motores ya avisan al crearse.
        self._ui_queue: "queue.SimpleQueue" = queue.SimpleQueue()
        self.after(15, self._drain_ui)
        # Los módulos se avisan entre sí por aquí (ver app/bus.py), sin importarse
        self.bus = EventBus(report=lambda ev, e: GLOBAL_LOGGER.log(f"Error en un aviso «{ev}»: {e}", "WARN"))
        self.title(f"{APP_NAME}")
        self.geometry("1360x880")
        self.minsize(1180, 760)
        self.configure(fg_color=C["bg"])
        self._set_window_icon()

        fams = set(tkfont.families(self))
        self.ui_family = "Segoe UI Variable Text" if "Segoe UI Variable Text" in fams else "Segoe UI"
        self.mono_family = "Cascadia Mono" if "Cascadia Mono" in fams else "Consolas"
        self.icon_family = "Segoe Fluent Icons" if "Segoe Fluent Icons" in fams else "Segoe MDL2 Assets"

        # Motores
        self.engine = CameraEngine()
        self.engine.on_log_callback = self._on_engine_log
        GLOBAL_LOGGER.add_listener(lambda m, c: self._on_engine_log(m, c))
        self.camera_paused = False
        self.audio_engine = AudioEngine()
        ae = self.audio_engine
        ae.on_levels = self._on_audio_levels
        ae.on_stats = lambda st: self._ui(self._on_audio_stats, st)
        ae.on_log = lambda m, c: self._on_engine_log(m, c)
        ae.on_fx = lambda cid: self._ui(self._on_fx_loaded, cid)
        ae.on_fx_state = lambda cid, fid, st: self._ui(self._persist_audio)
        ae.on_editor = lambda cid, fid, is_open: self._ui(self._on_editor_state, cid, fid, is_open)
        ae.on_midi = lambda ids: self._ui(self._flash_midi, ids)
        ae.on_inputs = lambda dbs, devs: self._ui(self._on_input_levels, dbs, devs)
        ae.on_midi_learned = lambda dev, mch: self._ui(self._on_midi_learned, dev, mch)

        # Estado
        self.settings = self._load_settings()
        self.sources: List[Source] = []
        self.sources_sig = ""
        self.selected_id: Optional[str] = None
        self.caps: Dict[str, Dict] = {}
        self.fmt_by_src: Dict[str, Dict] = {}          # {"size", "fps", "rotation"} por fuente
        self.lens_by_serial: Dict[str, List[Dict]] = {}
        self.android_info: Dict[str, Dict] = {}
        self.image = {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "sharpness": 0.0}
        self.preset: Optional[str] = None
        self.stream_gen = 0
        self.monitor_title: Optional[str] = None
        self.monitor_hwnd: Optional[int] = None
        self.rec_state = "idle"                         # idle | starting | recording | saving
        self.record_start_time = 0.0
        self.scan_force = threading.Event()
        self.running = True
        self.last_dshow_scan = 0.0
        self.pending_restart = None
        self.pending_save = None
        self._log_has_error = False                     # el módulo General lo marca en el riel
        self.connect_dialog = None
        self.settings_win = None
        self.audio_devices: Dict = {}
        self.audio_stats: Dict = {}
        self.vst_list: List[Dict] = []
        self.vst_probing = False                        # clasificando plugins (instrumento / efecto)
        self.vst_probe_progress = (0, 0)                # (revisados, total) mientras se clasifican
        self.add_dialog: Optional[AddChannelDialog] = None
        self._chord_pending: set = set()                # instrumentos nuevos: suenan al quedar cargados
        self.strips: Dict[str, Dict] = {}
        self.vcam_state = {"status": "off", "message": ""}
        # Controles de Configuración (existen solo mientras esa ventana está abierta)
        self.dev_body = self.dev_kind_tag = self.music_tip = self.image_box = None
        self.lbl_saved_for = self.image_note = self.lbl_dir = self.lbl_sync = self.slider_sync = None
        self.preset_buttons: Dict = {}
        self.sliders: Dict = {}
        self.norm_buttons: Dict = {}
        self._lens_map: Dict = {}

        # Opciones persistentes
        s = self.settings
        self.record_dir_var = ctk.StringVar(value=s.get("record_dir", os.path.join(os.path.expanduser("~"), "Videos", "GalaxyCam")))
        self.record_prefix_var = ctk.StringVar(value=s.get("prefix", "UltraCam_Session"))
        self.norm_mode = s.get("normalize", "ebu_r128")
        self.sync_ms = int(s.get("sync_ms", 0))
        self.opt_stems = ctk.BooleanVar(value=s.get("stems", False))
        self.opt_reveal = ctk.BooleanVar(value=s.get("reveal", False))
        self.opt_autoplay = ctk.BooleanVar(value=s.get("autoplay", False))
        self.opt_summary = ctk.BooleanVar(value=s.get("summary", False))   # el aviso de la toma ya da acceso directo
        self.opt_multitrack = ctk.BooleanVar(value=s.get("multitrack", True))
        # Archivo final comprimido (mismo flujo; ver modules/recording/export): activado por defecto
        self.opt_compress = ctk.BooleanVar(value=s.get("compress_export", True))
        self._encoders = None                           # codificadores que funcionan en esta PC
        self._encoders_lock = threading.Lock()
        self.save_overlay = None
        self.vcam_cfg = s.setdefault("vcam", {})
        # Opciones de versiones anteriores que ya no existen: el driver propio siempre
        # está en Windows y recibe 1080p, y la salida sigue a la cámara elegida (ya no
        # se activa cámara por cámara).
        for old in ("canvas", "autostart", "by_source"):
            self.vcam_cfg.pop(old, None)
        # Encendida: «UltraCam» muestra siempre la cámara elegida. Apagada: «Sin señal».
        self.vcam_cfg.setdefault("enabled", True)
        self._stream_retries = 0
        # Arrancar y detener cámaras puede tardar segundos (liberar una webcam, abrir el
        # teléfono): se hace en este hilo aparte, en orden, para que la ventana no se congele.
        self._stream_jobs = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="stream")
        self.video_cfg = s.setdefault("video", {"android_codec": "h265", "android_bitrate": "50M"})
        ae.config = self._load_audio_config()

        # Los módulos del marco (riel, cajón y columna fija): cada uno en modules/<clave>/module.py
        self.modules = {m.spec.key: m for m in (CamerasModule(self), AudioModule(self), RecordingModule(self),
                                                StreamingModule(self), GeneralModule(self))}
        self._build_layout()
        self._paint_vcam()
        self._init_audio()
        self._refresh_takes()
        self._check_binaries()
        self._start_vcam_device()
        if not self.settings.get("onboarded"):
            self.after(1200, self.show_welcome)      # primera vez: cómo empezar
        if not self.settings.get("last_source"):
            self.after(800, lambda: self.open_module("cameras"))   # sin cámara elegida: empezar por ahí
        # Averiguar el codificador de la grabación ahora, en segundo plano: así la
        # primera vez que se pulse Grabar no hay que esperar a la comprobación.
        threading.Thread(target=self.engine.video_encoder_args, daemon=True).start()
        threading.Thread(target=self._export_encoders, daemon=True).start()
        self.after(2500, self._check_pending_takes)     # ¿quedó una toma a medio guardar?
        threading.Thread(target=self._scan_loop, daemon=True).start()
        self._tick_ui()

    # ------------------------------ FOOTER -----------------------------------
    def _build_footer(self):
        f = ctk.CTkFrame(self, height=30, corner_radius=0, fg_color=C["footer"])
        f.grid(row=1, column=0, columnspan=3, sticky="ew")
        f.grid_columnconfigure(1, weight=1)
        self.footer_dot = ctk.CTkLabel(f, text="●", font=self.F(9), text_color=C["ok"])
        self.footer_dot.grid(row=0, column=0, padx=(14, 6))
        self.footer_text = ctk.CTkLabel(f, text=t("app.starting"), font=self.F(12), text_color=C["muted"], anchor="w")
        self.footer_text.grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(f, text=f"v{APP_VERSION}", font=self.F(11), text_color=C["off"]).grid(row=0, column=2, padx=10)
        self.btn_log = ctk.CTkButton(f, text=t("ui.main.registro_y_diagnostico"), height=24, width=160, corner_radius=6,
                                     fg_color=C["panel"], hover_color=C["raised"], text_color=C["text2"], font=self.F(12),
                                     command=self.toggle_log)
        self.btn_log.grid(row=0, column=4, padx=(0, 10), pady=3)
        ctk.CTkButton(f, text=t("ui.main.invitame_un_cafe"), height=24, width=90, corner_radius=6,
                      fg_color=C["accent_bg"], hover_color=C["raised"], text_color=C["accent_text"], font=self.F(12),
                      command=lambda: webbrowser.open(DONATE_URL)).grid(row=0, column=3, padx=(0, 8), pady=3)


if __name__ == "__main__":
    app = GalaxyCamApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
