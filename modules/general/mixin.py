"""
UltraCam Studio - Módulo General: configuración, bienvenida, registro y diagnóstico.

Mixin de GalaxyCamApp (gui.py): sus métodos usan el estado compartido de la ventana.
"""

import customtkinter as ctk
import virtualcam
from presentation.strings import t
from modules.general.ui.welcome_dialog import WelcomeDialog
from presentation.theme import C


class GeneralMixin:
    def _build_log_panel(self, parent):
        p = ctk.CTkFrame(parent, fg_color="#141416", corner_radius=12, border_width=1, border_color=C["line2"])
        p.grid_columnconfigure(0, weight=1)
        p.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(p, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        ctk.CTkLabel(head, text=t("ui.main.registro_y_diagnostico"), font=self.F(13, "bold"), text_color=C["text"]).pack(side="left")
        self._outline_button(head, t("ui.main.copiar"), self.copy_logs_to_clipboard, height=28, width=70).pack(side="right")
        self.console = ctk.CTkTextbox(p, font=self.F(12, mono=True), fg_color="transparent", text_color=C["text2"], wrap="none")
        self.console.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.log_panel = p

    def show_welcome(self):
        """Bienvenida en tres pasos. Se marca como vista al cerrarla."""
        def done():
            self.settings["onboarded"] = True
            self._save_settings()
        WelcomeDialog.show(self, self.F, self.IF, virtualcam.DEVICE_NAME, self._short_dir(),
                           on_connect_phone=self._open_connect_dialog, on_close=done)

    # =========================================================================
    # CONFIGURACIÓN (ahora el «Avanzado» de cada módulo, en el cajón: ver app/frame.py)
    # =========================================================================
    def _on_settings_closed(self):
        self.settings_win = None
        self.dev_body = self.dev_kind_tag = self.music_tip = self.image_box = None
        self.lbl_saved_for = self.image_note = self.lbl_dir = self.lbl_sync = self.slider_sync = None
        self.preset_buttons, self.sliders, self.norm_buttons = {}, {}, {}

    @property
    def log_open(self) -> bool:
        """El registro está a la vista: el cajón General abierto en «Básico»."""
        return getattr(self, "_drawer_module", None) == "general" and not getattr(self, "_drawer_advanced", False)

    def _open_log(self):
        if not self.log_open:
            self.toggle_log()

    def toggle_log(self):
        if self.log_open:
            self.close_drawer()
            return
        self.btn_log.configure(text=t("ui.main.registro_y_diagnostico"), text_color=C["text2"])
        self.open_module("general")

    def copy_logs_to_clipboard(self):
        self.clipboard_clear()
        self.clipboard_append(self.console.get("1.0", "end-1c"))
        self.notify.toast(t("log.copied"), "info")

    def show_report_dialog(self):
        dialog = ctk.CTkInputDialog(text=t("ui.main.cuentanos_que_paso_que_hiciste"), title=t("ui.main.reportar_un_problema"))
        notes = dialog.get_input()
        if notes is None:
            return
        s = self._selected()
        cfg = self._stream_config() if s else {}
        res = self.engine.save_problem_report(notes, cfg)
        if res.get("success"):
            self.clipboard_clear()
            self.clipboard_append(res["clipboard_text"])
            self.notify.banner("report", t("report.ready", id=res["report_id"]), "success",
                               actions=[(t("action.reveal"), lambda p=res["file_path"]: self._reveal(p))])

    def _check_binaries(self):
        missing = []
        if not self.engine.ffmpeg_path:
            missing.append(t("missing.ffmpeg"))
        if not self.engine.scrcpy_path:
            missing.append(t("missing.scrcpy"))
        if missing:
            self.notify.banner("missing", t("missing.components", items=", ".join(missing)), "error",
                               dismissible=False)
