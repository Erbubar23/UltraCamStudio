"""
«+ Agregar»: crear un canal en uno o dos clics, eligiendo QUÉ es en vez de una «fuente».

  - Micrófono o entrada: cada entrada del dispositivo principal con su vúmetro en vivo
    (se ve cuál se mueve al hablar o tocar) y cuáles ya usa otro canal.
  - Instrumento virtual: recientes y favoritos a un clic, grupos por tipo (pianos,
    batería, samplers, sintetizadores) y búsqueda; el explorador completo queda a mano.
  - Sonido del PC: lo que suena en cada salida de Windows.

Crear el canal (nombre, color, mono/estéreo, monitor, MIDI) lo hace la app; aquí solo se
dibuja y se elige.
"""

from typing import Dict, List, Optional, Tuple

import customtkinter as ctk

from audio_engine import short_device
from plugin_library import instrument_group
from presentation.strings import t
from presentation.theme import C

TABS = ("input", "instrument", "pc")
GROUPS = ("piano", "drums", "sampler", "synth", "other")
MAX_ROWS = 40          # filas de instrumentos dibujadas a la vez (cada una son varios widgets)


def _db_to_level(db: float) -> float:
    return max(0.0, min(1.0, (db + 60) / 60))


def main_inputs(cfg: Dict, devices: Dict) -> Tuple[Optional[str], int]:
    """(nombre, cantidad de entradas) del dispositivo principal según el sistema de audio."""
    if cfg.get("driver") == "asio":
        name, pool = cfg.get("asio_device"), devices.get("asio", [])
    else:
        name, pool = cfg.get("input_device"), devices.get("wasapi_in", [])
    dev = next((d for d in pool if d["name"] == name), None)
    return name, (dev["in"] if dev else 0)


def input_rows(name: str, n_in: int) -> List[Tuple[List[int], str, Optional[str]]]:
    """(columnas, título, nombre del canal o None) de cada opción del dispositivo principal.
    Windows suele partir una interfaz en varios dispositivos de una entrada («IN 2 (UMC202HD)»):
    entonces la fila y el canal se llaman como el dispositivo, no «Entrada 1»."""
    if n_in == 1:
        return [([0], short_device(name), short_device(name))]
    rows = [([i], t("add.input_n", n=i + 1), None) for i in range(n_in)]
    rows += [([i, i + 1], t("add.inputs_pair", a=i + 1, b=i + 2), None) for i in range(0, n_in - 1, 2)]
    return rows


def used_inputs(channels: List[Dict]) -> Dict[int, str]:
    """{entrada: nombre del canal que la usa} para las fuentes del dispositivo principal."""
    used = {}
    for ch in channels:
        src = ch.get("source", {})
        if src.get("kind") == "main":
            for c in src.get("ch", []):
                used.setdefault(c, ch.get("name", ""))
    return used


class AddChannelDialog(ctk.CTkToplevel):
    def __init__(self, app, tab: str = "input"):
        super().__init__(app, fg_color=C["rail"])
        self.app = app
        self.F = app.F
        self.tab = tab if tab in TABS else "input"
        self.group: Optional[str] = None
        # (columnas…) del dispositivo principal, o ("dev", nombre) de otro micrófono
        self.meters: Dict[tuple, ctk.CTkProgressBar] = {}
        self._search_job = None
        self.title(t("add.title"))
        self.geometry(self._placement(600, 640))
        self.minsize(520, 480)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        self._build()
        self.show_tab(self.tab)
        app.audio_engine.meter_inputs(True)

    def _placement(self, w: int, h: int) -> str:
        """Junto al mezclador (a la derecha de la ventana principal)."""
        app = self.app
        try:
            x = app.winfo_rootx() + app.winfo_width() - w - 24
            y = app.winfo_rooty() + 70
            return f"{w}x{h}+{max(0, x)}+{max(0, y)}"
        except Exception:
            return f"{w}x{h}"

    def close(self):
        try:
            self.app.audio_engine.meter_inputs(False)
        finally:
            self.destroy()

    # ------------------------------------------------------------------ Armado
    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self, text=t("add.heading"), font=self.F(20, "bold"), text_color=C["text"],
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 10))
        self.seg = self.app._segmented(self, [(k, t(f"add.tab_{k}")) for k in TABS], self.tab, self.show_tab,
                                       height=34, font=self.F(13, "bold"))
        self.seg.grid(row=1, column=0, sticky="ew", padx=20)
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=2, column=0, sticky="nsew", padx=20, pady=(12, 16))
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

    def show_tab(self, tab: str):
        self.tab = tab
        self.seg.paint(tab)
        for w in self.body.winfo_children():
            w.destroy()
        for r in range(6):                       # cada pestaña estira una fila distinta
            self.body.grid_rowconfigure(r, weight=0)
        self.meters = {}
        {"input": self._tab_input, "instrument": self._tab_instrument, "pc": self._tab_pc}[tab]()

    def _scroll(self, row: int = 0) -> ctk.CTkScrollableFrame:
        box = ctk.CTkScrollableFrame(self.body, fg_color="transparent", scrollbar_button_color=C["raised"])
        box.grid(row=row, column=0, sticky="nsew")
        box.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(row, weight=1)
        return box

    def _note(self, parent, text, row, color=None, pady=(6, 0)):
        lbl = ctk.CTkLabel(parent, text=text, font=self.F(12), text_color=color or C["faint"], anchor="w",
                           justify="left", wraplength=520)
        lbl.grid(row=row, column=0, sticky="ew", pady=pady)
        return lbl

    def _heading(self, parent, text, row):
        self.app._section_label(parent, text).grid(row=row, column=0, sticky="ew", pady=(10, 4))

    def _row(self, parent, row: int, title: str, sub: str = "", on_add=None, meter_key=None,
             tag: Optional[str] = None):
        box = ctk.CTkFrame(parent, fg_color=C["panel"], corner_radius=10)
        box.grid(row=row, column=0, sticky="ew", pady=3)
        box.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=(12, 6), pady=(8, 0 if meter_key or sub else 8))
        ctk.CTkLabel(top, text=title, font=self.F(13, "bold"), text_color=C["text"], wraplength=380,
                     justify="left", anchor="w").pack(side="left")
        if tag:
            ctk.CTkLabel(top, text=tag, font=self.F(11), text_color=C["faint"]).pack(side="left", padx=8)
        if sub:
            ctk.CTkLabel(box, text=sub, font=self.F(11), text_color=C["muted"], anchor="w", justify="left",
                         wraplength=400).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 0 if meter_key else 8))
        if meter_key is not None:
            bar = ctk.CTkProgressBar(box, height=6, corner_radius=3, fg_color=C["line"], progress_color=C["ok"])
            bar.set(0)
            bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 10))
            self.meters[meter_key] = bar
        if on_add is not None:
            ctk.CTkButton(box, text=t("add.add"), width=86, height=30, corner_radius=8, font=self.F(12, "bold"),
                          fg_color=C["text"], hover_color="#FFFFFF", text_color="#141413",
                          command=on_add).grid(row=0, column=1, rowspan=3, padx=10, pady=8)
        return box

    # ------------------------------------------------------- Micrófono / entrada
    def _tab_input(self):
        app = self.app
        cfg = app.audio_engine.config
        devs = app.audio_devices or {}
        name, n_in = main_inputs(cfg, devs)
        used = used_inputs(cfg.get("channels", []))
        box = self._scroll()
        r = 0
        if name and n_in:
            self._heading(box, t("add.main_device", name=name), r)
            r += 1
            for cols, title, label in input_rows(name, n_in):
                busy = [used[c] for c in cols if c in used]
                self._row(box, r, title, sub=t("add.stereo") if len(cols) > 1 else "",
                          on_add=lambda c=cols, lb=label: self._add_source({"kind": "main", "ch": list(c)}, lb),
                          meter_key=tuple(cols), tag=t("add.in_use", name=busy[0]) if busy else None)
                r += 1
            rec = app.rec_state != "idle"
            self._note(box, t("add.input_tip_rec" if rec else "add.input_tip"), r,
                       color=C["warn"] if rec else C["accent"])
            r += 1
        else:
            self._note(box, t("add.no_main"), r, color=C["warn"], pady=(4, 6))
            app._outline_button(box, t("add.choose_main"), lambda: (self.close(), app.open_settings("audio")),
                                height=34).grid(row=r + 1, column=0, sticky="w")
            r += 2
        mics = [d for d in devs.get("extra", []) if not d.get("loopback") and d["name"] != name]
        if mics:
            self._heading(box, t("add.other_mics"), r)
            r += 1
            in_use = {c["source"].get("device"): c.get("name", "") for c in cfg.get("channels", [])
                      if c["source"].get("kind") == "device" and not c["source"].get("loopback")}
            for d in mics:
                dn = d["name"]
                short = short_device(dn)
                self._row(box, r, short, sub=dn if short != dn else "", meter_key=("dev", dn),
                          tag=t("add.in_use", name=in_use[dn]) if dn in in_use else None,
                          on_add=lambda dn=dn: self._add_source({"kind": "device", "device": dn, "loopback": False}))
                r += 1
        if not (name and n_in) and not mics:
            self._note(box, t("add.no_inputs"), r)

    def set_input_levels(self, dbs: List[float], devices: Dict[str, float]):
        """Niveles (dB) de cada entrada del dispositivo principal y de los otros micrófonos."""
        for key, bar in self.meters.items():
            if not self.app._alive(bar):
                continue
            if key[0] == "dev":
                lvl = _db_to_level(devices.get(key[1], -90.0))
            else:
                vals = [dbs[c] for c in key if c < len(dbs)]
                lvl = _db_to_level(max(vals)) if vals else 0.0
            bar.set(lvl)
            bar.configure(progress_color=C["accent"] if lvl > 0.92 else C["ok"])

    def _add_source(self, src: Dict, label: Optional[str] = None):
        self.close()
        self.app.add_channel_from(src, label)

    # ------------------------------------------------------- Instrumento virtual
    def _tab_instrument(self):
        app = self.app
        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        self.q =ctk.CTkEntry(top, height=34, corner_radius=8, fg_color=C["raised"], border_color=C["line2"],
                              text_color=C["text"], font=self.F(13), placeholder_text=t("add.search"))
        self.q.grid(row=0, column=0, sticky="ew")
        self.q.bind("<KeyRelease>", lambda _e: self._schedule_list())
        self.q.bind("<Return>", lambda _e: self._pick_first())
        app._ghost_button(top, t("add.browse"), self._browse, height=34).grid(row=0, column=1, padx=(8, 0))
        self.inst_status = ctk.CTkLabel(self.body, text="", font=self.F(12), text_color=C["accent"], anchor="w",
                                        justify="left", wraplength=540)
        self.inst_status.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.quick_box = ctk.CTkFrame(self.body, fg_color="transparent")
        self.quick_box.grid(row=2, column=0, sticky="ew")
        self.group_box = ctk.CTkFrame(self.body, fg_color="transparent")
        self.group_box.grid(row=3, column=0, sticky="ew", pady=(8, 4))
        self.list_box = self._scroll(row=4)
        self.reload_instruments()
        self.after(60, lambda: self.app._alive(self.q) and self.q.focus_set())

    def reload_instruments(self):
        """Vuelve a leer la biblioteca (al terminar de revisar plugins, por ejemplo)."""
        if self.tab != "instrument" or not self.app._alive(getattr(self, "list_box", None)):
            return
        self.lib = self.app.plugin_library()
        self.update_probe_status()
        self._fill_quick()
        self._fill_groups()
        self._fill_list()

    def update_probe_status(self):
        lbl = getattr(self, "inst_status", None)
        if not self.app._alive(lbl):
            return
        done, total = self.app.vst_probe_progress
        if self.app.vst_probing:
            lbl.configure(text=t("inst.probing_n", done=done, total=total) if total else t("inst.probing"))
            lbl.grid()
        else:
            lbl.grid_remove()

    def _chip(self, parent, text, cmd, on=False):
        return ctk.CTkButton(parent, text=text, height=28, corner_radius=14, font=self.F(12, "bold" if on else "normal"),
                             fg_color=C["line2"] if on else C["panel"], hover_color=C["raised"],
                             text_color=C["text"] if on else C["text2"], border_width=1,
                             border_color=C["accent"] if on else C["line"], command=cmd, width=10)

    def _fill_quick(self):
        for w in self.quick_box.winfo_children():
            w.destroy()
        r = 0
        for node, label in ((("recent",), t("add.recent")), (("fav",), t("add.favorites"))):
            items = self.lib.quick(node, "instrument")
            if not items:
                continue
            row = ctk.CTkFrame(self.quick_box, fg_color="transparent")
            row.grid(row=r, column=0, sticky="w", pady=(8, 0))
            ctk.CTkLabel(row, text=label, font=self.F(11, "bold"), text_color=C["muted"], width=84,
                         anchor="w").pack(side="left")
            for it in items:
                name = it["name"] if len(it["name"]) <= 18 else it["name"][:17] + "…"
                self._chip(row, name, lambda i=it: self._add_instrument(i)).pack(side="left", padx=(0, 6))
            r += 1

    def _fill_groups(self):
        for w in self.group_box.winfo_children():
            w.destroy()
        q = self.q.get() if self.app._alive(getattr(self, "q", None)) else ""
        all_items = self.lib.instruments(q)
        counts = {g: 0 for g in GROUPS}
        for it in all_items:
            counts[instrument_group(it)] += 1
        if self.group is not None and not counts.get(self.group):
            self.group = None
        if not all_items:
            return
        opts = [(None, t("add.group_all", n=len(all_items)))] + \
               [(g, f"{t('add.group_' + g)} {counts[g]}") for g in GROUPS if counts[g]]
        if len(opts) <= 2:
            return                                   # un solo grupo: los chips no ayudan
        for g, label in opts:
            self._chip(self.group_box, label, lambda gg=g: self._set_group(gg),
                       on=g == self.group).pack(side="left", padx=(0, 6), pady=2)

    def _set_group(self, g):
        self.group = g
        self._fill_groups()
        self._fill_list()

    def _schedule_list(self):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(160, lambda: (self._fill_groups(), self._fill_list()))

    def _fill_list(self):
        self._search_job = None
        box = self.list_box
        for w in box.winfo_children():
            w.destroy()
        q = self.q.get() if self.app._alive(getattr(self, "q", None)) else ""
        items = self.lib.instruments(q, self.group)
        self._shown = items
        if not items:
            if q:
                self._note(box, t("add.no_match"), 0)
            elif self.app.vst_probing:
                pass                                  # el aviso de arriba ya dice que se están buscando
            else:
                self._empty_state(box)
            return
        for r, it in enumerate(items[:MAX_ROWS]):
            sub = " · ".join(x for x in [it["vendor"]] + it["cats"][:2] if x)
            self._row(box, r, f"🎹  {it['name']}", sub=sub, on_add=lambda i=it: self._add_instrument(i))
        if len(items) > MAX_ROWS:
            self._note(box, t("add.more", n=len(items) - MAX_ROWS), MAX_ROWS)
        self._note(box, t("add.inst_tip"), MAX_ROWS + 1, pady=(10, 0))

    def _empty_state(self, box):
        self._note(box, t("add.no_instruments"), 0, color=C["text2"], pady=(4, 0))
        self._note(box, t("add.no_instruments_tip"), 1)
        acts = ctk.CTkFrame(box, fg_color="transparent")
        acts.grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.app._outline_button(acts, t("add.rescan"), self._rescan, height=32).pack(side="left")
        self.app._ghost_button(acts, t("add.file"), self._browse, height=32).pack(side="left", padx=8)

    def _rescan(self):
        self.app.refresh_audio_devices(lambda: self.app._alive(self) and self.reload_instruments())

    def _pick_first(self):
        items = getattr(self, "_shown", [])
        if items:
            self._add_instrument(items[0])

    def _add_instrument(self, it: Dict):
        self.lib.touch_recent(it["path"])
        self.close()
        self.app.add_instrument_channel(it["path"], it["name"])

    def _browse(self):
        app = self.app
        self.close()
        app.open_plugin_browser("instrument", lambda p: app.add_instrument_channel(p))

    # ------------------------------------------------------------ Sonido del PC
    def _tab_pc(self):
        app = self.app
        devs = app.audio_devices or {}
        cfg = app.audio_engine.config
        outs = [d for d in devs.get("extra", []) if d.get("loopback")]
        box = self._scroll()
        if not outs:
            self._note(box, t("add.no_pc"), 0)
            return
        default_out = devs.get("default_out")
        monitor_out = cfg.get("output_device") if cfg.get("driver") != "asio" else None
        outs.sort(key=lambda d: d["name"] != default_out)      # la predeterminada primero
        for r, d in enumerate(outs):
            notes = []
            if d["name"] == default_out:
                notes.append(t("add.pc_default"))
            if monitor_out and d["name"] == monitor_out:
                notes.append(t("add.pc_monitor"))
            self._row(box, r, t("add.pc_output", name=d["name"]), sub=" · ".join(notes),
                      on_add=lambda dn=d["name"]: self._add_source({"kind": "device", "device": dn, "loopback": True}))
        self._note(box, t("add.pc_tip"), len(outs), pady=(10, 0))
