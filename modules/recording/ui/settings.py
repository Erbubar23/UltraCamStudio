"""
UltraCam Studio - Módulo Grabación › Avanzado: archivo, pistas, sincronía y guardado.

Mixin del panel de ajustes (app/settings_panel.py): usa sus utilidades (h1, card, note, field, menu,
refresh) y su estado (sel_channel, wrap…).
"""

import customtkinter as ctk
from presentation.strings import t


class RecordingSettings:
    # =============================================================== GRABACIÓN
    def _sec_recording(self, b):
        self.h1(b, t("ui.settings.grabacion"), t("ui.settings.donde_se_guardan_las_tomas"))
        holder = ctk.CTkFrame(b, fg_color="transparent")
        holder.grid(row=2, column=0, sticky="ew")
        holder.grid_columnconfigure(0, weight=1)
        self.app.build_recording_settings(holder, wrap=self.wrap)
