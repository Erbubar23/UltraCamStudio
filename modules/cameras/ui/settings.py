"""
UltraCam Studio - Módulo Cámaras › Avanzado: imagen y calidad de la cámara, cámara virtual.

Mixin del panel de ajustes (app/settings_panel.py): usa sus utilidades (h1, card, note, field, menu,
refresh) y su estado (sel_channel, wrap…).
"""

import customtkinter as ctk
import virtualcam
from presentation.strings import t


class CamerasSettings:
    # ===================================================================== VIDEO
    def _sec_video(self, b):
        self.h1(b, t("ui.settings.video"), t("ui.settings.ajustes_de_la_camara_seleccionada"))
        holder = ctk.CTkFrame(b, fg_color="transparent")
        holder.grid(row=2, column=0, sticky="ew")
        holder.grid_columnconfigure(0, weight=1)
        self.app.build_video_settings(holder, wrap=self.wrap)

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
        grid.grid_columnconfigure(0, weight=1)
        cells = [
            (t("ui.settings.en_windows"), t("ui.settings.registrada") if info["registered"] else t("ui.settings.no_registrada"), info["registered"]),
            (t("ui.settings.enlace_con_la_app"), t("ui.settings.activo") if info["running"] else t("ui.settings.sin_enlace"), info["running"]),
            (t("ui.settings.imagen"), f"● {sel.name}" if sending else
             (t("ui.settings.en_pausa") if not app._vcam_on() else t("ui.settings.cartel_sin_senal")), sending or None),
        ]
        for i, (label, value, good) in enumerate(cells):
            cell = ctk.CTkFrame(grid, fg_color=self.C["raised"], corner_radius=9)
            cell.grid(row=i, column=0, sticky="ew", pady=(0 if i == 0 else 4, 0))
            ctk.CTkLabel(cell, text=label, font=app.F(11), text_color=self.C["muted"]).pack(anchor="w", padx=10, pady=(8, 0))
            color = self.C["muted"] if good is None else (self.C["ok"] if good else self.C["warn"])
            ctk.CTkLabel(cell, text=value if len(value) <= 26 else value[:25] + "…", font=app.F(15, "bold"),
                         text_color=color).pack(anchor="w", padx=10, pady=(0, 8))
        if info.get("error"):
            self.note(c, t("settings.vcam.last_error", error=info['error']), 2, color=self.C["warn"])
        app._outline_button(c, t("settings.vcam.reregister", vcam=virtualcam.DEVICE_NAME), self._reregister,
                            height=34).grid(row=3, column=0, sticky="ew", pady=(12, 0))
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
