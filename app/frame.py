"""
UltraCam Studio - El marco: riel de módulos, cajón y atajos.

    ┌────┬───────────┬──────────────────────────┬──────────────┐
    │riel│  cajón    │  cabecera · monitor ·    │ Audio (fijo) │
    │    │ (módulo)  │  barra de transporte     │              │
    └────┴───────────┴──────────────────────────┴──────────────┘

- El riel muestra un icono por módulo con su estado; un clic abre o cierra su cajón.
- El cajón empuja al monitor (no puede taparlo: el monitor es una ventana nativa que
  siempre queda encima). Cada módulo tiene «Básico» y, si lo tiene, «Avanzado».
- Audio vive siempre en la columna derecha; su «Avanzado» se abre en el cajón.
- ⚙ ya no abre una ventana de Configuración: muestra atajos al «Avanzado» de cada módulo.
- Los módulos opcionales (Transmisión) empiezan ocultos y se activan con ＋.

Los módulos (self.modules) los arma gui.py; aquí no se importa ninguno.
"""

from typing import Dict, Optional

import customtkinter as ctk

from app.bus import MODULES_CHANGED
from app.settings_panel import SECTION_MODULE, SettingsPanel
from presentation.strings import t
from presentation.theme import C, ICON

RAIL_W = 76
DRAWER_W = 400
LEVEL_COLOR = {"ok": C["ok"], "warn": C["warn"], "rec": C["rec"], "live": "#7C3AED"}


class FrameMixin:
    # ------------------------------------------------------------ Visibilidad
    def _modules_cfg(self) -> Dict:
        return self.settings.setdefault("modules", {"enabled": []})

    def module_visible(self, key: str) -> bool:
        m = self.modules.get(key)
        if m is None:
            return False
        return not m.spec.optional or key in self._modules_cfg().get("enabled", [])

    def toggle_module(self, key: str, on: Optional[bool] = None):
        enabled = self._modules_cfg().setdefault("enabled", [])
        on = (key not in enabled) if on is None else on
        if on and key not in enabled:
            enabled.append(key)
        elif not on and key in enabled:
            enabled.remove(key)
            if self._drawer_module == key:
                self.close_drawer()
        self._save_settings()
        self._build_rail_buttons()
        for m in self.modules.values():
            m.attach()
        self.bus.emit(MODULES_CHANGED, visible=[k for k in self.modules if self.module_visible(k)])

    # ------------------------------------------------------------------- Riel
    def _build_module_rail(self):
        r = self.module_rail
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(r, text=ICON["video"], font=self.IF(22), text_color=C["accent"]).grid(row=0, column=0, pady=(16, 10))
        self._rail_box = ctk.CTkFrame(r, fg_color="transparent")
        self._rail_box.grid(row=1, column=0, sticky="n")
        self._rail_buttons: Dict[str, Dict] = {}
        bottom = ctk.CTkFrame(r, fg_color="transparent")
        bottom.grid(row=3, column=0, pady=(0, 12))
        self.btn_gear = self._rail_item(bottom, ICON["settings"], t("mod.settings"), self._show_shortcuts)
        self.btn_gear["box"].pack()
        self._build_rail_buttons()

    def _rail_item(self, master, icon, label, command):
        box = ctk.CTkFrame(master, fg_color="transparent", corner_radius=10, width=64, height=56)
        box.pack_propagate(False)
        ic = ctk.CTkLabel(box, text=icon, font=self.IF(18), text_color=C["muted"])
        ic.pack(pady=(9, 0))
        tx = ctk.CTkLabel(box, text=label, font=self.F(10), text_color=C["muted"])
        tx.pack()
        badge = ctk.CTkLabel(box, text="", font=self.F(9, "bold"), width=14, height=14, corner_radius=7,
                             fg_color="transparent", text_color="#FFFFFF")
        item = {"box": box, "icon": ic, "text": tx, "badge": badge, "on": False}

        def enter(_e):
            if not item["on"]:
                box.configure(fg_color=C["raised"])

        def leave(_e):
            if not item["on"]:
                box.configure(fg_color="transparent")
        for w in (box, ic, tx, badge):
            w.bind("<Button-1>", lambda _e: command())
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
        return item

    def _build_rail_buttons(self):
        for w in self._rail_box.winfo_children():
            w.destroy()
        self._rail_buttons = {}
        drawer_mods = sorted((m for m in self.modules.values() if not m.spec.fixed and self.module_visible(m.spec.key)),
                             key=lambda m: m.spec.order)
        for m in drawer_mods:
            item = self._rail_item(self._rail_box, m.spec.icon, m.spec.title, lambda k=m.spec.key: self.toggle_drawer(k))
            item["box"].pack(pady=2)
            self._rail_buttons[m.spec.key] = item
        hidden = [m for m in self.modules.values() if m.spec.optional and not self.module_visible(m.spec.key)]
        if hidden:
            plus = self._rail_item(self._rail_box, ICON["add"], t("mod.more"), self._show_hidden_modules)
            plus["box"].pack(pady=(10, 2))
        self._paint_rail()

    def _paint_rail(self):
        """Resaltado del módulo abierto y el indicador de estado de cada uno (se llama seguido)."""
        for key, item in getattr(self, "_rail_buttons", {}).items():
            if not self._alive(item["box"]):
                continue
            on = key == self._drawer_module
            item["on"] = on
            item["box"].configure(fg_color=C["raised"] if on else "transparent")
            item["icon"].configure(text_color=C["text"] if on else C["muted"])
            item["text"].configure(text_color=C["text"] if on else C["muted"])
            try:
                st = self.modules[key].status()
            except Exception:
                continue
            color = LEVEL_COLOR.get(st.level)
            if color and st.badge:
                item["badge"].configure(text=st.badge if len(st.badge) <= 2 else "", fg_color=color)
                item["badge"].place(relx=1.0, x=-8, y=6, anchor="ne")
            else:
                item["badge"].place_forget()

    # ------------------------------------------------------------------ Cajón
    def _build_drawer(self):
        d = self.drawer
        d.grid_columnconfigure(0, weight=1)
        d.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(d, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=(14, 8))
        head.grid_columnconfigure(0, weight=1)
        self._drawer_title = ctk.CTkLabel(head, text="", font=self.F(16, "bold"), text_color=C["text"], anchor="w")
        self._drawer_title.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(head, text=ICON["close"], font=self.IF(12), width=30, height=28, fg_color="transparent",
                      hover_color=C["raised"], text_color=C["muted"], command=self.close_drawer).grid(row=0, column=2)
        self._drawer_mode = self._segmented(head, [("basic", t("mod.basic")), ("advanced", t("mod.advanced"))], "basic",
                                            lambda v: self.open_module(self._drawer_module, advanced=v == "advanced"),
                                            height=26, font=self.F(11, "bold"))
        self._drawer_mode.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self._drawer_body = ctk.CTkFrame(d, fg_color="transparent")
        self._drawer_body.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=(0, 12))
        self._drawer_body.grid_columnconfigure(0, weight=1)
        self._drawer_body.grid_rowconfigure(0, weight=1)
        # Lo básico de cada módulo se arma una vez y queda (sus controles siempre existen)
        self._panels: Dict[str, ctk.CTkFrame] = {}
        for key, m in self.modules.items():
            if m.spec.fixed:
                continue
            scroll = getattr(m, "scrollable", True)
            frame = (ctk.CTkScrollableFrame(self._drawer_body, fg_color="transparent", scrollbar_button_color=C["raised"])
                     if scroll else ctk.CTkFrame(self._drawer_body, fg_color="transparent"))
            frame.grid_columnconfigure(0, weight=1)
            m.build_panel(frame)
            self._panels[key] = frame
        self.drawer.grid_remove()

    def toggle_drawer(self, key: str):
        if self._drawer_module == key and not self._drawer_advanced:
            self.close_drawer()
        else:
            self.open_module(key)

    def open_module(self, key: Optional[str], advanced: bool = False, section: Optional[str] = None,
                    channel_id: Optional[str] = None):
        """Abre el cajón con un módulo (o su «Avanzado», en una sección)."""
        m = self.modules.get(key) if key else None
        if m is None:
            return
        pop = getattr(self, "_pop", None)
        if pop is not None and self._alive(pop):
            pop.destroy()                         # la ventanita de atajos ya cumplió
        if m.spec.optional and not self.module_visible(key):
            self.toggle_module(key, True)
        if m.spec.fixed:
            advanced = True                       # lo básico de Audio ya está a la vista
        prev = self._drawer_module
        if prev and prev != key:
            self.modules[prev].on_hide()
        self._unmount_settings()
        for k, f in self._panels.items():
            if k != key or advanced:
                f.grid_remove()
        self._drawer_module, self._drawer_advanced = key, advanced
        self._drawer_title.configure(text=m.spec.title)
        if m.spec.fixed or not m.has_advanced() and not self._has_settings(key):
            self._drawer_mode.grid_remove()
        else:
            self._drawer_mode.grid()
            self._drawer_mode.paint("advanced" if advanced else "basic")
        if advanced:
            self.settings_win = SettingsPanel(self._drawer_body, self, key)
            self.settings_win.grid(row=0, column=0, sticky="nsew")
            self.settings_win.show(section, channel_id)
        else:
            self._panels[key].grid(row=0, column=0, sticky="nsew")
            m.on_show()
        if not self.drawer.winfo_ismapped():
            self.drawer.grid()
            self.drawer_sep.grid()
        self._paint_rail()

    @staticmethod
    def _has_settings(key: str) -> bool:
        return key in SECTION_MODULE.values()

    def close_drawer(self):
        if self._drawer_module:
            self.modules[self._drawer_module].on_hide()
        self._unmount_settings()
        self._drawer_module, self._drawer_advanced = None, False
        self.drawer.grid_remove()
        self.drawer_sep.grid_remove()
        self._paint_rail()

    def _unmount_settings(self):
        sw = getattr(self, "settings_win", None)
        if sw is not None:
            self.settings_win = None
            try:
                sw.close()                        # suelta los controles que dejó (ver _on_settings_closed)
            except Exception:
                pass

    def open_settings(self, section: str = "general", channel_id: Optional[str] = None):
        """Compatibilidad: lo que antes abría la ventana de Configuración en una sección ahora
        abre el «Avanzado» del módulo dueño de esa sección, en el cajón."""
        key = SECTION_MODULE.get(section or "general", "general")
        self.open_module(key, advanced=True, section=section, channel_id=channel_id)

    # ------------------------------------------------------ Listo para grabar
    def ready_check(self) -> bool:
        """Antes de grabar: lo que cada módulo dice que falta. Lo que impide grabar se muestra con
        su arreglo; lo que solo conviene revisar (sin canales de audio) se pregunta una vez."""
        from presentation.dialogs.confirm_dialog import ConfirmDialog
        issues = []
        for m in sorted(self.modules.values(), key=lambda m: m.spec.order):
            if self.module_visible(m.spec.key):
                try:
                    issues += m.readiness()
                except Exception:
                    continue
        blocking = [i for i in issues if i.blocking]
        if blocking:
            first = blocking[0]
            self.notify.banner("ready", first.message, "warn",
                               actions=[(first.action_label, first.action)] if first.action else ())
            return False
        for issue in issues:
            ans = ConfirmDialog.ask(self, t("ready.title"), issue.message,
                                    [("fix", issue.action_label, "ghost"), ("go", t("ready.record_anyway"), "primary")],
                                    self.F)
            if ans != "go":
                if ans == "fix" and issue.action:
                    issue.action()
                return False
        self.notify.clear("ready")
        return True

    # ---------------------------------------------------------------- Atajos
    def _popover(self, anchor, title: str, rows):
        """Ventanita junto al riel. rows: [(texto, detalle, acción)]. Se cierra al elegir o al salir."""
        old = getattr(self, "_pop", None)
        if old is not None and self._alive(old):
            old.destroy()
        pop = ctk.CTkToplevel(self, fg_color=C["panel"])
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        self._pop = pop
        frame = ctk.CTkFrame(pop, fg_color=C["panel"], border_width=1, border_color=C["line2"], corner_radius=0)
        frame.pack(fill="both", expand=True)
        ctk.CTkLabel(frame, text=title, font=self.F(13, "bold"), text_color=C["text"], anchor="w", justify="left",
                     wraplength=300).pack(fill="x", padx=14, pady=(12, 6))
        for text, detail, action in rows:
            b = ctk.CTkButton(frame, text=text, anchor="w", height=30, corner_radius=6, font=self.F(12, "bold"),
                              fg_color="transparent", hover_color=C["raised"], text_color=C["text"],
                              command=lambda a=action: (pop.destroy(), a()))
            b.pack(fill="x", padx=8)
            if detail:
                ctk.CTkLabel(frame, text=detail, font=self.F(11), text_color=C["faint"], anchor="w",
                             wraplength=290, justify="left").pack(fill="x", padx=18, pady=(0, 4))
        ctk.CTkFrame(frame, height=8, fg_color="transparent").pack()
        pop.update_idletasks()
        x = anchor.winfo_rootx() + anchor.winfo_width() + 6
        y = max(self.winfo_rooty(), anchor.winfo_rooty() + anchor.winfo_height() - pop.winfo_reqheight())
        pop.geometry(f"+{x}+{y}")
        pop.bind("<Escape>", lambda _e: pop.destroy())

        def maybe_close(_e=None):
            # Se cierra cuando el foco se va a otra ventana (clic fuera); no al moverse por sus botones
            def check():
                if not self._alive(pop):
                    return
                w = self.focus_get()
                if w is None or not str(w).startswith(str(pop)):
                    pop.destroy()
            self.after(150, check)
        pop.bind("<FocusOut>", maybe_close)
        pop.after(50, pop.focus_force)

    def _show_shortcuts(self):
        """⚙: ya no hay ventana de Configuración; cada ajuste vive en su módulo."""
        order = sorted((m for m in self.modules.values() if self.module_visible(m.spec.key)),
                       key=lambda m: (m.spec.key != self._drawer_module, m.spec.order))
        rows = [(f"{m.spec.title} › {t('mod.advanced')}", m.spec.advanced_hint,
                 lambda k=m.spec.key: self.open_module(k, advanced=True)) for m in order]
        self._popover(self.btn_gear["box"], t("mod.settings.moved"), rows)

    def _show_hidden_modules(self):
        hidden = [m for m in self.modules.values() if m.spec.optional and not self.module_visible(m.spec.key)]
        rows = [(f"{t('mod.enable')}  {m.spec.title}", m.spec.advanced_hint,
                 lambda k=m.spec.key: (self.toggle_module(k, True), self.open_module(k))) for m in hidden]
        anchor = self._rail_box.winfo_children()[-1] if self._rail_box.winfo_children() else self.module_rail
        self._popover(anchor, t("mod.hidden.title"), rows)
