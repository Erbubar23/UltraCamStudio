"""
UltraCam Studio - Módulo General en el marco: registro y diagnóstico, módulos opcionales,
bienvenida y «acerca de». Su «Avanzado» (datos de la app, restablecer, diagnóstico) está en
modules/general/ui/settings.py.
"""

import webbrowser

import customtkinter as ctk

from app.constants import APP_NAME, DONATE_URL
from app.module import Module, ModuleSpec, Status
from presentation.strings import t
from presentation.theme import C, ICON


class GeneralModule(Module):
    scrollable = False          # el registro ya se desplaza solo

    def __init__(self, app):
        super().__init__(app, ModuleSpec("general", t("mod.general"), ICON["info"], order=90,
                                         advanced_hint=t("mod.general.hint")))
        self.modules_box = None

    def build_panel(self, parent):
        app = self.app
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        app._build_log_panel(parent)
        app.log_panel.grid(row=0, column=0, sticky="nsew")

        app._section_label(parent, t("mod.optional")).grid(row=1, column=0, sticky="ew", pady=(16, 6))
        self.modules_box = ctk.CTkFrame(parent, fg_color="transparent")
        self.modules_box.grid(row=2, column=0, sticky="ew")
        self.modules_box.grid_columnconfigure(0, weight=1)
        self.render_optional()

        about = ctk.CTkFrame(parent, fg_color="transparent")
        about.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        about.grid_columnconfigure(0, weight=1)
        from gui import APP_VERSION
        ctk.CTkLabel(about, text=f"{APP_NAME} v{APP_VERSION}", font=app.F(12), text_color=C["muted"],
                     anchor="w").grid(row=0, column=0, sticky="w")
        app._ghost_button(about, t("welcome.reopen"), app.show_welcome, height=28).grid(row=0, column=1)
        ctk.CTkButton(about, text=t("ui.main.invitame_un_cafe"), height=28, width=90, corner_radius=6,
                      fg_color=C["accent_bg"], hover_color=C["raised"], text_color=C["accent_text"], font=app.F(12),
                      command=lambda: webbrowser.open(DONATE_URL)).grid(row=0, column=2, padx=(6, 0))

    def render_optional(self):
        """Interruptor de cada módulo opcional (Transmisión…): ocultarlo quita su icono y su botón."""
        box = self.modules_box
        if box is None or not self.app._alive(box):
            return
        for w in box.winfo_children():
            w.destroy()
        optional = [m for m in self.app.modules.values() if m.spec.optional]
        if not optional:
            ctk.CTkLabel(box, text=t("mod.optional.none"), font=self.app.F(12), text_color=C["faint"],
                         anchor="w").grid(row=0, column=0, sticky="ew")
            return
        for i, m in enumerate(optional):
            sw = ctk.CTkSwitch(box, text=f"{m.spec.title} — {m.spec.advanced_hint}", font=self.app.F(12),
                               text_color=C["text"], progress_color=C["accent"], button_color=C["text"],
                               fg_color=C["line2"], command=lambda k=m.spec.key: self.app.toggle_module(k))
            if self.app.module_visible(m.spec.key):
                sw.select()
            sw.grid(row=i, column=0, sticky="w", pady=2)

    def status(self) -> Status:
        return Status("warn", "!") if getattr(self.app, "_log_has_error", False) else Status()

    def on_show(self):
        self.app._log_has_error = False
        self.render_optional()
