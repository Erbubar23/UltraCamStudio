"""
UltraCam Studio - Ventana única de Configuración

Un solo lugar para todo lo que no es de uso diario, en secciones con navegación
lateral (patrón de OBS, Ableton o Discord). La pantalla principal conserva solo lo
básico: cámara, formato, mezclador, OBS y grabar.
"""

import os
import threading
from typing import Dict, List, Optional

import customtkinter as ctk
from tkinter import filedialog

import paths
import virtualcam
from audio_engine import new_id, source_label
from presentation.dialogs.confirm_dialog import ConfirmDialog
from presentation.strings import t

SECTIONS = [
    ("general", t("ui.settings.general")),
    ("video", t("ui.settings.video")),
    ("audio", t("ui.settings.audio")),
    ("channels", t("ui.settings.canales_y_efectos")),
    ("recording", t("ui.settings.grabacion")),
    ("vcam", t("ui.settings.camara_virtual")),
    ("advanced", t("ui.settings.avanzado")),
]
SAMPLE_RATES = [44100, 48000, 88200, 96000]
BUFFERS = [64, 128, 256, 512, 1024]
NONE = t("ui.settings.ninguno")


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        from gui import C
        self.C = C
        super().__init__(app, fg_color=C["rail"])
        self.app = app
        self.title(t("ui.settings.configuracion_ultracam_studio"))
        self.geometry("1060x740")
        self.minsize(900, 600)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.section = "general"
        self.sel_channel: Optional[str] = None
        self.wrap = 700
        self.stat_labels: Dict[str, ctk.CTkLabel] = {}
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=C["bg"])
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        ctk.CTkLabel(side, text=t("ui.settings.configuracion"), font=app.F(18, "bold"), text_color=C["text"],
                     anchor="w").pack(fill="x", padx=20, pady=(22, 14))
        self.nav = {}
        for key, label in SECTIONS:
            b = ctk.CTkButton(side, text=label, anchor="w", height=38, corner_radius=8, font=app.F(14),
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=2)
            self.nav[key] = b
        where = t("ui.settings.portable_junto_al_programa") if paths.is_portable() else t("ui.settings.guardado_en_tu_perfil_de")
        ctk.CTkLabel(side, text=where, font=app.F(11), text_color=C["faint"], anchor="w",
                     wraplength=200, justify="left").pack(side="bottom", fill="x", padx=20, pady=16)

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=C["raised"])
        self.body.grid(row=0, column=1, sticky="nsew", padx=(18, 8), pady=12)
        self.body.grid_columnconfigure(0, weight=1)
        self.after(50, self.lift)

    # ------------------------------------------------------------------ Shell
    def close(self):
        try:
            self.app._on_settings_closed()
        finally:
            self.destroy()

    def show(self, section: str = None, channel_id: Optional[str] = None):
        if section:
            self.section = section
        if channel_id:
            self.sel_channel = channel_id
        for k, b in self.nav.items():
            on = k == self.section
            b.configure(fg_color=self.C["raised"] if on else "transparent", hover_color=self.C["raised"],
                        text_color=self.C["text"] if on else self.C["muted"])
        self._render()
        self.deiconify()
        self.lift()
        self.focus_force()

    def refresh(self, section: Optional[str] = None):
        if section is None or section == self.section:
            self._render()

    def _render(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.stat_labels = {}
        self.wrap = 500 if self.section == "channels" else 700
        getattr(self, f"_sec_{self.section}")(self.body)
        self.body._parent_canvas.yview_moveto(0)

    # ------------------------------------------------------------ Utilidades
    def h1(self, parent, text, sub=None, row=0):
        ctk.CTkLabel(parent, text=text, font=self.app.F(22, "bold"), text_color=self.C["text"],
                     anchor="w").grid(row=row, column=0, sticky="ew", pady=(4, 2))
        if sub:
            ctk.CTkLabel(parent, text=sub, font=self.app.F(13), text_color=self.C["muted"], anchor="w",
                         wraplength=720, justify="left").grid(row=row + 1, column=0, sticky="ew", pady=(0, 16))

    def card(self, parent, row, title=None, pady=(0, 14)):
        c = ctk.CTkFrame(parent, fg_color=self.C["panel"], corner_radius=12, border_width=1, border_color=self.C["line"])
        c.grid(row=row, column=0, sticky="ew", pady=pady)
        c.grid_columnconfigure(0, weight=1)
        inner = ctk.CTkFrame(c, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=18, pady=16)
        inner.grid_columnconfigure(0, weight=1)
        if title:
            self.app._section_label(inner, title).grid(row=0, column=0, sticky="ew", pady=(0, 10))
        return inner

    def note(self, parent, text, row, color=None, pady=(4, 0), wrap=None):
        ctk.CTkLabel(parent, text=text, font=self.app.F(12), text_color=color or self.C["faint"], anchor="w",
                     wraplength=wrap or self.wrap, justify="left").grid(row=row, column=0, sticky="ew", pady=pady)

    def field(self, parent, label, widget_fn, row):
        """Fila «etiqueta: control» a dos columnas."""
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row, column=0, sticky="ew", pady=5)
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text=label, font=self.app.F(13), text_color=self.C["text2"], width=190,
                     anchor="w").grid(row=0, column=0, sticky="w")
        w = widget_fn(f)
        w.grid(row=0, column=1, sticky="ew")
        return w

    def menu(self, parent, values, current, command):
        m = self.app._option_menu(parent, values or [NONE], command)
        m.set(current if current in (values or []) else (values[0] if values else NONE))
        return m

    # =================================================================== GENERAL
    def _sec_general(self, b):
        self.h1(b, t("ui.settings.general"), t("ui.settings.donde_guarda_sus_datos_ultracam"))
        c = self.card(b, 2, t("ui.settings.datos_de_la_aplicacion"))
        portable = paths.is_portable()
        ctk.CTkLabel(c, text=(t("ui.settings.modo_portable_todo_se_guarda")) if portable else
                     (t("ui.settings.la_carpeta_del_programa_no")),
                     font=self.app.F(13), text_color=self.C["text2"], anchor="w", wraplength=700,
                     justify="left").grid(row=1, column=0, sticky="ew")
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=f"  {paths.data_dir()}", font=self.app.F(12, mono=True), text_color=self.C["text2"],
                     fg_color=self.C["raised"], corner_radius=8, height=34, anchor="w").grid(row=0, column=0, sticky="ew")
        self.app._outline_button(row, t("ui.settings.abrir_carpeta"), lambda: os.startfile(paths.data_dir()), height=34,
                                 width=120).grid(row=0, column=1, padx=(8, 0))

        c2 = self.card(b, 3, t("ui.settings.restablecer"))
        self.note(c2, t("ui.settings.borra_la_configuracion_canales_efectos"), 1, pady=(0, 10))
        self.app._outline_button(c2, t("ui.settings.restablecer_configuracion"), self._factory_reset, height=36,
                                 width=220).grid(row=2, column=0, sticky="w")
        self.app._outline_button(b, t("welcome.reopen"), self.app.show_welcome, height=34,
                                 width=220).grid(row=4, column=0, sticky="w", pady=(0, 8))
        from gui import APP_VERSION
        self.note(b, f"UltraCam Studio v{APP_VERSION}", 5, pady=(8, 0))

    def _factory_reset(self):
        ans = ConfirmDialog.ask(self, t("reset.title"), t("reset.body"),
                                [("cancel", t("action.cancel"), "ghost"), ("reset", t("reset.confirm"), "danger")],
                                self.app.F)
        if ans != "reset":
            return
        try:
            os.remove(paths.settings_path())
        except OSError:
            pass
        self.app.settings = {}
        self.app._save_settings = lambda: None      # que el cierre no vuelva a escribir la configuración
        self.app._shutdown()

    # ===================================================================== VIDEO
    def _sec_video(self, b):
        self.h1(b, t("ui.settings.video"), t("ui.settings.ajustes_de_la_camara_seleccionada"))
        holder = ctk.CTkFrame(b, fg_color="transparent")
        holder.grid(row=2, column=0, sticky="ew")
        holder.grid_columnconfigure(0, weight=1)
        self.app.build_video_settings(holder, wrap=700)

    # ===================================================================== AUDIO
    def _sec_audio(self, b):
        app = self.app
        cfg = app.audio_engine.config
        devs = app.audio_devices or {}
        self.h1(b, t("ui.settings.audio"), t("ui.settings.el_dispositivo_principal_marca_el"))
        c = self.card(b, 2, t("ui.settings.dispositivo_principal"))
        drv = cfg.get("driver", "wasapi")
        seg = app._segmented(c, [("wasapi", t("ui.settings.windows_audio")), ("asio", t("ui.settings.asio_baja_latencia"))], drv,
                             lambda v: self._set_audio("driver", v), font=app.F(13, "bold"))
        seg.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        r = 2
        if drv == "asio":
            names = [d["name"] for d in devs.get("asio", [])]
            if not names:
                self.note(c, t("ui.settings.no_se_encontraron_drivers_asio"), r, color=self.C["warn"])
                r += 1
            else:
                self.field(c, t("ui.settings.driver_asio"), lambda p: self.menu(p, names, cfg.get("asio_device"),
                                                                  lambda v: self._set_audio("asio_device", v)), r)
                r += 1
                dev = next((d for d in devs.get("asio", []) if d["name"] == cfg.get("asio_device")), None)
                outs = dev["out"] if dev else 2
                pairs = [t("settings.outputs_pair", a=i + 1, b=i + 2) for i in range(0, max(2, outs) - 1, 2)]
                cur = cfg.get("monitor_out", [0, 1])
                self.field(c, t("ui.settings.salida_del_monitor"), lambda p: self.menu(
                    p, pairs, t("settings.outputs_pair", a=cur[0] + 1, b=cur[0] + 2),
                    lambda v: self._set_audio("monitor_out", [int(v.split()[1].split("-")[0]) - 1,
                                                              int(v.split()[1].split("-")[0])])), r)
                r += 1
                bx = ctk.CTkFrame(c, fg_color="transparent")
                bx.grid(row=r, column=0, sticky="ew", pady=(8, 0))
                app._outline_button(bx, t("ui.settings.panel_del_driver_asio"), self._asio_panel, height=34, width=190).pack(side="left")
                ctk.CTkLabel(bx, text=t("ui.settings.muchas_interfaces_fijan_el_tamano"), font=app.F(12),
                             text_color=self.C["faint"]).pack(side="left", padx=12)
                r += 1
                self.note(c, t("ui.settings.con_asio_ultracam_usa_la"), r)
                r += 1
        else:
            ins = [d["name"] for d in devs.get("wasapi_in", [])]
            outs = [d["name"] for d in devs.get("wasapi_out", [])]
            self.field(c, t("ui.settings.entrada_principal"), lambda p: self.menu(p, [NONE] + ins, cfg.get("input_device") or NONE,
                                                                   lambda v: self._set_audio("input_device", None if v == NONE else v)), r)
            r += 1
            self.field(c, t("ui.settings.salida_del_monitor"), lambda p: self.menu(p, [NONE] + outs, cfg.get("output_device") or NONE,
                                                                    lambda v: self._set_audio("output_device", None if v == NONE else v)), r)
            r += 1
            self.note(c, t("ui.settings.en_windows_audio_la_latencia"), r)
            r += 1

        c2 = self.card(b, 3, t("ui.settings.formato"))
        self.field(c2, t("ui.settings.frecuencia_de_muestreo"), lambda p: self.menu(
            p, [f"{x} Hz" for x in SAMPLE_RATES], f"{cfg.get('sample_rate', 48000)} Hz",
            lambda v: self._set_audio("sample_rate", int(v.split()[0]))), 1)
        f = ctk.CTkFrame(c2, fg_color="transparent")
        f.grid(row=2, column=0, sticky="ew", pady=5)
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text=t("ui.settings.bufer_muestras"), font=app.F(13), text_color=self.C["text2"], width=190,
                     anchor="w").grid(row=0, column=0, sticky="w")
        sb = app._segmented(f, [(x, str(x)) for x in BUFFERS], int(cfg.get("buffer", 256)),
                            lambda v: self._set_audio("buffer", int(v)), font=app.F(12, "bold", mono=True))
        sb.grid(row=0, column=1, sticky="ew")
        self.note(c2, t("ui.settings.bufer_mas_chico_menos_retraso"), 3)

        c3 = self.card(b, 4, t("ui.settings.estado"))
        grid = ctk.CTkFrame(c3, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew")
        grid.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="s")
        for i, (k, lab) in enumerate([("latency", t("ui.settings.latencia_total")), ("detail", t("ui.settings.entrada_salida")),
                                      ("cpu", t("ui.settings.carga_de_audio")), ("xruns", t("ui.settings.cortes"))]):
            cell = ctk.CTkFrame(grid, fg_color=self.C["raised"], corner_radius=9)
            cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
            ctk.CTkLabel(cell, text=lab, font=app.F(11), text_color=self.C["muted"]).pack(anchor="w", padx=10, pady=(8, 0))
            v = ctk.CTkLabel(cell, text="—", font=app.F(16, mono=True), text_color=self.C["text"])
            v.pack(anchor="w", padx=10, pady=(0, 8))
            self.stat_labels[k] = v
        self.stat_labels["error"] = ctk.CTkLabel(c3, text="", font=app.F(12), text_color=self.C["warn"], anchor="w",
                                                 wraplength=700, justify="left")
        self.stat_labels["error"].grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bx = ctk.CTkFrame(c3, fg_color="transparent")
        bx.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        app._outline_button(bx, t("ui.settings.buscar_dispositivos_de_nuevo"), lambda: app.refresh_audio_devices(lambda: self.refresh("audio")),
                            height=34, width=220).pack(side="left")
        app._outline_button(bx, t("ui.settings.reiniciar_audio"), app.apply_audio_config, height=34, width=140).pack(side="left", padx=8)
        self.on_stats(app.audio_stats)

    def on_stats(self, st: Dict):
        if self.section != "audio" or not self.stat_labels:
            return
        try:
            li, lo = st.get("latency_in") or 0, st.get("latency_out") or 0
            self.stat_labels["latency"].configure(text=f"{li + lo:.1f} ms" if (li or lo) else "—")
            self.stat_labels["detail"].configure(text=f"{li:.1f} / {lo:.1f}" if (li or lo) else "—")
            self.stat_labels["cpu"].configure(text=f"{st.get('cpu', 0):.0f} %")
            self.stat_labels["xruns"].configure(text=str(st.get("xruns", 0)),
                                                text_color=self.C["warn"] if st.get("xruns") else self.C["text"])
            err = st.get("error") or ""
            if not err and not st.get("input") and not st.get("output"):
                err = t("ui.settings.sin_dispositivo_principal_el_audio")
            self.stat_labels["error"].configure(text=err)
        except Exception:
            pass

    def _set_audio(self, key, value):
        cfg = self.app.audio_engine.config
        cfg[key] = value
        if key == "driver" and value == "asio" and not cfg.get("asio_device"):
            names = [d["name"] for d in (self.app.audio_devices or {}).get("asio", [])]
            cfg["asio_device"] = next((n for n in names if "rearoute" not in n.lower()), names[0] if names else None)
        self.app.apply_audio_config()
        self.refresh("audio")

    def _asio_panel(self):
        self.app.audio_engine.open_asio_panel()

    # ================================================================= CANALES
    def _source_options(self) -> List[tuple]:
        """(etiqueta, fuente) para el menú de fuente de un canal."""
        app = self.app
        cfg = app.audio_engine.config
        devs = app.audio_devices or {}
        opts = []
        if cfg.get("driver") == "asio":
            dev = next((d for d in devs.get("asio", []) if d["name"] == cfg.get("asio_device")), None)
            n_in, dname = (dev["in"] if dev else 0), cfg.get("asio_device")
        else:
            dev = next((d for d in devs.get("wasapi_in", []) if d["name"] == cfg.get("input_device")), None)
            n_in, dname = (dev["in"] if dev else 0), cfg.get("input_device")
        for i in range(n_in):
            opts.append((t("settings.input_n", n=i + 1, device=dname), {"kind": "main", "ch": [i]}))
        for i in range(0, n_in - 1, 2):
            opts.append((t("settings.inputs_pair", a=i + 1, b=i + 2, device=dname), {"kind": "main", "ch": [i, i + 1]}))
        for d in devs.get("extra", []):
            lab = d["name"] + (" · Lo que suena" if d["loopback"] else "")
            opts.append((lab, {"kind": "device", "device": d["name"], "loopback": d["loopback"]}))
        opts.append((t("ui.settings.sin_fuente"), {"kind": "none"}))
        return opts

    def _sec_channels(self, b):
        app = self.app
        chans = app.audio_engine.config["channels"]
        self.h1(b, t("ui.settings.canales_y_efectos"), t("ui.settings.cada_canal_es_una_fuente"))
        wrap = ctk.CTkFrame(b, fg_color="transparent")
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.grid_columnconfigure(1, weight=1)
        lst = ctk.CTkFrame(wrap, fg_color=self.C["panel"], corner_radius=12, width=230)
        lst.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        if chans and self.sel_channel not in [c["id"] for c in chans]:
            self.sel_channel = chans[0]["id"]
        for i, ch in enumerate(chans):
            on = ch["id"] == self.sel_channel
            row = ctk.CTkButton(lst, text=f"   {ch['name']}", anchor="w", height=38, corner_radius=8, font=app.F(13),
                                fg_color=self.C["raised"] if on else "transparent", hover_color=self.C["raised"],
                                text_color=self.C["text"] if on else self.C["text2"], width=210,
                                command=lambda cid=ch["id"]: (setattr(self, "sel_channel", cid), self.refresh("channels")))
            row.grid(row=i, column=0, sticky="ew", padx=8, pady=(8 if i == 0 else 2, 2))
            ctk.CTkFrame(row, width=8, height=8, corner_radius=2, fg_color=ch.get("color") or "#888").place(x=10, rely=0.5, anchor="w")
        ctk.CTkButton(lst, text=t("ui.settings.nuevo_canal"), height=36, corner_radius=8, font=app.F(13, "bold"), width=210,
                      fg_color="transparent", border_width=1, border_color=self.C["line2"], hover_color=self.C["raised"],
                      text_color=self.C["text"], command=self._new_channel).grid(row=len(chans), column=0, padx=8, pady=10)

        ch = app.audio_engine.channel(self.sel_channel) if self.sel_channel else None
        det = ctk.CTkFrame(wrap, fg_color="transparent")
        det.grid(row=0, column=1, sticky="nsew")
        det.grid_columnconfigure(0, weight=1)
        if not ch:
            self.note(det, t("ui.settings.agrega_un_canal_para_empezar"), 0)
            return
        cid = ch["id"]
        c = self.card(det, 0, t("ui.settings.canal"))
        e = self.field(c, t("ui.settings.nombre"), lambda p: ctk.CTkEntry(p, height=34, corner_radius=8, fg_color=self.C["raised"],
                                                           border_color=self.C["line2"], text_color=self.C["text"],
                                                           font=app.F(13)), 1)
        e.insert(0, ch["name"])
        e.bind("<Return>", lambda _e: self._rename(cid, e.get()))
        e.bind("<FocusOut>", lambda _e: self._rename(cid, e.get()))
        opts = self._source_options()
        labels = [o[0] for o in opts]
        cur = next((lab for lab, src in opts if self._same_source(src, ch["source"])),
                   source_label(ch["source"], app.audio_engine.config))
        if cur not in labels:
            labels = [cur] + labels
        self.field(c, t("ui.settings.fuente"), lambda p: self.menu(p, labels, cur, lambda v: self._set_source(cid, v, opts)), 2)
        f = ctk.CTkFrame(c, fg_color="transparent")
        f.grid(row=3, column=0, sticky="ew", pady=5)
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text=t("ui.settings.canales"), font=app.F(13), text_color=self.C["text2"], width=190, anchor="w").grid(row=0, column=0)
        seg = app._segmented(f, [("mono", t("ui.settings.mono_al_centro")), ("stereo", t("ui.settings.estereo"))], ch.get("mode", "mono"),
                             lambda v: self._set_param(cid, "mode", v, refresh=True), font=app.F(12, "bold"))
        seg.grid(row=0, column=1, sticky="ew")
        sw = ctk.CTkSwitch(c, text=t("ui.settings.escucharlo_en_el_monitor_audifonos"), font=app.F(13), text_color=self.C["text"],
                           progress_color=self.C["accent"], button_color=self.C["text"], fg_color=self.C["line2"],
                           command=lambda: self._set_param(cid, "monitor", bool(sw.get())))
        if ch.get("monitor"):
            sw.select()
        sw.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.note(c, t("ui.settings.mono_al_centro_manda_una"), 5)
        err = (app.audio_stats.get("channel_errors") or {}).get(cid)
        if err:
            self.note(c, f"⚠ {err}", 6, color=self.C["warn"])

        # Efectos
        fxc = self.card(det, 1, t("ui.settings.efectos_vst3"))
        status = {f["id"]: f for f in app.audio_engine.fx_status.get(cid, [])}
        for i, fx in enumerate(ch.get("fx", [])):
            st = status.get(fx["id"], {})
            row = ctk.CTkFrame(fxc, fg_color=self.C["raised"], corner_radius=9)
            row.grid(row=1 + i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(1, weight=1)
            esw = ctk.CTkSwitch(row, text="", width=46, progress_color=self.C["accent"], button_color=self.C["text"],
                                fg_color=self.C["line2"], command=lambda k=i: self._toggle_fx(cid, k))
            if fx.get("enabled", True):
                esw.select()
            esw.grid(row=0, column=0, padx=(10, 4), pady=8)
            name = st.get("name") or os.path.splitext(os.path.basename(fx["path"]))[0]
            txt = f"{i + 1}.  {name}" + (t("ui.settings.no_se_pudo_cargar") if st.get("error") else "")
            ctk.CTkLabel(row, text=txt, font=app.F(13, "bold"), text_color=self.C["warn"] if st.get("error") else self.C["text"],
                         anchor="w").grid(row=0, column=1, sticky="ew")
            bx = ctk.CTkFrame(row, fg_color="transparent")
            bx.grid(row=0, column=2, padx=8)
            ctk.CTkButton(bx, text=t("ui.settings.abrir"), width=70, height=28, corner_radius=7, font=app.F(12, "bold"),
                          fg_color=self.C["text"], hover_color="#FFFFFF", text_color="#141413",
                          command=lambda f_id=fx["id"]: app.open_fx_editor(cid, f_id)).pack(side="left", padx=2)
            for sym, d in (("↑", -1), ("↓", 1)):
                app._ghost_button(bx, sym, lambda k=i, dd=d: self._move_fx(cid, k, dd), width=30, height=28).pack(side="left")
            app._ghost_button(bx, "✕", lambda k=i: self._remove_fx(cid, k), width=30, height=28).pack(side="left")
        if not ch.get("fx"):
            self.note(fxc, t("ui.settings.sin_efectos_la_senal_pasa"), 1, pady=(0, 6))
        add = ctk.CTkFrame(fxc, fg_color="transparent")
        add.grid(row=50, column=0, sticky="ew", pady=(10, 0))
        add.grid_columnconfigure(0, weight=1)
        names = [v["name"] for v in app.vst_list]
        pick = app._option_menu(add, (names or [t("ui.settings.no_se_encontraron_plugins")]) + [t("ui.settings.buscar_archivo_vst3")],
                                lambda v: self._add_fx(cid, v))
        pick.set(t("ui.settings.agregar_efecto"))
        pick.grid(row=0, column=0, sticky="ew")
        self.note(fxc, t("ui.settings.abre_la_ventana_del_efecto"), 51)

        acts = ctk.CTkFrame(det, fg_color="transparent")
        acts.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        app._outline_button(acts, t("ui.settings.subir"), lambda: self._move_channel(cid, -1), height=34, width=90).pack(side="left")
        app._outline_button(acts, t("ui.settings.bajar"), lambda: self._move_channel(cid, 1), height=34, width=90).pack(side="left", padx=8)
        ctk.CTkButton(acts, text=t("ui.settings.eliminar_canal"), height=34, width=140, corner_radius=9, font=app.F(13),
                      fg_color="transparent", border_width=1, border_color=self.C["rec"], hover_color="#3A1E20",
                      text_color=self.C["rec_text"], command=lambda: self._delete_channel(cid)).pack(side="right")

    @staticmethod
    def _same_source(a: Dict, b: Dict) -> bool:
        if a.get("kind") != b.get("kind"):
            return False
        if a.get("kind") == "main":
            return list(a.get("ch", [])) == list(b.get("ch", []))
        if a.get("kind") == "device":
            return a.get("device") == b.get("device") and bool(a.get("loopback")) == bool(b.get("loopback"))
        return True

    def _new_channel(self):
        ch = self.app.add_channel()
        self.sel_channel = ch["id"]
        self.refresh("channels")

    def _rename(self, cid, name):
        name = name.strip()
        ch = self.app.audio_engine.channel(cid)
        if not name or not ch or ch["name"] == name:
            return
        self.app.set_channel_param(cid, "name", name)
        self.app.render_mixer()
        self.refresh("channels")

    def _set_source(self, cid, label, opts):
        src = next((s for lab, s in opts if lab == label), None)
        ch = self.app.audio_engine.channel(cid)
        if src is None or ch is None:
            return
        ch["source"] = dict(src)
        if src.get("kind") == "main":
            ch["mode"] = "stereo" if len(src.get("ch", [])) > 1 else "mono"
        elif src.get("loopback"):
            ch["mode"] = "stereo"
        # Evitar realimentación: no monitorear lo que suena en la misma salida del monitor
        out = self.app.audio_engine.config.get("output_device")
        if src.get("loopback") and out and src.get("device") == out:
            ch["monitor"] = False
        self.app.apply_audio_config()
        self.refresh("channels")

    def _set_param(self, cid, key, value, refresh=False):
        self.app.set_channel_param(cid, key, value)
        self.app._paint_strip(cid)
        if refresh:
            self.refresh("channels")

    def _move_channel(self, cid, d):
        self.app.move_channel(cid, d)
        self.refresh("channels")

    def _delete_channel(self, cid):
        ch = self.app.audio_engine.channel(cid)
        if ch and ConfirmDialog.ask(self, t("channel.delete.title"), t("channel.delete.body", name=ch["name"]),
                                    [("cancel", t("action.cancel"), "ghost"),
                                     ("delete", t("channel.delete.confirm"), "danger")], self.app.F) == "delete":
            self.app.remove_channel(cid)
            self.sel_channel = None
            self.refresh("channels")

    def _fx_list(self, cid) -> List[Dict]:
        ch = self.app.audio_engine.channel(cid)
        return [dict(f) for f in ch.get("fx", [])] if ch else []

    def _add_fx(self, cid, label):
        path = None
        if label == t("ui.settings.buscar_archivo_vst3"):
            path = filedialog.askopenfilename(parent=self, title=t("ui.settings.elegir_plugin_vst3"),
                                              filetypes=[(t("ui.settings.plugin_vst3"), "*.vst3")])
            if path and os.path.basename(os.path.dirname(path)).lower().endswith(".vst3"):
                pass
        else:
            path = next((v["path"] for v in self.app.vst_list if v["name"] == label), None)
        if not path:
            self.refresh("channels")
            return
        fx = self._fx_list(cid) + [{"id": new_id("fx"), "path": path, "enabled": True}]
        self.app.set_channel_fx(cid, fx)
        self.refresh("channels")

    def _toggle_fx(self, cid, k):
        fx = self._fx_list(cid)
        fx[k]["enabled"] = not fx[k].get("enabled", True)
        self.app.set_channel_fx(cid, fx)

    def _move_fx(self, cid, k, d):
        fx = self._fx_list(cid)
        j = k + d
        if 0 <= j < len(fx):
            fx[k], fx[j] = fx[j], fx[k]
            self.app.set_channel_fx(cid, fx)
            self.refresh("channels")

    def _remove_fx(self, cid, k):
        fx = self._fx_list(cid)
        del fx[k]
        self.app.set_channel_fx(cid, fx)
        self.refresh("channels")

    def on_fx_loaded(self, cid):
        if self.section == "channels" and cid == self.sel_channel:
            self.refresh("channels")

    # =============================================================== GRABACIÓN
    def _sec_recording(self, b):
        self.h1(b, t("ui.settings.grabacion"), t("ui.settings.donde_se_guardan_las_tomas"))
        holder = ctk.CTkFrame(b, fg_color="transparent")
        holder.grid(row=2, column=0, sticky="ew")
        holder.grid_columnconfigure(0, weight=1)
        self.app.build_recording_settings(holder, wrap=700)

    # ===================================================================== CÁMARA VIRTUAL
    def _sec_vcam(self, b):
        app = self.app
        self.h1(b, t("ui.settings.camara_virtual_de_windows"),
                t("settings.vcam.intro", vcam=virtualcam.DEVICE_NAME))

        c = self.card(b, 2, t("ui.settings.estado"))
        info = virtualcam.SERVICE.status()
        sel = app._selected()
        sending = sel is not None and app.vcam_state.get("status") == "ok"
        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew")
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="v")
        cells = [
            (t("ui.settings.en_windows"), t("ui.settings.registrada") if info["registered"] else t("ui.settings.no_registrada"), info["registered"]),
            (t("ui.settings.enlace_con_la_app"), t("ui.settings.activo") if info["running"] else t("ui.settings.sin_enlace"), info["running"]),
            (t("ui.settings.imagen"), f"● {sel.name}" if sending else
             (t("ui.settings.en_pausa") if not app._vcam_on() else t("ui.settings.cartel_sin_senal")), sending or None),
        ]
        for i, (label, value, good) in enumerate(cells):
            cell = ctk.CTkFrame(grid, fg_color=self.C["raised"], corner_radius=9)
            cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
            ctk.CTkLabel(cell, text=label, font=app.F(11), text_color=self.C["muted"]).pack(anchor="w", padx=10, pady=(8, 0))
            color = self.C["muted"] if good is None else (self.C["ok"] if good else self.C["warn"])
            ctk.CTkLabel(cell, text=value if len(value) <= 26 else value[:25] + "…", font=app.F(15, "bold"),
                         text_color=color).pack(anchor="w", padx=10, pady=(0, 8))
        if info.get("error"):
            self.note(c, t("settings.vcam.last_error", error=info['error']), 2, color=self.C["warn"])
        app._outline_button(c, t("settings.vcam.reregister", vcam=virtualcam.DEVICE_NAME), self._reregister,
                            height=34, width=240).grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.note(c, t("ui.settings.usalo_si_la_camara_no"), 4)

        c2 = self.card(b, 3, t("ui.settings.calidad"))
        self.note(c2, t("ui.settings.como_con_una_webcam_cada"), 1, color=self.C["text2"], pady=(0, 0))

        c3 = self.card(b, 4, t("ui.settings.como_usarla_en_otros_programas"))
        instructions = t("settings.vcam.howto", vcam=virtualcam.DEVICE_NAME)
        self.note(c3, instructions, 1, color=self.C["text2"])

    def _reregister(self):
        virtualcam.SERVICE.stop()
        virtualcam.SERVICE.start(log=self.app.engine.log)
        self.app._paint_vcam()
        self.refresh("vcam")

    # ================================================================ AVANZADO
    def _sec_advanced(self, b):
        app = self.app
        self.h1(b, t("ui.settings.avanzado"))
        c = self.card(b, 2, t("ui.settings.registro_y_diagnostico"))
        bx = ctk.CTkFrame(c, fg_color="transparent")
        bx.grid(row=1, column=0, sticky="ew")
        app._outline_button(bx, t("ui.settings.mostrar_registro"), lambda: (app.log_open or app.toggle_log()), height=34, width=150).pack(side="left")
        app._outline_button(bx, t("ui.settings.copiar_registro"), app.copy_logs_to_clipboard, height=34, width=140).pack(side="left", padx=8)
        app._outline_button(bx, t("ui.settings.reportar_un_problema"), app.show_report_dialog, height=34, width=180).pack(side="left")

        c2 = self.card(b, 3, t("ui.settings.carpetas_de_plugins_vst3"))
        dirs = app.settings.setdefault("vst_dirs", [])
        from audio_engine import VST3_DIRS
        for i, d in enumerate([x for x in VST3_DIRS if x] + dirs):
            row = ctk.CTkFrame(c2, fg_color="transparent")
            row.grid(row=1 + i, column=0, sticky="ew", pady=2)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=f"  {d}", font=app.F(12, mono=True), text_color=self.C["text2"], fg_color=self.C["raised"],
                         corner_radius=7, height=30, anchor="w").grid(row=0, column=0, sticky="ew")
            if d in dirs:
                app._ghost_button(row, t("ui.settings.quitar"), lambda x=d: self._remove_vst_dir(x), height=30).grid(row=0, column=1, padx=(6, 0))
        bx2 = ctk.CTkFrame(c2, fg_color="transparent")
        bx2.grid(row=40, column=0, sticky="ew", pady=(10, 0))
        app._outline_button(bx2, t("ui.settings.agregar_carpeta"), self._add_vst_dir, height=34, width=160).pack(side="left")
        app._outline_button(bx2, t("ui.settings.buscar_plugins_de_nuevo"), lambda: app.refresh_audio_devices(lambda: self.refresh("advanced")),
                            height=34, width=200).pack(side="left", padx=8)
        ctk.CTkLabel(bx2, text=t("settings.vst_found", n=len(app.vst_list)), font=app.F(12),
                     text_color=self.C["muted"]).pack(side="left", padx=8)

        c3 = self.card(b, 4, t("ui.settings.motor_de_audio"))
        self.note(c3, t("ui.settings.el_audio_y_los_efectos"), 1, pady=(0, 10))
        app._outline_button(c3, t("ui.settings.reiniciar_motor_de_audio"), self._restart_engine, height=34, width=210).grid(row=2, column=0, sticky="w")

    def _add_vst_dir(self):
        d = filedialog.askdirectory(parent=self, title=t("ui.settings.carpeta_con_plugins_vst3"))
        if d:
            dirs = self.app.settings.setdefault("vst_dirs", [])
            if d not in dirs:
                dirs.append(os.path.normpath(d))
                self.app._save_settings()
            self.app.refresh_audio_devices(lambda: self.refresh("advanced"))

    def _remove_vst_dir(self, d):
        dirs = self.app.settings.setdefault("vst_dirs", [])
        if d in dirs:
            dirs.remove(d)
            self.app._save_settings()
        self.app.refresh_audio_devices(lambda: self.refresh("advanced"))

    def _restart_engine(self):
        import threading
        app = self.app
        if app.rec_state != "idle":
            app.notify.toast(t("audio.busy_recording"), "warn")
            return

        def work():
            try:
                app.audio_engine.collect_fx_states()
            except Exception:
                pass
            app.audio_engine.stop()
            app.audio_engine.start()
            app.audio_engine.apply(wait=True)
            app._ui(app.notify.toast, t("audio.restarted"))
        threading.Thread(target=work, daemon=True).start()
