"""
Diálogo para guiar al usuario en la conexión de smartphones (Android / iOS).
"""

from typing import Callable, Optional
import customtkinter as ctk
from presentation.theme import C, ICON
from presentation.strings import t
from infrastructure.logging.app_logger import GLOBAL_LOGGER


class ConnectDialog:
    """Ventana modal informativa para conectar teléfonos móviles por USB o Wi-Fi."""

    def __init__(self, parent: ctk.CTk, on_rescan: Callable[[], None],
                 on_repair: Callable[[], None], font_fn: Callable[..., ctk.CTkFont],
                 icon_font_fn: Callable[..., ctk.CTkFont],
                 on_wifi: Optional[Callable[[], None]] = None):
        self.parent = parent
        self.on_rescan = on_rescan
        self.on_repair = on_repair
        self.F = font_fn
        self.IF = icon_font_fn
        self.on_wifi = on_wifi
        self.win: Optional[ctk.CTkToplevel] = None
        self.connect_status: Optional[ctk.CTkLabel] = None

    def show(self) -> ctk.CTkToplevel:
        if self.win is not None and self.win.winfo_exists():
            self.win.focus()
            return self.win

        win = ctk.CTkToplevel(self.parent, fg_color=C["rail"])
        win.title(t("ui.connect.conectar_un_movil"))
        win.geometry("820x700")
        win.minsize(720, 620)
        win.transient(self.parent)
        win.protocol("WM_DELETE_WINDOW", self.close)
        self.win = win

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=28, pady=22)

        ctk.CTkLabel(
            body, text=t("ui.connect.conectar_un_movil_como_camara"),
            font=self.F(22, "bold"), text_color=C["text"], anchor="w"
        ).pack(anchor="w")

        ctk.CTkLabel(
            body,
            text=t("ui.connect.sigue_los_pasos_de_tu"),
            font=self.F(14), text_color=C["muted"], anchor="w", wraplength=700, justify="left"
        ).pack(anchor="w", pady=(4, 16))

        cols = ctk.CTkFrame(body, fg_color="transparent")
        cols.pack(fill="both", expand=True)
        cols.grid_columnconfigure((0, 1), weight=1, uniform="c")
        cols.grid_rowconfigure(0, weight=1)

        guides = [
            (t("ui.connect.android_cable_usb"), [
                t("ui.connect.en_ajustes_informacion_del_telefono"),
                t("ui.connect.en_opciones_de_desarrollador_activa"),
                t("ui.connect.conecta_el_cable_y_acepta"),
            ], t("ui.connect.requiere_android_12_o_superior")),
            (t("ui.connect.iphone_o_android_sin_cable"), [
                t("ui.connect.instala_iriun_webcam_en_el"),
                t("ui.connect.instala_iriun_webcam_para_windows"),
                t("ui.connect.abre_la_app_en_el"),
            ], t("ui.connect.tambien_sirven_camo_droidcam_o")),
        ]

        for i, (title, steps, foot) in enumerate(guides):
            card = ctk.CTkFrame(cols, fg_color=C["panel"], corner_radius=12, border_width=1, border_color=C["line"])
            card.grid(row=0, column=i, sticky="nsew", padx=(0, 7) if i == 0 else (7, 0))

            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.pack(fill="x", padx=18, pady=(18, 10))

            ctk.CTkLabel(
                hdr, text=ICON["phone"], font=self.IF(18), width=36, height=36,
                corner_radius=9, fg_color=C["raised"], text_color=C["text2"]
            ).pack(side="left", padx=(0, 10))

            ctk.CTkLabel(hdr, text=title, font=self.F(15, "bold"), text_color=C["text"]).pack(side="left")

            for n, st in enumerate(steps, 1):
                ctk.CTkLabel(
                    card, text=f"{n}.  {st}", font=self.F(13), text_color=C["text2"],
                    wraplength=300, justify="left", anchor="w"
                ).pack(anchor="w", padx=18, pady=5, fill="x")

            ctk.CTkLabel(
                card, text=foot, font=self.F(12), text_color=C["faint"],
                wraplength=300, justify="left", anchor="w"
            ).pack(anchor="w", side="bottom", padx=18, pady=16, fill="x")

        if self.on_wifi:
            wf = ctk.CTkFrame(body, fg_color=C["panel"], corner_radius=12, border_width=1, border_color=C["line"])
            wf.pack(fill="x", pady=(14, 0))
            wf.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(wf, text=t("wifi.guide.title"), font=self.F(15, "bold"), text_color=C["text"],
                         anchor="w").grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 2))
            ctk.CTkLabel(wf, text=t("wifi.guide.body"), font=self.F(12), text_color=C["text2"], anchor="w",
                         justify="left", wraplength=560).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
            ctk.CTkButton(wf, text=t("wifi.button"), command=self.on_wifi, height=38, width=140, corner_radius=9,
                          fg_color="transparent", border_width=1, border_color=C["line2"], hover_color=C["raised"],
                          text_color=C["text"], font=self.F(13, "bold")).grid(row=0, column=1, rowspan=2, padx=18)

        sb = ctk.CTkFrame(body, fg_color="#141416", corner_radius=12, border_width=1, border_color=C["line"])
        sb.pack(fill="x", pady=(16, 0))

        ctk.CTkLabel(sb, text=ICON["refresh"], font=self.IF(18), text_color=C["accent"]).pack(side="left", padx=(16, 12), pady=12)

        tx = ctk.CTkFrame(sb, fg_color="transparent")
        tx.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(tx, text=t("ui.connect.buscando_telefonos"), font=self.F(14, "bold"), text_color=C["text"], anchor="w").pack(anchor="w")

        self.connect_status = ctk.CTkLabel(
            tx, text=t("ui.connect.revisamos_cada_3_segundos_esta"),
            font=self.F(12), text_color=C["muted"], anchor="w", justify="left", wraplength=620
        )
        self.connect_status.pack(anchor="w")

        act = ctk.CTkFrame(body, fg_color="transparent")
        act.pack(fill="x", pady=(14, 0))

        ctk.CTkButton(
            act, text=t("ui.connect.mi_telefono_no_aparece"), command=self._handle_repair,
            fg_color="transparent", hover_color=C["raised"], text_color=C["text2"],
            font=self.F(12), height=38, corner_radius=7
        ).pack(side="left")

        ctk.CTkButton(
            act, text=t("ui.connect.listo"), command=self.close, height=40, width=90,
            corner_radius=10, fg_color=C["text"], hover_color="#FFFFFF",
            text_color="#141413", font=self.F(14, "bold")
        ).pack(side="right")

        self.on_rescan()
        return win

    def _handle_repair(self):
        if self.connect_status:
            self.connect_status.configure(text=t("ui.connect.reiniciando_la_conexion_usb_con"))
        self.on_repair()

    def set_status(self, text: str):
        if self.connect_status and self.connect_status.winfo_exists():
            self.connect_status.configure(text=text)

    def close(self):
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception as e:
                GLOBAL_LOGGER.debug(f"Aviso al cerrar ConnectDialog: {e}")
            self.win = None
            self.connect_status = None
