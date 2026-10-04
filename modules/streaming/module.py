"""
UltraCam Studio - Módulo Transmisión (opcional: oculto hasta activarlo con ＋).

En el cajón, un recuadro por plataforma agregada (con su símbolo y su estado: apagada,
conectando, en vivo, reintentando). Cada una se enciende y apaga sola con su botón; tocar el
recuadro abre sus accesos (servidor y clave) para actualizarlos. El recuadro «+» agrega otra.
Debajo, el medidor dice cuántas plataformas aguanta tu conexión a la vez.

Fuera del cajón: «◉ Live n» en la cabecera y «Transmitir» (todas) en la barra de transporte.

El codificador arranca con la primera plataforma encendida y se detiene con la última; cada
plataforma es su propia ruta en el repartidor, así que encender o apagar una no corta a las demás.
"""

import os
import sys
import threading
import time
from typing import Dict, List, Optional

import customtkinter as ctk

import virtualcam
from app.module import Module, ModuleSpec, Readiness, Status
from modules.streaming import bandwidth
from modules.streaming.accounts import Accounts
from modules.streaming.encoder import pick_encoder
from modules.streaming.planner import capacity, plan
from modules.streaming.platforms import PLATFORMS, get, ingest_url
from modules.streaming.session import LiveSession, Target
from presentation.dialogs.confirm_dialog import ConfirmDialog
from presentation.strings import t
from presentation.theme import C, ICON

LIVE = "#7C3AED"                # violeta oscuro: el texto blanco se lee bien encima
LIVE_HOVER = "#6D28D9"
STATE_COLOR = {"live": C["ok"], "connecting": C["warn"], "error": C["rec"], "off": C["text"]}
MEASURE_MAX_AGE_S = 24 * 3600


def find_mediamtx() -> Optional[str]:
    """bin/mediamtx/ junto al programa (versión empaquetada) o build/vendor/mediamtx/ (desarrollo)."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    roots = [root]
    if getattr(sys, "frozen", False):
        roots = [os.path.dirname(sys.executable), getattr(sys, "_MEIPASS", "")] + roots
    for r in roots:
        for sub in (os.path.join("bin", "mediamtx"), os.path.join("build", "vendor", "mediamtx")):
            exe = os.path.join(r, sub, "mediamtx.exe")
            if r and os.path.isfile(exe):
                return exe
    return None


def clock(seconds: float) -> str:
    e = int(seconds)
    return f"{e // 3600:02d}:{e % 3600 // 60:02d}:{e % 60:02d}"


class StreamingModule(Module):
    def __init__(self, app):
        super().__init__(app, ModuleSpec("streaming", t("mod.streaming"), ICON["live"], order=30, optional=True,
                                         advanced_hint=t("mod.streaming.hint")))
        self.session: Optional[LiveSession] = None
        self.busy = set()                         # destinos encendiéndose o apagándose
        self.opening = False
        self.chip = self.btn_transport = None
        self.tiles_box = None
        self.tiles: Dict[str, Dict] = {}
        self._measuring = False
        self._ticking = False

    # ------------------------------------------------------------------- datos
    @property
    def store(self):
        return self.app.settings.setdefault("streaming", {})

    @property
    def accounts(self) -> Accounts:
        return Accounts(self.store)

    @property
    def live(self) -> bool:
        return self.session is not None and self.session.running and bool(self.session.targets)

    def is_on(self, did: str) -> bool:
        return self.session is not None and did in self.session.targets

    def current_plan(self):
        """Calidad para todas las plataformas agregadas (cualquiera puede encenderse)."""
        items = self.accounts.items
        hs = [d for d in items if get(d["platform"]).orientation == "h"]
        vs = [d for d in items if get(d["platform"]).orientation == "v"]
        max_h = min([get(d["platform"]).max_kbps for d in hs] or [20000])
        max_v = min([get(d["platform"]).max_kbps for d in vs] or [20000])
        bw = self.store.get("bandwidth") or {}
        return plan(bw.get("budget_kbps"), len(hs), len(vs), max_h, max_v)

    # ------------------------------------------------------------------ cajón
    def build_panel(self, parent):
        app = self.app
        parent.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(parent, fg_color=C["panel"], corner_radius=12)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        self.lbl_state = ctk.CTkLabel(top, text="", font=app.F(13, "bold"), text_color=C["text"], anchor="w",
                                      justify="left", wraplength=330)
        self.lbl_state.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 2))
        self.lbl_state_sub = ctk.CTkLabel(top, text="", font=app.F(11), text_color=C["text"], anchor="w",
                                          justify="left", wraplength=330)
        self.lbl_state_sub.grid(row=1, column=0, sticky="ew", padx=14)
        self.btn_all = ctk.CTkButton(top, text="", height=36, corner_radius=9, font=app.F(13, "bold"), text_color_disabled="#FFFFFF",
                                     text_color="#FFFFFF", command=self.toggle_all)
        self.btn_all.grid(row=2, column=0, sticky="ew", padx=12, pady=(10, 12))

        app._section_label(parent, t("live.platforms")).grid(row=1, column=0, sticky="ew", pady=(16, 6))
        self.tiles_box = ctk.CTkFrame(parent, fg_color="transparent")
        self.tiles_box.grid(row=2, column=0, sticky="ew")
        self.tiles_box.grid_columnconfigure((0, 1), weight=1, uniform="tile")

        app._section_label(parent, t("live.connection")).grid(row=3, column=0, sticky="ew", pady=(18, 4))
        self.lbl_bw = ctk.CTkLabel(parent, text="", font=app.F(12), text_color=C["text2"], anchor="w", justify="left",
                                   wraplength=340)
        self.lbl_bw.grid(row=4, column=0, sticky="ew")
        self.bw_bar = ctk.CTkProgressBar(parent, height=6, corner_radius=3, fg_color=C["line"], progress_color=LIVE)
        self.btn_measure = app._outline_button(parent, t("live.measure"), self.measure, height=32)
        self.btn_measure.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        self.lbl_plan = ctk.CTkLabel(parent, text="", font=app.F(11), text_color=C["text"], anchor="w",
                                     justify="left", wraplength=340)
        self.lbl_plan.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(parent, text=t("live.source_note"), font=app.F(11), text_color=C["text"], anchor="w",
                     justify="left", wraplength=340).grid(row=8, column=0, sticky="ew", pady=(10, 0))
        self.refresh()

    def refresh(self):
        if not self.app._alive(self.tiles_box):
            return
        self.render_tiles()
        self.render_connection()
        self.render_state()

    # ---------------------------------------------------------------- recuadros
    def _badge(self, parent, platform, size=36):
        p = get(platform)
        return ctk.CTkLabel(parent, text=p.glyph, width=size, height=size, corner_radius=size // 2, fg_color=p.color,
                            text_color=p.glyph_color, font=self.app.F(int(size * 0.45), "bold"))

    def render_tiles(self):
        app, box = self.app, self.tiles_box
        for w in box.winfo_children():
            w.destroy()
        self.tiles = {}
        items = self.accounts.items
        for i, d in enumerate(items):
            tile = ctk.CTkFrame(box, fg_color=C["panel"], corner_radius=12, border_width=1, border_color=C["line"])
            tile.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 4, 0 if i % 2 else 4), pady=4)
            tile.grid_columnconfigure(0, weight=1)
            head = ctk.CTkFrame(tile, fg_color="transparent")
            head.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
            self._badge(head, d["platform"]).pack(side="left")
            power = ctk.CTkButton(head, text=ICON["power"], width=34, height=34, corner_radius=17, font=app.IF(14),
                                  border_width=1, command=lambda did=d["id"]: self.toggle_one(did))
            power.pack(side="right")
            name = ctk.CTkLabel(tile, text=d.get("name") or get(d["platform"]).name, font=app.F(12, "bold"),
                                text_color=C["text"], anchor="w", justify="left", wraplength=140)
            name.grid(row=1, column=0, sticky="ew", padx=10)
            state = ctk.CTkLabel(tile, text="", font=app.F(11), anchor="w", justify="left", wraplength=140)
            state.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
            for w in (tile, head, name, state):
                w.bind("<Button-1>", lambda _e, dd=d: self.edit_destination(dd))
                try:
                    w.configure(cursor="hand2")
                except Exception:
                    pass
            self.tiles[d["id"]] = {"tile": tile, "power": power, "state": state, "dest": d}
        n = len(items)
        add = ctk.CTkButton(box, text=f"＋\n{t('live.add_platform')}", height=96, corner_radius=12, font=app.F(12, "bold"),
                            fg_color="transparent", border_width=1, border_color=C["line2"], hover_color=C["raised"],
                            text_color=C["text"], command=self.pick_platform)
        add.grid(row=n // 2, column=n % 2, sticky="nsew", padx=(0 if n % 2 == 0 else 4, 0 if n % 2 else 4), pady=4)
        self.paint_tiles()

    def paint_tiles(self):
        for did, w in self.tiles.items():
            if not self.app._alive(w["tile"]):
                continue
            busy = did in self.busy
            st = self.session.state_of(did) if self.session is not None else {"state": "off", "elapsed": 0}
            state = "connecting" if busy and st["state"] == "off" else st["state"]
            on = self.is_on(did)
            text = {"off": t("live.tile.off"), "connecting": t("live.tile.connecting"),
                    "live": t("live.tile.live", time=clock(st.get("elapsed", 0))), "error": t("live.tile.error")}[state]
            w["state"].configure(text=text, text_color=STATE_COLOR.get(state, C["text"]))
            w["power"].configure(fg_color=C["ok"] if on else "transparent", hover_color=C["raised"],
                                 border_color=C["ok"] if on else C["line2"], text_color="#FFFFFF" if on else C["text"],
                                 state="disabled" if busy else "normal")
            w["tile"].configure(border_color=STATE_COLOR["live"] if state == "live" else
                                (C["warn"] if state in ("connecting", "error") else C["line"]))

    # --------------------------------------------------------- estado general
    def render_connection(self):
        if self._measuring:
            return
        bw = self.store.get("bandwidth")
        if not bw:
            self.lbl_bw.configure(text=t("live.bw.none"))
        else:
            cap = capacity(bw.get("budget_kbps"))
            text = t("live.bw.result", stable=f"{bw['stable']:.0f}", median=f"{bw['median']:.0f}") + "\n" + \
                t("live.bw.capacity", h=cap["1080p"], m=cap["720p"], v=cap["vertical"])
            if time.time() - bw.get("time", 0) > MEASURE_MAX_AGE_S:
                text += "\n" + t("live.bw.old")
            self.lbl_bw.configure(text=text)
        p = self.current_plan()
        lines = []
        if p.h:
            lines.append(t("live.plan.h", q=p.h.label(), n=p.n_h))
        if p.v:
            lines.append(t("live.plan.v", q=p.v.label(), n=p.n_v))
        if p.n_h or p.n_v:
            lines.append(t("live.plan.total", total=f"{p.total_kbps / 1000:.1f}".replace(".", ",")))
            if not p.fits:
                lines.append(t("live.plan.not_enough", relay=f"{p.relay_kbps / 1000:.1f}".replace(".", ",")))
        self.lbl_plan.configure(text="\n".join(lines),
                                text_color=C["warn"] if (p.n_h or p.n_v) and not p.fits else C["text"])

    def render_state(self):
        n_on = len(self.session.targets) if self.session is not None else 0
        if n_on:
            n_live = sum(1 for s in self.session.status() if s["state"] == "live")
            title = t("live.status.on", n=n_live, total=n_on, time=clock(self.session.elapsed()))
            sub, go, color = t("live.status.on_sub"), t("live.stop_all"), C["rec"]
            chip = f"◉ {t('live.chip.on', n=n_live, total=n_on)}"
        else:
            title = t("live.status.off")
            sub = t("live.status.off_sub") if self.accounts.items else t("live.no_destinations")
            go, color, chip = t("live.go_all"), LIVE, f"○ {t('live.chip.off')}"
        busy = self.opening
        if self.app._alive(getattr(self, "btn_all", None)):
            self.lbl_state.configure(text=title)
            self.lbl_state_sub.configure(text=sub)
            self.btn_all.configure(text=go, fg_color=color, hover_color=LIVE_HOVER if color == LIVE else color,
                                   state="disabled" if busy or not self.accounts.items else "normal")
        if self.app._alive(self.btn_transport):
            self.btn_transport.configure(text=t("live.stop") if n_on else t("live.go"), fg_color=color,
                                         state="disabled" if busy else "normal")
        if self.app._alive(self.chip):
            self.chip.configure(text=chip, fg_color=LIVE if n_on else C["panel"],
                                text_color="#FFFFFF" if n_on else C["text"])

    # ------------------------------------------------------- agregar / editar
    def pick_platform(self):
        """Elegir la plataforma con su símbolo; después se pegan sus accesos."""
        from modules.streaming.ui.destination_dialog import DestinationDialog
        app = self.app
        win = ctk.CTkToplevel(app, fg_color=C["rail"])
        win.title(t("live.pick.title"))
        app.update_idletasks()
        x = app.winfo_rootx() + max(0, (app.winfo_width() - 420) // 2)
        y = app.winfo_rooty() + max(0, (app.winfo_height() - 360) // 3)
        win.geometry(f"420x360+{x}+{y}")
        win.resizable(False, False)
        win.transient(app)
        win.grid_columnconfigure((0, 1), weight=1, uniform="p")
        ctk.CTkLabel(win, text=t("live.pick.heading"), font=app.F(16, "bold"), text_color=C["text"],
                     anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(16, 10))

        def choose(key):
            win.destroy()
            DestinationDialog(app, self.accounts, None, on_done=self._saved, platform=key)
        for i, p in enumerate(PLATFORMS.values()):
            b = ctk.CTkFrame(win, fg_color=C["panel"], corner_radius=10, border_width=1, border_color=C["line"])
            b.grid(row=1 + i // 2, column=i % 2, sticky="ew", padx=(18 if i % 2 == 0 else 4, 4 if i % 2 == 0 else 18),
                   pady=4)
            badge = self._badge(b, p.key, 30)
            badge.pack(side="left", padx=(10, 8), pady=8)
            lbl = ctk.CTkLabel(b, text=p.name + ("  · 9:16" if p.orientation == "v" else ""), font=app.F(12, "bold"),
                               text_color=C["text"], anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            for w in (b, badge, lbl):
                w.bind("<Button-1>", lambda _e, k=p.key: choose(k))
                w.configure(cursor="hand2")
        win.bind("<Escape>", lambda _e: win.destroy())
        win.after(60, win.lift)

    def edit_destination(self, dest):
        if dest is not None and (self.is_on(dest["id"]) or dest["id"] in self.busy):
            self.app.notify.toast(t("live.tile.edit_live"), "warn")
            return
        from modules.streaming.ui.destination_dialog import DestinationDialog
        DestinationDialog(self.app, self.accounts, dest, on_done=self._saved)

    def _saved(self):
        self.app._save_settings()
        self.refresh()

    # ----------------------------------------------------------- fuera del cajón
    def attach(self):
        app = self.app
        visible = app.module_visible(self.spec.key)
        if visible and not app._alive(self.chip):
            self.chip = ctk.CTkButton(app.header_chips, text="", height=32, width=10, corner_radius=16,
                                      font=app.F(12, "bold"), border_width=1, border_color=C["line"],
                                      hover_color=C["raised"], command=lambda: app.open_module("streaming"))
            self.chip.pack(side="left", padx=(8, 0))
            self.btn_transport = ctk.CTkButton(app.transport_actions, text="", width=150, height=54, corner_radius=12,
                                               font=app.F(14, "bold"), text_color="#FFFFFF", hover_color=LIVE_HOVER,
                                               text_color_disabled="#FFFFFF",
                                               command=self.toggle_all)
            self.btn_transport.pack(side="left", padx=(10, 0))
            self.render_state()
        elif not visible:
            if self.session is not None:
                self.stop_all(confirm=False)
            for w in (self.chip, self.btn_transport):
                if app._alive(w):
                    w.destroy()
            self.chip = self.btn_transport = None

    def status(self) -> Status:
        if self.session is not None and self.session.targets:
            st = self.session.status()
            return Status("warn", "!") if any(s["state"] == "error" for s in st) else Status("live", "●")
        return Status()

    def readiness(self) -> List[Readiness]:
        return []                     # transmitir no condiciona grabar

    def on_show(self):
        self.refresh()

    def on_app_close(self):
        if self.session is not None:
            self.session.close()

    # ---------------------------------------------------------------- medidor
    def measure(self):
        if self._measuring:
            return
        if self.session is not None and self.session.targets:
            self.app.notify.toast(t("live.bw.busy"), "warn")
            return
        self._measuring = True
        self.btn_measure.configure(state="disabled")
        self.lbl_bw.configure(text=t("live.bw.measuring"))
        self.bw_bar.set(0)
        self.bw_bar.grid(row=5, column=0, sticky="ew", pady=(6, 0))

        def work():
            try:
                res = bandwidth.measure(progress=lambda f: self.app._ui(self.bw_bar.set, f))
            except Exception as e:
                res = {"error": str(e)}
            self.app._ui(done, res)

        def done(res):
            self._measuring = False
            self.btn_measure.configure(state="normal")
            self.bw_bar.grid_remove()
            if res.get("error") or not res.get("median"):
                self.lbl_bw.configure(text=t("live.bw.failed"))
                return
            self.store["bandwidth"] = {k: res[k] for k in ("median", "stable", "budget_kbps", "time", "latency_ms")}
            self.app._save_settings()
            self.app._on_engine_log(f"Medición de subida: mediana {res['median']} Mbps, estable {res['stable']} Mbps "
                                    f"({res['samples']})", "LIVE")
            self.render_connection()
        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- en vivo
    def toggle_all(self):
        if self.session is not None and self.session.targets:
            self.stop_all()
        else:
            self.start_all()

    def toggle_one(self, did):
        if did in self.busy:
            return
        if self.is_on(did):
            self.stop_one(did)
        else:
            d = self.accounts.get(did)
            if d:
                self.start([d])

    def start_all(self):
        items = self.accounts.items
        if not items:
            self.app.open_module("streaming")
            self.pick_platform()
            return
        self.start([d for d in items if not self.is_on(d["id"])])

    def _prepare(self, dests) -> Optional[List[tuple]]:
        """Comprobaciones antes de encender: cámara virtual, claves de un solo uso y accesos completos.
        Devuelve [(Target, clave)] o None si se canceló o falta algo."""
        app, acc = self.app, self.accounts
        if not app._vcam_on():
            ans = ConfirmDialog.ask(app, t("live.vcam.title"), t("live.vcam.body"),
                                    [("cancel", t("action.cancel"), "ghost"), ("on", t("live.vcam.on"), "primary")], app.F)
            if ans != "on":
                return None
            app._toggle_vcam()
        out = []
        for d in dests:
            if get(d["platform"]).key_per_session:            # TikTok / Instagram: clave nueva en cada directo
                dlg = ctk.CTkInputDialog(text=t("live.session_key", name=d.get("name")), title=get(d["platform"]).name)
                key = (dlg.get_input() or "").strip()
                if not key:
                    return None
                acc.save(d["platform"], d.get("name", ""), d.get("server", ""), key, did=d["id"])
            key = acc.key_of(d["id"])
            url = ingest_url(d.get("server", ""), key)
            if not url:
                app.notify.banner("live", t("live.bad_destination", name=d.get("name")), "warn",
                                  actions=[(t("live.dest.edit_short"), lambda dd=d: self.edit_destination(dd))])
                return None
            out.append((Target(d["id"], d.get("name", ""), url, get(d["platform"]).orientation == "v"), key))
        app._save_settings()
        return out

    def start(self, dests):
        """Enciende estas plataformas. Si el codificador no está en marcha, arranca primero."""
        app = self.app
        if not dests or self.opening:
            return
        prepared = self._prepare(dests)
        if not prepared:
            return
        need_v = any(tg.vertical for tg, _ in prepared)
        need_h = any(not tg.vertical for tg, _ in prepared)
        sess = self.session
        if sess is not None and sess.running and ((need_v and "vertical" not in sess.outputs) or
                                                   (need_h and "horizontal" not in sess.outputs)):
            # El codificador no produce esa orientación (se agregó la plataforma en vivo): hay que
            # reabrirlo, con un corte de unos segundos para las que ya están al aire.
            ans = ConfirmDialog.ask(app, t("live.restart.title"), t("live.restart.body"),
                                    [("cancel", t("action.cancel"), "ghost"), ("go", t("live.restart.go"), "primary")],
                                    app.F)
            if ans != "go":
                return
            prepared = [(sess.targets[did], self.accounts.key_of(did)) for did in list(sess.targets)] + prepared
            sess.close()
            self.session = sess = None
        p = self.current_plan()
        if not p.fits and (sess is None or not sess.targets):
            ans = ConfirmDialog.ask(app, t("live.slow.title"),
                                    t("live.slow.body", need=f"{p.total_kbps / 1000:.1f}".replace(".", ",")),
                                    [("cancel", t("action.cancel"), "ghost"), ("go", t("live.slow.anyway"), "primary")],
                                    app.F)
            if ans != "go":
                return
        open_needed = sess is None or not sess.running
        if open_needed:
            exe = find_mediamtx()
            if not exe or not app.engine.ffmpeg_path:
                app.notify.banner("live", t("live.missing_tools"), "error")
                return
            self.session = sess = LiveSession(app.engine.ffmpeg_path, exe, log=app._on_engine_log,
                                              on_end=lambda why: app._ui(self._on_end, why))
            self.opening = True
        for tg, _ in prepared:
            self.busy.add(tg.did)
        items = self.accounts.items
        horizontal = any(get(d["platform"]).orientation == "h" for d in items)
        vertical = any(get(d["platform"]).orientation == "v" for d in items)
        encoder = pick_encoder(app._export_encoders() or [])
        delay = int(self.store.get("audio_delay_ms", 0))
        sr = int(app.audio_engine.config.get("sample_rate", 48000))
        self.paint_tiles()
        self.render_state()

        def work():
            ok = True
            if open_needed:
                ok = sess.open(p, encoder, virtualcam.DEVICE_NAME, sr, horizontal, vertical,
                               lambda pipe: app.audio_engine.start_feed(pipe), app.audio_engine.stop_feed,
                               audio_delay_ms=delay)
            added = [tg.name for tg, key in prepared if ok and sess.add(tg, key)]
            app._ui(done, ok, added)

        def done(ok, added):
            self.opening = False
            self.busy.difference_update(tg.did for tg, _ in prepared)
            if not ok:
                self.session = None
                app.notify.banner("live", t("live.failed"), "error", actions=[(t("action.details"), app._open_log)])
            elif added:
                app.notify.toast(t("live.started", n=len(added)))
                self._start_tick()
            if self.session is not None and not self.session.targets:
                self.session.close()
                self.session = None
            self.refresh()
            app._paint_rail()
        threading.Thread(target=work, daemon=True).start()

    def stop_one(self, did):
        sess = self.session
        if sess is None:
            return
        self.busy.add(did)
        self.paint_tiles()

        def work():
            sess.remove(did)
            last = not sess.targets
            if last:
                sess.close()                       # la última: se apaga también el codificador
            self.app._ui(done, last)

        def done(last):
            self.busy.discard(did)
            if last and self.session is sess:
                self.session = None
                self.app.notify.toast(t("live.stopped"))
            self.refresh()
            self.app._paint_rail()
        threading.Thread(target=work, daemon=True).start()

    def stop_all(self, confirm=True):
        if confirm:
            ans = ConfirmDialog.ask(self.app, t("live.stop.title"), t("live.stop.body"),
                                    [("cancel", t("action.cancel"), "ghost"), ("stop", t("live.stop_all"), "danger")],
                                    self.app.F)
            if ans != "stop":
                return
        s = self.session
        self.session = None
        if s is not None:
            threading.Thread(target=s.close, daemon=True).start()
        self.app.notify.toast(t("live.stopped"))
        self.refresh()
        self.app._paint_rail()

    def _start_tick(self):
        if not self._ticking:
            self._ticking = True
            self._tick()

    def _tick(self):
        if self.session is None or not self.session.targets:
            self._ticking = False
            self.render_state()
            return
        self.render_state()
        self.paint_tiles()
        self.app.after(1000, self._tick)

    def _on_end(self, why):
        self.session = None
        self.busy.clear()
        self.app.notify.banner("live", t("live.dropped"), "error", actions=[(t("live.go"), self.start_all)])
        self.refresh()
