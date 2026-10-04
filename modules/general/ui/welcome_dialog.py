"""
Bienvenida de la primera ejecución: tres pasos para empezar, sobre todo cómo usar la
cámara «UltraCam» en otros programas. No bloquea la app y se puede volver a abrir
desde Configuración › General.
"""

from typing import Callable, Optional

import customtkinter as ctk

from presentation.strings import t
from presentation.theme import C, ICON


class WelcomeDialog:
    @staticmethod
    def show(parent: ctk.CTk, font_fn: Callable[..., ctk.CTkFont], icon_font_fn: Callable[..., ctk.CTkFont],
             vcam_name: str, folder: str, on_connect_phone: Optional[Callable[[], None]] = None,
             on_close: Optional[Callable[[], None]] = None) -> ctk.CTkToplevel:
        win = ctk.CTkToplevel(parent, fg_color=C["rail"])
        win.title(t("welcome.window_title"))
        win.geometry("640x600")
        win.minsize(560, 540)
        win.transient(parent)

        def close():
            win.destroy()
            if on_close:
                on_close()

        win.protocol("WM_DELETE_WINDOW", close)
        win.bind("<Escape>", lambda _e: close())

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=30, pady=26)
        ctk.CTkLabel(body, text=t("welcome.title"), font=font_fn(22, "bold"), text_color=C["text"],
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(body, text=t("welcome.subtitle"), font=font_fn(13), text_color=C["muted"], anchor="w",
                     justify="left", wraplength=560).pack(fill="x", pady=(4, 18))

        steps = [
            (ICON["camera"], t("welcome.step1.title"), t("welcome.step1.body")),
            (ICON["virtual"], t("welcome.step2.title", vcam=vcam_name), t("welcome.step2.body", vcam=vcam_name)),
            (ICON["video"], t("welcome.step3.title"), t("welcome.step3.body", folder=folder)),
        ]
        labels = []
        for icon, title, text in steps:
            card = ctk.CTkFrame(body, fg_color=C["panel"], corner_radius=12, border_width=1, border_color=C["line"])
            card.pack(fill="x", pady=(0, 10))
            card.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(card, text=icon, font=icon_font_fn(18), width=38, height=38, corner_radius=9,
                         fg_color=C["raised"], text_color=C["accent"]).grid(row=0, column=0, rowspan=2,
                                                                            padx=(14, 12), pady=14, sticky="n")
            ctk.CTkLabel(card, text=title, font=font_fn(14, "bold"), text_color=C["text"], anchor="w").grid(
                row=0, column=1, sticky="ew", pady=(14, 0), padx=(0, 14))
            lbl = ctk.CTkLabel(card, text=text, font=font_fn(12), text_color=C["text2"], anchor="w",
                               justify="left", wraplength=460)
            lbl.grid(row=1, column=1, sticky="ew", pady=(2, 14), padx=(0, 14))
            labels.append(lbl)

        def rewrap(_e=None):
            for lbl in labels:
                lbl.configure(wraplength=max(body.winfo_width() - 110, 300))
        body.bind("<Configure>", rewrap)

        act = ctk.CTkFrame(body, fg_color="transparent")
        act.pack(side="bottom", fill="x", pady=(8, 0))
        ctk.CTkButton(act, text=t("welcome.start"), command=close, height=40, width=130, corner_radius=10,
                      fg_color=C["text"], hover_color="#FFFFFF", text_color="#141413",
                      font=font_fn(14, "bold")).pack(side="right")
        if on_connect_phone:
            ctk.CTkButton(act, text=t("action.connect_phone"), command=lambda: (close(), on_connect_phone()),
                          height=40, corner_radius=10, fg_color="transparent", border_width=1,
                          border_color=C["line2"], hover_color=C["raised"], text_color=C["text"],
                          font=font_fn(13)).pack(side="right", padx=10)
        win.after(10, lambda: (win.lift(), win.focus_force()))
        return win
