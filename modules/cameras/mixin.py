"""
UltraCam Studio - Módulo Cámaras: fuentes de video, formato, vista previa en el monitor, cámara virtual
y conexión de teléfonos.

Mixin de GalaxyCamApp (gui.py): sus métodos usan el estado compartido de la ventana.
"""

import json
import time
import ctypes
import threading
from typing import Dict, List, Optional, Tuple
import customtkinter as ctk
import virtualcam
from infrastructure.logging.app_logger import GLOBAL_LOGGER
from infrastructure.system.win32_window import GLOBAL_WINDOW_EMBEDDER
from infrastructure.video.command_builder import high_speed_rate, high_speed_sizes_for
from presentation.strings import t
from modules.cameras.ui.connect_dialog import ConnectDialog
from presentation.theme import (C, ICON, KIND_LABEL, KIND_LONG, ANDROID_RES, PRESETS, PRESET_VALUES, fmt_res,
                                res_tier)
from modules.cameras.model import Source, is_own_virtual_camera, vertical_size, waiting_source
from modules.cameras import usb_apple


class CamerasMixin:
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
        cols = 2 if wrap < 500 else 4               # en el cajón (angosto) van de a dos
        pg.grid_columnconfigure(tuple(range(cols)), weight=1, uniform="p")
        self.preset_buttons = {}
        for i, (pid, label, sub) in enumerate(PRESETS):
            b = ctk.CTkButton(pg, text=f"{label}\n{sub}", height=54, corner_radius=10, anchor="w", border_width=1,
                              font=self.F(12), text_color=C["text"], text_color_disabled=C["off"], width=10,
                              command=lambda p=pid: self._apply_preset(p))
            b.grid(row=i // cols, column=i % cols, sticky="ew", padx=(0 if i % cols == 0 else 4, 0), pady=4)
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
        stack = wrap < 500                           # en el cajón: códec arriba, calidad debajo
        q.grid_columnconfigure((0, 1) if not stack else 0, weight=1, uniform="q")
        self._field_label(q, t("ui.main.codec")).grid(row=0, column=0, sticky="ew")
        self._field_label(q, t("ui.main.calidad_mbps")).grid(row=2 if stack else 0, column=0 if stack else 1,
                                                             sticky="ew", padx=(0 if stack else 8, 0))
        codecs = [("h265", t("ui.main.h_265_mejor")), ("h264", t("ui.main.h_264_compatible"))]
        seg_c = self._segmented(q, codecs, self.video_cfg.get("android_codec", "h265"),
                                lambda v: self._set_video_opt("android_codec", v, seg_c), font=self.F(12, "bold"))
        seg_c.grid(row=1, column=0, sticky="ew", pady=4)
        rates = [("20M", "20"), ("50M", "50"), ("80M", "80")]
        seg_b = self._segmented(q, rates, self.video_cfg.get("android_bitrate", "50M"),
                                lambda v: self._set_video_opt("android_bitrate", v, seg_b), font=self.F(12, "bold", mono=True))
        seg_b.grid(row=3 if stack else 1, column=0 if stack else 1, sticky="ew", padx=(0 if stack else 8, 0), pady=4)
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
                # iPhone por cable: se guía la instalación de la app que hace de puente (ver usb_apple.py)
                iphone = usb_apple.iphone_connected()
                if iphone != getattr(self, "iphone_usb", False):
                    self.iphone_usb = iphone
                    self._ui(self.modules["cameras"].render_iphone_card)
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
                # Las guardadas antes de conocer la alta velocidad se vuelven a preguntar
                if saved_cams and all("high_speed" in c for c in saved_cams if c.get("id") != "auto"):
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
        """Elegir una cámara abre sus ajustes (el botón «← Cámaras» vuelve a la lista)."""
        if sid != self.selected_id:
            if self.rec_state != "idle":
                self.notify.toast(t("source.locked_while_recording"), "warn")
                return
            self.select_source(sid)
        self.modules["cameras"].show_detail()

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
            cam = self._lens_camera(s)
            cam_fps = (cam or {}).get("fps")
            fast = [r for r in ANDROID_RES if r in high_speed_sizes_for(cam, 60)]
            fps_avail = [f for f in (24, 30, 60) if f in cam_fps or (f == 60 and fast)] if cam_fps else [24, 30, 60]
            fps_avail = fps_avail or [30]
            def_res, def_fps = "1920x1080", 30
            # 60 fps con la captura de alta velocidad: solo a los tamaños que la admiten (1080p/720p)
            if fast and self.fmt_by_src.get(s.id, {}).get("fps") == 60:
                res_list = fast
                def_res = def_res if def_res in fast else fast[0]
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
        if 60 in disabled:
            note = t("ui.main.esta_camara_no_ofrece_60")
        elif fps == 60 and self._high_speed_rate(s):
            note = t("format.fps60_high_speed")
        else:
            note = ""
        self.lbl_fps_note.configure(text=note)
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
            self.rot_box.grid(row=6, column=0, sticky="ew", pady=(0, 0))
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

    def _high_speed_rate(self, s) -> Optional[int]:
        """Frecuencia de alta velocidad del sensor que hace falta para los fps elegidos (o None)."""
        if s is None or s.kind != "android":
            return None
        _, _, size, fps = self._format_options(s)
        return high_speed_rate(self._lens_camera(s), size, fps)

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
            # Máxima definición: sin los 60 fps de alta velocidad, que obligan a bajar a 1080p
            if self._high_speed_rate(s):
                fmt["fps"] = 30
            res_list = self._format_options(s)[0]
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
            cfg["high_speed_fps"] = self._high_speed_rate(s)
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
                # Repintar ya: sin cuadros nuevos (cámara en pausa) quedaba la imagen vieja al abrir o
                # cerrar el cajón. RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW
                ctypes.windll.user32.RedrawWindow(self.monitor_hwnd, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0100)
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
