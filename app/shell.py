"""
UltraCam Studio - Marco de la ventana: utilidades visuales, armado de la pantalla, ciclo de la interfaz,
registro, configuración guardada y cierre.

Mixin de GalaxyCamApp (gui.py): sus métodos usan el estado compartido de la ventana.
"""

import os
import sys
import time
import queue
from typing import Dict, Optional
import customtkinter as ctk
import paths
import virtualcam
from infrastructure.logging.app_logger import GLOBAL_LOGGER
from infrastructure.system.win32_window import GLOBAL_WINDOW_EMBEDDER
from presentation.dialogs.confirm_dialog import ConfirmDialog
from presentation.notifier import Notifier
from presentation.strings import t
from presentation.theme import C, ICON
from app.constants import APP_NAME
from app.frame import DRAWER_W, RAIL_W


def settings_path() -> str:
    return paths.settings_path()


class ShellMixin:
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
            b = ctk.CTkButton(wrap, text=text, height=height, corner_radius=7, font=font or self.F(13, "bold"), width=10,
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
        """riel de módulos | cajón | centro (cabecera, monitor, transporte) | Audio fijo."""
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.module_rail = ctk.CTkFrame(self, width=RAIL_W, corner_radius=0, fg_color=C["rail"])
        self.module_rail.grid(row=0, column=0, sticky="ns")
        self.module_rail.grid_propagate(False)
        self.drawer = ctk.CTkFrame(self, width=DRAWER_W, corner_radius=0, fg_color=C["rail"])
        self.drawer.grid(row=0, column=1, sticky="ns")
        self.drawer.grid_propagate(False)
        self.center = ctk.CTkFrame(self, corner_radius=0, fg_color=C["bg"])
        self.center.grid(row=0, column=2, sticky="nsew")
        self.inspector = ctk.CTkFrame(self, width=340, corner_radius=0, fg_color=C["rail"])
        self.inspector.grid(row=0, column=3, sticky="ns")
        self.inspector.grid_propagate(False)
        # separadores
        ctk.CTkFrame(self, width=1, fg_color=C["line"], corner_radius=0).grid(row=0, column=0, sticky="nse")
        self.drawer_sep = ctk.CTkFrame(self, width=1, fg_color=C["line"], corner_radius=0)
        self.drawer_sep.grid(row=0, column=1, sticky="nse")
        self.drawer_sep.grid_remove()
        ctk.CTkFrame(self, width=1, fg_color=C["line"], corner_radius=0).grid(row=0, column=3, sticky="nsw")

        self._drawer_module: Optional[str] = None
        self._drawer_advanced = False
        self._build_center()
        self.modules["audio"].build_panel(self.inspector)      # Audio: siempre a la vista
        self._build_drawer()                                     # lo básico de cada módulo, una vez
        self._build_module_rail()
        self._build_footer()
        for m in self.modules.values():
            m.attach()                          # lo que cada módulo agrega a la cabecera o a la barra

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
        self.lbl_src_name = ctk.CTkLabel(name_row, text=t("ui.main.sin_camara"), font=self.F(18, "bold"),
                                         text_color=C["text"], anchor="w")
        self.lbl_src_name.pack(side="left")
        # Modo de la cámara («4K · 30 fps ▾»): un clic abre el formato en el módulo Cámaras
        self.lbl_mode = ctk.CTkButton(name_row, text="", font=self.F(11, "bold"), height=24, width=10, corner_radius=6,
                                      fg_color=C["accent_bg"], hover_color=C["raised"], text_color=C["accent_text"],
                                      command=lambda: self.modules["cameras"].open_detail())
        self.lbl_src_kind = ctk.CTkLabel(head, text=t("ui.main.elige_una_camara_en_la"), font=self.F(12),
                                         text_color=C["muted"], anchor="w")
        self.lbl_src_kind.grid(row=1, column=0, sticky="w")
        # Indicadores: Cámara (señal) · Virtual · Live (si Transmisión está activo)
        chips = ctk.CTkFrame(head, fg_color="transparent")
        chips.grid(row=0, column=1, rowspan=2, sticky="e")
        self._head_chips = chips
        pill = ctk.CTkFrame(chips, fg_color=C["panel"], corner_radius=15, border_width=1, border_color=C["line"])
        pill.pack(side="left")
        self.live_dot = ctk.CTkLabel(pill, text="●", font=self.F(10), text_color=C["off"])
        self.live_dot.pack(side="left", padx=(12, 6), pady=4)
        self.live_text = ctk.CTkLabel(pill, text=t("ui.main.sin_senal"), font=self.F(12), text_color=C["text2"])
        self.live_text.pack(side="left", padx=(0, 12), pady=4)
        self.btn_vcam = ctk.CTkButton(chips, text=t("ui.main.camara_virtual"), width=175, height=32, corner_radius=16,
                                      font=self.F(12, "bold"), border_width=1, command=self._toggle_vcam)
        self.btn_vcam.pack(side="left", padx=(8, 0))
        self.header_chips = chips                 # los módulos opcionales agregan el suyo (Live)

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
        self.vm_title = ctk.CTkLabel(self.video_msg, text="", font=self.F(17, "bold"), text_color=C["text"], anchor="w",
                                     justify="left", wraplength=460)
        self.vm_title.pack(anchor="w", pady=(10, 6))
        self.vm_body = ctk.CTkLabel(self.video_msg, text="", font=self.F(14), text_color=C["text2"], anchor="w",
                                    justify="left", wraplength=460)
        self.vm_body.pack(anchor="w")
        self.vm_actions = ctk.CTkFrame(self.video_msg, fg_color="transparent")
        self.vm_actions.pack(anchor="w", pady=(14, 0))
        self._set_video_message(t("video.searching.title"), t("video.searching.body"), icon="camera")

        # Transporte: Grabar (y Transmitir, si está activo) · tiempo · mezcla · tomas
        tr = ctk.CTkFrame(c, fg_color=C["panel"], corner_radius=12, border_width=1, border_color=C["line"], height=88)
        tr.grid(row=3, column=0, sticky="ew", padx=22, pady=(14, 18))
        tr.grid_columnconfigure(2, weight=1)
        actions = ctk.CTkFrame(tr, fg_color="transparent")
        actions.grid(row=0, column=0, rowspan=2, padx=(16, 18), pady=16)
        self.btn_rec = ctk.CTkButton(actions, text=t("ui.main.grabar"), width=180, height=54, corner_radius=12,
                                     font=self.F(15, "bold"), fg_color=C["rec"], hover_color=C["rec_hover"],
                                     text_color="#FFFFFF", text_color_disabled=C["off"], command=self.toggle_recording)
        self.btn_rec.pack(side="left")
        self.transport_actions = actions          # los módulos opcionales agregan su acción (Transmitir)
        tbox = ctk.CTkFrame(tr, fg_color="transparent", width=200)
        tbox.grid(row=0, column=1, rowspan=2, sticky="w")
        self.lbl_timer = ctk.CTkLabel(tbox, text="00:00:00", font=self.F(26, mono=True), text_color=C["text"], anchor="w")
        self.lbl_timer.pack(anchor="w")
        self.lbl_rec_status = ctk.CTkLabel(tbox, text="", font=self.F(12), text_color=C["muted"], anchor="w")
        self.lbl_rec_status.pack(anchor="w")
        mbox = ctk.CTkFrame(tr, fg_color="transparent")
        mbox.grid(row=0, column=2, rowspan=2, sticky="ew", padx=(18, 12))
        self._transport_meter = mbox
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
        self.btn_takes = self._ghost_button(tr, t("mod.takes"), lambda: self.toggle_drawer("recording"), height=30)
        self.btn_takes.grid(row=0, column=3, rowspan=2, padx=(0, 14))
        self._narrow = None
        c.bind("<Configure>", self._on_center_resize)

    def _on_center_resize(self, e=None):
        """Con el cajón abierto el centro se angosta: los indicadores bajan bajo el nombre, el
        vúmetro de la mezcla pasa a su propia fila y el aviso del monitor se acomoda al ancho."""
        width = self.center.winfo_width()
        if width <= 1:
            return
        narrow = width < 820
        wrap = max(220, min(460, width - 140))
        for lbl in (self.vm_title, self.vm_body):
            lbl.configure(wraplength=wrap)
        if narrow == self._narrow:
            return
        self._narrow = narrow
        if narrow:
            self._head_chips.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
            self._transport_meter.grid(row=2, column=0, columnspan=4, sticky="ew", padx=16, pady=(0, 14))
        else:
            self._head_chips.grid(row=0, column=1, rowspan=2, columnspan=1, sticky="e", pady=0)
            self._transport_meter.grid(row=0, column=2, rowspan=2, columnspan=1, sticky="ew", padx=(18, 12), pady=0)

    def _field_label(self, master, text):
        return ctk.CTkLabel(master, text=text, font=self.F(12), text_color=C["muted"], anchor="w")

    def _option_menu(self, master, values, command, **kw):
        return ctk.CTkOptionMenu(master, values=values, command=command, height=34, corner_radius=8, dynamic_resizing=False,
                                 fg_color=C["raised"], button_color=C["raised"], button_hover_color=C["line2"],
                                 text_color=C["text"], dropdown_fg_color=C["panel"], dropdown_hover_color=C["raised"],
                                 dropdown_text_color=C["text"], font=self.F(13), dropdown_font=self.F(13), **kw)

    # ---- Secciones de «Avanzado» que viven en la app (las usa app/settings_panel.py) ----
    def _alive(self, w) -> bool:
        try:
            return bool(w and w.winfo_exists())
        except (AttributeError, RuntimeError):
            return False

    def _checkbox(self, master, text, var, wrap=320):
        """Casilla con su texto al lado, que se parte en líneas si no cabe (el cajón es angosto).
        Un clic en el texto también la marca o desmarca."""
        f = ctk.CTkFrame(master, fg_color="transparent")
        f.grid_columnconfigure(1, weight=1)
        cb = ctk.CTkCheckBox(f, text="", variable=var, width=24, fg_color=C["accent"], hover_color=C["accent"],
                             checkmark_color="#1A1408", border_color=C["line2"], checkbox_width=18, checkbox_height=18,
                             corner_radius=4, command=self._save_settings)
        cb.grid(row=0, column=0, sticky="nw", pady=(1, 0))
        lbl = ctk.CTkLabel(f, text=text, font=self.F(13), text_color=C["text"], anchor="w", justify="left",
                           wraplength=wrap)
        lbl.grid(row=0, column=1, sticky="w", padx=(6, 0))
        lbl.bind("<Button-1>", lambda _e: cb.toggle())
        return f

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
        self._rail_tick = getattr(self, "_rail_tick", 0) + 1
        if self._rail_tick % 4 == 0 and hasattr(self, "_rail_buttons"):
            self._paint_rail()                  # estado de cada módulo en el riel, una vez por segundo
        self.after(250, self._tick_ui)

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
                self._log_has_error = True
        try:
            self._ui(ins)
        except (AttributeError, RuntimeError):
            pass

    def _status(self, text, warn=False):
        clean = "".join(ch for ch in text if ord(ch) < 0x2600 or ch in "‑–—…«»")
        self.footer_text.configure(text=clean.strip()[:140])
        self.footer_dot.configure(text_color=C["warn"] if warn else C["ok"])

    def _load_settings(self) -> Dict:
        return paths.load_json(settings_path(), {})

    def _save_settings(self):
        s = self.settings
        s.update({
            "record_dir": self.record_dir_var.get(), "prefix": self.record_prefix_var.get(),
            "normalize": self.norm_mode, "sync_ms": self.sync_ms, "stems": self.opt_stems.get(),
            "reveal": self.opt_reveal.get(), "autoplay": self.opt_autoplay.get(),
            "summary": self.opt_summary.get(), "multitrack": self.opt_multitrack.get(),
            "compress_export": self.opt_compress.get(),
        })
        for old in ("audio_dev", "vol", "mode", "sample_rate", "buffer", "virtual_cam"):
            s.pop(old, None)                    # claves de la versión anterior, ya migradas
        paths.save_json(settings_path(), s)

    def on_closing(self):
        """Cerrar la ventana cierra la app por completo, siempre tras confirmarlo."""
        if self.rec_state == "saving":
            # Preguntar antes: cerrar a mitad no pierde la toma (los originales siguen en disco
            # y su ficha la termina de guardar al volver a abrir), pero conviene esperar.
            ans = ConfirmDialog.ask(self, t("save.close.title"), t("save.close.body"),
                                    [("wait", t("save.close.wait"), "primary"),
                                     ("close", t("save.close.anyway"), "danger")], self.F)
            ov = getattr(self, "save_overlay", None)
            if ans == "close":
                self.engine.cancel_export()
                self._shutdown()
            elif self._alive(ov):
                ov.grab_set()                   # el diálogo se llevó el bloqueo: vuelve a la barra
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
        for m in getattr(self, "modules", {}).values():
            try:
                m.on_app_close()                # p. ej. Transmisión: cortar el directo y el repartidor
            except Exception as e:
                GLOBAL_LOGGER.log(f"Aviso al cerrar el módulo {m.spec.key}: {e}", "WARN")

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
