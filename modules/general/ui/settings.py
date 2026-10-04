"""
UltraCam Studio - Módulo General › Avanzado: datos de la app, restablecer, diagnóstico.

Mixin del panel de ajustes (app/settings_panel.py): usa sus utilidades (h1, card, note, field, menu,
refresh) y su estado (sel_channel, wrap…).
"""

import os
import customtkinter as ctk
import paths
from presentation.dialogs.confirm_dialog import ConfirmDialog
from presentation.strings import t


class GeneralSettings:
    # =================================================================== GENERAL
    def _sec_general(self, b):
        self.h1(b, t("ui.settings.general"), t("ui.settings.donde_guarda_sus_datos_ultracam"))
        c = self.card(b, 2, t("ui.settings.datos_de_la_aplicacion"))
        portable = paths.is_portable()
        ctk.CTkLabel(c, text=(t("ui.settings.modo_portable_todo_se_guarda")) if portable else
                     (t("ui.settings.la_carpeta_del_programa_no")),
                     font=self.app.F(13), text_color=self.C["text2"], anchor="w", wraplength=self.wrap,
                     justify="left").grid(row=1, column=0, sticky="ew")
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        row.grid_columnconfigure(0, weight=1)
        shown = paths.data_dir() if len(paths.data_dir()) <= 30 else "…" + paths.data_dir()[-29:]
        ctk.CTkLabel(row, text=f"  {shown}", font=self.app.F(11, mono=True), text_color=self.C["text2"],
                     fg_color=self.C["raised"], corner_radius=8, height=34, anchor="w").grid(row=0, column=0, sticky="ew")
        self.app._outline_button(row, t("ui.settings.abrir_carpeta"), lambda: os.startfile(paths.data_dir()), height=34,
                                 width=90).grid(row=0, column=1, padx=(8, 0))

        c2 = self.card(b, 3, t("ui.settings.restablecer"))
        self.note(c2, t("ui.settings.borra_la_configuracion_canales_efectos"), 1, pady=(0, 10))
        self.app._outline_button(c2, t("ui.settings.restablecer_configuracion"), self._factory_reset,
                                 height=36).grid(row=2, column=0, sticky="ew")

    # =============================================================== DIAGNÓSTICO
    def _sec_diagnostics(self, b):
        app = self.app
        self.h1(b, t("adv.general.diagnostics"))
        c = self.card(b, 2, t("ui.settings.registro_y_diagnostico"))
        for i, (label, cmd) in enumerate([(t("ui.settings.mostrar_registro"), lambda: (app.log_open or app.toggle_log())),
                                          (t("ui.settings.copiar_registro"), app.copy_logs_to_clipboard),
                                          (t("ui.settings.reportar_un_problema"), app.show_report_dialog)]):
            app._outline_button(c, label, cmd, height=34).grid(row=1 + i, column=0, sticky="ew", pady=(0 if i == 0 else 6, 0))

    def _factory_reset(self):
        ans = ConfirmDialog.ask(self.app, t("reset.title"), t("reset.body"),
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
