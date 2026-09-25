"""
UltraCam Studio Pro - Interfaz Gráfica de Estudio Integrada (Android 12+ & iPhone iOS)
Monitor de video 100% integrado dentro de la app (Win32 SetParent, cero ventanas emergentes),
Mezclador de audio profesional multi-entrada (Audio del Sistema + Entrada 1 + Entrada 2 + Master),
Suite de post-grabación multipista (MP4, Stems WAV, EBU R128) y diagnóstico con IA.
"""

import os
import sys
import threading
import time
import subprocess
import datetime
import webbrowser
import json
import re
from typing import List, Optional, Dict
import customtkinter as ctk
from tkinter import messagebox, filedialog
from engine import CameraEngine
from audio_engine import AudioEngine

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class GalaxyCamApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("UltraCam Studio Pro - Universal Mobile 4K & Audio Studio")
        self.geometry("1240x890")
        self.minsize(1100, 780)

        # Motores de backend
        self.engine = CameraEngine()
        self.engine.on_log_callback = self.append_process_log
        
        self.audio_engine = AudioEngine()
        self.audio_engine.on_levels_callback = self._on_audio_levels_update
        self.audio_engine.on_log_callback = self.append_process_log

        # Estado de streaming y plataforma
        self.active_platform = "pc"  # "pc", "android", "ios"
        self.connected_devices = []
        self.selected_device = None
        self.selected_camera_name: Optional[str] = None
        self.active_pixel_format: Optional[str] = None
        self.pc_cameras_cache: List[Dict] = []
        
        self.is_monitoring = True
        self.benchmark_running = False
        self.is_recording = False
        self.record_start_time = None
        self.timer_running = False
        self.temp_video_path = None
        self.is_embedded = False
        
        # Filtros de imagen en tiempo real (ProcAmp)
        self.brightness_val = 0.0
        self.contrast_val = 1.0
        self.saturation_val = 1.0
        self.sharpness_val = 0.0
        
        # Rutas y configuración de grabación
        default_videos_dir = os.path.join(os.path.expanduser("~"), "Videos", "GalaxyCam")
        self.record_dir_var = ctk.StringVar(value=default_videos_dir)
        self.record_prefix_var = ctk.StringVar(value="UltraCam_Session")
        
        # Opciones de post-grabación
        self.opt_reveal_explorer = ctk.BooleanVar(value=True)
        self.opt_auto_play = ctk.BooleanVar(value=False)
        self.opt_show_summary = ctk.BooleanVar(value=True)
        self.opt_embed_multitrack = ctk.BooleanVar(value=True)
        self.opt_export_stems = ctk.BooleanVar(value=False)
        self.opt_normalize_mode = ctk.StringVar(value="ebu_r128")
        self.sync_offset_ms_var = ctk.IntVar(value=0)

        # Opciones de video
        self.all_resolutions = [
            "1920x1080 (Full HD 1080p) - Estándar",
            "1280x720 (HD 720p) - Ligero",
            "3840x2160 (4K UHD) - Máxima Calidad",
            "2560x1440 (2K QHD) - Alta Definición",
            "640x480 (SD) - Económico"
        ]
        self.fps_options = [
            "30 FPS (Nativo / Estable)",
            "60 FPS (Ultra Fluido / Recomendado)",
            "24 FPS (Cinemático)"
        ]
        self.buffer_options = [
            "100 ms (Recomendado - Fluido y Estable)",
            "50 ms (Baja Latencia)",
            "200 ms (Ultra Estable - Cero Tirones)",
            "0 ms (Cero Latencia - Posible Jitter)"
        ]

        # Listas dinámicas de audio (Zero Hardcoding)
        self.audio_outputs_cache: List[Dict] = []
        self.audio_inputs_cache: List[Dict] = []

        self._create_layout()
        self._init_audio_system()
        self._start_device_monitor()
        self.refresh_cameras()

    # =========================================================================
    # CONSTRUCCIÓN DE LA INTERFAZ PRINCIPAL (UI/UX PRO MAX)
    # =========================================================================
    def _create_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Header
        self.grid_rowconfigure(1, weight=1)  # Tabs
        self.grid_rowconfigure(2, weight=0)  # Bottom Bar

        # 1. Header Superior
        self.header_frame = ctk.CTkFrame(self, height=54, corner_radius=0, fg_color="#121214")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        self.header_frame.grid_columnconfigure(0, weight=0)
        self.header_frame.grid_columnconfigure(1, weight=1)
        self.header_frame.grid_columnconfigure(2, weight=0)

        brand_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        brand_box.grid(row=0, column=0, sticky="w", padx=(18, 10), pady=6)
        ctk.CTkLabel(
            brand_box, text="UltraCam", 
            font=ctk.CTkFont(size=19, weight="bold"), text_color="#3b82f6"
        ).pack(side="left")
        ctk.CTkLabel(
            brand_box, text="Studio Pro", 
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#e4e4e7"
        ).pack(side="left", padx=(4, 0))

        # Selector de Plataforma
        self.platform_seg = ctk.CTkSegmentedButton(
            self.header_frame,
            values=["📷 Cámaras PC / Webcams", "📱 Móvil Android", "🍏 iPhone (iOS)"],
            command=self._on_platform_toggle,
            selected_color="#2563eb",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=30
        )
        self.platform_seg.set("📷 Cámaras PC / Webcams")
        self.platform_seg.grid(row=0, column=1, sticky="w", padx=20, pady=6)

        # Pastilla de Estado
        status_box = ctk.CTkFrame(self.header_frame, fg_color="#18181b", corner_radius=8)
        status_box.grid(row=0, column=2, sticky="e", padx=18, pady=6)

        self.dev_pill_icon = ctk.CTkLabel(status_box, text="●", font=ctk.CTkFont(size=14), text_color="#10b981")
        self.dev_pill_icon.pack(side="left", padx=(10, 4))
        
        self.dev_pill_text = ctk.CTkLabel(
            status_box, text="Iniciando cámaras...", 
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#e4e4e7"
        )
        self.dev_pill_text.pack(side="left", padx=(0, 6))

        self.dev_battery_lbl = ctk.CTkLabel(
            status_box, text="🔌 AC", 
            font=ctk.CTkFont(size=11), text_color="#a1a1aa"
        )
        self.dev_battery_lbl.pack(side="left", padx=(0, 10))

        # 2. Pestañas de Trabajo
        self.tabview = ctk.CTkTabview(
            self,
            fg_color="#09090b",
            segmented_button_fg_color="#18181b",
            segmented_button_selected_color="#2563eb",
            segmented_button_selected_hover_color="#1d4ed8"
        )
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=12, pady=(8, 4))

        self.tab_studio = self.tabview.add("🎛️ Estudio & Grabación")
        self.tab_camera = self.tabview.add("🎥 Control de Cámara & Calibración")
        self.tab_audio_config = self.tabview.add("🎚️ Configuración de Audio (DAW / OBS)")
        self.tab_post_rec = self.tabview.add("🎬 Post-Grabación & Exportación")
        self.tab_logs = self.tabview.add("📜 Diagnóstico & Logs")

        self._build_studio_tab()
        self._build_audio_config_tab()
        self._build_post_recording_tab()
        self._build_camera_tab()
        self._build_logs_tab()

        # 3. Barra Inferior
        self.bottom_bar = ctk.CTkFrame(self, height=32, corner_radius=0, fg_color="#121214")
        self.bottom_bar.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        self.bottom_bar.grid_columnconfigure(0, weight=1)
        self.bottom_bar.grid_columnconfigure(1, weight=0)

        self.lbl_bottom_info = ctk.CTkLabel(
            self.bottom_bar,
            text="Listo. Monitor integrado activo y captura de salida general lista.",
            font=ctk.CTkFont(size=11),
            text_color="#a1a1aa"
        )
        self.lbl_bottom_info.grid(row=0, column=0, sticky="w", padx=16, pady=4)

        self.btn_open_folder_quick = ctk.CTkButton(
            self.bottom_bar,
            text="📂 Abrir Carpeta de Videos",
            command=self.open_recordings_folder,
            fg_color="transparent",
            hover_color="#27272a",
            text_color="#60a5fa",
            font=ctk.CTkFont(size=11, weight="bold"),
            height=24
        )
        self.btn_open_folder_quick.grid(row=0, column=1, sticky="e", padx=16, pady=4)

    # =========================================================================
    # PESTAÑA 1: ESTUDIO & MONITOR DE VIDEO INTEGRADO (CERO VENTANAS EXTERNAS)
    # =========================================================================
    def _build_studio_tab(self):
        tab = self.tab_studio
        tab.grid_columnconfigure(0, weight=3)  # Monitor de Video
        tab.grid_columnconfigure(1, weight=2)  # Mezclador de Audio Multi-Canal
        tab.grid_rowconfigure(0, weight=1)

        # --- PANEL IZQUIERDO: MONITOR DE VIDEO INTEGRADO + DECK DE CONTROL ---
        monitor_panel = ctk.CTkFrame(tab, fg_color="#18181b", corner_radius=12)
        monitor_panel.grid(row=0, column=0, sticky="nsew", padx=(6, 6), pady=6)
        monitor_panel.grid_columnconfigure(0, weight=1)
        monitor_panel.grid_rowconfigure(1, weight=1)

        # Título del Monitor
        mon_header = ctk.CTkFrame(monitor_panel, fg_color="transparent", height=32)
        mon_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        ctk.CTkLabel(
            mon_header, text="📺 MONITOR DE VIDEO EN VIVO (INTEGRADO)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#60a5fa"
        ).pack(side="left")

        ctk.CTkButton(
            mon_header, text="⚙️ Calibrar Cámara",
            command=lambda: self.tabview.set("🎥 Control de Cámara & Calibración"),
            fg_color="#27272a", hover_color="#3f3f46", text_color="#60a5fa",
            font=ctk.CTkFont(size=11, weight="bold"), height=24, width=130
        ).pack(side="right")

        # CONTENEDOR DE VIDEO NATIVO (Win32 HWND)
        self.video_container = ctk.CTkFrame(
            monitor_panel,
            fg_color="#000000",
            corner_radius=8
        )
        self.video_container.grid(row=1, column=0, sticky="nsew", padx=14, pady=4)
        self.video_container.grid_columnconfigure(0, weight=1)
        self.video_container.grid_rowconfigure(0, weight=1)

        # Placeholder visible cuando la cámara está apagada
        self.lbl_video_placeholder = ctk.CTkLabel(
            self.video_container,
            text="📷 CÁMARA EN ESPERA\nPulsa 'Iniciar Cámara' para ver la transmisión integrada aquí",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#71717a",
            justify="center"
        )
        self.lbl_video_placeholder.grid(row=0, column=0, sticky="nsew")

        # Deck de Control de Grabación (Bajo el Monitor)
        deck_ctrl = ctk.CTkFrame(monitor_panel, fg_color="transparent")
        deck_ctrl.grid(row=2, column=0, sticky="ew", padx=14, pady=(8, 12))
        deck_ctrl.grid_columnconfigure((0, 1), weight=1)

        self.btn_stream = ctk.CTkButton(
            deck_ctrl,
            text="▶️ Iniciar Cámara",
            command=self.toggle_stream,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=44,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.btn_stream.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=4)

        self.btn_record = ctk.CTkButton(
            deck_ctrl,
            text="⏺️ INICIAR GRABACIÓN",
            command=self.toggle_recording,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            height=44,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.btn_record.grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=4)

        # Tarjeta de Estado del Timer
        timer_box = ctk.CTkFrame(deck_ctrl, fg_color="#09090b", corner_radius=8, height=36)
        timer_box.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        timer_box.grid_columnconfigure(1, weight=1)

        self.rec_dot = ctk.CTkLabel(timer_box, text="⏹️", font=ctk.CTkFont(size=14), text_color="#71717a")
        self.rec_dot.grid(row=0, column=0, padx=(10, 4), pady=4)

        self.lbl_rec_timer = ctk.CTkLabel(
            timer_box, text="00:00:00", 
            font=ctk.CTkFont(family="Consolas", size=16, weight="bold"), 
            text_color="#e4e4e7"
        )
        self.lbl_rec_timer.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        self.lbl_rec_info = ctk.CTkLabel(
            timer_box, text="En espera | Multipista listo",
            font=ctk.CTkFont(size=11), text_color="#a1a1aa"
        )
        self.lbl_rec_info.grid(row=0, column=2, sticky="e", padx=12, pady=4)

        # --- PANEL DERECHO: MEZCLADOR DE AUDIO MULTI-CANAL ESTILO DAW ---
        mixer_panel = ctk.CTkFrame(tab, fg_color="#18181b", corner_radius=12)
        mixer_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 6), pady=6)
        mixer_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            mixer_panel, text="🎚️ MEZCLADOR MULTI-CANAL ESTILO DAW",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#22c55e"
        ).pack(anchor="w", padx=16, pady=(12, 6))

        # 1. CANAL: AUDIO DEL SISTEMA (SALIDA GENERAL)
        ch_sys = ctk.CTkFrame(mixer_panel, fg_color="#09090b", corner_radius=8)
        ch_sys.pack(fill="x", padx=12, pady=4)

        head_sys = ctk.CTkFrame(ch_sys, fg_color="transparent")
        head_sys.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(head_sys, text="🔊 Audio del Sistema", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(side="left")
        self.lbl_sys_val = ctk.CTkLabel(head_sys, text="0.0 dB (100%)", font=ctk.CTkFont(size=10), text_color="#a1a1aa")
        self.lbl_sys_val.pack(side="right")

        self.meter_sys = ctk.CTkProgressBar(ch_sys, height=8, progress_color="#22c55e")
        self.meter_sys.set(0.0)
        self.meter_sys.pack(fill="x", padx=10, pady=2)

        ctrl_sys = ctk.CTkFrame(ch_sys, fg_color="transparent")
        ctrl_sys.pack(fill="x", padx=10, pady=(2, 6))
        self.slider_sys = ctk.CTkSlider(ctrl_sys, from_=0.0, to=1.5, number_of_steps=150, command=self._on_sys_slider_change, height=16)
        self.slider_sys.set(1.0)
        self.slider_sys.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_mute_sys = ctk.CTkButton(ctrl_sys, text="MUTE", width=46, height=22, command=self._toggle_mute_sys, fg_color="#3f3f46", font=ctk.CTkFont(size=9, weight="bold"))
        self.btn_mute_sys.pack(side="right")

        # 2. CANAL: ENTRADA FÍSICA 1 (IN 1)
        ch_in1 = ctk.CTkFrame(mixer_panel, fg_color="#09090b", corner_radius=8)
        ch_in1.pack(fill="x", padx=12, pady=4)

        head_in1 = ctk.CTkFrame(ch_in1, fg_color="transparent")
        head_in1.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(head_in1, text="🎙️ Entrada 1 (Instrumento / IN 1)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#a855f7").pack(side="left")
        self.lbl_in1_val = ctk.CTkLabel(head_in1, text="0.0 dB (100%)", font=ctk.CTkFont(size=10), text_color="#a1a1aa")
        self.lbl_in1_val.pack(side="right")

        self.meter_in1 = ctk.CTkProgressBar(ch_in1, height=8, progress_color="#a855f7")
        self.meter_in1.set(0.0)
        self.meter_in1.pack(fill="x", padx=10, pady=2)

        ctrl_in1 = ctk.CTkFrame(ch_in1, fg_color="transparent")
        ctrl_in1.pack(fill="x", padx=10, pady=(2, 6))
        self.slider_in1 = ctk.CTkSlider(ctrl_in1, from_=0.0, to=1.5, number_of_steps=150, command=self._on_in1_slider_change, height=16)
        self.slider_in1.set(1.0)
        self.slider_in1.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_mute_in1 = ctk.CTkButton(ctrl_in1, text="MUTE", width=46, height=22, command=self._toggle_mute_in1, fg_color="#3f3f46", font=ctk.CTkFont(size=9, weight="bold"))
        self.btn_mute_in1.pack(side="right")

        # 3. CANAL: ENTRADA FÍSICA 2 (IN 2)
        ch_in2 = ctk.CTkFrame(mixer_panel, fg_color="#09090b", corner_radius=8)
        ch_in2.pack(fill="x", padx=12, pady=4)

        head_in2 = ctk.CTkFrame(ch_in2, fg_color="transparent")
        head_in2.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(head_in2, text="🎙️ Entrada 2 (Micrófono / IN 2)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#ec4899").pack(side="left")
        self.lbl_in2_val = ctk.CTkLabel(head_in2, text="0.0 dB (100%)", font=ctk.CTkFont(size=10), text_color="#a1a1aa")
        self.lbl_in2_val.pack(side="right")

        self.meter_in2 = ctk.CTkProgressBar(ch_in2, height=8, progress_color="#ec4899")
        self.meter_in2.set(0.0)
        self.meter_in2.pack(fill="x", padx=10, pady=2)

        ctrl_in2 = ctk.CTkFrame(ch_in2, fg_color="transparent")
        ctrl_in2.pack(fill="x", padx=10, pady=(2, 6))
        self.slider_in2 = ctk.CTkSlider(ctrl_in2, from_=0.0, to=1.5, number_of_steps=150, command=self._on_in2_slider_change, height=16)
        self.slider_in2.set(1.0)
        self.slider_in2.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_mute_in2 = ctk.CTkButton(ctrl_in2, text="MUTE", width=46, height=22, command=self._toggle_mute_in2, fg_color="#3f3f46", font=ctk.CTkFont(size=9, weight="bold"))
        self.btn_mute_in2.pack(side="right")

        # 4. CANAL: MASTER MIX
        ch_mst = ctk.CTkFrame(mixer_panel, fg_color="#09090b", corner_radius=8)
        ch_mst.pack(fill="x", padx=12, pady=(4, 10))

        head_mst = ctk.CTkFrame(ch_mst, fg_color="transparent")
        head_mst.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(head_mst, text="🎚️ Master Mix (Salida Estéreo)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#e4e4e7").pack(side="left")
        self.clip_badge = ctk.CTkLabel(head_mst, text="CLIP", font=ctk.CTkFont(size=9, weight="bold"), text_color="#71717a", fg_color="#27272a", corner_radius=4, width=36)
        self.clip_badge.pack(side="right")

        self.meter_mst = ctk.CTkProgressBar(ch_mst, height=10, progress_color="#22c55e")
        self.meter_mst.set(0.0)
        self.meter_mst.pack(fill="x", padx=10, pady=(2, 8))

    # =========================================================================
    # PESTAÑA 2: CONFIGURACIÓN DE AUDIO (ESTILO OBS / REAPER)
    # =========================================================================
    def _build_audio_config_tab(self):
        tab = self.tab_audio_config
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        banner = ctk.CTkFrame(scroll, fg_color="#1e1b4b", corner_radius=10)
        banner.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            banner, text="🎚️ MATRIZ MULTI-ENTRADA DE AUDIO UNIVERSAL (WASAPI)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#a5b4fc"
        ).pack(anchor="w", padx=14, pady=(8, 2))
        ctk.CTkLabel(
            banner,
            text="Configura individualmente la salida general de tu PC y las múltiples entradas de tu interfaz "
                 "(Focusrite, Behringer, MOTU, etc.). Cada entrada cuenta con fader propio y centrado Dual-Mono.",
            font=ctk.CTkFont(size=11), text_color="#e0e7ff", wraplength=700, justify="left"
        ).pack(anchor="w", padx=14, pady=(0, 8))

        grp_devs = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_devs.pack(fill="x", pady=6)

        dev_head = ctk.CTkFrame(grp_devs, fg_color="transparent")
        dev_head.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(dev_head, text="ASIGNACIÓN DE DISPOSITIVOS DE HARDWARE", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(side="left")
        ctk.CTkButton(dev_head, text="🔄 Refrescar Dispositivos", command=self.refresh_audio_devices, height=26, width=160, fg_color="#3f3f46", font=ctk.CTkFont(size=11, weight="bold")).pack(side="right")

        # 1. Salida General del Sistema (Loopback)
        ctk.CTkLabel(grp_devs, text="Salida General del Sistema (Audio de la PC / Loopback):", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=14, pady=(8, 2))
        self.combo_audio_output = ctk.CTkComboBox(grp_devs, values=["Buscando..."], command=self._on_output_device_selected, height=30)
        self.combo_audio_output.pack(fill="x", padx=14, pady=(0, 8))

        # 2. Entrada Física 1
        ctk.CTkLabel(grp_devs, text="Entrada Física 1 (ej. Instrumento / Guitarra en IN 1):", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=14, pady=(6, 2))
        self.combo_in1 = ctk.CTkComboBox(grp_devs, values=["Buscando..."], command=self._on_in1_device_selected, height=30)
        self.combo_in1.pack(fill="x", padx=14, pady=(0, 8))

        # 3. Entrada Física 2
        ctk.CTkLabel(grp_devs, text="Entrada Física 2 (ej. Micrófono de Voz en IN 2):", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=14, pady=(6, 2))
        self.combo_in2 = ctk.CTkComboBox(grp_devs, values=["Buscando..."], command=self._on_in2_device_selected, height=30)
        self.combo_in2.pack(fill="x", padx=14, pady=(0, 14))

        # Parámetros y Centrado de Canales
        grp_p = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_p.pack(fill="x", pady=6)

        ctk.CTkLabel(grp_p, text="PARÁMETROS DE LATENCIA Y CENTRADO DUAL-MONO", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(anchor="w", padx=14, pady=(10, 8))

        grid_p = ctk.CTkFrame(grp_p, fg_color="transparent")
        grid_p.pack(fill="x", padx=14, pady=(0, 14))
        grid_p.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(grid_p, text="Frecuencia Master de Proyecto:", font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w", pady=2)
        self.combo_sr = ctk.CTkComboBox(grid_p, values=["48000 Hz (Estándar Estudio/Video)", "44100 Hz", "96000 Hz"], height=30)
        self.combo_sr.set("48000 Hz (Estándar Estudio/Video)")
        self.combo_sr.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))

        ctk.CTkLabel(grid_p, text="Búfer de Audio (Latencia):", font=ctk.CTkFont(size=11)).grid(row=0, column=1, sticky="w", pady=2)
        self.combo_abuf = ctk.CTkComboBox(grid_p, values=["1024 muestras (Recomendado)", "512 muestras", "256 muestras"], height=30)
        self.combo_abuf.set("1024 muestras (Recomendado)")
        self.combo_abuf.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        ctk.CTkLabel(grid_p, text="Modo de Canal para Entrada 1:", font=ctk.CTkFont(size=11)).grid(row=2, column=0, sticky="w", pady=2)
        self.combo_mode_in1 = ctk.CTkComboBox(grid_p, values=["Dual Mono / Centrado L+R", "Estéreo Nativo L/R"], command=self._on_in1_mode_change, height=30)
        self.combo_mode_in1.set("Dual Mono / Centrado L+R")
        self.combo_mode_in1.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))

        ctk.CTkLabel(grid_p, text="Modo de Canal para Entrada 2:", font=ctk.CTkFont(size=11)).grid(row=2, column=1, sticky="w", pady=2)
        self.combo_mode_in2 = ctk.CTkComboBox(grid_p, values=["Dual Mono / Centrado L+R", "Estéreo Nativo L/R"], command=self._on_in2_mode_change, height=30)
        self.combo_mode_in2.set("Dual Mono / Centrado L+R")
        self.combo_mode_in2.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        ctk.CTkCheckBox(
            grp_p, text="Embeber pistas múltiples en el MP4 (Pista 1: Master, Pista 2: Sistema, Pista 3: Entrada 1, Pista 4: Entrada 2)",
            variable=self.opt_embed_multitrack, font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=14, pady=(0, 12))

    # =========================================================================
    # PESTAÑA 3: POST-GRABACIÓN & EXPORTACIÓN
    # =========================================================================
    def _build_post_recording_tab(self):
        tab = self.tab_post_rec
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        grp_act = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_act.pack(fill="x", pady=6)
        ctk.CTkLabel(grp_act, text="ACCIONES AUTOMÁTICAS AL FINALIZAR LA GRABACIÓN", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(anchor="w", padx=14, pady=(10, 8))

        ctk.CTkCheckBox(grp_act, text="Abrir carpeta y seleccionar video en el Explorador de Windows", variable=self.opt_reveal_explorer, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=4)
        ctk.CTkCheckBox(grp_act, text="Reproducir video automáticamente al finalizar", variable=self.opt_auto_play, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=4)
        ctk.CTkCheckBox(grp_act, text="Mostrar ventana modal de resumen técnico de la sesión", variable=self.opt_show_summary, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=(4, 12))

        grp_stems = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_stems.pack(fill="x", pady=6)
        ctk.CTkLabel(grp_stems, text="EXPORTACIÓN DE STEMS INDEPENDIENTES (REAPER / PREMIERE)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(anchor="w", padx=14, pady=(10, 8))
        ctk.CTkCheckBox(grp_stems, text="Guardar archivos .WAV 24-bit / 48kHz limpios en subcarpeta 'stems/'", variable=self.opt_export_stems, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=(4, 12))

        grp_dsp = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_dsp.pack(fill="x", pady=6)
        ctk.CTkLabel(grp_dsp, text="PROCESAMIENTO DSP Y SINCRONIZACIÓN (FFMPEG)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(anchor="w", padx=14, pady=(10, 8))

        ctk.CTkLabel(grp_dsp, text="Normalización de Volumen:", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=14, pady=(4, 2))
        combo_norm = ctk.CTkComboBox(
            grp_dsp,
            values=[
                "Normalización EBU R128 (-14 LUFS - Estándar YouTube/Streaming)",
                "Peak Normalization (-1.0 dBFS)",
                "Sin Normalización"
            ],
            command=self._on_normalize_change, height=30
        )
        combo_norm.set("Normalización EBU R128 (-14 LUFS - Estándar YouTube/Streaming)")
        combo_norm.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(grp_dsp, text="Compensación de Sincronización A/V (ms):", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=14, pady=(4, 2))
        sync_box = ctk.CTkFrame(grp_dsp, fg_color="transparent")
        sync_box.pack(fill="x", padx=14, pady=(0, 14))

        self.slider_sync = ctk.CTkSlider(sync_box, from_=-300, to=300, number_of_steps=60, command=self._on_sync_slider_change, height=18)
        self.slider_sync.set(0)
        self.slider_sync.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.lbl_sync_val = ctk.CTkLabel(sync_box, text="0 ms", font=ctk.CTkFont(size=11, weight="bold"), width=50)
        self.lbl_sync_val.pack(side="right")

    # =========================================================================
    # PESTAÑA 2: CONTROL DE CÁMARA & CALIBRACIÓN PRO
    # =========================================================================
    def _build_camera_tab(self):
        tab = self.tab_camera
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        # --- 1. SELECCIÓN UNIVERSAL DE CÁMARA ---
        grp_source = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_source.pack(fill="x", pady=6)
        
        src_head = ctk.CTkFrame(grp_source, fg_color="transparent")
        src_head.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(
            src_head, text="FUENTE DE VIDEO & DETECCIÓN UNIVERSAL", 
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa"
        ).pack(side="left")

        box_src = ctk.CTkFrame(grp_source, fg_color="transparent")
        box_src.pack(fill="x", padx=14, pady=(0, 10))
        box_src.grid_columnconfigure(0, weight=3)
        box_src.grid_columnconfigure(1, weight=1)
        box_src.grid_columnconfigure(2, weight=2)

        ctk.CTkLabel(box_src, text="Cámara / Dispositivo Seleccionado:", font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w", pady=2)
        self.combo_cameras = ctk.CTkComboBox(box_src, values=["Buscando cámaras..."], command=self._on_camera_device_changed, height=32)
        self.combo_cameras.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=2)

        self.btn_refresh_cams = ctk.CTkButton(
            box_src, text="🔄 Detectar Cámaras", 
            command=self.refresh_cameras, 
            fg_color="#3f3f46", hover_color="#52525b", height=32, font=ctk.CTkFont(size=11, weight="bold")
        )
        self.btn_refresh_cams.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=2)

        self.btn_hw_dialog = ctk.CTkButton(
            box_src, text="⚙️ Propiedades de Hardware", 
            command=self._open_hardware_dialog, 
            fg_color="#2563eb", hover_color="#1d4ed8", height=32, font=ctk.CTkFont(size=11, weight="bold")
        )
        self.btn_hw_dialog.grid(row=1, column=2, sticky="ew", pady=2)

        self.lbl_hw_hint = ctk.CTkLabel(
            grp_source, 
            text="💡 'Propiedades de Hardware' abre el panel de Windows/driver para fijar Exposición, Balance de Blancos y Enfoque manual en el sensor.",
            font=ctk.CTkFont(size=10), text_color="#a1a1aa", justify="left"
        )
        self.lbl_hw_hint.pack(anchor="w", padx=14, pady=(0, 10))

        # --- 2. RESOLUCIÓN, FPS Y FORMATO NATIVO ÓPTIMO ---
        grp_res = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_res.pack(fill="x", pady=6)
        
        ctk.CTkLabel(
            grp_res, text="RESOLUCIÓN Y TASA DE CUADROS ÓPTIMAS (SONDEO DINÁMICO)", 
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa"
        ).pack(anchor="w", padx=14, pady=(10, 4))

        box_res = ctk.CTkFrame(grp_res, fg_color="transparent")
        box_res.pack(fill="x", padx=14, pady=(0, 10))
        box_res.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkLabel(box_res, text="Resolución Nativa Soportada:", font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w", pady=2)
        self.combo_res = ctk.CTkComboBox(box_res, values=self.all_resolutions, height=30)
        self.combo_res.set(self.all_resolutions[0])
        self.combo_res.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=2)

        ctk.CTkLabel(box_res, text="Tasa de Cuadros (FPS):", font=ctk.CTkFont(size=11)).grid(row=0, column=1, sticky="w", pady=2)
        self.combo_fps = ctk.CTkComboBox(box_res, values=self.fps_options, height=30)
        self.combo_fps.set(self.fps_options[0])
        self.combo_fps.grid(row=1, column=1, sticky="ew", padx=6, pady=2)

        ctk.CTkLabel(box_res, text="Búfer Anti-Lag de Video:", font=ctk.CTkFont(size=11)).grid(row=0, column=2, sticky="w", pady=2)
        self.combo_buf = ctk.CTkComboBox(box_res, values=self.buffer_options, height=30)
        self.combo_buf.set(self.buffer_options[0])
        self.combo_buf.grid(row=1, column=2, sticky="ew", padx=(6, 0), pady=2)

        self.lbl_codec_pill = ctk.CTkLabel(
            grp_res, text="Códec Óptimo: MJPEG / H.265 (Garantiza máxima fluidez sin saturar el bus USB)",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#10b981"
        )
        self.lbl_codec_pill.pack(anchor="w", padx=14, pady=(0, 10))

        # --- 3. PRESETS DE ESTUDIO ("LAS MEJORES CONFIGURACIONES") ---
        grp_presets = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_presets.pack(fill="x", pady=6)
        
        ctk.CTkLabel(
            grp_presets, text="PRESETS DE ESTUDIO (MEJORES CONFIGURACIONES EN 1 CLIC)", 
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa"
        ).pack(anchor="w", padx=14, pady=(10, 6))

        box_presets = ctk.CTkFrame(grp_presets, fg_color="transparent")
        box_presets.pack(fill="x", padx=14, pady=(0, 12))
        box_presets.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkButton(
            box_presets, text="🌟 Studio Pro", command=self.apply_preset_studio_pro,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=11, weight="bold"), height=34
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

        ctk.CTkButton(
            box_presets, text="⚡ Fluidez 60 FPS", command=self.apply_preset_60fps,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=11, weight="bold"), height=34
        ).grid(row=0, column=1, sticky="ew", padx=4)

        ctk.CTkButton(
            box_presets, text="🎸 Músico Performance", command=self.apply_preset_musician,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=11, weight="bold"), height=34
        ).grid(row=0, column=2, sticky="ew", padx=4)

        ctk.CTkButton(
            box_presets, text="🌙 Baja Luz", command=self.apply_preset_low_light,
            fg_color="#1e293b", hover_color="#334155", font=ctk.CTkFont(size=11, weight="bold"), height=34
        ).grid(row=0, column=3, sticky="ew", padx=(4, 0))

        # --- 4. CALIBRACIÓN DE IMAGEN EN TIEMPO REAL (FILTROS PROCAMP) ---
        grp_procamp = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_procamp.pack(fill="x", pady=6)
        
        proc_head = ctk.CTkFrame(grp_procamp, fg_color="transparent")
        proc_head.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(
            proc_head, text="CALIBRACIÓN DE IMAGEN EN TIEMPO REAL (FILTROS DE VIDEO)", 
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa"
        ).pack(side="left")

        ctk.CTkButton(
            proc_head, text="🔄 Restablecer Filtros", command=self.reset_procamp_filters,
            width=130, height=24, fg_color="#3f3f46", font=ctk.CTkFont(size=10)
        ).pack(side="right")

        box_proc = ctk.CTkFrame(grp_procamp, fg_color="transparent")
        box_proc.pack(fill="x", padx=14, pady=(0, 10))
        box_proc.grid_columnconfigure((0, 1), weight=1)

        # Brillo
        ctk.CTkLabel(box_proc, text="Brillo (Luminosidad):", font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        b_frame = ctk.CTkFrame(box_proc, fg_color="transparent")
        b_frame.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(0, 6))
        self.slider_brightness = ctk.CTkSlider(b_frame, from_=-0.5, to=0.5, number_of_steps=50, command=self._on_brightness_change)
        self.slider_brightness.set(0.0)
        self.slider_brightness.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.lbl_brightness_val = ctk.CTkLabel(b_frame, text="0.00", font=ctk.CTkFont(size=11, weight="bold"), width=42)
        self.lbl_brightness_val.pack(side="right")

        # Contraste
        ctk.CTkLabel(box_proc, text="Contraste:", font=ctk.CTkFont(size=11)).grid(row=0, column=1, sticky="w", padx=(6, 0), pady=(4, 0))
        c_frame = ctk.CTkFrame(box_proc, fg_color="transparent")
        c_frame.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(0, 6))
        self.slider_contrast = ctk.CTkSlider(c_frame, from_=0.5, to=2.0, number_of_steps=60, command=self._on_contrast_change)
        self.slider_contrast.set(1.0)
        self.slider_contrast.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.lbl_contrast_val = ctk.CTkLabel(c_frame, text="1.00x", font=ctk.CTkFont(size=11, weight="bold"), width=42)
        self.lbl_contrast_val.pack(side="right")

        # Saturación
        ctk.CTkLabel(box_proc, text="Saturación de Color:", font=ctk.CTkFont(size=11)).grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        s_frame = ctk.CTkFrame(box_proc, fg_color="transparent")
        s_frame.grid(row=3, column=0, sticky="ew", padx=(0, 6), pady=(0, 6))
        self.slider_saturation = ctk.CTkSlider(s_frame, from_=0.0, to=2.0, number_of_steps=50, command=self._on_saturation_change)
        self.slider_saturation.set(1.0)
        self.slider_saturation.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.lbl_saturation_val = ctk.CTkLabel(s_frame, text="1.00x", font=ctk.CTkFont(size=11, weight="bold"), width=42)
        self.lbl_saturation_val.pack(side="right")

        # Nitidez (Sharpness)
        ctk.CTkLabel(box_proc, text="Nitidez / Realce de Bordes:", font=ctk.CTkFont(size=11)).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(4, 0))
        sh_frame = ctk.CTkFrame(box_proc, fg_color="transparent")
        sh_frame.grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=(0, 6))
        self.slider_sharpness = ctk.CTkSlider(sh_frame, from_=0.0, to=5.0, number_of_steps=50, command=self._on_sharpness_change)
        self.slider_sharpness.set(0.0)
        self.slider_sharpness.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.lbl_sharpness_val = ctk.CTkLabel(sh_frame, text="0.0 (Neutro)", font=ctk.CTkFont(size=11, weight="bold"), width=70)
        self.lbl_sharpness_val.pack(side="right")

        # Botón Guardar Preset
        ctk.CTkButton(
            grp_procamp, text="💾 Guardar como Mi Configuración Predeterminada para esta Cámara",
            command=self.save_current_camera_preset, fg_color="#15803d", hover_color="#166534",
            height=32, font=ctk.CTkFont(size=11, weight="bold")
        ).pack(fill="x", padx=14, pady=(6, 12))

        # --- 5. CALIBRACIÓN DE ENLACE PARA MÓVILES (USB / WI-FI) ---
        grp_link = ctk.CTkFrame(scroll, fg_color="#18181b", corner_radius=10)
        grp_link.pack(fill="x", pady=6)
        ctk.CTkLabel(grp_link, text="HERRAMIENTAS PARA MÓVILES ANDROID (USB / WI-FI 6)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").pack(anchor="w", padx=14, pady=(10, 6))

        box_link = ctk.CTkFrame(grp_link, fg_color="transparent")
        box_link.pack(fill="x", padx=14, pady=(0, 12))
        box_link.grid_columnconfigure((0, 1), weight=1)

        self.btn_speed_test = ctk.CTkButton(box_link, text="⚡ Probar Velocidad Cable USB", command=self.run_manual_speed_test, fg_color="#3f3f46", height=32, font=ctk.CTkFont(size=11, weight="bold"))
        self.btn_speed_test.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.btn_wifi_mode = ctk.CTkButton(box_link, text="📶 Conectar por Wi-Fi 6", command=self.activate_wireless_mode, fg_color="#4f46e5", hover_color="#4338ca", height=32, font=ctk.CTkFont(size=11, weight="bold"))
        self.btn_wifi_mode.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    # =========================================================================
    # PESTAÑA 5: DIAGNÓSTICO & LOGS
    # =========================================================================
    def _build_logs_tab(self):
        tab = self.tab_logs
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=0)
        tab.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(tab, fg_color="transparent", height=36)
        bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 4))
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_columnconfigure((1, 2, 3), weight=0)

        ctk.CTkLabel(bar, text="REGISTRO DE ERRORES Y DIAGNÓSTICO", font=ctk.CTkFont(size=11, weight="bold"), text_color="#60a5fa").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(bar, text="📋 Copiar Logs", command=self.copy_logs_to_clipboard, width=100, height=26, fg_color="#3f3f46", font=ctk.CTkFont(size=11)).grid(row=0, column=1, padx=4)
        ctk.CTkButton(bar, text="🧹 Limpiar", command=self.clear_logs, width=80, height=26, fg_color="#3f3f46", font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=4)
        ctk.CTkButton(bar, text="🚨 Reportar con IA", command=self.show_report_dialog, width=130, height=26, fg_color="#dc2626", hover_color="#b91c1c", font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=3, padx=(4, 0))

        self.console_textbox = ctk.CTkTextbox(tab, font=ctk.CTkFont(family="Consolas", size=11), fg_color="#09090b", text_color="#e4e4e7", wrap="none")
        self.console_textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))

    # =========================================================================
    # LÓGICA DE AUDIO (MULTI-ENTRADA UNIVERSAL)
    # =========================================================================
    def _init_audio_system(self):
        self.refresh_audio_devices()
        self.audio_engine.start_preview()

    def refresh_audio_devices(self):
        try:
            devs = AudioEngine.discover_devices()
            self.audio_outputs_cache = devs["outputs"]
            self.audio_inputs_cache = devs["inputs"]

            # Llenar salida de sistema
            out_labels = []
            def_out_label = None
            for o in self.audio_outputs_cache:
                lbl = f"[{o['index']}] {o['name']} ({o['sample_rate']}Hz)"
                out_labels.append(lbl)
                if o.get("is_default"):
                    def_out_label = lbl

            if out_labels:
                self.combo_audio_output.configure(values=out_labels)
                self.combo_audio_output.set(def_out_label or out_labels[0])
                self._on_output_device_selected(def_out_label or out_labels[0])

            # Llenar Entrada 1 y Entrada 2
            in_labels = ["[Desactivado]"]
            for i in self.audio_inputs_cache:
                lbl = f"[{i['index']}] {i['name']} ({i['sample_rate']}Hz)"
                in_labels.append(lbl)

            self.combo_in1.configure(values=in_labels)
            self.combo_in2.configure(values=in_labels)

            # Autoasignar entrada 1 al primer micrófono/línea
            if len(in_labels) > 1:
                self.combo_in1.set(in_labels[1])
                self._on_in1_device_selected(in_labels[1])
            else:
                self.combo_in1.set(in_labels[0])

            # Autoasignar entrada 2 a la segunda línea si existe
            if len(in_labels) > 2:
                self.combo_in2.set(in_labels[2])
                self._on_in2_device_selected(in_labels[2])
            else:
                self.combo_in2.set(in_labels[0])

            self.append_process_log(f"Audio actualizado: {len(out_labels)} salidas y {len(in_labels)-1} entradas detectadas.", "AUDIO")
        except Exception as e:
            self.append_process_log(f"Error enumerando audio: {e}", "ERROR")

    def _on_output_device_selected(self, choice: str):
        match = re.match(r"\[(\d+)\]", choice)
        idx = int(match.group(1)) if match else None
        self.audio_engine.loopback_device_idx = idx

    def _on_in1_device_selected(self, choice: str):
        if "Desactivado" in choice:
            self.audio_engine.in1_device_idx = None
            return
        match = re.match(r"\[(\d+)\]", choice)
        idx = int(match.group(1)) if match else None
        self.audio_engine.in1_device_idx = idx

    def _on_in2_device_selected(self, choice: str):
        if "Desactivado" in choice:
            self.audio_engine.in2_device_idx = None
            return
        match = re.match(r"\[(\d+)\]", choice)
        idx = int(match.group(1)) if match else None
        self.audio_engine.in2_device_idx = idx

    def _on_in1_mode_change(self, choice: str):
        self.audio_engine.in1_mode = "dual_mono" if "Dual Mono" in choice else "stereo"

    def _on_in2_mode_change(self, choice: str):
        self.audio_engine.in2_mode = "dual_mono" if "Dual Mono" in choice else "stereo"

    def _on_sys_slider_change(self, val: float):
        self.audio_engine.system_volume = float(val)
        db = 20.0 * (val - 1.0) * 1.5 if val < 1.0 else (val - 1.0) * 6.0
        pct = int(val * 100)
        self.lbl_sys_val.configure(text=f"{db:+.1f} dB ({pct}%)")

    def _on_in1_slider_change(self, val: float):
        self.audio_engine.in1_volume = float(val)
        db = 20.0 * (val - 1.0) * 1.5 if val < 1.0 else (val - 1.0) * 6.0
        pct = int(val * 100)
        self.lbl_in1_val.configure(text=f"{db:+.1f} dB ({pct}%)")

    def _on_in2_slider_change(self, val: float):
        self.audio_engine.in2_volume = float(val)
        db = 20.0 * (val - 1.0) * 1.5 if val < 1.0 else (val - 1.0) * 6.0
        pct = int(val * 100)
        self.lbl_in2_val.configure(text=f"{db:+.1f} dB ({pct}%)")

    def _toggle_mute_sys(self):
        self.audio_engine.system_mute = not self.audio_engine.system_mute
        self.btn_mute_sys.configure(fg_color="#dc2626" if self.audio_engine.system_mute else "#3f3f46", text="MUTED" if self.audio_engine.system_mute else "MUTE")

    def _toggle_mute_in1(self):
        self.audio_engine.in1_mute = not self.audio_engine.in1_mute
        self.btn_mute_in1.configure(fg_color="#dc2626" if self.audio_engine.in1_mute else "#3f3f46", text="MUTED" if self.audio_engine.in1_mute else "MUTE")

    def _toggle_mute_in2(self):
        self.audio_engine.in2_mute = not self.audio_engine.in2_mute
        self.btn_mute_in2.configure(fg_color="#dc2626" if self.audio_engine.in2_mute else "#3f3f46", text="MUTED" if self.audio_engine.in2_mute else "MUTE")

    def _on_audio_levels_update(self, sys_db: float, in1_db: float, in2_db: float, mst_db: float):
        def _update():
            norm_sys = max(0.0, min(1.0, (sys_db + 60.0) / 60.0))
            norm_in1 = max(0.0, min(1.0, (in1_db + 60.0) / 60.0))
            norm_in2 = max(0.0, min(1.0, (in2_db + 60.0) / 60.0))
            norm_mst = max(0.0, min(1.0, (mst_db + 60.0) / 60.0))

            self.meter_sys.set(norm_sys)
            self.meter_in1.set(norm_in1)
            self.meter_in2.set(norm_in2)
            self.meter_mst.set(norm_mst)

            if norm_mst >= 0.98 or self.audio_engine.clipping_detected:
                self.clip_badge.configure(fg_color="#dc2626", text_color="#ffffff")
            else:
                self.clip_badge.configure(fg_color="#27272a", text_color="#71717a")
        self.after(0, _update)

    # =========================================================================
    # LÓGICA DE STREAMING CON MONITOR INTEGRADO (WIN32 SETPARENT)
    # =========================================================================
    def toggle_stream(self):
        if not self.engine.is_running:
            config = self._get_active_stream_config()
            config["window_title"] = "UltraCam_Studio_Monitor"
            
            # Ocultar placeholder
            self.lbl_video_placeholder.grid_remove()
            
            success = self.engine.start_stream(config, on_exit=self._on_stream_exit)
            if success:
                self.btn_stream.configure(text="⏹️ Detener Cámara", fg_color="#b91c1c")
                self.dev_pill_icon.configure(text_color="#22c55e")
                self.lbl_bottom_info.configure(text=f"Cámara integrada activa en {config.get('size')} @ {config.get('fps')}fps")
                
                # Hilo de Incrustación Nativa Win32
                threading.Thread(target=self._embed_monitor_thread, daemon=True).start()
        else:
            self.engine.stop_stream()
            self._on_stream_exit(0)

    def _embed_monitor_thread(self):
        """Incrusta la ventana de scrcpy o ffplay directamente dentro de self.video_container"""
        time.sleep(0.3)
        self.update_idletasks()
        w = max(self.video_container.winfo_width(), 480)
        h = max(self.video_container.winfo_height(), 270)
        hwnd_parent = self.video_container.winfo_id()
        
        ok = self.engine.embed_window_into_hwnd("UltraCam_Studio_Monitor", hwnd_parent, w, h, timeout=6.0)
        if ok:
            self.is_embedded = True
            self.append_process_log("Monitor de video integrado con éxito dentro de la aplicación.", "PROCESS")
        else:
            self.append_process_log("No se pudo incrustar ventana en el contenedor.", "WARN")

    def _on_stream_exit(self, code: int):
        self.is_embedded = False
        self.after(0, lambda: self.btn_stream.configure(text="▶️ Iniciar Cámara", fg_color="#2563eb"))
        self.after(0, lambda: self.dev_pill_icon.configure(text_color="#f87171"))
        self.after(0, lambda: self.lbl_bottom_info.configure(text="Cámara detenida."))
        self.after(0, lambda: self.lbl_video_placeholder.grid())

    # =========================================================================
    # LÓGICA DE GRABACIÓN & POST-GRABACIÓN
    # =========================================================================
    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording_session()
        else:
            self.stop_recording_session()

    def start_recording_session(self):
        self.is_recording = True
        self.record_start_time = time.time()
        self.timer_running = True

        out_dir = self.record_dir_var.get()
        os.makedirs(out_dir, exist_ok=True)

        self.audio_engine.start_recording(out_dir)

        config = self._get_active_stream_config()
        config["record_video"] = True
        config["record_dir"] = out_dir
        config["window_title"] = "UltraCam_Studio_Monitor"

        if not self.engine.is_running:
            self.temp_video_path = os.path.join(out_dir, f"temp_vid_{int(time.time())}.mp4")
            self.lbl_video_placeholder.grid_remove()
            self.engine.start_stream(config, on_exit=self._on_stream_exit)
            threading.Thread(target=self._embed_monitor_thread, daemon=True).start()
        elif self.active_platform in ("pc", "ios") or not self.engine.current_recording_file:
            self.engine.stop_stream()
            time.sleep(0.2)
            self.lbl_video_placeholder.grid_remove()
            self.engine.start_stream(config, on_exit=self._on_stream_exit)
            threading.Thread(target=self._embed_monitor_thread, daemon=True).start()

        self.btn_record.configure(text="⏹️ DETENER Y GUARDAR", fg_color="#b91c1c")
        self.rec_dot.configure(text="🔴", text_color="#ef4444")
        self.lbl_rec_info.configure(text="Grabando audio multipista + video...")
        self._update_rec_timer()

    def stop_recording_session(self):
        self.is_recording = False
        self.timer_running = False

        self.btn_record.configure(text="⏺️ INICIAR GRABACIÓN", fg_color="#dc2626")
        self.rec_dot.configure(text="⏹️", text_color="#71717a")
        self.lbl_rec_info.configure(text="Finalizando y ensamblando...")

        audio_info = self.audio_engine.stop_recording()

        vid_path = self.engine.current_recording_file or self.temp_video_path
        if self.engine.is_running:
            self.engine.stop_stream()

        time.sleep(0.5)

        options = {
            "output_dir": self.record_dir_var.get(),
            "prefix": self.record_prefix_var.get(),
            "embed_multitrack": self.opt_embed_multitrack.get(),
            "export_stems": self.opt_export_stems.get(),
            "normalize": self.opt_normalize_mode.get(),
            "sync_offset_ms": self.sync_offset_ms_var.get(),
            "reveal_in_explorer": self.opt_reveal_explorer.get(),
            "auto_play": self.opt_auto_play.get()
        }

        if vid_path and os.path.exists(vid_path):
            threading.Thread(target=self._run_finalize_pipeline, args=(vid_path, audio_info, options), daemon=True).start()
        else:
            self.append_process_log("No se encontró archivo de video para multiplexar.", "WARN")

    def _run_finalize_pipeline(self, vid_path, audio_info, options):
        res = self.engine.finalize_recording(vid_path, audio_info, options)
        if res.get("success"):
            self.after(0, lambda: self._on_post_record_success(res))
        else:
            self.after(0, lambda: messagebox.showerror("Error en Post-Grabación", res.get("message", "Error desconocido")))

    def _on_post_record_success(self, res: Dict):
        self.lbl_rec_info.configure(text="Listo | Sesión guardada")
        if self.opt_show_summary.get():
            clip_txt = "⚠️ SÍ (baja el fader)" if res.get("clipping_detected") else "✅ No (dinámica sana)"
            msg = (
                f"¡Grabación Finalizada con Éxito!\n\n"
                f"📁 Archivo: {os.path.basename(res['final_path'])}\n"
                f"💾 Tamaño: {res['file_size_mb']} MB\n"
                f"⚡ Tiempo de ensamblado: {res['render_time_s']}s\n"
                f"🎚️ Saturación (Clipping): {clip_txt}\n"
            )
            if res.get("stems_dir"):
                msg += f"\n📂 Stems WAV guardados en:\n{res['stems_dir']}"
            messagebox.showinfo("Resumen Técnico de Sesión", msg)

    def _update_rec_timer(self):
        if not self.timer_running:
            return
        elapsed = int(time.time() - self.record_start_time)
        hrs = elapsed // 3600
        mins = (elapsed % 3600) // 60
        secs = elapsed % 60
        self.lbl_rec_timer.configure(text=f"{hrs:02d}:{mins:02d}:{secs:02d}")
        self.after(500, self._update_rec_timer)

    # =========================================================================
    # PLATAFORMA & STREAMING
    # =========================================================================
    def _on_platform_toggle(self, choice: str):
        if "Cámara" in choice or "Webcam" in choice:
            self.active_platform = "pc"
            self.dev_pill_text.configure(text="Modo PC Webcam / DirectShow")
            self.dev_pill_icon.configure(text_color="#10b981")
            self.dev_battery_lbl.configure(text="🔌 AC")
            self._update_pc_camera_choices()
        elif "iPhone" in choice:
            self.active_platform = "ios"
            self.dev_pill_text.configure(text="Modo iPhone (iOS DirectShow 4K)")
            self.dev_pill_icon.configure(text_color="#a855f7")
            self.dev_battery_lbl.configure(text="📱 iOS")
            self._update_ios_camera_choices()
        else:
            self.active_platform = "android"
            self.dev_pill_text.configure(text="Modo Android (scrcpy 4K)")
            self.dev_pill_icon.configure(text_color="#60a5fa")
            self._update_android_camera_choices()

    def refresh_cameras(self):
        """Actualiza la lista de cámaras según la plataforma activa"""
        if self.active_platform == "pc":
            self._update_pc_camera_choices(force=True)
        elif self.active_platform == "ios":
            self._update_ios_camera_choices()
        else:
            self._update_android_camera_choices()

    def _open_hardware_dialog(self):
        dev = self._get_selected_device_name()
        if not dev:
            messagebox.showwarning("Aviso", "Selecciona una cámara para abrir sus propiedades de hardware.")
            return
        ok = self.engine.open_camera_hardware_dialog(dev)
        if ok:
            self.append_process_log(f"Panel de hardware DirectShow abierto para '{dev}'.", "CAM")
        else:
            messagebox.showerror("Error", "No se pudo abrir el diálogo de hardware. Asegúrate de que la cámara esté conectada.")

    def _get_selected_device_name(self) -> Optional[str]:
        if self.active_platform == "android":
            return self.selected_device
        label = self.combo_cameras.get()
        dev_list = self.engine.cached_pc_cameras if self.active_platform == "pc" else self.engine.cached_ios_cameras
        for c in dev_list:
            if c["label"] == label or c["name"] == label:
                return c["name"]
        return label

    def _on_camera_device_changed(self, choice: str):
        dev = self._get_selected_device_name()
        if not dev:
            return
        self.selected_camera_name = dev
        clean_lbl = choice.split("(")[0].strip() if "(" in choice else choice
        self.dev_pill_text.configure(text=f"{clean_lbl[:28]}")

        # Sondear capacidades nativas
        if self.active_platform in ("pc", "ios"):
            caps = self.engine.probe_camera_capabilities(dev)
            if caps.get("resolutions"):
                self.combo_res.configure(values=caps["resolutions"])
                self.combo_res.set(caps["default_res"])
            if caps.get("framerates"):
                fps_strs = [f"{f} fps" for f in caps["framerates"]]
                self.combo_fps.configure(values=fps_strs)
                self.combo_fps.set(f"{caps['default_fps']} fps")
            
            vcodec = caps.get("vcodec")
            fmt = caps.get("pixel_format", "yuyv422")
            self.active_pixel_format = fmt
            if vcodec == "mjpeg":
                codec_msg = "MJPEG por Hardware (Máxima fluidez USB 30/60 FPS)"
            else:
                codec_msg = f"{fmt.upper()} (Sin comprimir)"
            self.lbl_codec_pill.configure(text=f"Códec Óptimo: {codec_msg}")

            # Cargar preset guardado si existe
            saved = self.engine.load_camera_preset(dev)
            if saved:
                if "size" in saved and saved["size"] in caps.get("resolutions", []):
                    self.combo_res.set(saved["size"])
                if "fps" in saved:
                    self.combo_fps.set(f"{saved['fps']} fps")
                if "brightness" in saved:
                    self.slider_brightness.set(float(saved["brightness"]))
                    self._on_brightness_change(saved["brightness"])
                if "contrast" in saved:
                    self.slider_contrast.set(float(saved["contrast"]))
                    self._on_contrast_change(saved["contrast"])
                if "saturation" in saved:
                    self.slider_saturation.set(float(saved["saturation"]))
                    self._on_saturation_change(saved["saturation"])
                if "sharpness" in saved:
                    self.slider_sharpness.set(float(saved["sharpness"]))
                    self._on_sharpness_change(saved["sharpness"])

    def _update_pc_camera_choices(self, force: bool = False):
        pc_cams = self.engine.get_pc_cameras(force_refresh=force)
        labels = [c["label"] for c in pc_cams]
        if labels:
            self.combo_cameras.configure(values=labels)
            self.combo_cameras.set(labels[0])
            self._on_camera_device_changed(labels[0])

    def _update_android_camera_choices(self):
        cams = ["Cámara Principal Trasera (200MP)", "Cámara Frontal (Selfie)"]
        if self.selected_device:
            dev_cams = self.engine.get_device_cameras(self.selected_device)
            if dev_cams:
                cams = [f"Lente {c.get('id', 0)} ({c.get('facing', 'back')}) - {c.get('size', '4K')}" for c in dev_cams]
        self.combo_cameras.configure(values=cams)
        self.combo_cameras.set(cams[0])
        self.combo_res.configure(values=self.all_resolutions)
        self.combo_res.set(self.all_resolutions[0])
        self.combo_fps.configure(values=self.fps_options)
        self.combo_fps.set(self.fps_options[0])
        self.lbl_codec_pill.configure(text="Códec Óptimo: H.265 / HEVC 4K 60fps")

    def _update_ios_camera_choices(self):
        ios_cams = self.engine.get_ios_cameras()
        labels = [c["label"] for c in ios_cams]
        if labels:
            self.combo_cameras.configure(values=labels)
            self.combo_cameras.set(labels[0])
            self._on_camera_device_changed(labels[0])

    def _on_brightness_change(self, val: float):
        v = float(val)
        self.brightness_val = v
        self.lbl_brightness_val.configure(text=f"{v:+.2f}")

    def _on_contrast_change(self, val: float):
        v = float(val)
        self.contrast_val = v
        self.lbl_contrast_val.configure(text=f"{v:.2f}x")

    def _on_saturation_change(self, val: float):
        v = float(val)
        self.saturation_val = v
        self.lbl_saturation_val.configure(text=f"{v:.2f}x")

    def _on_sharpness_change(self, val: float):
        v = float(val)
        self.sharpness_val = v
        txt = "0.0 (Neutro)" if v <= 0.05 else f"{v:.1f}"
        self.lbl_sharpness_val.configure(text=txt)

    def reset_procamp_filters(self):
        self.slider_brightness.set(0.0)
        self._on_brightness_change(0.0)
        self.slider_contrast.set(1.0)
        self._on_contrast_change(1.0)
        self.slider_saturation.set(1.0)
        self._on_saturation_change(1.0)
        self.slider_sharpness.set(0.0)
        self._on_sharpness_change(0.0)

    def apply_preset_studio_pro(self):
        vals = self.combo_res.cget("values")
        if vals:
            self.combo_res.set(vals[0])
        fps_vals = self.combo_fps.cget("values")
        if any("60" in f for f in fps_vals):
            self.combo_fps.set([f for f in fps_vals if "60" in f][0])
        elif fps_vals:
            self.combo_fps.set(fps_vals[0])
        self.slider_contrast.set(1.05)
        self._on_contrast_change(1.05)
        self.slider_saturation.set(1.05)
        self._on_saturation_change(1.05)
        self.slider_sharpness.set(1.2)
        self._on_sharpness_change(1.2)
        messagebox.showinfo("Preset Aplicado", "🌟 Preset 'Studio Pro' aplicado:\nMáxima definición nativa, saturación natural y nitidez optimizada.")

    def apply_preset_60fps(self):
        fps_vals = self.combo_fps.cget("values")
        if any("60" in f for f in fps_vals):
            self.combo_fps.set([f for f in fps_vals if "60" in f][0])
            messagebox.showinfo("Preset 60 FPS", "⚡ Modo 60 FPS activado para máxima fluidez.")
        else:
            messagebox.showinfo("Aviso", "Esta cámara no reporta soporte para 60 FPS nativo. Se mantuvo el framerate más alto disponible.")

    def apply_preset_musician(self):
        self.slider_contrast.set(1.0)
        self._on_contrast_change(1.0)
        self.slider_saturation.set(1.05)
        self._on_saturation_change(1.05)
        self.slider_sharpness.set(1.0)
        self._on_sharpness_change(1.0)
        messagebox.showinfo(
            "Preset Músico / Performance",
            "🎸 Preset 'Músico / Performance' preparado.\n\n"
            "💡 CONSEJO CLAVE:\n"
            "Pulsa el botón '⚙️ Propiedades de Hardware' y ajusta:\n"
            "• ENFOQUE: Desactiva 'Auto' y ponlo MANUAL en tu instrumento/rostro.\n"
            "• EXPOSICIÓN: Fíjala en MANUAL.\n\n"
            "Esto evita que la cámara cambie de brillo o desenfoque tus tomas al mover las manos o tocar."
        )

    def apply_preset_low_light(self):
        self.slider_brightness.set(0.10)
        self._on_brightness_change(0.10)
        self.slider_contrast.set(1.15)
        self._on_contrast_change(1.15)
        self.slider_saturation.set(1.10)
        self._on_saturation_change(1.10)
        self.slider_sharpness.set(0.6)
        self._on_sharpness_change(0.6)
        messagebox.showinfo("Preset Baja Luz", "🌙 Preset 'Baja Luz / Anti-Ruido' aplicado:\nLuminosidad elevada y contraste ajustado para salas con iluminación tenue.")

    def save_current_camera_preset(self):
        dev = self._get_selected_device_name()
        if not dev:
            messagebox.showwarning("Aviso", "No hay cámara seleccionada para guardar.")
            return
        res = self.combo_res.get().split()[0]
        fps_str = self.combo_fps.get().split()[0]
        try:
            fps = int(fps_str)
        except Exception:
            fps = 30
        settings = {
            "size": res,
            "fps": fps,
            "brightness": round(self.brightness_val, 2),
            "contrast": round(self.contrast_val, 2),
            "saturation": round(self.saturation_val, 2),
            "sharpness": round(self.sharpness_val, 1)
        }
        ok = self.engine.save_camera_preset(dev, settings)
        if ok:
            messagebox.showinfo("Configuración Guardada", f"✅ Las preferencias de '{dev}' se guardaron con éxito.\nLa aplicación las recordará siempre que uses esta cámara.")

    def _get_active_stream_config(self) -> Dict:
        res_choice = self.combo_res.get().split()[0]
        fps_choice = int(self.combo_fps.get().split()[0])
        buf_choice = int(self.combo_buf.get().split()[0])

        cfg = {
            "platform": self.active_platform,
            "size": res_choice,
            "fps": fps_choice,
            "video_buffer": buf_choice,
            "codec": "h265",
            "bitrate": "50M",
            "window_title": "UltraCam_Studio_Monitor",
            "brightness": self.brightness_val,
            "contrast": self.contrast_val,
            "saturation": self.saturation_val,
            "sharpness": self.sharpness_val
        }
        if self.active_platform == "android" and self.selected_device:
            cfg["serial"] = self.selected_device
        elif self.active_platform in ("pc", "ios"):
            dev_name = self._get_selected_device_name()
            cfg["pc_device"] = dev_name
            cfg["ios_device"] = dev_name
            cfg["device_name"] = dev_name
            caps = self.engine.cached_camera_caps.get(dev_name or "", {})
            cfg["vcodec"] = caps.get("vcodec")
            cfg["pixel_format"] = caps.get("pixel_format")
        return cfg

    # =========================================================================
    # HELPERS DE UI
    # =========================================================================
    def _on_normalize_change(self, choice: str):
        if "EBU R128" in choice:
            self.opt_normalize_mode.set("ebu_r128")
        elif "Peak" in choice:
            self.opt_normalize_mode.set("peak")
        else:
            self.opt_normalize_mode.set("none")

    def _on_sync_slider_change(self, val: float):
        ms = int(val)
        self.sync_offset_ms_var.set(ms)
        self.lbl_sync_val.configure(text=f"{ms:+d} ms")

    def open_recordings_folder(self):
        d = self.record_dir_var.get()
        os.makedirs(d, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(d)
        else:
            subprocess.Popen(["xdg-open", d])

    def append_process_log(self, text: str, category: str = "INFO"):
        def _insert():
            self.console_textbox.insert("end", text + "\n")
            self.console_textbox.see("end")
        self.after(0, _insert)

    def copy_logs_to_clipboard(self):
        content = self.console_textbox.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(content)
        messagebox.showinfo("Copiado", "Registros copiados al portapapeles.")

    def clear_logs(self):
        self.console_textbox.delete("1.0", "end")

    def show_report_dialog(self):
        dialog = ctk.CTkInputDialog(text="Describe brevemente lo sucedido para el análisis con IA:", title="Reportar Problema")
        notes = dialog.get_input()
        if notes is not None:
            res = self.engine.save_problem_report(notes, self._get_active_stream_config())
            if res.get("success"):
                messagebox.showinfo(
                    "Reporte Guardado",
                    f"Reporte {res['report_id']} generado con éxito.\n"
                    f"Archivo local: {os.path.basename(res['file_path'])}\n\n"
                    f"Los datos de diagnóstico se han copiado al portapapeles."
                )

    def run_manual_speed_test(self):
        if self.benchmark_running:
            return
        self.benchmark_running = True
        self.btn_speed_test.configure(text="⏳ Probando cable...", state="disabled")
        def _run():
            res = self.engine.test_cable_speed(self.selected_device, size_mb=3)
            self.after(0, lambda: self._on_speed_test_done(res))
        threading.Thread(target=_run, daemon=True).start()

    def _on_speed_test_done(self, res: Dict):
        self.benchmark_running = False
        self.btn_speed_test.configure(text="⚡ Probar Velocidad Cable USB", state="normal")
        if res.get("success"):
            messagebox.showinfo("Resultado de Velocidad", f"Velocidad: {res['speed_mb_s']} MB/s\nClasificación: {res['classification']}\n\n{res['message']}")
        else:
            messagebox.showwarning("Aviso", res.get("message", "Error en prueba"))

    def activate_wireless_mode(self):
        if not self.selected_device:
            messagebox.showwarning("Atención", "Conecta tu teléfono por USB primero para autorizar la conexión Wi-Fi.")
            return
        res = self.engine.setup_wireless_mode(self.selected_device)
        if res.get("success"):
            messagebox.showinfo("Modo Wi-Fi Activado", res["message"])
        else:
            messagebox.showwarning("Error Wi-Fi", res["message"])

    def _start_device_monitor(self):
        def _loop():
            while self.is_monitoring:
                if self.active_platform == "android":
                    devs = self.engine.check_device_changes(log_pings=False)
                    self.connected_devices = devs
                    if devs and not self.selected_device:
                        self.selected_device = devs[0]["serial"]
                        info = self.engine.get_device_info(self.selected_device)
                        bat = self.engine.get_device_battery(self.selected_device)
                        self.after(0, lambda: self._update_device_ui(info, bat))
                    elif not devs:
                        self.selected_device = None
                        self.after(0, self._set_device_disconnected_ui)
                time.sleep(3)
        threading.Thread(target=_loop, daemon=True).start()

    def _update_device_ui(self, info: Dict, battery: Optional[int]):
        model = info.get("friendly_name", "Android")
        conn = "📶 Wi-Fi" if info.get("is_wifi") else "⚡ USB 3.0"
        self.dev_pill_text.configure(text=f"{model} ({conn})")
        self.dev_pill_icon.configure(text_color="#22c55e")
        if battery is not None:
            self.dev_battery_lbl.configure(text=f"🔋 {battery}%")

        cams = self.engine.get_device_cameras(info.get("serial"))
        labels = [c["label"] for c in cams]
        if labels:
            self.combo_cameras.configure(values=labels)
            self.combo_cameras.set(labels[0])

    def _set_device_disconnected_ui(self):
        if self.active_platform == "android":
            self.dev_pill_text.configure(text="Sin dispositivo conectado")
            self.dev_pill_icon.configure(text_color="#f87171")
            self.dev_battery_lbl.configure(text="🔋 --")

    def on_closing(self):
        self.is_monitoring = False
        if self.is_recording:
            self.stop_recording_session()
        self.audio_engine.stop()
        self.engine.stop_stream()
        self.destroy()

if __name__ == "__main__":
    app = GalaxyCamApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
