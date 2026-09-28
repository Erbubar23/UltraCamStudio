"""
UltraCam Studio - Interfaz de estudio unificada.

Una sola pantalla: todas las cámaras (webcams, capturadoras, Android, apps de
iPhone) aparecen juntas en la lista de la izquierda, sin "modos" de plataforma.
El monitor se integra en la ventana (Win32 SetParent) y la grabación usa un solo
botón. Los ajustes propios de cada tipo de cámara viven en el bloque
"Este dispositivo" del panel derecho.
"""

import os
import sys
import json
import math
import time
import ctypes
import queue
import shutil
import threading
import concurrent.futures
import subprocess
import datetime
import webbrowser
import tkinter.font as tkfont
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple

import customtkinter as ctk
from tkinter import filedialog

from engine import CameraEngine
from audio_engine import AudioEngine, DEFAULT_CONFIG, CHANNEL_COLORS, new_channel, scan_vst3, source_label
import paths
import virtualcam
import winpipes
from infrastructure.logging.app_logger import GLOBAL_LOGGER
from infrastructure.system.win32_window import GLOBAL_WINDOW_EMBEDDER
from presentation.dialogs.confirm_dialog import ConfirmDialog
from presentation.notifier import Notifier
from presentation.strings import t
from presentation.dialogs.connect_dialog import ConnectDialog
from presentation.dialogs.welcome_dialog import WelcomeDialog
from presentation.dialogs.summary_dialog import TakeSummaryDialog

APP_NAME = "UltraCam Studio"
APP_VERSION = "0.20.4-beta"
DONATE_URL = "https://www.paypal.com/donate/?hosted_button_id=TGKZ4QZPA5878"

ctk.set_appearance_mode("Dark")

# Paleta, iconos y textos de dominio: una sola fuente, compartida con los diálogos.
from presentation.theme import (C, ICON, KIND_LABEL, KIND_LONG, ANDROID_RES, PRESETS,  # noqa: E402
                                PRESET_VALUES, NORM_OPTIONS, fmt_res, res_tier)


def settings_path() -> str:
    return paths.settings_path()


def vol_to_db_text(v: float) -> str:
    if v <= 0.001:
        return "−∞ dB"
    db = 20 * math.log10(v)
    return f"{db:+.1f} dB".replace("-", "−")


@dataclass
class Source:
    id: str
    kind: str                      # webcam | capture | virtual | app | android
    name: str
    meta: str = ""
    ready: bool = True
    hint_title: str = ""
    hint_steps: List[str] = field(default_factory=list)
    device_name: Optional[str] = None   # DirectShow
    serial: Optional[str] = None        # Android (adb)
    battery: Optional[int] = None
    is_wifi: bool = False
    waiting: bool = False               # desconectada: se conserva elegida hasta que vuelva

    @property
    def is_dshow(self) -> bool:
        return self.device_name is not None


def vertical_size(size: str, mode: Optional[str]) -> Optional[tuple]:
    """Tamaño (ancho, alto) del video vertical que sale de una resolución y un modo:
    'crop' recorta el centro a 9:16; 'cw'/'ccw'/'phone' giran la imagen completa."""
    try:
        w, h = (int(x) for x in size.lower().split("x"))
    except (ValueError, AttributeError):
        return None
    if mode == "crop":
        return int(h * 9 / 32) * 2, h
    if mode in ("cw", "ccw", "phone"):
        return h, w
    return None


def is_own_virtual_camera(name: str) -> bool:
    """«UltraCam» no puede ser fuente de sí misma: su imagen volvería a entrar en bucle."""
    return name.strip().casefold() == virtualcam.DEVICE_NAME.casefold()


def waiting_source(prev: Source) -> Source:
    """La fuente elegida se desconectó: sigue en la lista como «Desconectada», con pasos
    para recuperarla, y la imagen vuelve sola cuando aparece (no se salta a otra cámara)."""
    s = Source(id=prev.id, kind=prev.kind, name=prev.name, meta=t("ui.main.desconectada"), ready=False,
               device_name=prev.device_name, serial=prev.serial, is_wifi=prev.is_wifi, waiting=True)
    s.hint_title = t("source.waiting_title", name=prev.name)
    back = t("ui.main.la_imagen_vuelve_sola_en")
    if prev.kind == "android":
        s.hint_steps = [
            t("ui.main.comprueba_que_el_telefono_y") if prev.is_wifi
            else t("ui.main.vuelve_a_conectar_el_cable"),
            t("ui.main.desbloquea_el_telefono_y_acepta"),
            back,
        ]
    elif prev.kind == "app":
        s.hint_steps = [
            t("ui.main.abre_la_app_de_camara"),
            t("ui.main.comprueba_que_el_telefono_y"),
            back,
        ]
    else:
        s.hint_steps = [t("ui.main.revisa_el_cable_usb_o"), back]
    return s


# Espacio en disco para grabar. Al terminar, unir video y audio crea el MP4 junto al
# archivo en curso, así que hace falta al menos otro tanto libre para poder guardar.
GB = 1024 ** 3
DISK_MIN_TO_START = 2 * GB      # por debajo no se empieza a grabar
DISK_LOW = 5 * GB               # aviso durante la grabación
DISK_RESERVE = 1 * GB           # margen que se deja siempre libre


def disk_free(folder: str):
    """(bytes libres, unidad) de la carpeta, o (None, "") si no se puede saber."""
    path = os.path.abspath(folder)
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        return None, ""
    drive = os.path.splitdrive(path)[0] or path
    return free, drive


def fmt_bytes(n: int) -> str:
    """Tamaño legible con coma decimal: «45,2 GB», «820 MB»."""
    if n >= GB:
        return f"{n / GB:.1f} GB".replace(".", ",")
    return f"{n / 1024 ** 2:.0f} MB"


def disk_verdict(free: Optional[int], recording_bytes: int = 0) -> str:
    """'ok', 'low' (avisar) o 'stop' (detener y guardar ya), según lo libre y lo grabado."""
    if free is None:
        return "ok"
    if free < DISK_RESERVE + recording_bytes:
        return "stop"
    if free < DISK_LOW + recording_bytes:
        return "low"
    return "ok"


# =============================================================================
# APLICACIÓN
# =============================================================================
class GalaxyCamApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        # Cola de tareas para la interfaz: los hilos de fondo dejan aquí lo que hay que
        # pintar y la interfaz lo ejecuta (ver _ui). Va primero: los motores ya avisan al crearse.
        self._ui_queue: "queue.SimpleQueue" = queue.SimpleQueue()
        self.after(15, self._drain_ui)
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
        self.log_open = False
        self.connect_dialog = None
        self.settings_win = None
        self.audio_devices: Dict = {}
        self.audio_stats: Dict = {}
        self.vst_list: List[Dict] = []
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

        self._build_layout()
        self._paint_vcam()
        self._init_audio()
        self._refresh_takes()
        self._check_binaries()
        self._start_vcam_device()
        if not self.settings.get("onboarded"):
            self.after(1200, self.show_welcome)      # primera vez: cómo empezar
        # Averiguar el codificador de la grabación ahora, en segundo plano: así la
        # primera vez que se pulse Grabar no hay que esperar a la comprobación.
        threading.Thread(target=self.engine.video_encoder_args, daemon=True).start()
        threading.Thread(target=self._scan_loop, daemon=True).start()
        self._tick_ui()

    def _ui(self, fn, *args):
        """Ejecuta fn en el hilo de la interfaz, sin que quien llama tenga que esperar.

        Llamar a Tk desde otro hilo (incluido self.after) espera a que la interfaz esté
        libre. Si la interfaz a su vez espera a ese hilo —por ejemplo, la respuesta del motor
        de audio al grabar— los dos quedan bloqueados hasta que se agota el tiempo: la
        ventana se congelaba 15–30 s y la toma se guardaba sin audio. Con la cola, nadie espera."""
        self._ui_queue.put((fn, args))

    def _drain_ui(self):
        for _ in range(500):
            try:
                fn, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:
                self.report_callback_exception(*sys.exc_info())
        try:
            self.after(15, self._drain_ui)
        except Exception:
            pass            # la ventana ya se cerró

    # -------------------------------------------------------------------------
    # Utilidades visuales
    # -------------------------------------------------------------------------
    def F(self, size=13, weight="normal", mono=False):
        return ctk.CTkFont(family=self.mono_family if mono else self.ui_family, size=size, weight=weight)

    def IF(self, size=16):
        return ctk.CTkFont(family=self.icon_family, size=size)

    def _set_window_icon(self):
        for base in (os.path.dirname(os.path.abspath(__file__)), getattr(sys, "_MEIPASS", "")):
            ico = os.path.join(base, "assets", "app.ico")
            if base and os.path.exists(ico):
                try:
                    self.iconbitmap(ico)
                except Exception as e:
                    GLOBAL_LOGGER.debug(f"Aviso al establecer icono de ventana: {e}")
                return

    def _section_label(self, master, text):
        return ctk.CTkLabel(master, text=text.upper(), font=self.F(11, "bold"), text_color=C["muted"], anchor="w")

    def _ghost_button(self, master, text, command, width=0, icon=None, **kw):
        label = f"{text}" if not icon else text
        b = ctk.CTkButton(master, text=label, command=command, fg_color="transparent", hover_color=C["raised"],
                          text_color=C["text2"], font=self.F(12), height=kw.pop("height", 30),
                          width=width or 10, corner_radius=7, **kw)
        return b

    def _outline_button(self, master, text, command, height=36, **kw):
        return ctk.CTkButton(master, text=text, command=command, fg_color="transparent", hover_color=C["raised"],
                             border_width=1, border_color=C["line2"], text_color=C["text"], font=self.F(13),
                             height=height, corner_radius=9, **kw)

    def _segmented(self, master, options, current, on_pick, height=32, font=None):
        """Control segmentado propio: permite desactivar opciones individuales."""
        wrap = ctk.CTkFrame(master, fg_color=C["raised"], corner_radius=9)
        buttons = {}
        for i, (value, text) in enumerate(options):
            wrap.grid_columnconfigure(i, weight=1, uniform="seg")
            b = ctk.CTkButton(wrap, text=text, height=height, corner_radius=7, font=font or self.F(13, "bold"),
                              command=lambda v=value: on_pick(v))
            b.grid(row=0, column=i, sticky="ew", padx=3, pady=3)
            buttons[value] = b
        wrap.buttons = buttons

        def paint(selected, disabled=()):
            for v, b in buttons.items():
                on = v == selected
                dis = v in disabled
                b.configure(fg_color=C["line2"] if on else "transparent", hover_color=C["line2"],
                            text_color=C["text"] if on else C["muted"], text_color_disabled=C["off"],
                            state="disabled" if dis else "normal")
        wrap.paint = paint
        paint(current)
        return wrap

    # =========================================================================
    # LAYOUT
    # =========================================================================
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.rail = ctk.CTkFrame(self, width=288, corner_radius=0, fg_color=C["rail"])
        self.rail.grid(row=0, column=0, sticky="ns")
        self.rail.grid_propagate(False)
        self.center = ctk.CTkFrame(self, corner_radius=0, fg_color=C["bg"])
        self.center.grid(row=0, column=1, sticky="nsew")
        self.inspector = ctk.CTkFrame(self, width=348, corner_radius=0, fg_color=C["rail"])
        self.inspector.grid(row=0, column=2, sticky="ns")
        self.inspector.grid_propagate(False)
        # separadores
        ctk.CTkFrame(self, width=1, fg_color=C["line"], corner_radius=0).grid(row=0, column=0, sticky="nse")
        ctk.CTkFrame(self, width=1, fg_color=C["line"], corner_radius=0).grid(row=0, column=2, sticky="nsw")

        self._build_rail()
        self._build_center()
        self._build_inspector()
        self._build_footer()

    # ------------------------------ RAIL -------------------------------------
    def _build_rail(self):
        r = self.rail
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(r, fg_color="transparent", height=60)
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 4))
        ctk.CTkLabel(brand, text=ICON["video"], font=self.IF(20), text_color=C["accent"]).pack(side="left")
        ctk.CTkLabel(brand, text="UltraCam", font=self.F(16, "bold"), text_color=C["text"]).pack(side="left", padx=(10, 4))
        ctk.CTkLabel(brand, text="Studio", font=self.F(16), text_color=C["muted"]).pack(side="left")

        head = ctk.CTkFrame(r, fg_color="transparent")
        head.grid(row=1, column=0, sticky="ew", padx=(20, 12), pady=(10, 2))
        self._section_label(head, t("ui.main.camaras")).pack(side="left")
        self.btn_rescan = ctk.CTkButton(head, text=ICON["refresh"], font=self.IF(14), width=30, height=30,
                                        fg_color="transparent", hover_color=C["raised"], text_color=C["muted"],
                                        command=self._force_rescan)
        self.btn_rescan.pack(side="right")

        # Lista de cámaras + acceso a conectar móvil + audio, en un contenedor desplazable
        body = ctk.CTkScrollableFrame(r, fg_color="transparent", scrollbar_button_color=C["raised"])
        body.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=(0, 10))
        body.grid_columnconfigure(0, weight=1)
        self.rail_body = body

        self.sources_box = ctk.CTkFrame(body, fg_color="transparent")
        self.sources_box.grid(row=0, column=0, sticky="ew")
        self.sources_box.grid_columnconfigure(0, weight=1)
        self.source_rows: Dict[str, Dict] = {}
        self.lbl_no_sources = ctk.CTkLabel(self.sources_box, text=t("ui.main.buscando_camaras"), font=self.F(12),
                                           text_color=C["muted"], anchor="w")
        self.lbl_no_sources.grid(row=0, column=0, sticky="ew", padx=10, pady=8)

        self.btn_connect = ctk.CTkButton(body, text=f"{ICON['add']}   {t('action.connect_phone')}", font=ctk.CTkFont(family=self.ui_family, size=13),
                                         height=42, corner_radius=10, anchor="w", fg_color="transparent",
                                         border_width=1, border_color=C["line2"], hover_color=C["raised"],
                                         text_color=C["text2"], command=self._open_connect_dialog)
        self.btn_connect.grid(row=1, column=0, sticky="ew", padx=4, pady=(6, 4))


    # ------------------------------ CENTRO -----------------------------------
    def _build_center(self):
        c = self.center
        c.grid_columnconfigure(0, weight=1)
        c.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(c, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 0))
        head.grid_columnconfigure(0, weight=1)
        name_row = ctk.CTkFrame(head, fg_color="transparent")
        name_row.grid(row=0, column=0, sticky="w")
        self.lbl_src_name = ctk.CTkLabel(name_row, text=t("ui.main.sin_camara"), font=self.F(18, "bold"), text_color=C["text"], anchor="w")
        self.lbl_src_name.pack(side="left")
        # Modo en que está la cámara (4K, 2K, Full HD… y fps): se ve siempre, sin abrir el panel
        self.lbl_mode = ctk.CTkLabel(name_row, text="", font=self.F(11, "bold"), height=22, corner_radius=6,
                                     fg_color=C["accent_bg"], text_color=C["accent_text"])
        self.lbl_src_kind = ctk.CTkLabel(head, text=t("ui.main.elige_una_camara_en_la"), font=self.F(12), text_color=C["muted"], anchor="w")
        self.lbl_src_kind.grid(row=1, column=0, sticky="w")
        self.btn_pause_cam = ctk.CTkButton(head, text=t("pause.button"), width=120, height=32, corner_radius=16, font=self.F(12),
                                           fg_color=C["panel"], hover_color=C["raised"], text_color=C["text2"], border_width=1,
                                           border_color=C["line"], command=self._toggle_camera_power)
        self.btn_pause_cam.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 8))
        self.btn_vcam = ctk.CTkButton(head, text=t("ui.main.camara_virtual"), width=175, height=32, corner_radius=16, font=self.F(12, "bold"),
                                      border_width=1, command=self._toggle_vcam)
        self.btn_vcam.grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 8))
        pill = ctk.CTkFrame(head, fg_color=C["panel"], corner_radius=15, border_width=1, border_color=C["line"])
        pill.grid(row=0, column=3, rowspan=2, sticky="e")
        ctk.CTkButton(head, text=ICON["settings"], font=self.IF(16), width=36, height=32, corner_radius=16,
                      fg_color=C["panel"], hover_color=C["raised"], text_color=C["text2"], border_width=1,
                      border_color=C["line"], command=lambda: self.open_settings()).grid(row=0, column=4, rowspan=2,
                                                                                         sticky="e", padx=(8, 0))
        self.live_dot = ctk.CTkLabel(pill, text="●", font=self.F(10), text_color=C["off"])
        self.live_dot.pack(side="left", padx=(12, 6), pady=4)
        self.live_text = ctk.CTkLabel(pill, text=t("ui.main.sin_senal"), font=self.F(12), text_color=C["text2"])
        self.live_text.pack(side="left", padx=(0, 12), pady=4)

        # Avisos (toasts y banners) entre el encabezado y el monitor; ver presentation/notifier.py
        self.notices = ctk.CTkFrame(c, fg_color="transparent")
        self.notices.grid(row=1, column=0, sticky="ew", padx=22, pady=(10, 0))
        self.notify = Notifier(self.notices, self.F, self.IF,
                               on_footer=lambda text, level: self._status(text, warn=level in ("warn", "error")))

        # Monitor
        self.video_container = ctk.CTkFrame(c, fg_color=C["black"], corner_radius=12, border_width=2, border_color=C["panel"])
        self.video_container.grid(row=2, column=0, sticky="nsew", padx=22, pady=(14, 0))
        self.video_container.grid_columnconfigure(0, weight=1)
        self.video_container.grid_rowconfigure(0, weight=1)
        self.video_container.bind("<Configure>", self._on_monitor_resize)

        self.video_msg = ctk.CTkFrame(self.video_container, fg_color="transparent")
        self.video_msg.grid(row=0, column=0)
        self.vm_icon = ctk.CTkLabel(self.video_msg, text=ICON["camera"], font=self.IF(36), text_color=C["off"])
        self.vm_icon.pack(anchor="w")
        self.vm_title = ctk.CTkLabel(self.video_msg, text="", font=self.F(17, "bold"), text_color=C["text"], anchor="w", justify="left", wraplength=460)
        self.vm_title.pack(anchor="w", pady=(10, 6))
        self.vm_body = ctk.CTkLabel(self.video_msg, text="", font=self.F(14), text_color=C["text2"], anchor="w", justify="left", wraplength=460)
        self.vm_body.pack(anchor="w")
        self.vm_actions = ctk.CTkFrame(self.video_msg, fg_color="transparent")
        self.vm_actions.pack(anchor="w", pady=(14, 0))
        self._set_video_message(t("video.searching.title"), t("video.searching.body"), icon="camera")

        # Transporte
        tr = ctk.CTkFrame(c, fg_color=C["panel"], corner_radius=12, border_width=1, border_color=C["line"], height=88)
        tr.grid(row=3, column=0, sticky="ew", padx=22, pady=(14, 0))
        tr.grid_columnconfigure(2, weight=1)
        self.btn_rec = ctk.CTkButton(tr, text=t("ui.main.grabar"), width=200, height=54, corner_radius=12, font=self.F(15, "bold"),
                                     fg_color=C["rec"], hover_color=C["rec_hover"], text_color="#FFFFFF",
                                     text_color_disabled=C["off"], command=self.toggle_recording)
        self.btn_rec.grid(row=0, column=0, rowspan=2, padx=(16, 18), pady=16)
        tbox = ctk.CTkFrame(tr, fg_color="transparent", width=200)
        tbox.grid(row=0, column=1, rowspan=2, sticky="w")
        self.lbl_timer = ctk.CTkLabel(tbox, text="00:00:00", font=self.F(26, mono=True), text_color=C["text"], anchor="w")
        self.lbl_timer.pack(anchor="w")
        self.lbl_rec_status = ctk.CTkLabel(tbox, text="", font=self.F(12), text_color=C["muted"], anchor="w")
        self.lbl_rec_status.pack(anchor="w")
        mbox = ctk.CTkFrame(tr, fg_color="transparent")
        mbox.grid(row=0, column=2, rowspan=2, sticky="ew", padx=(18, 18))
        mtop = ctk.CTkFrame(mbox, fg_color="transparent")
        mtop.pack(fill="x")
        ctk.CTkLabel(mtop, text=t("ui.main.mezcla_final"), font=self.F(11, "bold"), text_color=C["muted"]).pack(side="left")
        self.clip_badge = ctk.CTkLabel(mtop, text="CLIP", font=self.F(10, "bold"), fg_color=C["line"], text_color=C["off"],
                                       corner_radius=4, width=38, height=18)
        self.clip_badge.pack(side="right")
        self.meter_master = ctk.CTkProgressBar(mbox, height=10, corner_radius=4, fg_color=C["line"], progress_color=C["ok"])
        self.meter_master.set(0)
        self.meter_master.pack(fill="x", pady=(6, 0))
        self.clip_hold_until = 0.0

        # Zona inferior: tomas o registro
        self.bottom = ctk.CTkFrame(c, fg_color="transparent", height=210)
        self.bottom.grid(row=4, column=0, sticky="ew", padx=22, pady=(14, 14))
        self.bottom.grid_propagate(False)
        self.bottom.grid_columnconfigure(0, weight=1)
        self.bottom.grid_rowconfigure(0, weight=1)
        self._build_takes_panel()
        self._build_log_panel()

    def _build_takes_panel(self):
        p = ctk.CTkFrame(self.bottom, fg_color="transparent")
        p.grid(row=0, column=0, sticky="nsew")
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(2, weight=1)
        head = ctk.CTkFrame(p, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        self._section_label(head, t("ui.main.tomas_recientes")).pack(side="left")
        self._ghost_button(head, t("action.open_folder"), self.open_recordings_folder, height=28).pack(side="right")

        self.saved_banner = ctk.CTkFrame(p, fg_color=C["ok_bg"], corner_radius=9, border_width=1, border_color=C["ok_line"])
        self.saved_lbl = ctk.CTkLabel(self.saved_banner, text="", font=self.F(13), text_color=C["ok_text"], anchor="w")
        self.saved_lbl.pack(side="left", padx=12, pady=8, fill="x", expand=True)
        # Accesos directos a la última toma: lo primero que se quiere hacer al terminar
        for attr, key in (("saved_btn", "action.summary"), ("saved_reveal", "action.reveal"), ("saved_play", "action.play")):
            b = ctk.CTkButton(self.saved_banner, text=t(key), width=90, height=28, fg_color="transparent",
                              hover_color=C["ok_line"], text_color="#7FDCA9", font=self.F(13, "bold"))
            b.pack(side="right", padx=(0, 6))
            setattr(self, attr, b)

        self.takes_list = ctk.CTkScrollableFrame(p, fg_color="transparent", scrollbar_button_color=C["raised"])
        self.takes_list.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        self.takes_list.grid_columnconfigure(0, weight=1)
        self.takes_panel = p

    def _build_log_panel(self):
        p = ctk.CTkFrame(self.bottom, fg_color="#141416", corner_radius=12, border_width=1, border_color=C["line2"])
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(p, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        ctk.CTkLabel(head, text=t("ui.main.registro_y_diagnostico"), font=self.F(13, "bold"), text_color=C["text"]).pack(side="left")
        ctk.CTkButton(head, text=ICON["close"], font=self.IF(12), width=30, height=28, fg_color="transparent",
                      hover_color=C["raised"], text_color=C["muted"], command=self.toggle_log).pack(side="right")
        self._outline_button(head, t("ui.main.reportar_un_problema"), self.show_report_dialog, height=28, width=150).pack(side="right", padx=4)
        self._outline_button(head, t("ui.main.copiar"), self.copy_logs_to_clipboard, height=28, width=70).pack(side="right", padx=4)
        self.console = ctk.CTkTextbox(p, font=self.F(12, mono=True), fg_color="transparent", text_color=C["text2"], wrap="none")
        self.console.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.log_panel = p

    # ----------------------------- PANEL DERECHO ------------------------------
    def _build_inspector(self):
        """Lo básico a mano: formato de la cámara y el mezclador. Todo lo demás en Configuración."""
        ins = self.inspector
        ins.grid_columnconfigure(0, weight=1)
        ins.grid_rowconfigure(1, weight=1)

        cam = ctk.CTkFrame(ins, fg_color="transparent")
        cam.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 6))
        cam.grid_columnconfigure(0, weight=1)
        h = ctk.CTkFrame(cam, fg_color="transparent")
        h.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._section_label(h, t("ui.main.camara")).pack(side="left")
        self._ghost_button(h, t("ui.main.mas_ajustes"), lambda: self.open_settings("video"), height=26).pack(side="right")
        self.menu_res = self._option_menu(cam, ["—"], self._on_res_change)
        self.menu_res.grid(row=1, column=0, sticky="ew")
        self.seg_fps = self._segmented(cam, [(24, "24"), (30, "30"), (60, "60")], 30, self._on_fps_pick,
                                       font=self.F(12, "bold", mono=True), height=28)
        self.seg_fps.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.lbl_fps_note = ctk.CTkLabel(cam, text="", font=self.F(11), text_color=C["faint"], anchor="w")
        self.lbl_fps_note.grid(row=3, column=0, sticky="ew")
        self.lens_menu = self._option_menu(cam, ["—"], self._on_lens_change)

        # Girar la imagen: manual y solo para teléfonos por cable (lo hace el teléfono)
        self.rot_box = ctk.CTkFrame(cam, fg_color="transparent")
        self.rot_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.rot_box, text=t("ui.main.girar_imagen"), font=self.F(12), text_color=C["text2"],
                     anchor="w").grid(row=0, column=0, sticky="ew")
        self.seg_rot = self._segmented(self.rot_box, [(0, t("ui.main.sin_girar")), (90, "90°"), (180, "180°"), (270, "270°")],
                                       0, self._on_rot_pick, font=self.F(12, "bold"), height=28)
        self.seg_rot.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.lbl_rot_note = ctk.CTkLabel(self.rot_box, text="", font=self.F(11), text_color=C["faint"], anchor="w",
                                         wraplength=250, justify="left")
        self.lbl_rot_note.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        # Formato de la toma: horizontal, o vertical 9:16 para redes (sin recortar después)
        self.fmt_box = ctk.CTkFrame(cam, fg_color="transparent")
        self.fmt_box.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        self.fmt_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.fmt_box, text=t("format.label"), font=self.F(12), text_color=C["text2"],
                     anchor="w").grid(row=0, column=0, sticky="ew")
        self.seg_orient = self._segmented(self.fmt_box, [("h", t("format.horizontal")), ("v", t("format.vertical"))],
                                          "h", self._on_orient_pick, font=self.F(12, "bold"), height=28)
        self.seg_orient.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.seg_vmode = self._segmented(self.fmt_box, [("crop", t("vertical.mode.crop")), ("cw", t("vertical.mode.cw")),
                                                        ("ccw", t("vertical.mode.ccw"))],
                                         "crop", self._on_vmode_pick, font=self.F(12, "bold"), height=28)
        self.lbl_fmt_note = ctk.CTkLabel(self.fmt_box, text="", font=self.F(11), text_color=C["faint"], anchor="w",
                                         wraplength=250, justify="left")
        self.lbl_fmt_note.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        mix = ctk.CTkFrame(ins, fg_color="transparent")
        mix.grid(row=1, column=0, sticky="nsew", padx=(10, 6), pady=(6, 0))
        mix.grid_columnconfigure(0, weight=1)
        mix.grid_rowconfigure(1, weight=1)
        mh = ctk.CTkFrame(mix, fg_color="transparent")
        mh.grid(row=0, column=0, sticky="ew", padx=(6, 6), pady=(4, 6))
        self._section_label(mh, t("ui.main.mezclador")).pack(side="left")
        self._ghost_button(mh, t("ui.main.audio"), lambda: self.open_settings("audio"), height=26).pack(side="right")
        self._ghost_button(mh, t("ui.main.canal"), self._quick_add_channel, height=26).pack(side="right")
        self.strips_box = ctk.CTkScrollableFrame(mix, fg_color="transparent", scrollbar_button_color=C["raised"])
        self.strips_box.grid(row=1, column=0, sticky="nsew")
        self.strips_box.grid_columnconfigure(0, weight=1)

        mon = ctk.CTkFrame(ins, fg_color=C["panel"], corner_radius=10)
        mon.grid(row=2, column=0, sticky="ew", padx=14, pady=(8, 6))
        mon.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mon, text=t("ui.main.monitor"), font=self.F(12, "bold"), text_color=C["text"]).grid(row=0, column=0, padx=(12, 8), pady=(8, 0), sticky="w")
        self.lbl_mon_db = ctk.CTkLabel(mon, text="", font=self.F(11, mono=True), text_color=C["muted"])
        self.lbl_mon_db.grid(row=0, column=2, padx=(0, 12), pady=(8, 0), sticky="e")
        self.meter_monitor = ctk.CTkProgressBar(mon, height=5, corner_radius=3, fg_color=C["line"], progress_color=C["ok"])
        self.meter_monitor.set(0)
        self.meter_monitor.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 2))
        self.slider_monitor = ctk.CTkSlider(mon, from_=0, to=1.5, number_of_steps=150, height=14, fg_color=C["line"],
                                            progress_color=C["text2"], button_color=C["text"], button_hover_color="#FFFFFF",
                                            command=self._on_monitor_volume)
        self.slider_monitor.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=(2, 8))
        self.slider_monitor.set(float(self.audio_engine.config.get("monitor_volume", 1.0)))
        self._on_monitor_volume(self.slider_monitor.get(), save=False)

        self.lbl_audio_status = ctk.CTkButton(ins, text=t("ui.main.audio_iniciando"), font=self.F(11), height=26, anchor="w",
                                              fg_color="transparent", hover_color=C["raised"], text_color=C["muted"],
                                              command=lambda: self.open_settings("audio"))
        self.lbl_audio_status.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))

    def _field_label(self, master, text):
        return ctk.CTkLabel(master, text=text, font=self.F(12), text_color=C["muted"], anchor="w")

    def _option_menu(self, master, values, command, **kw):
        return ctk.CTkOptionMenu(master, values=values, command=command, height=34, corner_radius=8, dynamic_resizing=False,
                                 fg_color=C["raised"], button_color=C["raised"], button_hover_color=C["line2"],
                                 text_color=C["text"], dropdown_fg_color=C["panel"], dropdown_hover_color=C["raised"],
                                 dropdown_text_color=C["text"], font=self.F(13), dropdown_font=self.F(13), **kw)

    # ---- Secciones de Configuración que viven en la app (las usa settings_window) ----
    def _alive(self, w) -> bool:
        try:
            return bool(w and w.winfo_exists())
        except (AttributeError, RuntimeError):
            return False

    def build_video_settings(self, parent, wrap=560):
        pad = {"padx": 4}
        # Cámara seleccionada
        self.dev_card = ctk.CTkFrame(parent, fg_color=C["panel"], corner_radius=12, border_width=1, border_color=C["line"])
        self.dev_card.grid(row=0, column=0, sticky="ew", pady=(0, 20), **pad)
        self.dev_card.grid_columnconfigure(0, weight=1)
        dh = ctk.CTkFrame(self.dev_card, fg_color="transparent")
        dh.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        self._section_label(dh, t("ui.main.camara_seleccionada")).pack(side="left")
        self.dev_kind_tag = ctk.CTkLabel(dh, text="", font=self.F(10, "bold"), fg_color="#2C2C31", text_color=C["text2"],
                                         corner_radius=4, height=18)
        self.dev_kind_tag.pack(side="right")
        self.dev_body = ctk.CTkFrame(self.dev_card, fg_color="transparent")
        self.dev_body.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.dev_body.grid_columnconfigure(0, weight=1)
        self._render_device_card()

        # Estilo rápido
        self._section_label(parent, t("ui.main.estilo_rapido")).grid(row=7, column=0, sticky="ew", pady=(0, 8), **pad)
        pg = ctk.CTkFrame(parent, fg_color="transparent")
        pg.grid(row=8, column=0, sticky="ew", **pad)
        pg.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="p")
        self.preset_buttons = {}
        for i, (pid, label, sub) in enumerate(PRESETS):
            b = ctk.CTkButton(pg, text=f"{label}\n{sub}", height=54, corner_radius=10, anchor="w", border_width=1,
                              font=self.F(12), text_color=C["text"], text_color_disabled=C["off"],
                              command=lambda p=pid: self._apply_preset(p))
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0), pady=4)
            self.preset_buttons[pid] = b
        self.music_tip = ctk.CTkLabel(parent, text=t("ui.main.para_que_la_camara_no"),
                                      font=self.F(12), text_color=C["accent_text"], fg_color=C["accent_bg"], corner_radius=9,
                                      wraplength=wrap, justify="left", anchor="w")
        self._paint_presets()

        # Imagen
        self.image_box = ctk.CTkFrame(parent, fg_color="transparent")
        self.image_box.grid(row=10, column=0, sticky="ew", pady=(18, 10), **pad)
        self.image_box.grid_columnconfigure(0, weight=1)
        ih = ctk.CTkFrame(self.image_box, fg_color="transparent")
        ih.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._section_label(ih, t("ui.main.imagen")).pack(side="left")
        self._ghost_button(ih, t("ui.main.restablecer"), self.reset_image, height=28).pack(side="right")
        self.sliders = {}
        specs = [("brightness", t("ui.main.brillo"), -0.5, 0.5, 100), ("contrast", t("ui.main.contraste"), 0.5, 2.0, 60),
                 ("saturation", t("ui.main.saturacion"), 0.0, 2.0, 80), ("sharpness", t("ui.main.nitidez"), 0.0, 5.0, 50)]
        for i, (key, label, lo, hi, steps) in enumerate(specs):
            row = ctk.CTkFrame(self.image_box, fg_color="transparent")
            row.grid(row=1 + i, column=0, sticky="ew", pady=5)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=label, font=self.F(13), text_color=C["text"], anchor="w").grid(row=0, column=0, sticky="w")
            val = ctk.CTkLabel(row, text="", font=self.F(12, mono=True), text_color=C["muted"])
            val.grid(row=0, column=1, sticky="e")
            s = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=steps, height=16, fg_color=C["line"],
                              progress_color=C["accent"], button_color=C["text"], button_hover_color="#FFFFFF",
                              command=lambda v, k=key: self._on_image_slider(k, v))
            s.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            self.sliders[key] = (s, val)
        self._sync_sliders()
        self.lbl_saved_for = ctk.CTkLabel(self.image_box, text="", font=self.F(12), text_color=C["faint"], anchor="w")
        self.lbl_saved_for.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        self.image_note = ctk.CTkLabel(parent, text=t("ui.main.los_ajustes_de_imagen_se"),
                                       font=self.F(12), text_color=C["faint"], wraplength=wrap, justify="left", anchor="w")

        # Calidad del teléfono Android
        self._section_label(parent, t("ui.main.calidad_del_telefono_android")).grid(row=12, column=0, sticky="ew", pady=(18, 8), **pad)
        q = ctk.CTkFrame(parent, fg_color="transparent")
        q.grid(row=13, column=0, sticky="ew", **pad)
        q.grid_columnconfigure((0, 1), weight=1, uniform="q")
        self._field_label(q, t("ui.main.codec")).grid(row=0, column=0, sticky="ew")
        self._field_label(q, t("ui.main.calidad_mbps")).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        codecs = [("h265", t("ui.main.h_265_mejor")), ("h264", t("ui.main.h_264_compatible"))]
        seg_c = self._segmented(q, codecs, self.video_cfg.get("android_codec", "h265"),
                                lambda v: self._set_video_opt("android_codec", v, seg_c), font=self.F(12, "bold"))
        seg_c.grid(row=1, column=0, sticky="ew", pady=4)
        rates = [("20M", "20"), ("50M", "50"), ("80M", "80")]
        seg_b = self._segmented(q, rates, self.video_cfg.get("android_bitrate", "50M"),
                                lambda v: self._set_video_opt("android_bitrate", v, seg_b), font=self.F(12, "bold", mono=True))
        seg_b.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)
        ctk.CTkLabel(parent, text=t("ui.main.mas_mbps_mas_detalle_y"),
                     font=self.F(12), text_color=C["faint"], wraplength=wrap, justify="left",
                     anchor="w").grid(row=14, column=0, sticky="ew", pady=(4, 0), **pad)
        self._render_format()

    def _set_video_opt(self, key, value, seg):
        self.video_cfg[key] = value
        seg.paint(value)
        self._save_settings()
        s = self._selected()
        if s and s.kind == "android" and self.rec_state == "idle":
            self._settings_changed()

    def _checkbox(self, master, text, var):
        return ctk.CTkCheckBox(master, text=text, variable=var, font=self.F(13), text_color=C["text"],
                               fg_color=C["accent"], hover_color=C["accent"], checkmark_color="#1A1408",
                               border_color=C["line2"], checkbox_width=18, checkbox_height=18, corner_radius=4,
                               command=self._save_settings)

    def build_recording_settings(self, parent, wrap=560):
        pad = {"padx": 4}
        self._section_label(parent, t("ui.main.archivo")).grid(row=0, column=0, sticky="ew", pady=(0, 8), **pad)
        self._field_label(parent, t("ui.main.nombre_de_la_sesion")).grid(row=1, column=0, sticky="ew", **pad)
        e = ctk.CTkEntry(parent, textvariable=self.record_prefix_var, height=34, corner_radius=8, fg_color=C["raised"],
                         border_color=C["line2"], text_color=C["text"], font=self.F(13))
        e.grid(row=2, column=0, sticky="ew", pady=(4, 12), **pad)
        e.bind("<FocusOut>", lambda _e: self._save_settings())
        self._field_label(parent, t("ui.main.carpeta")).grid(row=3, column=0, sticky="ew", **pad)
        fr = ctk.CTkFrame(parent, fg_color="transparent")
        fr.grid(row=4, column=0, sticky="ew", pady=(4, 20), **pad)
        fr.grid_columnconfigure(0, weight=1)
        self.lbl_dir = ctk.CTkLabel(fr, text="", font=self.F(12, mono=True), text_color=C["text2"], fg_color=C["raised"],
                                    corner_radius=8, height=34, anchor="w")
        self.lbl_dir.grid(row=0, column=0, sticky="ew")
        self._outline_button(fr, t("ui.main.cambiar"), self._pick_dir, height=34, width=90).grid(row=0, column=1, padx=(8, 0))
        self._paint_dir()

        self._section_label(parent, t("ui.main.volumen_final")).grid(row=5, column=0, sticky="ew", pady=(0, 8), **pad)
        self.norm_buttons = {}
        nb = ctk.CTkFrame(parent, fg_color="transparent")
        nb.grid(row=6, column=0, sticky="ew", **pad)
        nb.grid_columnconfigure((0, 1, 2), weight=1, uniform="n")
        for i, (key, title, sub) in enumerate(NORM_OPTIONS):
            b = ctk.CTkButton(nb, text=f"{title}\n{sub}", height=56, corner_radius=10, anchor="w", border_width=1,
                              font=self.F(12), text_color=C["text"], command=lambda k=key: self._pick_norm(k))
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
            self.norm_buttons[key] = b
        self._paint_norm()

        self._section_label(parent, t("ui.main.pistas")).grid(row=7, column=0, sticky="ew", pady=(20, 8), **pad)
        self._checkbox(parent, t("ui.main.guardar_cada_canal_del_mezclador"), self.opt_multitrack).grid(
            row=8, column=0, sticky="ew", **pad)
        ctk.CTkLabel(parent, text=t("ui.main.pista_1_la_mezcla_final"),
                     font=self.F(12), text_color=C["faint"], wraplength=wrap, justify="left",
                     anchor="w").grid(row=9, column=0, sticky="ew", padx=(32, 4), pady=(2, 0))

        self._section_label(parent, t("ui.main.sincronia_audio_video")).grid(row=10, column=0, sticky="ew", pady=(20, 8), **pad)
        sr = ctk.CTkFrame(parent, fg_color="transparent")
        sr.grid(row=11, column=0, sticky="ew", **pad)
        ctk.CTkLabel(sr, text=t("ui.main.adelantar_o_retrasar_el_audio"), font=self.F(13), text_color=C["text"]).pack(side="left")
        self.lbl_sync = ctk.CTkLabel(sr, text="", font=self.F(12, mono=True), text_color=C["muted"])
        self.lbl_sync.pack(side="right")
        self.slider_sync = ctk.CTkSlider(parent, from_=-300, to=300, number_of_steps=60, height=16, fg_color=C["line"],
                                         progress_color=C["accent"], button_color=C["text"], button_hover_color="#FFFFFF",
                                         command=self._on_sync)
        self.slider_sync.set(self.sync_ms)
        self.slider_sync.grid(row=12, column=0, sticky="ew", pady=(6, 20), **pad)
        self._on_sync(self.sync_ms, save=False)

        self._section_label(parent, t("ui.main.al_terminar_de_grabar")).grid(row=13, column=0, sticky="ew", pady=(0, 8), **pad)
        for i, (text, var) in enumerate([(t("ui.main.guardar_tambien_cada_canal_como"), self.opt_stems),
                                         (t("ui.main.mostrar_el_archivo_en_el"), self.opt_reveal),
                                         (t("ui.main.reproducirlo_automaticamente"), self.opt_autoplay),
                                         (t("ui.main.mostrar_el_resumen_de_la"), self.opt_summary)]):
            self._checkbox(parent, text, var).grid(row=14 + i, column=0, sticky="ew", pady=5, **pad)

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

    # =========================================================================
    # DETECCIÓN UNIFICADA DE CÁMARAS (sin modos de plataforma)
    # =========================================================================
    def _force_rescan(self):
        self.engine.cached_pc_cameras = []
        self.last_dshow_scan = 0
        self.scan_force.set()
        self.notify.status(t("scan.searching"))

    def _reconnect_wifi_phones(self, first_pass: bool):
        """Reconecta sin cable los teléfonos que ya estuvieron por Wi‑Fi: al abrir la app, los
        recordados; después, cada 10 s, el que está «Desconectado» esperando volver."""
        if not self.engine.adb_path:
            return
        if first_pass:
            targets = list(self.settings.get("wifi_endpoints", {}).values())
        elif time.time() - getattr(self, "_last_wifi_retry", 0) >= 10:
            self._last_wifi_retry = time.time()
            targets = [s.serial for s in list(self.sources) if s.waiting and s.is_wifi and s.serial]
        else:
            return
        for endpoint in targets:
            if self.engine.connect_wifi(endpoint, timeout=3):
                self._on_engine_log(f"Reconectado por Wi‑Fi: {endpoint}", "WIFI")

    def _scan_loop(self):
        dshow_cache: List[Dict] = []
        first_pass = True
        while self.running:
            try:
                self._reconnect_wifi_phones(first_pass)
                first_pass = False
                now = time.time()
                if now - self.last_dshow_scan > 10 or not dshow_cache:
                    if self.rec_state == "idle":
                        dshow_cache = self.engine.get_pc_cameras(force_refresh=True)
                        self.last_dshow_scan = now
                adb = self.engine.check_device_changes(log_pings=False) if self.engine.adb_path else []
                srcs = self._build_sources(dshow_cache, adb)
                self._ui(lambda s=srcs: self._apply_sources(s))
                problem = self.engine.scanner.adb_problem
                apps = (self.engine.scanner.other_adb_programs(self.engine.adb_path)
                        if problem in ("conflict", "timeout") else [])
                self._ui(lambda p=problem, a=apps: self._show_adb_problem(p, a))
            except Exception as e:
                self._on_engine_log(f"Error buscando cámaras: {e}", "ERROR")
            self.scan_force.wait(3.0)
            self.scan_force.clear()

    def _build_sources(self, dshow: List[Dict], adb: List[Dict]) -> List[Source]:
        out: List[Source] = []
        for d in dshow:
            name = d.get("name", "")
            if name == "Webcam Genérica" or is_own_virtual_camera(name):   # marcador del motor / nuestra salida
                continue
            cat = d.get("category", "webcam")
            kind = {"capture_card": "capture", "virtual": "virtual", "ios": "app"}.get(cat, "webcam")
            meta = {"webcam": t("ui.main.webcam_usb"), "capture": t("ui.main.capturadora_hdmi"), "virtual": t("ui.main.camara_virtual_2"),
                    "app": t("ui.main.abre_la_app_del_movil")}[kind]
            caps = self.caps.get(f"dshow:{name}")
            if caps and kind != "app":
                h = caps.get("default_res", "").split("x")[-1]
                meta = f"{h}p · {caps.get('default_fps', 30)} fps" + (t("ui.main.mjpeg") if caps.get("has_mjpeg") else "")
            out.append(Source(id=f"dshow:{name}", kind=kind, name=name, meta=meta, device_name=name))

        for d in adb:
            serial = d["serial"]
            state = d.get("state", "")
            info = self.android_info.get(serial)
            if state == "device" and info is None:
                info = self.engine.get_device_info(serial)
                info["battery"] = self.engine.get_device_battery(serial)
                self.android_info[serial] = info
                saved_cams = self.settings.get("phone_cameras", {}).get(serial)
                if saved_cams:
                    self.lens_by_serial[serial] = saved_cams     # ya se conocen: sin preguntar
                else:
                    self._stream_jobs.submit(self._load_lenses, serial)
            elif state == "device" and info is not None and time.time() - info.get("_bat_t", 0) > 60:
                info["battery"] = self.engine.get_device_battery(serial)
                info["_bat_t"] = time.time()
            name = (info or {}).get("friendly_name") or d.get("model") or t("ui.main.telefono_android")
            conn = t("ui.main.wifi") if d.get("is_wifi") else "USB"
            s = Source(id=f"adb:{serial}", kind="android", name=name, serial=serial, is_wifi=d.get("is_wifi", False),
                       battery=(info or {}).get("battery"))
            if state == "device":
                if info and not info.get("camera_supported", True):
                    s.ready = False
                    s.meta = t("ui.main.necesita_android_12")
                    s.hint_title = t("phone.old_android", name=name, version=info.get('android_version'))
                    s.hint_steps = [t("ui.main.usar_la_camara_del_telefono"),
                                    t("ui.main.alternativa_instala_una_app_de")]
                else:
                    bat = f" · {s.battery} %" if s.battery is not None else ""
                    s.meta = f"{conn}{bat}"
            elif state == "unauthorized":
                s.ready = False
                s.meta = t("ui.main.falta_autorizar")
                s.hint_title = t("ui.main.el_telefono_esta_conectado_pero")
                s.hint_steps = [t("ui.main.desbloquea_el_telefono"),
                                t("ui.main.acepta_el_aviso_permitir_depuracion"),
                                t("ui.main.si_no_aparece_el_aviso")]
            else:
                s.ready = False
                s.meta = t("ui.main.sin_conexion")
                s.hint_title = t("ui.main.el_telefono_dejo_de_responder")
                s.hint_steps = [t("ui.main.desconecta_y_vuelve_a_conectar"),
                                t("ui.main.prueba_otro_puerto_usb_idealmente")]
            out.append(s)
        return out

    def _load_lenses(self, serial):
        """Pide al teléfono sus cámaras (una vez: se guarda). Corre en la cola de la cámara,
        porque dos scrcpy arrancando a la vez se pisan y cortan la vista previa."""
        cams = self.engine.get_device_cameras(serial)
        if serial in self.engine.cached_cameras:          # solo si el teléfono respondió
            self.settings.setdefault("phone_cameras", {})[serial] = cams
            self._ui(self._save_settings)

        def refresh():
            s = self._selected()
            before = self._format_options(s)[3] if s and s.serial == serial else None
            self.lens_by_serial[serial] = cams
            if before is None:
                return
            self._render_device_card()
            self._render_format()
            # La vista previa arrancó antes de conocer la cámara: si pidió unos fps que
            # no da (p. ej. 60 en una que llega a 30), se vuelve a abrir con los buenos.
            if self._format_options(s)[3] != before and self.rec_state == "idle":
                self._settings_changed()
        self._ui(refresh)

    def _apply_sources(self, srcs: List[Source]):
        prev = self._selected()
        prev_ids = {s.id for s in self.sources if not s.waiting}
        # La fuente elegida desapareció (se desconectó el teléfono, el cable…): se queda
        # elegida como «Desconectada» en vez de saltar a otra cámara, y vuelve sola.
        if prev and prev.id not in {s.id for s in srcs}:
            if not prev.waiting:
                self._on_engine_log(t("source.disconnected", name=prev.name), "WARN")
                self.notify.status(t("source.disconnected", name=prev.name), "warn")
                if self.rec_state == "idle":
                    self._stop_preview()
            srcs = srcs + [prev if prev.waiting else waiting_source(prev)]
        sig = json.dumps([(s.id, s.name, s.meta, s.ready) for s in srcs])
        self.sources = srcs
        if sig != self.sources_sig:
            self.sources_sig = sig
            self._render_source_rows()
            new_phone = any(s.kind in ("android", "app") and s.id not in prev_ids and not s.waiting
                            for s in srcs) and prev_ids
            if new_phone and self.connect_dialog is not None:
                self._close_connect_dialog()
                self.notify.toast(t("phone.detected"))

        pending = getattr(self, "_pending_select", None)
        if pending and self.rec_state == "idle" and any(x.id == pending and x.ready for x in srcs):
            self._pending_select = None
            self.select_source(pending)
            return
        now = self._selected()
        if not self.selected_id and srcs and self.rec_state == "idle":
            last = self.settings.get("last_source")
            rank = {"webcam": 0, "capture": 0, "android": 1, "app": 2, "virtual": 3}
            by_pref = sorted(srcs, key=lambda x: (not x.ready, rank.get(x.kind, 4)))
            pick = next((s for s in srcs if s.id == last), None) or by_pref[0]
            self.select_source(pick.id)
        elif self.selected_id:
            self._render_selected_header()
            # Volvió (se reconectó, o se autorizó la depuración USB): se reanuda sola.
            back = prev is not None and not prev.ready and now is not None and now.ready
            if back and self.rec_state == "idle" and not self.camera_paused:
                self._on_engine_log(f"«{now.name}» está de vuelta. Reanudando la imagen…", "INFO")
                self.notify.toast(t("source.back", name=now.name))
                self.select_source(now.id)
            elif self.rec_state == "idle" and not self.engine.is_running:
                self._render_video_state()
        if not srcs:
            self._render_video_state()

    def _render_source_rows(self):
        for w in self.sources_box.winfo_children():
            w.destroy()
        self.source_rows = {}
        if not self.sources:
            ctk.CTkLabel(self.sources_box, text=t("ui.main.no_hay_camaras_conectadas"), font=self.F(12), text_color=C["muted"],
                         anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=8)
            return
        for i, s in enumerate(self.sources):
            row = ctk.CTkFrame(self.sources_box, corner_radius=10, border_width=1, height=60)
            row.grid(row=i, column=0, sticky="ew", padx=4, pady=3)
            row.grid_columnconfigure(1, weight=1)
            icon = {"webcam": ICON["camera"], "capture": ICON["hdmi"], "virtual": ICON["virtual"],
                    "app": ICON["phone"], "android": ICON["phone"]}[s.kind]
            ib = ctk.CTkLabel(row, text=icon, font=self.IF(17), width=38, height=38, corner_radius=9,
                              fg_color=C["raised"], text_color=C["text2"])
            ib.grid(row=0, column=0, rowspan=2, padx=(10, 12), pady=10)
            nm = ctk.CTkLabel(row, text=s.name if len(s.name) < 26 else s.name[:24] + "…", font=self.F(14, "bold"),
                              text_color=C["text"], anchor="w")
            nm.grid(row=0, column=1, sticky="sw", pady=(10, 0))
            meta = ctk.CTkFrame(row, fg_color="transparent")
            meta.grid(row=1, column=1, sticky="nw", pady=(1, 10))
            tag = ctk.CTkLabel(meta, text=KIND_LABEL[s.kind], font=self.F(9, "bold"), fg_color="#2C2C31",
                               text_color=C["text2"], corner_radius=4, height=16)
            tag.pack(side="left", padx=(0, 6))
            mt = ctk.CTkLabel(meta, text=s.meta if len(s.meta) <= 24 else s.meta[:23] + "…", font=self.F(12), text_color=C["muted"] if s.ready else C["warn"])
            mt.pack(side="left")
            dot = ctk.CTkLabel(row, text="●", font=self.F(9), text_color=C["ok"] if s.ready else C["warn"])
            dot.grid(row=0, column=2, rowspan=2, padx=(4, 12))
            widgets = [row, ib, nm, meta, tag, mt, dot]
            for w in widgets:
                w.bind("<Button-1>", lambda _e, sid=s.id: self._on_row_click(sid))
                w.bind("<Enter>", lambda _e, sid=s.id: self._hover_row(sid, True))
                w.bind("<Leave>", lambda _e, sid=s.id: self._hover_row(sid, False))
                try:
                    w.configure(cursor="hand2")
                except (ctk.CTkError, AttributeError):
                    pass
            self.source_rows[s.id] = {"frame": row}
        self._paint_rows()

    def _paint_rows(self):
        for sid, r in self.source_rows.items():
            on = sid == self.selected_id
            r["frame"].configure(fg_color=C["raised"] if on else "transparent",
                                 border_color=C["accent"] if on else C["rail"])

    def _hover_row(self, sid, inside):
        r = self.source_rows.get(sid)
        if r and sid != self.selected_id:
            r["frame"].configure(fg_color=C["panel"] if inside else "transparent")

    def _on_row_click(self, sid):
        if sid == self.selected_id:
            return
        if self.rec_state != "idle":
            self.notify.toast(t("source.locked_while_recording"), "warn")
            return
        self.select_source(sid)

    def _selected(self) -> Optional[Source]:
        return next((s for s in self.sources if s.id == self.selected_id), None)

    # =========================================================================
    # SELECCIÓN DE CÁMARA Y VISTA PREVIA AUTOMÁTICA
    # =========================================================================
    def _hold_vcam(self):
        """Cambio pedido por el usuario: «UltraCam» mantiene el último cuadro hasta que
        llega la imagen nueva (como mucho 5 s) en vez de parpadear con «Sin señal».
        No se usa al pausar ni si la fuente se desconectó: ahí el cartel es lo correcto."""
        if self.engine.is_running and self._vcam_on():
            virtualcam.SERVICE.hold_last_frame(5.0)

    def select_source(self, sid):
        self._hold_vcam()
        self._stop_preview()
        self.selected_id = sid
        self._stream_retries = 0
        self.settings["last_source"] = sid
        self._save_settings()
        self.preset = None
        # Al elegir otra cámara deja de esperarse la que estaba «Desconectada».
        if any(x.waiting and x.id != sid for x in self.sources):
            self.sources = [x for x in self.sources if not x.waiting or x.id == sid]
            self.sources_sig = ""
            self._render_source_rows()
        self._paint_rows()
        self._render_selected_header()
        self._render_device_card()
        self.vcam_state = {"status": "off", "message": ""}
        self._paint_vcam()
        s = self._selected()
        if not s:
            return
        # Ajustes de imagen guardados para esta cámara
        saved = self.engine.load_camera_preset(self._preset_key(s))
        self.image = {k: float(saved.get(k, d)) for k, d in (("brightness", 0.0), ("contrast", 1.0), ("saturation", 1.0), ("sharpness", 0.0))}
        self._sync_sliders()
        self._paint_presets()
        keys = [k for k in ("size", "fps", "rotation", "vertical", "lens") if k in saved]
        if keys:
            self.fmt_by_src.setdefault(sid, {}).update({k: saved[k] for k in keys})

        if s.is_dshow and sid not in self.caps:
            self._set_video_message(t("video.probing.title"), t("video.probing.body"), icon="camera")
            threading.Thread(target=self._probe_then_start, args=(s,), daemon=True).start()
        else:
            self._render_format()
            self._start_preview()

    def _probe_then_start(self, s: Source):
        caps = self.engine.probe_camera_capabilities(s.device_name)
        self.caps[s.id] = caps

        def done():
            if self.selected_id != s.id:
                return
            self._render_device_card()
            self._render_format()
            self._start_preview()
        self._ui(done)

    def _format_options(self, s: Source):
        """Devuelve (resoluciones, fps disponibles, fps elegidos, resolución elegida)."""
        if s.kind == "android":
            res_list = ANDROID_RES
            cam_fps = (self._lens_camera(s) or {}).get("fps")
            fps_avail = [f for f in (24, 30, 60) if f in cam_fps] if cam_fps else [24, 30, 60]
            fps_avail = fps_avail or [30]
            def_res, def_fps = "1920x1080", 30
        else:
            caps = self.caps.get(s.id, {})
            res_list = caps.get("resolutions") or ["1920x1080", "1280x720"]
            fps_avail = caps.get("framerates") or [30]
            def_res = caps.get("default_res", res_list[0])
            def_fps = 30 if 30 in fps_avail else fps_avail[0]
        chosen = self.fmt_by_src.get(s.id, {})
        size = chosen.get("size") if chosen.get("size") in res_list else def_res
        fps = chosen.get("fps") if chosen.get("fps") in fps_avail else def_fps
        return res_list, fps_avail, size, fps

    def _render_format(self):
        s = self._selected()
        if not s:
            return
        res_list, fps_avail, size, fps = self._format_options(s)
        self.menu_res.configure(values=[fmt_res(r) for r in res_list])
        self.menu_res.set(fmt_res(size))
        disabled = [f for f in (24, 30, 60) if f not in fps_avail]
        self.seg_fps.paint(fps, disabled)
        self.lbl_fps_note.configure(text=t("ui.main.esta_camara_no_ofrece_60") if 60 in disabled else "")
        if s.kind == "android" and s.ready:
            options = self._lens_options(s)
            self._lens_map = dict(options)
            self.lens_menu.configure(values=[lab for lab, _ in options])
            self.lens_menu.set(self._lens_label(s, options))
            self.lens_menu.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        else:
            self.lens_menu.grid_remove()
        # Girar solo tiene sentido —y solo es posible— en teléfonos conectados por cable:
        # en las webcams y capturadoras la imagen llega ya fija desde el dispositivo.
        if s.kind == "android" and s.ready:
            self.seg_rot.paint(self._rotation(s))
            self.lbl_rot_note.configure(
                text=t("ui.main.90_gira_a_la_derecha"))
            self.rot_box.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        else:
            self.rot_box.grid_remove()
        self._render_orientation(s, size)
        # Controles que solo existen con Configuración › Video abierta
        if self.preset_buttons and self._alive(self.preset_buttons.get("fluid")):
            self.preset_buttons["fluid"].configure(state="disabled" if 60 in disabled else "normal")
        if self._alive(self.image_box):
            if s.kind == "android":
                self.image_box.grid_remove()
                self.image_note.grid(row=10, column=0, sticky="ew", padx=4, pady=(18, 10))
            else:
                self.image_note.grid_remove()
                self.image_box.grid()
                self.lbl_saved_for.configure(text=t("image.saved_for", name=s.name))

    def _lens_options(self, s) -> List[Tuple[str, Dict]]:
        """Objetivos del teléfono como (texto, {"id", "facing", "zoom"}). En la primera
        cámara trasera se ofrecen saltos de zoom: el teléfono cambia de objetivo solo
        (0.6× gran angular, 3× / 10× tele en los que los tienen)."""
        cams = [c for c in self.lens_by_serial.get(s.serial, []) if c.get("id") != "auto"]
        if not cams:
            return [(t("lens.back"), {"id": None, "facing": "back", "zoom": None}),
                    (t("lens.front"), {"id": None, "facing": "front", "zoom": None})]
        out, seen = [], {}
        for c in cams:
            facing = c.get("facing", "back")
            seen[facing] = seen.get(facing, 0) + 1
            base = {"id": c["id"], "facing": facing}
            if seen[facing] > 1:
                orient = t("ui.main.trasera") if facing == "back" else t("ui.main.frontal")
                out.append((t("lens.other", orient=orient, n=seen[facing], id=c["id"]), dict(base, zoom=None)))
            elif facing == "back" and c.get("zoom_max"):
                zmin, zmax = c.get("zoom_min", 1.0), c["zoom_max"]
                if zmin < 0.99:
                    out.append((t("lens.wide", z=f"{zmin:g}"), dict(base, zoom=zmin)))
                out.append((t("lens.main"), dict(base, zoom=None)))
                out += [(t("lens.zoom", z=z), dict(base, zoom=float(z))) for z in (2, 3, 5, 10) if z <= zmax]
            else:
                out.append((t("lens.back") if facing == "back" else t("lens.front"), dict(base, zoom=None)))
        return out

    def _lens_label(self, s, options) -> str:
        """Texto del objetivo elegido; sin elegir, la cámara trasera principal a 1×."""
        cur = self.fmt_by_src.get(s.id, {}).get("lens")
        if isinstance(cur, dict):
            for lab, o in options:
                if (o["id"], o["facing"], o["zoom"]) == (cur.get("id"), cur.get("facing"), cur.get("zoom")):
                    return lab
        for lab, o in options:
            if o["facing"] == "back" and not o["zoom"]:
                return lab
        return options[0][0]

    def _lens_camera(self, s) -> Optional[Dict]:
        """Lo que informó el teléfono (fps, zoom) de la cámara del objetivo elegido."""
        cams = [c for c in self.lens_by_serial.get(s.serial, []) if c.get("id") != "auto"]
        cur = self.fmt_by_src.get(s.id, {}).get("lens")
        if isinstance(cur, dict) and cur.get("id") is not None:
            return next((c for c in cams if c["id"] == cur["id"]), None)
        facing = cur.get("facing", "back") if isinstance(cur, dict) else "back"
        return next((c for c in cams if c.get("facing") == facing), None)

    def _render_selected_header(self):
        s = self._selected()
        if not s:
            self._update_transport()
            self.lbl_src_name.configure(text=t("ui.main.sin_camara"))
            self.lbl_src_kind.configure(text=t("ui.main.elige_una_camara_en_la"))
            self._paint_mode_badge()
            return
        self._update_transport()
        self.lbl_src_name.configure(text=s.name)
        extra = f" · {s.meta}" if s.meta else ""
        self.lbl_src_kind.configure(text=f"{KIND_LONG[s.kind]}{extra}")

    def _render_device_card(self):
        if not self._alive(self.dev_body):
            return
        for w in self.dev_body.winfo_children():
            w.destroy()
        s = self._selected()
        if not s:
            self.dev_kind_tag.configure(text="")
            ctk.CTkLabel(self.dev_body, text=t("ui.main.elige_una_camara_para_ver"), font=self.F(13),
                         text_color=C["muted"], anchor="w").grid(row=0, column=0, sticky="ew")
            return
        self.dev_kind_tag.configure(text=f"  {KIND_LABEL[s.kind]}  ")
        b = self.dev_body

        def note(text, row, color=None):
            ctk.CTkLabel(b, text=text, font=self.F(12), text_color=color or C["faint"], wraplength=280, justify="left",
                         anchor="w").grid(row=row, column=0, sticky="ew", pady=(0, 6))

        if s.kind in ("webcam", "capture", "virtual"):
            caps = self.caps.get(s.id, {})
            codec = t("ui.main.mjpeg_por_hardware") if caps.get("has_mjpeg") else t("ui.main.formato_sin_comprimir")
            txt = {"webcam": t("device.usb_codec", codec=codec),
                   "capture": t("ui.main.capturadora_hdmi_el_enfoque_lo"),
                   "virtual": t("ui.main.imagen_que_envia_otro_programa")}[s.kind]
            note(txt, 0, C["text2"])
            if s.kind != "virtual":
                self._outline_button(b, t("ui.main.enfoque_exposicion_y_balance"), self._open_hardware_dialog, height=38).grid(
                    row=1, column=0, sticky="ew", pady=(4, 8))
                note(t("ui.main.abre_el_panel_del_fabricante"), 2)
        elif s.kind == "app":
            note(t("device.app_source", name=s.name), 0, C["text2"])
            note(t("ui.main.si_ves_una_imagen_de"), 1)
            self._outline_button(b, t("ui.main.como_conectar_un_telefono"), self._open_connect_dialog, height=36).grid(row=2, column=0, sticky="ew", pady=(4, 0))
        elif s.kind == "android":
            if not s.ready:
                ctk.CTkLabel(b, text=f"●  {s.meta}", font=self.F(13), text_color=C["warn"], anchor="w").grid(row=0, column=0, sticky="ew", pady=(0, 6))
                note(t("ui.main.sigue_los_pasos_que_aparecen"), 1)
                return
            stats = ctk.CTkFrame(b, fg_color="transparent")
            stats.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            stats.grid_columnconfigure((0, 1), weight=1, uniform="st")
            for i, (k, v, mono) in enumerate([(t("ui.main.bateria"), f"{s.battery} %" if s.battery is not None else "—", True),
                                               (t("ui.main.enlace"), t("ui.main.wifi") if s.is_wifi else "USB", False)]):
                cell = ctk.CTkFrame(stats, fg_color=C["raised"], corner_radius=9)
                cell.grid(row=0, column=i, sticky="ew", padx=(0, 4) if i == 0 else (4, 0))
                ctk.CTkLabel(cell, text=k, font=self.F(11), text_color=C["muted"], anchor="w").pack(anchor="w", padx=10, pady=(8, 0))
                ctk.CTkLabel(cell, text=v, font=self.F(15, mono=mono), text_color=C["text"], anchor="w").pack(anchor="w", padx=10, pady=(0, 8))
            note(t("ui.main.la_lente_la_resolucion_y"), 1)
            self._outline_button(b, t("ui.main.pasar_a_wifi_sin_cable") if not s.is_wifi else t("ui.main.conectado_por_wifi"),
                                 self.activate_wireless_mode, height=36,
                                 state="normal" if not s.is_wifi else "disabled").grid(row=3, column=0, sticky="ew", pady=(0, 6))
            self.btn_speed = self._outline_button(b, t("ui.main.probar_velocidad_del_cable"), self.run_speed_test, height=36)
            self.btn_speed.grid(row=4, column=0, sticky="ew")
            self.lbl_speed = ctk.CTkLabel(b, text="", font=self.F(12), text_color=C["muted"], wraplength=280, justify="left", anchor="w")
            self.lbl_speed.grid(row=5, column=0, sticky="ew", pady=(6, 0))

    # ---- Cambios de formato / imagen ----
    def _on_res_change(self, label):
        s = self._selected()
        if not s:
            return
        self.fmt_by_src.setdefault(s.id, {})["size"] = label.replace(" × ", "x")
        self.preset = None
        self._paint_presets()
        self._settings_changed()

    def _on_fps_pick(self, fps):
        s = self._selected()
        if not s:
            return
        self.fmt_by_src.setdefault(s.id, {})["fps"] = fps
        self.seg_fps.paint(fps, [f for f in (24, 30, 60) if f not in self._format_options(s)[1]])
        self.preset = None
        self._paint_presets()
        self._settings_changed()

    @staticmethod
    def _preset_key(s) -> str:
        """Clave del perfil guardado: el nombre DirectShow de la cámara, o el número de
        serie del teléfono (estable aunque cambie el nombre y distinto en dos iguales)."""
        return s.device_name or s.serial or s.name

    def _rotation(self, s) -> int:
        """Giro elegido para esta fuente (0, 90, 180 o 270 grados)."""
        try:
            deg = int(self.fmt_by_src.get(s.id, {}).get("rotation") or 0) % 360
        except (TypeError, ValueError):
            deg = 0
        return deg if deg in (90, 180, 270) else 0

    def _on_rot_pick(self, deg: int):
        s = self._selected()
        if not s:
            return
        self.fmt_by_src.setdefault(s.id, {})["rotation"] = int(deg)
        self.seg_rot.paint(int(deg))
        self._render_orientation(s, self._format_options(s)[2])
        if self.rec_state != "idle":
            self.notify.toast(t("rotation.after_recording"), "warn")
        self._settings_changed()

    def _is_vertical(self, s) -> bool:
        if s.kind == "android":
            return self._rotation(s) in (90, 270)       # el teléfono captura ya girado
        return bool(self.fmt_by_src.get(s.id, {}).get("vertical"))

    def _paint_mode_badge(self, s=None):
        s = s or self._selected()
        if not s or not s.ready:
            self.lbl_mode.pack_forget()
            return
        _, _, size, fps = self._format_options(s)
        key = "mode.badge.vertical" if self._is_vertical(s) else "mode.badge"
        self.lbl_mode.configure(text=f"  {t(key, tier=res_tier(size), fps=fps)}  ")
        if not self.lbl_mode.winfo_ismapped():
            self.lbl_mode.pack(side="left", padx=(10, 0))

    def _render_orientation(self, s, size):
        self._paint_mode_badge(s)
        if not s.ready:
            self.fmt_box.grid_remove()
            return
        vertical = self._is_vertical(s)
        self.seg_orient.paint("v" if vertical else "h")
        mode = "phone" if s.kind == "android" else self.fmt_by_src.get(s.id, {}).get("vertical")
        if vertical and s.kind != "android":
            self.seg_vmode.paint(mode)
            self.seg_vmode.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        else:
            self.seg_vmode.grid_remove()
        out = vertical_size(size, mode) if vertical else None
        key = {"phone": "vertical.phone_note", "crop": "vertical.crop_note"}.get(mode, "vertical.rotate_note")
        self.lbl_fmt_note.configure(text=t(key, w=out[0], h=out[1]) if out else "")
        self.fmt_box.grid()

    def _on_orient_pick(self, value):
        s = self._selected()
        if not s:
            return
        fmt = self.fmt_by_src.setdefault(s.id, {})
        if s.kind == "android":
            rot = self._rotation(s)
            if value == "v" and rot not in (90, 270):
                fmt["rotation"] = 90
            elif value == "h" and rot in (90, 270):
                fmt["rotation"] = 0
            self.seg_rot.paint(self._rotation(s))
        elif value == "v":
            fmt["vertical"] = fmt.get("last_vertical") or "crop"
        else:
            if fmt.get("vertical"):
                fmt["last_vertical"] = fmt["vertical"]   # al volver a vertical se recupera
            fmt["vertical"] = None
        if self.rec_state != "idle":
            self.notify.toast(t("rotation.after_recording"), "warn")
        self._render_format()
        self._settings_changed()

    def _on_vmode_pick(self, mode):
        s = self._selected()
        if not s:
            return
        self.fmt_by_src.setdefault(s.id, {})["vertical"] = mode
        self._render_format()
        self._settings_changed()

    def _on_lens_change(self, label):
        s = self._selected()
        lens = self._lens_map.get(label)
        if s and lens:
            self.fmt_by_src.setdefault(s.id, {})["lens"] = dict(lens)
            self._render_format()          # los fps disponibles dependen de la cámara
            self._settings_changed()

    def _on_image_slider(self, key, v):
        self.image[key] = float(v)
        self.preset = None
        self._paint_presets()
        self._sync_sliders(only_labels=True)
        self._settings_changed()

    def _sync_sliders(self, only_labels=False):
        if not self.sliders or not self._alive(next(iter(self.sliders.values()))[0]):
            return
        for key, (s, lbl) in self.sliders.items():
            v = self.image[key]
            if not only_labels:
                s.set(v)
            if key == "brightness":
                txt = f"{v:+.2f}"
            elif key == "sharpness":
                txt = t("ui.main.neutra") if v <= 0.05 else f"{v:.1f}"
            else:
                txt = f"{v:.2f}×"
            lbl.configure(text=txt)

    def reset_image(self):
        self.image = {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "sharpness": 0.0}
        self.preset = None
        self._sync_sliders()
        self._paint_presets()
        self._settings_changed()

    def _apply_preset(self, pid):
        s = self._selected()
        if not s:
            return
        res_list, fps_avail, _, _ = self._format_options(s)
        fmt = self.fmt_by_src.setdefault(s.id, {})
        if pid in PRESET_VALUES:
            self.image.update(PRESET_VALUES[pid])
        if pid in ("studio", "fluid") and 60 in fps_avail:
            fmt["fps"] = 60
        if pid == "studio":
            fmt["size"] = res_list[0]
        self.preset = pid
        self._sync_sliders()
        self._render_format()
        self._paint_presets()
        self._settings_changed()

    def _paint_presets(self):
        if not self.preset_buttons or not self._alive(next(iter(self.preset_buttons.values()))):
            return
        for pid, b in self.preset_buttons.items():
            on = pid == self.preset
            b.configure(fg_color=C["accent_bg"] if on else C["panel"], hover_color=C["raised"],
                        border_color=C["accent"] if on else C["line"])
        if self._alive(self.music_tip):
            if self.preset == "music":
                self.music_tip.grid(row=9, column=0, sticky="ew", padx=4, pady=(10, 0), ipadx=8, ipady=8)
            else:
                self.music_tip.grid_remove()

    def _settings_changed(self):
        """Reinicia la vista previa (con los nuevos filtros) y guarda el perfil, con retardo."""
        if self.pending_restart:
            self.after_cancel(self.pending_restart)
        if self.pending_save:
            self.after_cancel(self.pending_save)
        if self.rec_state == "idle":
            self.pending_restart = self.after(700, lambda: (self._hold_vcam(), self._restart_preview()))
        self.pending_save = self.after(1200, self._save_camera_profile)

    def _save_camera_profile(self):
        self.pending_save = None
        s = self._selected()
        if not s:
            return
        _, _, size, fps = self._format_options(s)
        data = {"size": size, "fps": fps}
        if s.kind == "android":
            data["rotation"] = self._rotation(s)
            lens = self.fmt_by_src.get(s.id, {}).get("lens")
            if isinstance(lens, dict):
                data["lens"] = lens
        else:
            data.update({k: round(v, 2) for k, v in self.image.items()})
            data["vertical"] = self.fmt_by_src.get(s.id, {}).get("vertical")
        self.engine.save_camera_preset(self._preset_key(s), data)

    # =========================================================================
    # MONITOR INTEGRADO
    # =========================================================================
    def _stream_config(self, record=False) -> Dict:
        s = self._selected()
        _, _, size, fps = self._format_options(s)
        self.stream_gen += 1
        self.monitor_title = f"UltraCam_Monitor_{self.stream_gen}"
        cfg = {
            # Por cable no hace falta búfer (cada ms se nota en el monitor); por Wi-Fi uno
            # corto absorbe los tirones de la red.
            "size": size, "fps": fps, "video_buffer": 80 if s.is_wifi else 0,
            "codec": self.video_cfg.get("android_codec", "h265"), "bitrate": self.video_cfg.get("android_bitrate", "50M"),
            "window_title": self.monitor_title, "virtual_cam": False,
        }
        if self._vcam_on():
            cfg["virtual_cam"] = True
            # Con la cámara virtual, las webcams pasan por ffmpeg en vez de ffplay:
            # sin esta rama de vista previa el monitor se quedaría vacío.
            cfg["live_preview"] = True
        if s.kind == "android":
            cfg["platform"] = "android"
            cfg["serial"] = s.serial
            cfg["rotation"] = self._rotation(s)
            lens = self.fmt_by_src.get(s.id, {}).get("lens")
            if isinstance(lens, dict):
                cfg["camera_id"] = lens.get("id")
                cfg["camera_facing"] = lens.get("facing")
                cfg["zoom"] = lens.get("zoom")
        else:
            caps = self.caps.get(s.id, {})
            cfg.update({"platform": "pc", "pc_device": s.device_name, "device_name": s.device_name,
                        "vcodec": caps.get("vcodec"), "pixel_format": caps.get("pixel_format")})
            cfg.update(self.image)
            cfg["vertical"] = self.fmt_by_src.get(s.id, {}).get("vertical")
        if record:
            cfg.update({"record_video": True, "record_dir": self.record_dir_var.get(), "live_preview": True})
        return cfg

    def _toggle_camera_power(self):
        """Permite pausar o reactivar la cámara física sin cerrar la aplicación."""
        if self.rec_state != "idle":
            self.notify.toast(t("pause.blocked_while_recording"), "warn")
            return

        if not self.camera_paused:
            self.camera_paused = True
            self._stop_preview()
            if hasattr(self, "btn_pause_cam"):
                self.btn_pause_cam.configure(text=t("pause.button.resume"), text_color=C["ok"])
            self._set_video_message(t("video.paused.title"), t("video.paused.body"),
                                    icon="camera", actions=[(t("action.activate_camera"), self._toggle_camera_power)])
            self.notify.toast(t("pause.done"), "info")
        else:
            self.camera_paused = False
            if hasattr(self, "btn_pause_cam"):
                self.btn_pause_cam.configure(text=t("pause.button"), text_color=C["text2"])
            self._start_preview()
            self.notify.toast(t("pause.resumed"), "info")

    def _start_preview(self):
        if getattr(self, "camera_paused", False):
            return
        if hasattr(self, "btn_pause_cam"):
            self.btn_pause_cam.configure(text=t("pause.button"), text_color=C["text2"])

        s = self._selected()
        if not s:
            return
        if not s.ready:
            self._render_video_state()
            return
        if s.kind == "android" and not self.engine.scrcpy_path:
            self._set_video_message(t("video.missing_scrcpy.title"), t("video.missing_scrcpy.body"), icon="warning")
            return
        if s.is_dshow and not self.engine.ffmpeg_path:
            self._set_video_message(t("video.missing_ffmpeg.title"), t("video.missing_ffmpeg.body"), icon="warning")
            return
        self._set_video_message(t("video.connecting.title"), t("video.connecting.body"), icon="camera")
        cfg = self._stream_config()
        self._start_stream_async(cfg, self._on_preview_started)

    def _start_stream_async(self, cfg, done):
        """Arranca la cámara en el hilo de trabajos y llama a done(gen, cfg, ok) en la
        interfaz. Si antes de arrancar ya se pidió otra cosa (otra cámara, detener), no
        arranca: así nunca queda abierta una cámara que ya no se quiere."""
        gen = self.stream_gen

        def job():
            if gen != self.stream_gen or not self.running:
                return
            ok = self.engine.start_stream(cfg, on_exit=lambda code, g=gen: self._ui(lambda: self._on_stream_exit(g, code)))
            self._ui(done, gen, cfg, ok)
        self._stream_jobs.submit(job)

    def _on_preview_started(self, gen, cfg, ok):
        if gen != self.stream_gen:
            return          # llegó tarde: el trabajo de detener ya está en cola detrás de este
        if ok:
            self._set_live(t("live.connecting"), C["accent"])
            self._launch_embed(gen, cfg["window_title"])
            self._after_stream_started(cfg)
        else:
            self._set_video_message(t("video.open_failed.title"), t("video.open_failed.body", vcam=virtualcam.DEVICE_NAME),
                                    icon="warning", actions=[(t("action.retry"), self._retry_stream)])

    def _stop_preview(self):
        self.stream_gen += 1          # invalida callbacks del proceso anterior
        if getattr(self, "monitor_hwnd", None):
            try:
                GLOBAL_WINDOW_EMBEDDER.detach_window(self.monitor_hwnd)
            except Exception as e:
                GLOBAL_LOGGER.debug(f"Aviso al desvincular monitor en _stop_preview: {e}")
            self.monitor_hwnd = None
        self._stop_stream_async()
        self._set_live(t("live.off"), C["off"])
        if self.vcam_state.get("status") != "off":
            self.vcam_state = {"status": "off", "message": ""}   # «UltraCam» pasa a «Sin señal»
            self._paint_vcam()

    def _stop_stream_async(self):
        """Detiene la cámara en el hilo de trabajos, detrás de cualquier arranque pendiente."""
        self._stream_jobs.submit(lambda: self.engine.stop_stream() if self.engine.is_running else None)

    def _restart_preview(self):
        self.pending_restart = None
        if self.rec_state != "idle":
            return
        self.camera_paused = False
        self._stop_preview()
        self._start_preview()

    def _launch_embed(self, gen, title):
        self.update_idletasks()
        parent = self.video_container.winfo_id()
        w, h = self._monitor_size()
        threading.Thread(target=self._embed_monitor, args=(gen, title, parent, w, h), daemon=True).start()

    def _embed_monitor(self, gen, title, parent, w, h):
        # Al grabar en vertical, el teléfono entrega la primera imagen a los ~12 s (su audio
        # guía llega con otro reloj y scrcpy retiene el video hasta emparejarlos).
        timeout = 10.0 if self.rec_state == "idle" else 30.0
        ok = self.engine.embed_window_into_hwnd(title, parent, w, h, timeout=timeout)
        if gen != self.stream_gen:
            return
        if ok:
            hwnd = ctypes.windll.user32.FindWindowExW(parent, None, None, title)
            self.monitor_hwnd = hwnd or None
            self._ui(self._on_monitor_resize)
            self._ui(lambda: self.video_msg.grid_remove())
            self._ui(lambda: self._set_live(t("live.on"), C["ok"]) if self.rec_state == "idle" else None)
            # Tras 10 s de imagen estable se renuevan los reintentos automáticos.
            self._ui(lambda: self.after(10000, lambda: setattr(self, "_stream_retries", 0)
                                                 if gen == self.stream_gen else None))
        else:
            self._on_engine_log("No se pudo integrar la ventana de video en el monitor.", "WARN")
            self._ui(lambda: self._on_embed_failed(gen))

    def _on_embed_failed(self, gen):
        """La imagen no llegó al monitor a tiempo: salir de «Conectando…» con una acción."""
        if gen != self.stream_gen:
            return
        if self.rec_state == "idle":
            self._set_video_message(t("video.embed_failed.title"), t("video.embed_failed.body"),
                                    icon="warning", actions=[(t("action.retry"), self._retry_stream)])
        elif self.rec_state == "recording":
            self._set_video_message(t("video.recording_continues.title"), t("video.recording_continues.body"),
                                    icon="warning")

    def _monitor_size(self):
        w = max(self.video_container.winfo_width() - 8, 320)
        h = max(self.video_container.winfo_height() - 8, 180)
        return w, h

    def _on_monitor_resize(self, _e=None):
        if self.monitor_hwnd:
            w, h = self._monitor_size()
            try:
                ctypes.windll.user32.MoveWindow(self.monitor_hwnd, 4, 4, int(w), int(h), True)
            except Exception as e:
                GLOBAL_LOGGER.debug(f"Aviso redimensionando monitor HWND: {e}")

    def _on_stream_exit(self, gen, code):
        if gen != self.stream_gen:
            return
        if getattr(self, "monitor_hwnd", None):
            try:
                GLOBAL_WINDOW_EMBEDDER.detach_window(self.monitor_hwnd)
            except Exception as e:
                GLOBAL_LOGGER.debug(f"Aviso al desvincular monitor en _on_stream_exit: {e}")
            self.monitor_hwnd = None
        self._set_live(t("ui.main.sin_senal"), C["off"])
        if getattr(self, "camera_paused", False):
            return
        if self.rec_state == "starting":
            self._recording_failed(t("rec.closed_on_start"))
            return
        if self.rec_state == "recording":
            self._on_engine_log("La cámara se detuvo durante la grabación. Guardando lo grabado…", "ERROR")
            self.stop_recording_session(camera_lost=True)
            return
        if self.vcam_state.get("status") != "off":
            self.vcam_state = {"status": "off", "message": ""}
            self._paint_vcam()
        s = self._selected()
        if s and s.ready and self._stream_retries < self.MAX_STREAM_RETRIES:
            # Reconexión automática: un corte suelto (cable flojo, el teléfono tardó en
            # responder) no debe obligar a pulsar nada. Si la fuente desapareció de la
            # lista, _apply_sources muestra en su lugar los pasos para recuperarla.
            self._stream_retries += 1
            n = self._stream_retries
            self._set_video_message(t("video.reconnecting.title", name=s.name),
                                    t("video.reconnecting.body", n=n, total=self.MAX_STREAM_RETRIES), icon="camera")
            if self.pending_restart:
                self.after_cancel(self.pending_restart)
            self.pending_restart = self.after(1500 * n, self._restart_preview)
            return
        self._set_video_message(t("video.lost.title"), t("video.lost.body"),
                                icon="warning", actions=[(t("action.retry"), self._retry_stream)])

    MAX_STREAM_RETRIES = 3

    def _retry_stream(self):
        """Reintento manual: vuelve a dar margen a la reconexión automática."""
        self._stream_retries = 0
        self._restart_preview()

    # =========================================================================
    # CÁMARA VIRTUAL DE WINDOWS
    # =========================================================================
    def _start_vcam_device(self):
        """Registra la cámara «UltraCam» (driver propio) y abre el enlace con ella.

        El driver sigue en Windows aunque la app esté cerrada, así los demás programas
        (Zoom, Meet, Teams, Discord, OBS) la ven siempre en su lista. Al abrir la app
        pasa de «UltraCam Studio está cerrado» a «Sin señal» hasta que se le envíe una
        cámara. En segundo plano, para no retrasar el arranque.
        """
        def boot():
            virtualcam.SERVICE.start(log=self.engine.log)
            self._ui(self._paint_vcam)

        threading.Thread(target=boot, daemon=True).start()

    def _vcam_on(self) -> bool:
        """¿Se envía la cámara elegida a «UltraCam»? Es un solo interruptor para todas las
        cámaras: al cambiar de fuente, la cámara virtual la sigue sin volver a activarla."""
        return bool(self.vcam_cfg.get("enabled", True)) and virtualcam.available()

    def _toggle_vcam(self):
        """Enciende o pausa el envío a «UltraCam». No hace falta confirmarlo: los demás
        programas no se desconectan en ningún caso, solo ven la imagen o «Sin señal»."""
        if not virtualcam.available():
            self.notify.banner("vcam", t("vcam.unavailable"), "error")
            return
        on = not self.vcam_cfg.get("enabled", True)
        self.vcam_cfg["enabled"] = on
        self._save_settings()
        s = self._selected()
        name = virtualcam.DEVICE_NAME
        if on:
            what = f"«{s.name}»" if s else t("vcam.on.no_source")
            self.engine.log(t("vcam.on", vcam=name, what=what), "VCAM")
            self.notify.toast(t("vcam.on", vcam=name, what=what))
        else:
            self.engine.log(t("vcam.off", vcam=name), "VCAM")
            self.notify.toast(t("vcam.off", vcam=name), "info")
        self.vcam_state = {"status": "off", "message": ""}
        self._paint_vcam()
        if self.rec_state != "idle":
            self.notify.toast(t("vcam.after_recording"), "warn")
            return
        if s and s.ready:
            self._restart_preview()

    def _after_stream_started(self, cfg):
        # El reparto también existe sin cámara virtual (monitor de fuentes mayores que Full HD)
        if cfg.get("virtual_cam") and self.engine.vcam and self.engine.vcam.sink:
            writer = virtualcam.SERVICE.writer
            self._vcam_frames_at_start = writer.frames_in if writer else 0
            self.vcam_state = {"status": "busy", "message": ""}
            self._paint_vcam()
            self.notify.clear("vcam")
        elif cfg.get("virtual_cam"):
            err = virtualcam.SERVICE.last_error or t("ui.main.sin_enlace_con_el_driver")
            self._on_engine_log(f"La cámara virtual no recibe imagen: {err}", "WARN")   # detalle, solo al registro
            self.vcam_state = {"status": "warn", "message": err}
            self._paint_vcam()
            self.notify.banner("vcam", t("vcam.failed", vcam=virtualcam.DEVICE_NAME), "warn",
                               actions=[(t("action.vcam_settings"), lambda: self.open_settings("vcam"))])
        else:
            self.vcam_state = {"status": "off", "message": ""}
            self._paint_vcam()

    def _paint_vcam(self):
        on = self._vcam_on()
        st = self.vcam_state.get("status") if on else "off"
        color = {"ok": C["ok"], "busy": C["accent"], "warn": C["warn"]}.get(st, C["line2"])
        self.btn_vcam.configure(
            # Dice de un vistazo si «UltraCam» muestra imagen, el cartel o está en pausa
            text=t({"ok": "vcam.button.live", "busy": "vcam.button.connecting"}.get(st, "vcam.button.waiting") if on else
                   ("vcam.button.paused" if virtualcam.available() else "vcam.button.unavailable"),
                   vcam=virtualcam.DEVICE_NAME),
            fg_color=C["ok_bg"] if st == "ok" else ("transparent" if not on else C["accent_bg"]),
            border_color=color, hover_color=C["raised"],
            text_color=C["ok_text"] if st == "ok" else (C["text2"] if not on else C["accent_text"])
        )

    def retry_vcam(self):
        if self._vcam_on() and self.rec_state == "idle":
            self._restart_preview()

    def _set_live(self, text, color):
        self.live_text.configure(text=text)
        self.live_dot.configure(text_color=color)

    def _set_video_message(self, title, body, icon="camera", steps=None, actions=None):
        self.vm_icon.configure(text=ICON.get(icon, ICON["camera"]),
                               text_color=C["warn"] if icon == "warning" else C["off"])
        self.vm_title.configure(text=title)
        text = body
        if steps:
            text = "\n".join(f"{i}.  {st}" for i, st in enumerate(steps, 1))
        self.vm_body.configure(text=text)
        for w in self.vm_actions.winfo_children():
            w.destroy()
        for i, (label, cmd) in enumerate(actions or []):
            if i == 0:
                ctk.CTkButton(self.vm_actions, text=label, command=cmd, height=38, corner_radius=9, fg_color=C["text"],
                              hover_color="#FFFFFF", text_color="#141413", font=self.F(13, "bold")).pack(side="left", padx=(0, 10))
            else:
                self._ghost_button(self.vm_actions, label, cmd, height=38).pack(side="left")
        self.video_msg.grid()

    def _render_video_state(self):
        s = self._selected()
        if not self.sources:
            self._set_video_message(t("video.none.title"), t("video.none.body"), icon="camera",
                                    actions=[(t("action.connect_phone"), self._open_connect_dialog),
                                             (t("action.rescan"), self._force_rescan)])
            self._update_transport()
            return
        if s and not s.ready:
            actions = [(t("action.rescan"), self._force_rescan)]
            if s.kind in ("android", "app"):
                actions.append((t("action.phone_guide"), self._open_connect_dialog))
            self._set_video_message(s.hint_title, "", icon="warning", steps=s.hint_steps, actions=actions)
        self._update_transport()

    # =========================================================================
    # GRABACIÓN
    # =========================================================================
    def toggle_recording(self):
        if self.rec_state == "idle":
            self.start_recording_session()
        elif self.rec_state == "starting":
            self._cancel_recording_start()
        elif self.rec_state == "recording":
            self.stop_recording_session()

    def _cancel_recording_start(self):
        """La cámara tarda en dar imagen (hasta 15 s): se puede cancelar sin esperar.
        Se borra el archivo a medio empezar y se vuelve a la vista previa."""
        if self.rec_state != "starting":
            return
        partial = self.engine.current_recording_file
        self._discard_audio()
        self.rec_state = "idle"
        self._stop_preview()
        if partial:
            # En la cola de trabajos, detrás de la parada: ya no está abierto por ffmpeg.
            self._stream_jobs.submit(lambda: os.path.exists(partial) and os.remove(partial))
        self._update_transport()
        self.notify.toast(t("rec.cancelled"), "info")
        self._start_preview()

    def start_recording_session(self):
        s = self._selected()
        if not s or not s.ready:
            return
        out_dir = self.record_dir_var.get()
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            self._on_engine_log(f"No se puede escribir en {out_dir}: {e}", "ERROR")
            self.notify.banner("rec", t("rec.folder_unwritable", folder=self._short_dir()), "error",
                               actions=[(t("action.change_folder"), self._pick_dir)])
            return
        self.notify.clear("rec")
        free, drive = disk_free(out_dir)
        if free is not None and free < DISK_MIN_TO_START:
            self.notify.banner("disk", t("disk.full", drive=drive, free=fmt_bytes(free)), "error",
                               actions=[(t("action.change_folder"), self._pick_dir)])
            return
        self.notify.clear("disk")
        if self.pending_restart:
            self.after_cancel(self.pending_restart)
            self.pending_restart = None
        # El audio empieza ya: la cámara tarda unos segundos en dar su primera imagen y así no
        # se pierde el comienzo (la primera nota). Al unir, se recorta la diferencia exacta.
        t_audio = time.monotonic()
        audio_res = self.audio_engine.start_recording(out_dir)
        self._audio_start_mono = (t_audio + time.monotonic()) / 2
        if not audio_res.get("ok"):
            self._on_engine_log(f"El audio no empezó a grabar: {audio_res.get('error')}", "WARN")
        self.rec_state = "starting"
        self.saved_banner.grid_remove()
        self._update_transport()
        self._stop_preview()
        cfg = self._stream_config(record=True)
        self._set_video_message(t("rec.starting.title"), t("rec.starting.body"), icon="camera")
        self._start_stream_async(cfg, lambda gen, cfg, ok: self._on_record_stream_started(gen, cfg, ok, out_dir))

    def _on_record_stream_started(self, gen, cfg, ok, out_dir):
        if gen != self.stream_gen or self.rec_state != "starting":
            return
        if not ok:
            self.rec_state = "idle"
            self._update_transport()
            self._set_video_message(t("rec.start_failed.title"), t("rec.start_failed.body"), icon="warning",
                                    actions=[(t("action.retry"), self._retry_stream), (t("action.details"), self._open_log)])
            return
        self._launch_embed(gen, cfg["window_title"])
        self._after_stream_started(cfg)
        threading.Thread(target=self._wait_first_frames, args=(gen, out_dir), daemon=True).start()

    def _wait_first_frames(self, gen, out_dir):
        """El audio arranca cuando el video ya está escribiendo, para que queden sincronizados."""
        evt = self.engine.recording_started
        sm = self.engine.stream_manager
        t0 = time.time()
        first_growth = None
        while time.time() - t0 < 25:        # vertical en el teléfono: la imagen llega a los ~12 s
            if gen != self.stream_gen or self.rec_state != "starting":
                return
            if evt.wait(0.02):
                self._ui(lambda: self._begin_audio(gen, out_dir))
                return
            f = self.engine.current_recording_file   # respaldo: el archivo ya está creciendo
            try:
                size = os.path.getsize(f) if f and os.path.exists(f) else 0
            except OSError:
                size = 0
            if size > 4096 and first_growth is None:
                first_growth = time.monotonic()    # llegó el primer cuadro (así se alinea el audio del teléfono)
            if size > 512 * 1024:
                if sm.recording_started_at is None:
                    # Último recurso: el .mkv crece recién al cerrar su primer bloque (~5 MB o 5 s),
                    # así que esta hora llega tarde y el audio puede quedar adelantado.
                    sm.recording_started_at = first_growth
                    self.engine.log("Sin aviso de inicio de grabación: la sincronía se estima por el tamaño "
                                    "del archivo y puede quedar corrida.", "WARN")
                self._ui(lambda: self._begin_audio(gen, out_dir))
                return
        self._ui(lambda: self._recording_failed(t("rec.no_frames")))

    def _begin_audio(self, gen, out_dir):
        if gen != self.stream_gen or self.rec_state != "starting":
            return
        self.rec_state = "recording"       # el audio ya grababa desde el clic
        self.record_start_time = time.time()
        self._set_live(t("ui.main.grabando"), C["rec"])
        self.video_container.configure(border_color=C["rec"])
        self._update_transport()
        self.notify.status(t("rec.recording", name=self._selected().name if self._selected() else ""))

    def _recording_failed(self, reason):
        if self.rec_state != "starting":
            return
        self._on_engine_log(f"No se pudo grabar: {reason}", "ERROR")
        self._discard_audio()
        self.rec_state = "idle"
        self._stop_preview()
        self._update_transport()
        self._set_video_message(t("rec.start_failed.title"), t("rec.failed_reason.body", reason=reason),
                                icon="warning", actions=[(t("action.retry"), self._retry_stream)])

    def stop_recording_session(self, camera_lost=False, then=None):
        if self.rec_state not in ("recording", "starting"):
            return
        was_recording = self.rec_state == "recording"
        self._camera_lost = camera_lost
        self.rec_state = "saving"
        self.video_container.configure(border_color=C["panel"])
        self._update_transport()
        audio_info = self.audio_engine.stop_recording() if was_recording else (self._discard_audio() or {})
        vid_path = self.engine.current_recording_file
        # Alineación: cuándo empezó el audio y cuándo llegó el primer cuadro, en el mismo reloj.
        sm = self.engine.stream_manager
        video_start = sm.video_start_ts or sm.recording_started_at
        audio_start = getattr(self, "_audio_start_mono", None)
        av_offset = audio_start - video_start if audio_start and video_start else 0.0
        if abs(av_offset) > 20:
            av_offset = 0.0         # reloj de la cámara en otra escala (algunas capturadoras): sin ajuste
        self.engine.log(f"Audio respecto al video: {av_offset:+.3f} s (ajuste manual {self.sync_ms:+d} ms)", "REC")
        options = {
            "output_dir": self.record_dir_var.get(),
            "prefix": (self.record_prefix_var.get().strip() or "UltraCam_Session"),
            "resolution_tag": self._res_tag(),
            "embed_multitrack": self.opt_multitrack.get(),
            "export_stems": self.opt_stems.get(),
            "normalize": self.norm_mode,
            "sync_offset_ms": self.sync_ms,
            "av_offset_s": round(av_offset, 3),
            "phone_serial": getattr(self._selected(), "serial", None),   # relojes del teléfono (pista guía)
            "reveal_in_explorer": self.opt_reveal.get(),
            "auto_play": self.opt_autoplay.get(),
        }
        self.stream_gen += 1   # el cierre del proceso de grabación no debe mostrarse como error
        self.monitor_hwnd = None

        def work():
            if self.engine.is_running:
                self.engine.stop_stream()
            if not was_recording or not vid_path or not os.path.exists(vid_path):
                self._ui(lambda: self._after_save({"success": False, "message": t("ui.main.no_se_genero_video")}, then))
                return
            res = self.engine.finalize_recording(vid_path, audio_info, options)
            self._ui(lambda: self._after_save(res, then))
        self._stream_jobs.submit(work)     # en orden con los arranques y paradas de cámara

    def _discard_audio(self):
        """La toma no llegó a empezar: se detiene el audio que ya grababa y se borran sus temporales."""
        if not self.audio_engine.is_recording:
            return None
        info = self.audio_engine.stop_recording()
        for p in [info.get("master_wav")] + [tr.get("wav") for tr in info.get("tracks") or []]:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        return None

    def _res_tag(self):
        s = self._selected()
        if not s:
            return "HD"
        h = int(self._format_options(s)[2].split("x")[-1])
        tag = "4K" if h >= 2160 else f"{h}p"
        return tag + ("_vertical" if self._is_vertical(s) else "")     # fácil de encontrar al publicar

    def _after_save(self, res, then=None):
        self.rec_state = "idle"
        self.lbl_timer.configure(text="00:00:00")     # la duración queda en el nombre y en el resumen
        self._update_transport()
        if getattr(self, "_pending_audio_apply", False):
            self._pending_audio_apply = False
            self.apply_audio_config()
        if res.get("success"):
            name = os.path.basename(res["final_path"])
            clip = res.get("clipping_detected")
            self.saved_lbl.configure(text=f"✓  {t('rec.saved.banner', file=name)}" +
                                     t("rec.saved.clip" if clip else "rec.saved.clean"))
            path = res["final_path"]
            self.saved_btn.configure(command=lambda r=res: self._show_summary(r))
            self.saved_play.configure(command=lambda p=path: self._play(p))
            self.saved_reveal.configure(command=lambda p=path: self._reveal(p))
            self.saved_banner.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            self._refresh_takes()
            self.notify.toast(t("rec.saved", file=name))
            if getattr(self, "_camera_lost", False):
                self.notify.banner("rec", t("rec.camera_lost"), "warn")
            if self.opt_summary.get():
                self._show_summary(res)
        else:
            msg = res.get("message", t("ui.main.error_desconocido"))
            self._on_engine_log(f"No se pudo guardar la toma: {msg[:300]}", "ERROR")
            self.notify.banner("rec", t("rec.save_failed"), "error",
                               actions=[(t("action.details"), self._open_log),
                                        (t("action.open_folder"), self.open_recordings_folder)])
        if then:
            then()
            return
        self._start_preview()

    def _update_transport(self):
        s = self._selected()
        st = self.rec_state
        ready = bool(s and s.ready)
        if st == "idle":
            self.btn_rec.configure(text=t("ui.main.grabar"), state="normal" if ready else "disabled",
                                   fg_color=C["rec"] if ready else C["line"], hover_color=C["rec_hover"])
            self.lbl_timer.configure(text_color=C["text"])
            if not s:
                txt = t("rec.pick_camera")
            elif not s.ready:
                txt = t("rec.waiting_device")
            else:
                free, _drive = disk_free(self.record_dir_var.get())
                txt = (t("rec.ready.space", folder=self._short_dir(), free=fmt_bytes(free)) if free is not None
                       else t("rec.ready", folder=self._short_dir()))
            self.lbl_rec_status.configure(text=txt)
        elif st == "starting":
            self.btn_rec.configure(text=t("rec.cancel"), state="normal", fg_color=C["line2"], hover_color="#4A4A52")
            self.lbl_rec_status.configure(text=t("rec.starting.detail"))
        elif st == "recording":
            n = sum(1 for ch in self.audio_engine.config.get("channels", [])
                    if not ch.get("mute") and ch["source"].get("kind") not in (None, "none"))
            channels = t("rec.recording.channels_one") if n == 1 else t("rec.recording.channels_many", n=n)
            self.btn_rec.configure(text=t("ui.main.detener_y_guardar"), state="normal", fg_color=C["line2"], hover_color="#4A4A52")
            self.lbl_timer.configure(text_color=C["rec_text"])
            self.lbl_rec_status.configure(text=t("rec.recording.detail", n=channels, folder=self._short_dir()))
        elif st == "saving":
            self.btn_rec.configure(text=t("ui.main.guardando"), state="disabled", fg_color=C["line2"])
            self.lbl_timer.configure(text_color=C["text"])
            self.lbl_rec_status.configure(text=t("rec.saving.detail"))
        self.btn_rescan.configure(state="normal" if st == "idle" else "disabled")
        # Liberar la cámara mientras se graba cortaría la toma: no se ofrece.
        self.btn_pause_cam.configure(state="normal" if st == "idle" else "disabled")
        if st != "recording":
            self.title(APP_NAME)

    def _short_dir(self):
        d = self.record_dir_var.get()
        home = os.path.expanduser("~")
        return d.replace(home, "~") if d.startswith(home) else d

    def _tick_ui(self):
        if self.rec_state == "recording":
            e = int(time.time() - self.record_start_time)
            elapsed = f"{e // 3600:02d}:{e % 3600 // 60:02d}:{e % 60:02d}"
            self.lbl_timer.configure(text=elapsed)
            # La grabación y su tiempo se ven desde el encabezado y la barra de tareas.
            self.live_text.configure(text=t("rec.pill", time=elapsed))
            self.title(t("rec.window_title", time=elapsed, app=APP_NAME))
            if time.time() - getattr(self, "_last_disk_check", 0) >= 10:
                self._last_disk_check = time.time()
                self._check_disk_while_recording()
        elif self.rec_state == "starting":
            self.lbl_timer.configure(text="00:00:00")
        if self.vcam_state.get("status") == "busy":
            writer = virtualcam.SERVICE.writer
            if writer and writer.frames_in > getattr(self, "_vcam_frames_at_start", 0):
                self.vcam_state = {"status": "ok", "message": ""}
                self._paint_vcam()
        self.after(250, self._tick_ui)

    def _check_disk_while_recording(self):
        """Avisa antes de que el disco se llene y, si hace falta, detiene y guarda a
        tiempo: sin espacio para unir video y audio se perdería la toma entera."""
        free, drive = disk_free(self.record_dir_var.get())
        f = self.engine.current_recording_file
        try:
            recorded = os.path.getsize(f) if f and os.path.exists(f) else 0
        except OSError:
            recorded = 0
        verdict = disk_verdict(free, recorded)
        if verdict == "stop":
            self._on_engine_log(f"Disco casi lleno ({fmt_bytes(free)} libres en {drive}): se detiene la grabación.", "WARN")
            self.notify.banner("disk", t("disk.stopped", drive=drive), "error",
                               actions=[(t("action.change_folder"), self._pick_dir)])
            self.stop_recording_session()
        elif verdict == "low":
            self.notify.banner("disk", t("disk.low", drive=drive, free=fmt_bytes(free)), "warn")

    # =========================================================================
    # TOMAS RECIENTES Y RESUMEN
    # =========================================================================
    def _refresh_takes(self):
        for w in self.takes_list.winfo_children():
            w.destroy()
        d = self.record_dir_var.get()
        files = []
        try:
            for fn in os.listdir(d):
                if fn.lower().endswith(".mp4") and not fn.startswith("temp_"):
                    p = os.path.join(d, fn)
                    files.append((os.path.getmtime(p), p))
        except OSError as e:
            GLOBAL_LOGGER.debug(f"Aviso al listar tomas en {d}: {e}")
        files.sort(reverse=True)
        if not files:
            ctk.CTkLabel(self.takes_list, text=t("ui.main.aun_no_hay_tomas_pulsa"), font=self.F(12),
                         text_color=C["faint"], anchor="w").grid(row=0, column=0, sticky="ew", padx=4, pady=6)
            return
        today = datetime.date.today()
        for i, (mt, p) in enumerate(files[:8]):
            row = ctk.CTkFrame(self.takes_list, fg_color=C["rail"], corner_radius=9, border_width=1, border_color="#25252A", height=46)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=ICON["video"], font=self.IF(14), text_color=C["muted"]).grid(row=0, column=0, padx=(12, 10), pady=8)
            ctk.CTkLabel(row, text=os.path.basename(p), font=self.F(13), text_color=C["text"], anchor="w").grid(row=0, column=1, sticky="ew")
            dt = datetime.datetime.fromtimestamp(mt)
            when = (t("ui.main.hoy") if dt.date() == today else dt.strftime("%d/%m ")) + dt.strftime("%H:%M")
            size = os.path.getsize(p) / (1024 * 1024)
            ctk.CTkLabel(row, text=f"{when} · {size:.0f} MB", font=self.F(12), text_color=C["faint"]).grid(row=0, column=2, padx=10)
            self._ghost_button(row, t("ui.main.mostrar"), lambda f=p: self._reveal(f), height=30).grid(row=0, column=3, padx=(0, 4))
            ctk.CTkButton(row, text=t("ui.main.reproducir"), command=lambda f=p: self._play(f), height=30, width=90, corner_radius=7,
                          fg_color="transparent", border_width=1, border_color=C["line2"], hover_color=C["raised"],
                          text_color=C["text"], font=self.F(12)).grid(row=0, column=4, padx=(0, 8))

    def _reveal(self, path):
        try:
            subprocess.Popen(["explorer.exe", f"/select,{os.path.normpath(path)}"])
        except OSError as e:
            GLOBAL_LOGGER.warn(f"No se pudo mostrar archivo en explorador: {e}")

    def _play(self, path):
        try:
            os.startfile(path)
        except OSError as e:
            GLOBAL_LOGGER.warn(f"No se pudo reproducir archivo: {e}")

    def _show_summary(self, res):
        colors = {c["name"]: c.get("color") or C["text2"] for c in self.audio_engine.config.get("channels", [])}
        return TakeSummaryDialog.show(
            self, res, self.opt_multitrack.get(), colors,
            self.F, self.IF, self._reveal, self._play
        )

    # =========================================================================
    # CONECTAR UN MÓVIL
    # =========================================================================
    def _open_connect_dialog(self):
        if self.connect_dialog is not None and self.connect_dialog.winfo_exists():
            self.connect_dialog.focus()
            return
        self.connect_dialog_mgr = ConnectDialog(
            self, self._force_rescan, self._repair_phone_link, self.F, self.IF,
            on_wifi=self.activate_wireless_mode
        )
        self.connect_dialog = self.connect_dialog_mgr.show()
        self.connect_status = self.connect_dialog_mgr.connect_status

    def show_welcome(self):
        """Bienvenida en tres pasos. Se marca como vista al cerrarla."""
        def done():
            self.settings["onboarded"] = True
            self._save_settings()
        WelcomeDialog.show(self, self.F, self.IF, virtualcam.DEVICE_NAME, self._short_dir(),
                           on_connect_phone=self._open_connect_dialog, on_close=done)

    def _close_connect_dialog(self):
        if getattr(self, "connect_dialog_mgr", None) is not None:
            self.connect_dialog_mgr.close()
        elif self.connect_dialog is not None:
            try:
                self.connect_dialog.destroy()
            except Exception as e:
                GLOBAL_LOGGER.debug(f"Aviso al cerrar connect_dialog: {e}")
        self.connect_dialog = None
        self.connect_dialog_mgr = None

    def _set_connect_status(self, text):
        """Texto de estado del diálogo «Conectar un móvil», si está abierto."""
        mgr = getattr(self, "connect_dialog_mgr", None)
        if mgr is not None:
            mgr.set_status(text)

    def _repair_phone_link(self):
        self._set_connect_status(t("phone.repairing"))
        self.notify.status(t("phone.repairing"))

        def work():
            msg = self.engine.repair_adb()
            self.engine.cached_pc_cameras = []
            self.engine.scanner._adb_server_ready = False
            self._on_engine_log(msg, "USB")
            self._ui(lambda: (self._set_connect_status(t("phone.repaired")),
                                   self.notify.toast(t("phone.repaired"), "info"), self._force_rescan()))
        threading.Thread(target=work, daemon=True).start()

    def _show_adb_problem(self, problem, apps):
        """Explica por qué el teléfono se desconecta, si el problema es de adb. Solo si en
        esta sesión se usó un Android: a quien solo usa webcams o iPhone no le afecta."""
        if any(s.kind == "android" for s in self.sources):
            self._seen_android = True
        relevant = getattr(self, "_seen_android", False) or self.connect_dialog is not None
        if not problem or not relevant:
            self.notify.clear("adb")
            return
        names = " y ".join(apps) if apps else t("phone.other_app")
        key = "phone.adb_conflict" if problem == "conflict" else "phone.adb_timeout"
        self.notify.banner("adb", t(key, apps=names), "warn",
                           actions=[(t("action.repair_phone"), self._repair_phone_link)])

    # =========================================================================
    # AUDIO
    # =========================================================================
    def _load_audio_config(self) -> Dict:
        """Configuración de audio guardada, o una nueva a partir de la versión anterior
        (canales fijos Sistema / Entrada 1 / Entrada 2)."""
        s = self.settings
        if isinstance(s.get("audio"), dict) and "channels" in s["audio"]:
            cfg = dict(DEFAULT_CONFIG)
            cfg.update(s["audio"])
            return cfg
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        old = s.get("audio_dev", {})
        vols = s.get("vol", {})
        modes = s.get("mode", {})
        chans = []
        sys_dev = old.get("sys")
        if sys_dev and sys_dev not in ("Sin salida de audio",):
            chans.append(new_channel(t("ui.main.sistema"), {"kind": "device", "device": sys_dev, "loopback": True}, "stereo",
                                     color=CHANNEL_COLORS[0]))
        for cid, label in (("in1", t("ui.main.entrada_1")), ("in2", t("ui.main.entrada_2"))):
            dev = old.get(cid)
            if not dev or dev == "Desactivada":
                continue
            loop = dev.endswith(" · Lo que suena")
            name = dev.replace(" · Lo que suena", "")
            mode = "stereo" if modes.get(cid) == "stereo" or loop else "mono"
            chans.append(new_channel(label, {"kind": "device", "device": name, "loopback": loop}, mode,
                                     color=CHANNEL_COLORS[len(chans) % len(CHANNEL_COLORS)]))
        for ch, key in zip(chans, ("sys", "in1", "in2")):
            if key in vols:
                ch["volume"] = float(vols[key])
        if not chans:
            chans.append(new_channel(t("ui.main.sistema"), {"kind": "device", "device": "", "loopback": True}, "stereo",
                                     color=CHANNEL_COLORS[0]))
        cfg["channels"] = chans
        return cfg

    def _persist_audio(self):
        self.settings["audio"] = self.audio_engine.config
        self._save_settings()

    def _init_audio(self):
        self.render_mixer()

        def work():
            try:
                self.audio_engine.start()
                devs = self.audio_engine.list_devices()
                cfg = self.audio_engine.config
                # Primera vez: canal «Sistema» con lo que suena en la salida predeterminada de Windows
                for ch in cfg["channels"]:
                    src = ch["source"]
                    if src.get("kind") == "device" and src.get("loopback") and not src.get("device"):
                        src["device"] = devs.get("default_out") or ""
                self.audio_engine.apply(cfg, wait=True)
                self.vst_list = scan_vst3(self.settings.get("vst_dirs", []))
                self._ui(self._after_audio_ready, devs)
            except Exception as e:
                self._on_engine_log(f"No se pudo iniciar el motor de audio: {e}", "ERROR")
        threading.Thread(target=work, daemon=True).start()

    def _after_audio_ready(self, devs):
        self.audio_devices = devs
        self.notify.status(t("app.ready"))
        self.render_mixer()
        self._persist_audio()
        n_in = len(devs.get("wasapi_in", [])) + len(devs.get("asio", []))
        self._on_engine_log(f"Audio listo: {len(devs.get('asio', []))} drivers ASIO, "
                            f"{len(devs.get('extra', []))} fuentes de Windows y {len(self.vst_list)} plugins VST3.", "AUDIO")
        if self.settings_win is not None:
            self.settings_win.refresh()

    def refresh_audio_devices(self, then=None):
        def work():
            devs = self.audio_engine.list_devices()
            self.vst_list = scan_vst3(self.settings.get("vst_dirs", []))
            self._ui(lambda: (setattr(self, "audio_devices", devs), then() if then else None))
        threading.Thread(target=work, daemon=True).start()

    def apply_audio_config(self):
        """Reabre dispositivos con la configuración actual (tras cambiar sistema de audio, dispositivo,
        frecuencia, búfer o fuentes de canal)."""
        if self.rec_state != "idle":
            self.notify.toast(t("audio.after_recording"), "warn")
            self._pending_audio_apply = True
            return
        self._persist_audio()
        self.render_mixer()
        self.lbl_audio_status.configure(text=t("ui.main.audio_aplicando_cambios"))

        def work():
            self.audio_engine.apply(wait=True)
        threading.Thread(target=work, daemon=True).start()

    # ---- Canales ----
    def add_channel(self, source=None, name=None) -> Dict:
        cfg = self.audio_engine.config
        n = len(cfg["channels"])
        if source is None:
            source = self._default_new_source()
        ch = new_channel(name or t("channel.default_name", n=n + 1), source, "mono" if source.get("kind") == "main" else "stereo",
                         color=CHANNEL_COLORS[n % len(CHANNEL_COLORS)])
        cfg["channels"].append(ch)
        self.apply_audio_config()
        return ch

    def _default_new_source(self) -> Dict:
        cfg = self.audio_engine.config
        used = {tuple(c["source"].get("ch", [])) for c in cfg["channels"] if c["source"].get("kind") == "main"}
        main_dev = cfg.get("asio_device") if cfg.get("driver") == "asio" else cfg.get("input_device")
        if main_dev:
            for i in range(8):
                if (i,) not in used:
                    return {"kind": "main", "ch": [i]}
        return {"kind": "none"}

    def _quick_add_channel(self):
        ch = self.add_channel()
        self._quick_channel = ch["id"]
        self.open_settings("channels", ch["id"])

    def remove_channel(self, cid):
        cfg = self.audio_engine.config
        cfg["channels"] = [c for c in cfg["channels"] if c["id"] != cid]
        self.apply_audio_config()

    def move_channel(self, cid, delta):
        chans = self.audio_engine.config["channels"]
        i = next((k for k, c in enumerate(chans) if c["id"] == cid), None)
        j = (i or 0) + delta
        if i is None or not 0 <= j < len(chans):
            return
        chans[i], chans[j] = chans[j], chans[i]
        self.apply_audio_config()

    def set_channel_param(self, cid, key, value, persist=True):
        """Cambios en vivo (sin reabrir dispositivos): volumen, silencio, solo, monitor, modo, nombre."""
        self.audio_engine.set_param(cid, key, value)
        if persist:
            self._persist_audio()

    def set_channel_fx(self, cid, fx):
        self.audio_engine.set_fx(cid, fx)
        self._persist_audio()
        self._paint_strip(cid)

    def open_fx_editor(self, cid, fx_id):
        self.audio_engine.open_editor(cid, fx_id)
        self.notify.status(t("fx.opening"))

    def _on_fx_loaded(self, cid):
        self._paint_strip(cid)
        if self.settings_win is not None:
            self.settings_win.on_fx_loaded(cid)

    def _on_editor_state(self, cid, fx_id, is_open):
        ch = self.audio_engine.channel(cid)
        if is_open:
            self.notify.status(t("fx.editing", name=ch["name"] if ch else cid))
        else:
            self._persist_audio()
            self.notify.toast(t("fx.saved"))

    # ---- Mezclador de la pantalla principal ----
    def render_mixer(self):
        for w in self.strips_box.winfo_children():
            w.destroy()
        self.strips = {}
        chans = self.audio_engine.config.get("channels", [])
        if not chans:
            ctk.CTkLabel(self.strips_box, text=t("ui.main.sin_canales_pulsa_canal_para"),
                         font=self.F(12), text_color=C["faint"], wraplength=290, justify="left",
                         anchor="w").grid(row=0, column=0, sticky="ew", padx=6, pady=8)
        for i, ch in enumerate(chans):
            if not ch.get("color"):
                ch["color"] = CHANNEL_COLORS[i % len(CHANNEL_COLORS)]
            self.strips[ch["id"]] = self._build_strip(self.strips_box, ch, i)
        self._update_transport()

    def _build_strip(self, master, ch, row):
        cid = ch["id"]
        box = ctk.CTkFrame(master, fg_color=C["panel"], corner_radius=10)
        box.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        box.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        ctk.CTkFrame(top, width=8, height=8, corner_radius=2, fg_color=ch["color"]).pack(side="left", padx=(0, 8))
        name = ch["name"] if len(ch["name"]) <= 16 else ch["name"][:15] + "…"
        ctk.CTkLabel(top, text=name, font=self.F(13, "bold"), text_color=C["text"]).pack(side="left")

        def tb(text, cmd, width=28):
            return ctk.CTkButton(top, text=text, width=width, height=24, corner_radius=6, font=self.F(11, "bold"),
                                 border_width=1, command=cmd)
        b_m = tb("M", lambda: self._toggle_ch(cid, "mute"))
        b_m.pack(side="right")
        b_s = tb("S", lambda: self._toggle_ch(cid, "solo"))
        b_s.pack(side="right", padx=(0, 4))
        b_mon = tb("🎧", lambda: self._toggle_ch(cid, "monitor"), width=30)
        b_mon.pack(side="right", padx=(0, 4))
        b_fx = tb("FX", lambda: self.open_settings("channels", cid), width=34)
        b_fx.pack(side="right", padx=(0, 4))

        src = ctk.CTkButton(box, text=source_label(ch["source"], self.audio_engine.config), font=self.F(11), height=20,
                            anchor="w", fg_color="transparent", hover_color=C["raised"], text_color=C["muted"],
                            command=lambda: self.open_settings("channels", cid))
        src.grid(row=1, column=0, sticky="ew", padx=6)
        meter = ctk.CTkProgressBar(box, height=6, corner_radius=3, fg_color=C["line"], progress_color=C["ok"])
        meter.set(0)
        meter.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 2))
        bot = ctk.CTkFrame(box, fg_color="transparent")
        bot.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 8))
        bot.grid_columnconfigure(0, weight=1)
        vol = ctk.CTkSlider(bot, from_=0, to=1.5, number_of_steps=150, height=14, fg_color=C["line"],
                            progress_color=C["text2"], button_color=C["text"], button_hover_color="#FFFFFF",
                            command=lambda v: self._on_strip_volume(cid, v))
        vol.grid(row=0, column=0, sticky="ew")
        db = ctk.CTkLabel(bot, text="", font=self.F(11, mono=True), text_color=C["muted"], width=62)
        db.grid(row=0, column=1, padx=(4, 4))
        vol.set(float(ch.get("volume", 1.0)))
        db.configure(text=vol_to_db_text(float(ch.get("volume", 1.0))))
        strip = {"box": box, "m": b_m, "s": b_s, "mon": b_mon, "fx": b_fx, "src": src, "meter": meter, "vol": vol, "db": db}
        self._paint_strip(cid, strip)
        return strip

    def _paint_strip(self, cid, strip=None):
        strip = strip or self.strips.get(cid)
        ch = self.audio_engine.channel(cid)
        if not strip or not ch or not self._alive(strip["box"]):
            return

        def paint(btn, on, color):
            btn.configure(fg_color=color if on else "transparent", hover_color=C["raised"],
                          border_color=color if on else C["line2"], text_color="#FFFFFF" if on else C["muted"])
        paint(strip["m"], ch.get("mute"), C["rec"])
        paint(strip["s"], ch.get("solo"), "#B0892F")
        paint(strip["mon"], ch.get("monitor"), "#2F7A57")
        n_fx = len(ch.get("fx", []))
        status = self.audio_engine.fx_status.get(cid, [])
        err = any(f.get("error") for f in status)
        strip["fx"].configure(text=f"FX{n_fx}" if n_fx else "FX")
        paint(strip["fx"], n_fx > 0, C["warn"] if err else "#4A5BA8")
        err_ch = (self.audio_stats.get("channel_errors") or {}).get(cid)
        strip["src"].configure(text=("⚠ " + err_ch) if err_ch else source_label(ch["source"], self.audio_engine.config),
                               text_color=C["warn"] if err_ch else C["muted"])

    def _toggle_ch(self, cid, key):
        ch = self.audio_engine.channel(cid)
        if not ch:
            return
        self.set_channel_param(cid, key, not ch.get(key, False))
        self._paint_strip(cid)
        if self.rec_state == "recording":
            self._update_transport()
        if self.settings_win is not None:
            self.settings_win.refresh("channels")

    def _on_strip_volume(self, cid, v):
        v = float(v)
        self.set_channel_param(cid, "volume", round(v, 3), persist=False)
        strip = self.strips.get(cid)
        if strip:
            strip["db"].configure(text=vol_to_db_text(v))
        if self.pending_save:
            self.after_cancel(self.pending_save)
        self.pending_save = self.after(800, self._persist_audio)

    def _on_monitor_volume(self, v, save=True):
        v = float(v)
        self.lbl_mon_db.configure(text=vol_to_db_text(v))
        if save:
            self.audio_engine.set_master(monitor_volume=round(v, 3))
            if self.pending_save:
                self.after_cancel(self.pending_save)
            self.pending_save = self.after(800, self._persist_audio)

    def _on_audio_stats(self, st):
        self.audio_stats = st
        if st.get("error"):
            txt = t("audio.status.error")          # el detalle técnico ya está en el registro
            self.notify.banner("audio", t("audio.device_error"), "warn",
                               actions=[(t("action.audio_settings"), lambda: self.open_settings("audio"))])
        elif not st.get("running"):
            txt = t("ui.main.audio_detenido")
            self.notify.clear("audio")
        else:
            drv = "ASIO" if st.get("driver") == "asio" else t("ui.main.windows_audio")
            lat = (st.get("latency_in") or 0) + (st.get("latency_out") or 0)
            dev = st.get("input") or st.get("output") or t("ui.main.sin_dispositivo_principal")
            dev = dev if len(dev) < 22 else dev[:21] + "…"
            lat_txt = f" · {lat:.1f} ms" if lat else ""
            xr = t("audio.status.xruns", n=st['xruns']) if st.get("xruns") else ""
            txt = f"{drv} · {dev}{lat_txt} · CPU {st.get('cpu', 0):.0f}%{xr}"
            self.notify.clear("audio")
        self.lbl_audio_status.configure(text=txt, text_color=C["warn"] if st.get("error") else C["muted"])
        for cid in self.strips:
            self._paint_strip(cid)
        if self.settings_win is not None:
            self.settings_win.on_stats(st)

    def _on_audio_levels(self, ch_db, mst_db, mon_db):
        def upd():
            for cid, strip in self.strips.items():
                db = ch_db.get(cid, -90.0)
                lvl = max(0.0, min(1.0, (db + 60) / 60))
                try:
                    strip["meter"].set(lvl)
                    strip["meter"].configure(progress_color=C["accent"] if lvl > 0.92 else C["ok"])
                except (KeyError, AttributeError, RuntimeError):
                    pass
            m = max(0.0, min(1.0, (mst_db + 60) / 60))
            self.meter_master.set(m)
            if m >= 0.98:
                self.clip_hold_until = time.time() + 1.5
            clip = time.time() < self.clip_hold_until
            self.meter_master.configure(progress_color=C["accent"] if m > 0.92 else C["ok"])
            self.clip_badge.configure(fg_color=C["rec"] if clip else C["line"], text_color="#FFFFFF" if clip else C["off"])
            self.meter_monitor.set(max(0.0, min(1.0, (mon_db + 60) / 60)))
        try:
            self._ui(upd)
        except (AttributeError, RuntimeError):
            pass

    # =========================================================================
    # CONFIGURACIÓN
    # =========================================================================
    def open_settings(self, section: str = "general", channel_id: Optional[str] = None):
        from settings_window import SettingsWindow
        if self.settings_win is None or not self._alive(self.settings_win):
            self.settings_win = SettingsWindow(self)
        self.settings_win.show(section, channel_id)

    def _on_settings_closed(self):
        self.settings_win = None
        quick = getattr(self, "_quick_channel", None)
        self._quick_channel = None
        ch = self.audio_engine.channel(quick) if quick else None
        if ch and ch["source"].get("kind") in (None, "none") and not ch.get("fx"):
            self.remove_channel(quick)      # se agregó con «+ Canal» y nunca tuvo fuente
        self.dev_body = self.dev_kind_tag = self.music_tip = self.image_box = None
        self.lbl_saved_for = self.image_note = self.lbl_dir = self.lbl_sync = self.slider_sync = None
        self.preset_buttons, self.sliders, self.norm_buttons = {}, {}, {}

    # =========================================================================
    # SALIDA
    # =========================================================================
    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.record_dir_var.get(), title=t("ui.main.carpeta_para_las_grabaciones"))
        if d:
            self.record_dir_var.set(os.path.normpath(d))
            self.notify.clear("rec")      # los avisos de carpeta o de disco eran de la anterior
            self.notify.clear("disk")
            self._paint_dir()
            self._save_settings()
            self._refresh_takes()
            self._update_transport()

    def _paint_dir(self):
        if self._alive(self.lbl_dir):
            self.lbl_dir.configure(text=f"  {self._short_dir()}")

    def _pick_norm(self, key):
        self.norm_mode = key
        self._paint_norm()
        self._save_settings()

    def _paint_norm(self):
        if not self.norm_buttons or not self._alive(next(iter(self.norm_buttons.values()))):
            return
        for k, b in self.norm_buttons.items():
            on = k == self.norm_mode
            b.configure(fg_color=C["accent_bg"] if on else C["panel"], hover_color=C["raised"],
                        border_color=C["accent"] if on else C["line"])

    def _on_sync(self, v, save=True):
        self.sync_ms = int(round(float(v) / 10) * 10)
        if self._alive(self.lbl_sync):
            self.lbl_sync.configure(text=f"{self.sync_ms:+d} ms" if self.sync_ms else "0 ms")
        if save:
            self._save_settings()

    def open_recordings_folder(self):
        d = self.record_dir_var.get()
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    # =========================================================================
    # DISPOSITIVO: acciones específicas
    # =========================================================================
    def _open_hardware_dialog(self):
        s = self._selected()
        if not s or not s.device_name:
            return
        if not self.engine.open_camera_hardware_dialog(s.device_name):
            self.notify.toast(t("hw.failed"), "warn")
        else:
            self.notify.status(t("hw.opened"))

    def _wifi_candidate(self) -> Optional[Source]:
        """Teléfono Android listo y conectado por cable: el elegido, o el primero que haya."""
        s = self._selected()
        if s and s.kind == "android" and s.ready and not s.is_wifi:
            return s
        return next((x for x in self.sources if x.kind == "android" and x.ready and not x.is_wifi), None)

    def activate_wireless_mode(self):
        s = self._wifi_candidate()
        if not s:
            self._set_connect_status(t("wifi.need_cable"))
            self.notify.toast(t("wifi.need_cable"), "warn")
            return
        self.notify.status(t("wifi.configuring"))
        self._set_connect_status(t("wifi.configuring"))

        def done(res):
            self._on_engine_log(res.get("message", ""), "WIFI")     # el detalle, al registro
            if res.get("success"):
                # Se recuerda para reconectar sin cable (si se corta o al reabrir la app), y
                # si ese teléfono era el elegido, la imagen pasa sola a su conexión Wi‑Fi.
                self.settings.setdefault("wifi_endpoints", {})[s.serial] = res["endpoint"]
                self._save_settings()
                if self.selected_id == s.id:
                    self._pending_select = f"adb:{res['endpoint']}"
                self.notify.clear("wifi")
                self.notify.toast(t("wifi.ok"))
                self._set_connect_status(t("wifi.ok"))
            else:
                reason = res.get("reason")
                text = {"no_ip": t("wifi.no_ip"),
                        "other_network": t("wifi.other_network", phone=res.get("ip", "?"),
                                            pc=", ".join(res.get("pc_ips") or []) or "?"),
                        "unreachable": t("wifi.unreachable", phone=res.get("ip", "?"))}.get(reason, t("wifi.failed"))
                self.notify.banner("wifi", text, "warn", actions=[(t("action.retry"), self.activate_wireless_mode)])
                self._set_connect_status(text)
            self._force_rescan()

        def work():
            res = self.engine.setup_wireless_mode(s.serial)
            self._ui(lambda: done(res))
        threading.Thread(target=work, daemon=True).start()

    def run_speed_test(self):
        s = self._selected()
        if not s or not s.serial:
            return
        self.btn_speed.configure(text=t("ui.main.probando_el_cable"), state="disabled")

        def work():
            res = self.engine.test_cable_speed(s.serial, size_mb=3)

            def done():
                try:
                    self.btn_speed.configure(text=t("ui.main.probar_velocidad_del_cable"), state="normal")
                    if res.get("success"):
                        self.lbl_speed.configure(text=f"{res['speed_mb_s']} MB/s · {res['classification']}", text_color=C["text2"])
                    else:
                        self.lbl_speed.configure(text=res.get("message", t("ui.main.no_se_pudo_medir")), text_color=C["warn"])
                except (AttributeError, RuntimeError):
                    pass
            self._ui(done)
        threading.Thread(target=work, daemon=True).start()

    # =========================================================================
    # REGISTRO, ESTADO Y AJUSTES
    # =========================================================================
    def _on_engine_log(self, text, category="INFO"):
        cat = (category or "INFO").upper()

        def ins():
            try:
                self.console.insert("end", text + "\n")
                if int(self.console.index("end-1c").split(".")[0]) > 2000:
                    self.console.delete("1.0", "500.0")
                self.console.see("end")
            except (AttributeError, RuntimeError):
                return
            # El registro técnico no sale en pantalla: los avisos para la persona los da
            # el Notifier con textos del catálogo. Un error solo marca el botón del registro.
            if cat == "ERROR" and not self.log_open:
                self.btn_log.configure(text=t("ui.main.registro_y_diagnostico_2"), text_color=C["warn"])
        try:
            self._ui(ins)
        except (AttributeError, RuntimeError):
            pass

    def _status(self, text, warn=False):
        clean = "".join(ch for ch in text if ord(ch) < 0x2600 or ch in "‑–—…«»")
        self.footer_text.configure(text=clean.strip()[:140])
        self.footer_dot.configure(text_color=C["warn"] if warn else C["ok"])

    def _open_log(self):
        if not self.log_open:
            self.toggle_log()

    def toggle_log(self):
        self.log_open = not self.log_open
        if self.log_open:
            self.btn_log.configure(text=t("ui.main.registro_y_diagnostico"), text_color=C["text2"])
            self.takes_panel.grid_remove()
            self.log_panel.grid(row=0, column=0, sticky="nsew")
        else:
            self.log_panel.grid_remove()
            self.takes_panel.grid()

    def copy_logs_to_clipboard(self):
        self.clipboard_clear()
        self.clipboard_append(self.console.get("1.0", "end-1c"))
        self.notify.toast(t("log.copied"), "info")

    def show_report_dialog(self):
        dialog = ctk.CTkInputDialog(text=t("ui.main.cuentanos_que_paso_que_hiciste"), title=t("ui.main.reportar_un_problema"))
        notes = dialog.get_input()
        if notes is None:
            return
        s = self._selected()
        cfg = self._stream_config() if s else {}
        res = self.engine.save_problem_report(notes, cfg)
        if res.get("success"):
            self.clipboard_clear()
            self.clipboard_append(res["clipboard_text"])
            self.notify.banner("report", t("report.ready", id=res["report_id"]), "success",
                               actions=[(t("action.reveal"), lambda p=res["file_path"]: self._reveal(p))])

    def _check_binaries(self):
        missing = []
        if not self.engine.ffmpeg_path:
            missing.append(t("missing.ffmpeg"))
        if not self.engine.scrcpy_path:
            missing.append(t("missing.scrcpy"))
        if missing:
            self.notify.banner("missing", t("missing.components", items=", ".join(missing)), "error",
                               dismissible=False)

    def _load_settings(self) -> Dict:
        return paths.load_json(settings_path(), {})

    def _save_settings(self):
        s = self.settings
        s.update({
            "record_dir": self.record_dir_var.get(), "prefix": self.record_prefix_var.get(),
            "normalize": self.norm_mode, "sync_ms": self.sync_ms, "stems": self.opt_stems.get(),
            "reveal": self.opt_reveal.get(), "autoplay": self.opt_autoplay.get(),
            "summary": self.opt_summary.get(), "multitrack": self.opt_multitrack.get(),
        })
        for old in ("audio_dev", "vol", "mode", "sample_rate", "buffer", "virtual_cam"):
            s.pop(old, None)                    # claves de la versión anterior, ya migradas
        paths.save_json(settings_path(), s)

    def on_closing(self):
        """Cerrar la ventana cierra la app por completo, siempre tras confirmarlo."""
        if self.rec_state == "saving":
            self.notify.toast(t("rec.wait_saving"), "warn")
            return
        vcam_note = t("close.body", vcam=virtualcam.DEVICE_NAME)
        if self.rec_state in ("recording", "starting"):
            ans = ConfirmDialog.ask(self, t("close.recording.title"), t("close.recording.body", note=vcam_note),
                                    [("cancel", t("action.cancel"), "ghost"),
                                     ("discard", t("close.recording.discard"), "danger"),
                                     ("save", t("close.recording.save"), "primary")], self.F)
            if ans == "save":
                self.stop_recording_session(then=self._shutdown)
            elif ans == "discard":
                self._shutdown()
            return
        ans = ConfirmDialog.ask(self, t("close.title"), vcam_note,
                                [("cancel", t("action.cancel"), "ghost"), ("close", t("action.close"), "primary")],
                                self.F)
        if ans == "close":
            self._shutdown()

    def _shutdown(self):
        self.running = False
        self.scan_force.set()

        # 1. Desvincular ventana incrustada antes de cerrar Tkinter
        if getattr(self, "monitor_hwnd", None):
            try:
                GLOBAL_WINDOW_EMBEDDER.detach_window(self.monitor_hwnd)
                self.monitor_hwnd = None
            except Exception as e:
                GLOBAL_LOGGER.log(f"Aviso al desvincular monitor: {e}", "WARN")

        # 2. Detener stream de video y liberar cámara web DirectShow (lo pendiente se descarta)
        try:
            self.stream_gen += 1
            self._stream_jobs.shutdown(wait=False, cancel_futures=True)
            self.engine.stop_stream()
        except Exception as e:
            GLOBAL_LOGGER.error(f"Error deteniendo motor de video: {e}", e, "ERROR")

        # 3. Detener cámara virtual de Windows
        try:
            virtualcam.SERVICE.stop()
        except Exception as e:
            GLOBAL_LOGGER.log(f"Aviso deteniendo cámara virtual: {e}", "WARN")

        # 4. Recopilar estados y guardar configuración
        try:
            self.audio_engine.close_editor()
            self.audio_engine.collect_fx_states()
        except Exception as e:
            GLOBAL_LOGGER.debug(f"Aviso al recopilar estado de efectos en shutdown: {e}")
        self.settings["audio"] = self.audio_engine.config
        self._save_settings()

        if self.settings_win is not None:
            try:
                self.settings_win.destroy()
            except Exception as e:
                GLOBAL_LOGGER.debug(f"Aviso al cerrar ventana de ajustes en shutdown: {e}")

        # 5. Detener motor de audio
        try:
            self.audio_engine.stop()
        except Exception as e:
            GLOBAL_LOGGER.warn(f"Aviso al detener motor de audio en shutdown: {e}")

        # 6. Destruir interfaz gráfica
        try:
            self.destroy()
        except Exception as e:
            GLOBAL_LOGGER.debug(f"Aviso al destruir ventana principal: {e}")


if __name__ == "__main__":
    app = GalaxyCamApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
