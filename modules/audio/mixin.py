"""
UltraCam Studio - Módulo Audio: motor de audio, canales, instrumentos, efectos y mezclador.

Mixin de GalaxyCamApp (gui.py): sus métodos usan el estado compartido de la ventana.
"""

import json
import time
import threading
from typing import Dict, Optional
import customtkinter as ctk
from audio_engine import (DEFAULT_CONFIG, CHANNEL_COLORS, new_channel, scan_vst3, source_label,
                          default_channel_name, new_instrument_source, plugin_name)
import vst_probe
from plugin_library import PluginLibrary
from modules.audio.ui.plugin_browser import PluginBrowser
from modules.audio.ui.add_channel import AddChannelDialog
from presentation.strings import t
from presentation.theme import C
from modules.audio.levels import vol_to_db_text


class AudioMixin:
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
        self._on_engine_log(f"Audio listo: {len(devs.get('asio', []))} drivers ASIO, "
                            f"{len(devs.get('extra', []))} fuentes de Windows, {len(devs.get('midi_in', []))} "
                            f"entradas MIDI y {len(self.vst_list)} plugins VST3.", "AUDIO")
        if self.settings_win is not None:
            self.settings_win.refresh()
        self._probe_plugins()

    def refresh_audio_devices(self, then=None):
        def work():
            devs = self.audio_engine.list_devices()
            self.vst_list = scan_vst3(self.settings.get("vst_dirs", []))
            self._ui(lambda: (setattr(self, "audio_devices", devs), then() if then else None,
                              self._probe_plugins(retry_errors=True)))
        threading.Thread(target=work, daemon=True).start()

    def plugin_library(self) -> PluginLibrary:
        """Plugins encontrados + lo que se sabe de cada uno + favoritos y carpetas del usuario."""
        return PluginLibrary(self.vst_list, self.settings.get("vst_probe") or {},
                             self.settings.setdefault("plugin_library", {}))

    def open_plugin_browser(self, mode: str, on_pick):
        """Explorador de plugins (instrumentos o efectos), una sola ventana a la vez."""
        old = getattr(self, "plugin_browser", None)
        if old is not None and self._alive(old):
            old.destroy()
        self.plugin_browser = PluginBrowser(self, mode, on_pick, on_change=self._save_settings)

    def _probe_plugins(self, retry_errors=False):
        """Averigua qué plugins VST3 son instrumentos (en otro proceso; ver vst_probe).
        Solo prueba los nuevos o cambiados: el resultado queda en la configuración."""
        if self.vst_probing:
            return
        self.vst_probing = True
        plugins = self.vst_list
        cache = dict(self.settings.get("vst_probe") or {})

        def work():
            changed = False
            try:
                changed = vst_probe.classify(plugins, cache, retry_errors, log=self._on_engine_log,
                                             progress=lambda d, n: self._ui(self._on_probe_progress, d, n))
            except Exception as e:
                self._on_engine_log(f"No se pudieron revisar los plugins VST3: {e}", "WARN")
            self._ui(done, changed)

        def done(changed):
            self.vst_probing = False
            self.vst_probe_progress = (0, 0)
            if changed:
                self.settings["vst_probe"] = cache
                self._save_settings()
            if self.settings_win is not None:
                self.settings_win.refresh("channels")
            browser = getattr(self, "plugin_browser", None)
            if browser is not None and self._alive(browser):
                browser.reload()
            if self._alive(self.add_dialog):
                self.add_dialog.reload_instruments()
        threading.Thread(target=work, daemon=True).start()

    def _on_probe_progress(self, done, total):
        self.vst_probe_progress = (done, total)
        if self._alive(self.add_dialog):
            self.add_dialog.update_probe_status()

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
            self._ui(self._after_audio_applied)
        threading.Thread(target=work, daemon=True).start()

    def _after_audio_applied(self):
        """Los instrumentos recién creados tocan un acorde corto: se oye al instante que funcionan."""
        for cid in list(self._chord_pending):
            st = self.audio_engine.inst_status.get(cid)
            if st is None:
                continue                              # todavía cargando: espera a la próxima
            self._chord_pending.discard(cid)
            if not st.get("error"):
                self.audio_engine.test_chord(cid)

    # ---- Canales ----
    def add_channel(self, source: Dict, name: Optional[str] = None, monitor: bool = False) -> Dict:
        cfg = self.audio_engine.config
        n = len(cfg["channels"])
        stereo = source.get("kind") != "main" or len(source.get("ch", [])) > 1
        ch = new_channel(name or default_channel_name(source, cfg["channels"], (self.audio_devices or {}).get("default_out")),
                         source, "stereo" if stereo else "mono", monitor=monitor,
                         color=CHANNEL_COLORS[n % len(CHANNEL_COLORS)])
        cfg["channels"].append(ch)
        self.apply_audio_config()
        return ch

    def open_add_channel(self, tab: str = "input"):
        """«+ Agregar»: qué es el canal nuevo (entrada, instrumento o sonido del PC). Una sola ventana."""
        if self._alive(self.add_dialog):
            self.add_dialog.show_tab(tab)
            self.add_dialog.lift()
            self.add_dialog.focus_force()
            return
        self.add_dialog = AddChannelDialog(self, tab)

    def add_channel_from(self, source: Dict, label: Optional[str] = None) -> Dict:
        """Canal de una entrada, otro micrófono o lo que suena en una salida de Windows.
        `label`: como lo mostraba el diálogo («IN 2»), para que el canal se llame igual."""
        name = default_channel_name(source, self.audio_engine.config["channels"],
                                    (self.audio_devices or {}).get("default_out"), label=label) if label else None
        ch = self.add_channel(dict(source), name=name)
        self._after_channel_added(ch)
        return ch

    def add_instrument_channel(self, path: str, name: Optional[str] = None) -> Dict:
        """Canal de instrumento listo para tocar: monitor encendido (tocar sin escucharse no sirve
        de mucho), escucha cualquier teclado MIDI y suena un acorde en cuanto carga."""
        src = new_instrument_source(path)
        cfg = self.audio_engine.config
        ch = self.add_channel(src, name=default_channel_name(src, cfg["channels"], label=name or plugin_name(path)),
                              monitor=True)
        self._chord_pending.add(ch["id"])
        self._after_channel_added(ch)
        return ch

    def _after_channel_added(self, ch: Dict):
        self.notify.toast(t("add.added", name=ch["name"]))
        if self.settings_win is not None:
            self.settings_win.sel_channel = ch["id"]
            self.settings_win.refresh("channels")
        self.after(50, lambda: self._begin_rename(ch["id"]))

    def _on_input_levels(self, dbs, devs):
        if self._alive(self.add_dialog):
            self.add_dialog.set_input_levels(dbs, devs)

    def _on_midi_learned(self, dev, mch):
        if self.settings_win is not None:
            self.settings_win.on_midi_learned(dev, mch)

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
        inst = bool(ch) and ch["source"].get("id") == fx_id
        if is_open:
            self.notify.status(t("inst.editing" if inst else "fx.editing", name=ch["name"] if ch else cid))
        else:
            self._persist_audio()
            self.notify.toast(t("inst.saved" if inst else "fx.saved"))

    def _flash_midi(self, ids):
        """Enciende un instante el indicador MIDI de los canales que recibieron notas."""
        for cid in ids:
            strip = self.strips.get(cid)
            lbl = strip.get("midi") if strip else None
            if lbl is None or not self._alive(lbl):
                continue
            lbl.configure(text_color=C["ok"])
            if strip.get("midi_off"):
                self.after_cancel(strip["midi_off"])
            strip["midi_off"] = self.after(180, lambda w=lbl: self._alive(w) and w.configure(text_color=C["faint"]))
        if self.settings_win is not None:
            self.settings_win.on_midi(ids)

    # ---- Mezclador de la pantalla principal ----
    def render_mixer(self):
        for w in self.strips_box.winfo_children():
            w.destroy()
        self.strips = {}
        chans = self.audio_engine.config.get("channels", [])
        if not chans:
            self._empty_mixer()
        for i, ch in enumerate(chans):
            if not ch.get("color"):
                ch["color"] = CHANNEL_COLORS[i % len(CHANNEL_COLORS)]
            self.strips[ch["id"]] = self._build_strip(self.strips_box, ch, i)
        self._update_transport()

    def _empty_mixer(self):
        """Sin canales: los tres tipos a un clic, en vez de solo un texto."""
        box = ctk.CTkFrame(self.strips_box, fg_color=C["panel"], corner_radius=10)
        box.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=t("add.empty_mixer"), font=self.F(12), text_color=C["text2"], wraplength=270,
                     justify="left", anchor="w").grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        for i, tab in enumerate(("input", "instrument", "pc")):
            self._outline_button(box, t(f"add.tab_{tab}"), lambda tb=tab: self.open_add_channel(tb), height=32,
                                 anchor="w").grid(row=1 + i, column=0, sticky="ew", padx=12, pady=(0, 12 if i == 2 else 6))

    def _begin_rename(self, cid):
        """Renombrar en la tira del mezclador: Enter o salir del campo guarda, Esc deja el nombre."""
        strip = self.strips.get(cid)
        ch = self.audio_engine.channel(cid)
        if not strip or not ch or not self._alive(strip.get("name")):
            return
        lbl = strip["name"]
        entry = ctk.CTkEntry(lbl.master, width=140, height=24, corner_radius=6, fg_color=C["raised"],
                             border_color=C["accent"], text_color=C["text"], font=self.F(13, "bold"))
        entry.insert(0, ch["name"])
        entry.pack(side="left", after=lbl)
        lbl.pack_forget()
        entry.select_range(0, "end")
        entry.focus_set()
        done = {"v": False}

        def finish(save):
            if done["v"]:
                return
            done["v"] = True
            name = entry.get().strip()
            if save and name and name != ch["name"]:
                self.set_channel_param(cid, "name", name)
                if self.settings_win is not None:
                    self.settings_win.refresh("channels")
            self.render_mixer()
        entry.bind("<Return>", lambda _e: finish(True))
        entry.bind("<FocusOut>", lambda _e: finish(True))
        entry.bind("<Escape>", lambda _e: finish(False))

    def _build_strip(self, master, ch, row):
        cid = ch["id"]
        box = ctk.CTkFrame(master, fg_color=C["panel"], corner_radius=10)
        box.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        box.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        ctk.CTkFrame(top, width=8, height=8, corner_radius=2, fg_color=ch["color"]).pack(side="left", padx=(0, 8))
        name = ch["name"] if len(ch["name"]) <= 16 else ch["name"][:15] + "…"
        name_lbl = ctk.CTkLabel(top, text=name, font=self.F(13, "bold"), text_color=C["text"])
        name_lbl.pack(side="left")
        name_lbl.bind("<Double-Button-1>", lambda _e: self._begin_rename(cid))
        midi = None
        if ch["source"].get("kind") == "instrument":
            midi = ctk.CTkLabel(top, text="●", font=self.F(11, "bold"), text_color=C["faint"], width=14)
            midi.pack(side="left", padx=(6, 0))

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
        strip = {"box": box, "m": b_m, "s": b_s, "mon": b_mon, "fx": b_fx, "src": src, "meter": meter, "vol": vol, "db": db,
                 "midi": midi, "name": name_lbl}
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
