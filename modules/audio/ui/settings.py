"""
UltraCam Studio - Módulo Audio › Avanzado: dispositivo, canales, instrumentos, efectos y plugins.

Mixin del panel de ajustes (app/settings_panel.py): usa sus utilidades (h1, card, note, field, menu,
refresh) y su estado (sel_channel, wrap…).
"""

import os
from typing import Dict, List
import customtkinter as ctk
from tkinter import filedialog
from audio_engine import new_id, new_instrument_source, plugin_name, source_label
from presentation.dialogs.confirm_dialog import ConfirmDialog
from presentation.strings import t

SAMPLE_RATES = [44100, 48000, 88200, 96000]
BUFFERS = [64, 128, 256, 512, 1024]
NONE = t("ui.settings.ninguno")


class AudioSettings:
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
                app._outline_button(c, t("ui.settings.panel_del_driver_asio"), self._asio_panel,
                                    height=34).grid(row=r, column=0, sticky="ew", pady=(8, 0))
                r += 1
                self.note(c, t("ui.settings.muchas_interfaces_fijan_el_tamano"), r)
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
        self.field(c2, t("ui.settings.bufer_muestras"), lambda p: app._segmented(
            p, [(x, str(x)) for x in BUFFERS], int(cfg.get("buffer", 256)),
            lambda v: self._set_audio("buffer", int(v)), font=app.F(11, "bold", mono=True)), 2)
        self.note(c2, t("ui.settings.bufer_mas_chico_menos_retraso"), 3)

        c3 = self.card(b, 4, t("ui.settings.estado"))
        grid = ctk.CTkFrame(c3, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew")
        grid.grid_columnconfigure((0, 1), weight=1, uniform="s")
        for i, (k, lab) in enumerate([("latency", t("ui.settings.latencia_total")), ("detail", t("ui.settings.entrada_salida")),
                                      ("cpu", t("ui.settings.carga_de_audio")), ("xruns", t("ui.settings.cortes"))]):
            cell = ctk.CTkFrame(grid, fg_color=self.C["raised"], corner_radius=9)
            cell.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0 if i % 2 == 0 else 4, 0), pady=(0 if i < 2 else 4, 0))
            ctk.CTkLabel(cell, text=lab, font=app.F(11), text_color=self.C["muted"]).pack(anchor="w", padx=10, pady=(8, 0))
            v = ctk.CTkLabel(cell, text="—", font=app.F(15, mono=True), text_color=self.C["text"])
            v.pack(anchor="w", padx=10, pady=(0, 8))
            self.stat_labels[k] = v
        self.stat_labels["error"] = ctk.CTkLabel(c3, text="", font=app.F(12), text_color=self.C["warn"], anchor="w",
                                                 wraplength=self.wrap, justify="left")
        self.stat_labels["error"].grid(row=2, column=0, sticky="ew", pady=(8, 0))
        app._outline_button(c3, t("ui.settings.buscar_dispositivos_de_nuevo"),
                            lambda: app.refresh_audio_devices(lambda: self.refresh("audio")),
                            height=34).grid(row=3, column=0, sticky="ew", pady=(10, 0))
        app._outline_button(c3, t("ui.settings.reiniciar_audio"), app.apply_audio_config,
                            height=34).grid(row=4, column=0, sticky="ew", pady=(6, 0))
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
        opts.append((t("inst.source_browse"), {"kind": "instrument", "path": None}))
        opts.append((t("ui.settings.sin_fuente"), {"kind": "none"}))
        return opts

    def _sec_channels(self, b):
        app = self.app
        chans = app.audio_engine.config["channels"]
        self.h1(b, t("ui.settings.canales_y_efectos"), t("ui.settings.cada_canal_es_una_fuente"))
        wrap = ctk.CTkFrame(b, fg_color="transparent")
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.grid_columnconfigure(0, weight=1)
        lst = ctk.CTkFrame(wrap, fg_color=self.C["panel"], corner_radius=12)
        lst.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        lst.grid_columnconfigure(0, weight=1)
        if chans and self.sel_channel not in [c["id"] for c in chans]:
            self.sel_channel = chans[0]["id"]
        for i, ch in enumerate(chans):
            on = ch["id"] == self.sel_channel
            row = ctk.CTkButton(lst, text=f"   {ch['name']}", anchor="w", height=38, corner_radius=8, font=app.F(13),
                                fg_color=self.C["raised"] if on else "transparent", hover_color=self.C["raised"],
                                text_color=self.C["text"] if on else self.C["text2"], width=10,
                                command=lambda cid=ch["id"]: (setattr(self, "sel_channel", cid), self.refresh("channels")))
            row.grid(row=i, column=0, sticky="ew", padx=8, pady=(8 if i == 0 else 2, 2))
            ctk.CTkFrame(row, width=8, height=8, corner_radius=2, fg_color=ch.get("color") or "#888").place(x=10, rely=0.5, anchor="w")
        for k, (label, cmd) in enumerate(((t("ui.settings.nuevo_canal"), self._new_channel),
                                          (t("inst.new"), self._new_instrument))):
            ctk.CTkButton(lst, text=label, height=34, corner_radius=8, font=app.F(13, "bold"), width=10,
                          fg_color="transparent", border_width=1, border_color=self.C["line2"], hover_color=self.C["raised"],
                          text_color=self.C["text"], command=cmd).grid(row=len(chans) + k, column=0, padx=8, sticky="ew",
                                                                        pady=(10 if k == 0 else 0, 10 if k == 1 else 6))

        ch = app.audio_engine.channel(self.sel_channel) if self.sel_channel else None
        det = ctk.CTkFrame(wrap, fg_color="transparent")
        det.grid(row=1, column=0, sticky="nsew")
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
        is_inst = ch["source"].get("kind") == "instrument"
        if not is_inst:                          # un instrumento siempre sale en estéreo
            self.field(c, t("ui.settings.canales"), lambda p: app._segmented(
                p, [("mono", t("ui.settings.mono_al_centro")), ("stereo", t("ui.settings.estereo"))], ch.get("mode", "mono"),
                lambda v: self._set_param(cid, "mode", v, refresh=True), font=app.F(12, "bold")), 3)
        sw = ctk.CTkSwitch(c, text=t("ui.settings.escucharlo_en_el_monitor_audifonos"), font=app.F(13), text_color=self.C["text"],
                           progress_color=self.C["accent"], button_color=self.C["text"], fg_color=self.C["line2"],
                           command=lambda: self._set_param(cid, "monitor", bool(sw.get())))
        if ch.get("monitor"):
            sw.select()
        sw.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.note(c, t("inst.monitor_tip") if is_inst else t("ui.settings.mono_al_centro_manda_una"), 5)
        err = (app.audio_stats.get("channel_errors") or {}).get(cid)
        if err:
            self.note(c, f"⚠ {err}", 6, color=self.C["warn"])
        if app.vst_probing:
            done, total = app.vst_probe_progress
            self.note(c, t("inst.probing_n", done=done, total=total) if total else t("inst.probing"), 7)

        if is_inst:
            self._instrument_card(det, ch)

        # Efectos
        fxc = self.card(det, 2, t("ui.settings.efectos_vst3"))
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
        app._outline_button(add, t("ui.settings.agregar_efecto"),
                            lambda: app.open_plugin_browser("effect", lambda p: self._add_fx(cid, p)),
                            height=34).grid(row=0, column=0, sticky="ew")
        self.note(fxc, t("ui.settings.abre_la_ventana_del_efecto"), 51)

        acts = ctk.CTkFrame(det, fg_color="transparent")
        acts.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        app._outline_button(acts, t("ui.settings.subir"), lambda: self._move_channel(cid, -1), height=34, width=80).pack(side="left")
        app._outline_button(acts, t("ui.settings.bajar"), lambda: self._move_channel(cid, 1), height=34, width=80).pack(side="left", padx=6)
        ctk.CTkButton(acts, text=t("ui.settings.eliminar_canal"), height=34, width=120, corner_radius=9, font=app.F(13),
                      fg_color="transparent", border_width=1, border_color=self.C["rec"], hover_color="#3A1E20",
                      text_color=self.C["rec_text"], command=lambda: self._delete_channel(cid)).pack(side="right")

    def _instrument_card(self, parent, ch):
        """Instrumento VST3 del canal y de dónde recibe MIDI."""
        app = self.app
        cid, src = ch["id"], ch["source"]
        c = self.card(parent, 1, t("inst.section"))
        st = app.audio_engine.inst_status.get(cid, {})
        row = ctk.CTkFrame(c, fg_color=self.C["raised"], corner_radius=9)
        row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        row.grid_columnconfigure(0, weight=1)
        name = st.get("name") or plugin_name(src.get("path"))
        ctk.CTkLabel(row, text=f"🎹  {name}", font=app.F(13, "bold"), anchor="w",
                     text_color=self.C["warn"] if st.get("error") else self.C["text"]).grid(row=0, column=0, sticky="ew", padx=12)
        self.midi_dot = ctk.CTkLabel(row, text=t("inst.activity"), font=app.F(12, "bold"), text_color=self.C["faint"])
        self.midi_dot.grid(row=0, column=1, padx=8)
        bx = ctk.CTkFrame(row, fg_color="transparent")
        bx.grid(row=0, column=2, padx=8, pady=8)
        ctk.CTkButton(bx, text=t("inst.choose_sound"), width=70, height=28, corner_radius=7, font=app.F(12, "bold"),
                      fg_color=self.C["text"], hover_color="#FFFFFF", text_color="#141413",
                      command=lambda: app.open_fx_editor(cid, src.get("id"))).pack(side="left", padx=2)
        app._ghost_button(bx, t("inst.change"), lambda: app.open_plugin_browser(
            "instrument", lambda p: self._use_instrument(cid, p)), height=28).pack(side="left", padx=2)
        app._ghost_button(bx, t("inst.test"), lambda: app.audio_engine.test_note(cid), height=28).pack(side="left", padx=2)

        midi_devs = (app.audio_devices or {}).get("midi_in", [])
        all_l, none_l = t("inst.midi_all"), t("inst.midi_none")
        dev = src.get("midi_in", "*")
        cur = all_l if dev == "*" else (none_l if not dev else dev)
        values = [all_l] + midi_devs + [none_l]
        if cur not in values:
            values.insert(1, cur)                # teclado guardado que ahora no está conectado
        self.field(c, t("inst.midi_in"), lambda p: self.menu(
            p, values, cur, lambda v: self._set_midi(cid, "midi_in", "*" if v == all_l else (None if v == none_l else v))), 2)
        chans = [t("inst.omni")] + [t("inst.midi_ch_n", n=n) for n in range(1, 17)]
        mch = int(src.get("midi_ch", 0) or 0)
        self.field(c, t("inst.midi_ch"), lambda p: self.menu(
            p, chans, chans[mch], lambda v: self._set_midi(cid, "midi_ch", chans.index(v))), 3)
        if midi_devs:
            app._outline_button(c, t("inst.learn"), lambda: self._learn(cid), height=32,
                                state="disabled" if self.learn_cid == cid else "normal").grid(
                row=4, column=0, sticky="w", pady=(6, 0))
            if self.learn_msg_cid == cid and self.learn_msg:
                self.note(c, self.learn_msg, 5, color=self.C["accent"])
        else:
            self.note(c, t("inst.no_midi_devices"), 4, color=self.C["warn"])
        self.note(c, t("inst.note"), 6)

    def on_midi(self, ids):
        dot = getattr(self, "midi_dot", None)
        if self.section != "channels" or self.sel_channel not in ids or not self.app._alive(dot):
            return
        dot.configure(text_color=self.C["ok"])
        if getattr(self, "_midi_off", None):
            self.after_cancel(self._midi_off)
        self._midi_off = self.after(180, lambda: self.app._alive(dot) and dot.configure(text_color=self.C["faint"]))

    def _learn(self, cid):
        """«Toca una tecla para asignar»: la primera nota elige el teclado y el canal MIDI."""
        self.learn_cid, self.learn_msg_cid, self.learn_msg = cid, cid, t("inst.learning")
        self.app.audio_engine.midi_learn(True)
        if self._learn_timeout:
            self.after_cancel(self._learn_timeout)
        self._learn_timeout = self.after(15000, self._learn_expired)
        self.refresh("channels")

    def _learn_expired(self):
        self._learn_timeout = None
        if self.learn_cid is None:
            return
        self.learn_cid, self.learn_msg = None, t("inst.learn_timeout")
        self.app.audio_engine.midi_learn(False)
        self.refresh("channels")

    def on_midi_learned(self, dev, mch):
        cid = self.learn_cid
        if self._learn_timeout:
            self.after_cancel(self._learn_timeout)
            self._learn_timeout = None
        self.learn_cid = None
        ch = self.app.audio_engine.channel(cid) if cid else None
        if ch is None or ch["source"].get("kind") != "instrument":
            self.app.audio_engine.midi_learn(False)
            return
        ch["source"]["midi_in"], ch["source"]["midi_ch"] = dev, int(mch)
        self.learn_msg = t("inst.learned", dev=dev, ch=mch)
        self.app.apply_audio_config()           # abre solo ese teclado y cierra los que se abrieron para escuchar
        self.refresh("channels")

    def _set_midi(self, cid, key, value):
        ch = self.app.audio_engine.channel(cid)
        if ch is None or ch["source"].get(key) == value:
            return
        ch["source"][key] = value
        self.app.apply_audio_config()
        self.refresh("channels")

    def _new_instrument(self):
        self.app.open_add_channel("instrument")

    def _use_instrument(self, cid, path):
        """Pone `path` como instrumento del canal, conservando su teclado y canal MIDI."""
        ch = self.app.audio_engine.channel(cid)
        if ch is None:
            return
        old = ch["source"]
        if old.get("kind") == "instrument" and self._same_source(old, {"kind": "instrument", "path": path}):
            return
        src = new_instrument_source(path)
        if old.get("kind") == "instrument":
            src["midi_in"], src["midi_ch"] = old.get("midi_in", "*"), old.get("midi_ch", 0)
            if ch["name"] == plugin_name(old.get("path")):
                ch["name"] = plugin_name(path)       # el nombre seguía al plugin: que siga
        else:
            ch["monitor"] = True
        ch["source"] = src
        ch["mode"] = "stereo"
        self.app.apply_audio_config()
        self.show("channels")

    @staticmethod
    def _same_source(a: Dict, b: Dict) -> bool:
        if a.get("kind") != b.get("kind"):
            return False
        if a.get("kind") == "main":
            return list(a.get("ch", [])) == list(b.get("ch", []))
        if a.get("kind") == "instrument":
            return bool(a.get("path")) and os.path.normcase(a.get("path") or "") == os.path.normcase(b.get("path") or "")
        if a.get("kind") == "device":
            return a.get("device") == b.get("device") and bool(a.get("loopback")) == bool(b.get("loopback"))
        return True

    def _new_channel(self):
        self.app.open_add_channel("input")

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
        if src.get("kind") == "instrument":
            self.refresh("channels")                 # el menú vuelve a mostrar la fuente actual
            self.app.open_plugin_browser("instrument", lambda p: self._use_instrument(cid, p))
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
        if ch and ConfirmDialog.ask(self.app, t("channel.delete.title"), t("channel.delete.body", name=ch["name"]),
                                    [("cancel", t("action.cancel"), "ghost"),
                                     ("delete", t("channel.delete.confirm"), "danger")], self.app.F) == "delete":
            self.app.remove_channel(cid)
            self.sel_channel = None
            self.refresh("channels")

    def _fx_list(self, cid) -> List[Dict]:
        ch = self.app.audio_engine.channel(cid)
        return [dict(f) for f in ch.get("fx", [])] if ch else []

    def _add_fx(self, cid, path):
        fx = self._fx_list(cid) + [{"id": new_id("fx"), "path": path, "enabled": True}]
        self.app.set_channel_fx(cid, fx)
        self.show("channels", cid)

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

    # ================================================================= PLUGINS
    def _sec_plugins(self, b):
        app = self.app
        self.h1(b, t("adv.audio.plugins"))
        c2 = self.card(b, 3, t("ui.settings.carpetas_de_plugins_vst3"))
        dirs = app.settings.setdefault("vst_dirs", [])
        from audio_engine import VST3_DIRS
        for i, d in enumerate([x for x in VST3_DIRS if x] + dirs):
            row = ctk.CTkFrame(c2, fg_color="transparent")
            row.grid(row=1 + i, column=0, sticky="ew", pady=2)
            row.grid_columnconfigure(0, weight=1)
            shown = d if len(d) <= 34 else "…" + d[-33:]
            ctk.CTkLabel(row, text=f"  {shown}", font=app.F(11, mono=True), text_color=self.C["text2"], fg_color=self.C["raised"],
                         corner_radius=7, height=30, anchor="w").grid(row=0, column=0, sticky="ew")
            if d in dirs:
                app._ghost_button(row, t("ui.settings.quitar"), lambda x=d: self._remove_vst_dir(x), height=30).grid(row=0, column=1, padx=(6, 0))
        app._outline_button(c2, t("ui.settings.agregar_carpeta"), self._add_vst_dir,
                            height=34).grid(row=40, column=0, sticky="ew", pady=(10, 0))
        app._outline_button(c2, t("ui.settings.buscar_plugins_de_nuevo"),
                            lambda: app.refresh_audio_devices(lambda: self.refresh("plugins")),
                            height=34).grid(row=41, column=0, sticky="ew", pady=(6, 0))
        self.note(c2, t("settings.vst_found", n=len(app.vst_list)), 42)

        c3 = self.card(b, 4, t("ui.settings.motor_de_audio"))
        self.note(c3, t("ui.settings.el_audio_y_los_efectos"), 1, pady=(0, 10))
        app._outline_button(c3, t("ui.settings.reiniciar_motor_de_audio"), self._restart_engine,
                            height=34).grid(row=2, column=0, sticky="ew")

    def _add_vst_dir(self):
        d = filedialog.askdirectory(parent=self, title=t("ui.settings.carpeta_con_plugins_vst3"))
        if d:
            dirs = self.app.settings.setdefault("vst_dirs", [])
            if d not in dirs:
                dirs.append(os.path.normpath(d))
                self.app._save_settings()
            self.app.refresh_audio_devices(lambda: self.refresh("plugins"))

    def _remove_vst_dir(self, d):
        dirs = self.app.settings.setdefault("vst_dirs", [])
        if d in dirs:
            dirs.remove(d)
            self.app._save_settings()
        self.app.refresh_audio_devices(lambda: self.refresh("plugins"))

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
