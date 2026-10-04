"""
UltraCam Studio - Módulo Audio en el marco: la columna fija de la derecha (mezclador,
monitor y estado del audio). Siempre a la vista; su «Avanzado» (canales, dispositivo,
plugins) se abre en el cajón y está en modules/audio/ui/settings.py.
"""

from typing import List

import customtkinter as ctk

from app.module import Module, ModuleSpec, Readiness, Status
from presentation.strings import t
from presentation.theme import C, ICON


class AudioModule(Module):
    def __init__(self, app):
        super().__init__(app, ModuleSpec("audio", t("mod.audio"), ICON["mic"], order=5, fixed=True,
                                         advanced_hint=t("mod.audio.hint")))

    def build_panel(self, parent):
        app = self.app
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        mh = ctk.CTkFrame(parent, fg_color="transparent")
        mh.grid(row=0, column=0, sticky="ew", padx=(16, 10), pady=(16, 6))
        app._section_label(mh, t("ui.main.mezclador")).pack(side="left")
        app._ghost_button(mh, t("mod.advanced"), lambda: app.open_module("audio", advanced=True),
                          height=26).pack(side="right")
        app._ghost_button(mh, t("add.button"), app.open_add_channel, height=26).pack(side="right")
        app.strips_box = ctk.CTkScrollableFrame(parent, fg_color="transparent", scrollbar_button_color=C["raised"])
        app.strips_box.grid(row=1, column=0, sticky="nsew", padx=(10, 6))
        app.strips_box.grid_columnconfigure(0, weight=1)

        mon = ctk.CTkFrame(parent, fg_color=C["panel"], corner_radius=10)
        mon.grid(row=2, column=0, sticky="ew", padx=14, pady=(8, 6))
        mon.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mon, text=t("ui.main.monitor"), font=app.F(12, "bold"), text_color=C["text"]).grid(
            row=0, column=0, padx=(12, 8), pady=(8, 0), sticky="w")
        app.lbl_mon_db = ctk.CTkLabel(mon, text="", font=app.F(11, mono=True), text_color=C["muted"])
        app.lbl_mon_db.grid(row=0, column=2, padx=(0, 12), pady=(8, 0), sticky="e")
        app.meter_monitor = ctk.CTkProgressBar(mon, height=5, corner_radius=3, fg_color=C["line"], progress_color=C["ok"])
        app.meter_monitor.set(0)
        app.meter_monitor.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 2))
        app.slider_monitor = ctk.CTkSlider(mon, from_=0, to=1.5, number_of_steps=150, height=14, fg_color=C["line"],
                                           progress_color=C["text2"], button_color=C["text"],
                                           button_hover_color="#FFFFFF", command=app._on_monitor_volume)
        app.slider_monitor.grid(row=2, column=0, columnspan=3, sticky="ew", padx=8, pady=(2, 8))
        app.slider_monitor.set(float(app.audio_engine.config.get("monitor_volume", 1.0)))
        app._on_monitor_volume(app.slider_monitor.get(), save=False)

        app.lbl_audio_status = ctk.CTkButton(parent, text=t("ui.main.audio_iniciando"), font=app.F(11), height=26,
                                             anchor="w", fg_color="transparent", hover_color=C["raised"],
                                             text_color=C["muted"], command=lambda: app.open_settings("audio"))
        app.lbl_audio_status.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))

    def status(self) -> Status:
        return Status("warn", "!") if (self.app.audio_stats or {}).get("error") else Status()

    def readiness(self) -> List[Readiness]:
        if not self.app.audio_engine.config.get("channels"):
            return [Readiness(t("ready.no_audio"), t("add.button"), self.app.open_add_channel, False)]
        return []
