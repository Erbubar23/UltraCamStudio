"""
UltraCam Studio - Módulo Grabación: empezar y terminar tomas, unir video y audio, tomas recientes
y ajustes de archivo.

Mixin de GalaxyCamApp (gui.py): sus métodos usan el estado compartido de la ventana.
"""

import os
import time
import threading
import subprocess
import datetime
import customtkinter as ctk
from tkinter import filedialog
from infrastructure.logging.app_logger import GLOBAL_LOGGER
from presentation.strings import t
from modules.recording.ui.summary_dialog import TakeSummaryDialog
from presentation.theme import C, ICON, NORM_OPTIONS
from app.constants import APP_NAME
from app.bus import SAVE_PROGRESS
from modules.recording.disk import DISK_MIN_TO_START, disk_free, disk_verdict, fmt_bytes
from modules.recording.export import encoders, sessions
from modules.recording.ui.save_overlay import SaveOverlay
import paths


def fmt_mb(mb) -> str:
    """«9,1 GB» / «820 MB» a partir de megabytes."""
    mb = float(mb or 0)
    return f"{mb / 1024:.1f} GB".replace(".", ",") if mb >= 1024 else f"{mb:.0f} MB"


class RecordingMixin:
    def _build_takes_panel(self, parent):
        p = ctk.CTkFrame(parent, fg_color="transparent")
        p.grid(row=0, column=0, sticky="nsew")
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(2, weight=1)
        head = ctk.CTkFrame(p, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        self._section_label(head, t("ui.main.tomas_recientes")).pack(side="left")
        self._ghost_button(head, t("action.open_folder"), self.open_recordings_folder, height=28).pack(side="right")

        self.saved_banner = ctk.CTkFrame(p, fg_color=C["ok_bg"], corner_radius=9, border_width=1, border_color=C["ok_line"])
        self.saved_banner.grid_columnconfigure((0, 1, 2), weight=1)
        self.saved_lbl = ctk.CTkLabel(self.saved_banner, text="", font=self.F(12), text_color=C["ok_text"], anchor="w",
                                      justify="left", wraplength=330)
        self.saved_lbl.grid(row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(8, 2))
        # Accesos directos a la última toma: lo primero que se quiere hacer al terminar
        for i, (attr, key) in enumerate((("saved_play", "action.play"), ("saved_reveal", "action.reveal"),
                                         ("saved_btn", "action.summary"))):
            b = ctk.CTkButton(self.saved_banner, text=t(key), width=10, height=28, fg_color="transparent",
                              hover_color=C["ok_line"], text_color="#7FDCA9", font=self.F(12, "bold"))
            b.grid(row=1, column=i, sticky="ew", padx=4, pady=(0, 6))
            setattr(self, attr, b)

        self.takes_list = ctk.CTkScrollableFrame(p, fg_color="transparent", scrollbar_button_color=C["raised"])
        self.takes_list.grid(row=2, column=0, sticky="nsew", pady=(6, 0))
        self.takes_list.grid_columnconfigure(0, weight=1)
        self.takes_panel = p

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
        stack = wrap < 500                           # en el cajón (angosto) van uno debajo del otro
        nb.grid_columnconfigure(0 if stack else (0, 1, 2), weight=1, uniform="n")
        for i, (key, title, sub) in enumerate(NORM_OPTIONS):
            b = ctk.CTkButton(nb, text=f"{title}\n{sub}", height=50 if stack else 56, corner_radius=10, anchor="w",
                              border_width=1, font=self.F(12), text_color=C["text"], width=10,
                              command=lambda k=key: self._pick_norm(k))
            if stack:
                b.grid(row=i, column=0, sticky="ew", pady=(0 if i == 0 else 4, 0))
            else:
                b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
            self.norm_buttons[key] = b
        self._paint_norm()

        self._section_label(parent, t("ui.main.pistas")).grid(row=7, column=0, sticky="ew", pady=(20, 8), **pad)
        self._checkbox(parent, t("ui.main.guardar_cada_canal_del_mezclador"), self.opt_multitrack, wrap - 40).grid(
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
            self._checkbox(parent, text, var, wrap - 40).grid(row=14 + i, column=0, sticky="ew", pady=5, **pad)
        self._checkbox(parent, t("save.compress_option"), self.opt_compress, wrap - 40).grid(row=18, column=0, sticky="ew",
                                                                                  pady=(5, 0), **pad)
        ctk.CTkLabel(parent, text=t("save.compress_note"), font=self.F(12), text_color=C["faint"], wraplength=wrap,
                     justify="left", anchor="w").grid(row=19, column=0, sticky="ew", padx=(32, 4), pady=(2, 0))

    # =========================================================================
    # GRABACIÓN
    # =========================================================================
    def toggle_recording(self):
        if self.rec_state == "idle":
            if self.ready_check():
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
            "timestamp": datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
            "compress": self.opt_compress.get(),
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
        if was_recording:
            self._show_save_overlay()

        def work():
            if self.engine.is_running:
                self.engine.stop_stream()
            if not was_recording or not vid_path or not os.path.exists(vid_path):
                self._ui(lambda: self._after_save({"success": False, "message": t("ui.main.no_se_genero_video")}, then))
                return
            self._export_take(vid_path, audio_info, options, then)
        self._stream_jobs.submit(work)     # en orden con los arranques y paradas de cámara

    # ---- Exportación: comprimir sin cambiar el flujo, con barra y a prueba de cierres ----
    def _export_encoders(self):
        """Codificadores que funcionan en esta PC (se prueban una vez, ~1 s, en segundo plano)."""
        with self._encoders_lock:
            if self._encoders is None:
                ff = self.engine.ffmpeg_path
                no_window = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self._encoders = encoders.probe_available(
                    lambda cmd: subprocess.run(cmd, capture_output=True, timeout=30, creationflags=no_window).returncode,
                    ff) if ff else []
                desc = encoders.describe(self._encoders)
                self.engine.log(f"Archivo final comprimido con: HEVC {desc['hevc']} · H.264 {desc['h264']}", "REC")
            return self._encoders

    def _export_take(self, vid_path, audio_info, options, then=None, manifest=None):
        """(Hilo de trabajo) Elige el codificador, deja la ficha de la toma y une/comprime.
        Si algo sale mal, el motor guarda como siempre (copiando el video)."""
        info = self.engine.probe_media(vid_path)
        choice = None
        if options.get("compress", True):
            choice = encoders.choose(info.get("codec"), info.get("height") or 0, self._export_encoders(),
                                     info.get("bitrate"))
        opts = dict(options, source_info=info, video_args=choice.args if choice else None)
        if manifest is None:
            manifest = sessions.save(paths.data_dir(), vid_path, audio_info, opts)
        label = choice.label if choice else ""
        opts["progress"] = lambda step, frac, speed, eta: self._ui(self._on_save_progress, step, frac, speed, eta, label)
        res = self.engine.finalize_recording(vid_path, audio_info, opts)
        if res.get("success"):
            sessions.remove(manifest)          # si no se pudo, la ficha queda: se reintenta al abrir
        self._ui(lambda: self._after_save(res, then))

    def _show_save_overlay(self):
        if not self._alive(getattr(self, "save_overlay", None)):
            self.save_overlay = SaveOverlay(self, t("save.title"))

    def _on_save_progress(self, step, frac, speed, eta, label=""):
        ov = getattr(self, "save_overlay", None)
        if self._alive(ov):
            ov.encoder_label = label
            ov.update_step(step, frac, speed, eta)
        self.bus.emit(SAVE_PROGRESS, step=step, fraction=frac, eta_s=eta)

    def _close_save_overlay(self):
        ov = getattr(self, "save_overlay", None)
        if self._alive(ov):
            ov.close()
        self.save_overlay = None

    def _check_pending_takes(self):
        """Al abrir: ¿quedó alguna toma sin terminar de guardar (cierre o apagón a mitad)?"""
        found = sessions.pending(paths.data_dir())
        if found:
            self.notify.banner("pending", t("save.pending", n=len(found)), "warn",
                               actions=[(t("save.pending_action"), self._recover_take)])

    def _recover_take(self):
        """Termina de guardar la primera toma pendiente, con la misma barra (los originales
        siguen en disco: la ficha se borra recién con el MP4 verificado)."""
        if self.rec_state != "idle":
            self.notify.toast(t("save.busy"), "warn")
            return
        found = sessions.pending(paths.data_dir())
        self.notify.clear("pending")
        if not found:
            return
        take = found[0]
        self.rec_state = "saving"
        self._update_transport()
        self._stop_preview()                   # el monitor (ventana nativa) quedaría encima de la barra
        self._show_save_overlay()
        self._stream_jobs.submit(lambda: self._export_take(take["video"], take["audio"], take["options"],
                                                           then=self._after_recovery, manifest=take["path"]))

    def _after_recovery(self):
        self._start_preview()
        self.after(500, self._check_pending_takes)     # si había más de una, se ofrece la siguiente

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
        self._close_save_overlay()
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
            if res.get("compressed"):
                self.notify.toast(t("rec.saved.compressed", file=name, size=fmt_mb(res.get("file_size_mb")),
                                    before=fmt_mb(res.get("original_size_mb"))))
            else:
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
            # Dos líneas (el cajón es angosto): el nombre arriba; cuándo, cuánto pesa y las acciones abajo
            row = ctk.CTkFrame(self.takes_list, fg_color=C["rail"], corner_radius=9, border_width=1, border_color="#25252A")
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=ICON["video"], font=self.IF(14), text_color=C["muted"]).grid(row=0, column=0, padx=(12, 8),
                                                                                              pady=(8, 0), sticky="n")
            ctk.CTkLabel(row, text=os.path.basename(p), font=self.F(12), text_color=C["text"], anchor="w", justify="left",
                         wraplength=300).grid(row=0, column=1, columnspan=3, sticky="ew", pady=(8, 0), padx=(0, 10))
            dt = datetime.datetime.fromtimestamp(mt)
            when = (t("ui.main.hoy") if dt.date() == today else dt.strftime("%d/%m ")) + dt.strftime("%H:%M")
            size = os.path.getsize(p) / (1024 * 1024)
            ctk.CTkLabel(row, text=f"{when} · {fmt_mb(size)}", font=self.F(11), text_color=C["faint"],
                         anchor="w").grid(row=1, column=1, sticky="w", pady=(0, 8))
            self._ghost_button(row, t("ui.main.mostrar"), lambda f=p: self._reveal(f), height=28).grid(row=1, column=2, pady=(0, 6))
            ctk.CTkButton(row, text=t("ui.main.reproducir"), command=lambda f=p: self._play(f), height=28, width=84, corner_radius=7,
                          fg_color="transparent", border_width=1, border_color=C["line2"], hover_color=C["raised"],
                          text_color=C["text"], font=self.F(12)).grid(row=1, column=3, padx=(4, 8), pady=(0, 6))

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
