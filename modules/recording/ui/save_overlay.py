"""
UltraCam Studio - Barra de guardado.

Mientras se une (y comprime) la toma, una capa cubre toda la ventana: se ve el avance y
nada se puede tocar, para que nada choque con el guardado. Cerrar la app a mitad pregunta
antes (ver el marco); si se cierra igual, la toma se termina de guardar al volver a abrir.
"""

from typing import Optional

import customtkinter as ctk

from presentation.strings import t
from presentation.theme import C

STEPS = ("sync", "encode", "join", "verify", "done")


def fmt_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return ""
    if seconds < 60:
        return t("save.eta_seconds", n=max(1, int(seconds)))
    return t("save.eta_minutes", n=int(round(seconds / 60)))


class SaveOverlay(ctk.CTkFrame):
    def __init__(self, app, title: str):
        super().__init__(app, fg_color=C["bg"], corner_radius=0)
        self.app = app
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lift()
        card = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=16, border_width=1, border_color=C["line"])
        card.place(relx=0.5, rely=0.45, anchor="center")
        F = app.F
        ctk.CTkLabel(card, text=title, font=F(20, "bold"), text_color=C["text"], anchor="w").grid(
            row=0, column=0, sticky="ew", padx=28, pady=(24, 4))
        self.lbl_step = ctk.CTkLabel(card, text="", font=F(13), text_color=C["text2"], anchor="w", width=460)
        self.lbl_step.grid(row=1, column=0, sticky="ew", padx=28)
        self.bar = ctk.CTkProgressBar(card, height=10, corner_radius=5, width=460, fg_color=C["line"],
                                      progress_color=C["accent"])
        self.bar.grid(row=2, column=0, sticky="ew", padx=28, pady=(14, 6))
        self.lbl_detail = ctk.CTkLabel(card, text="", font=F(12, mono=True), text_color=C["muted"], anchor="w")
        self.lbl_detail.grid(row=3, column=0, sticky="ew", padx=28)
        ctk.CTkLabel(card, text=t("save.dont_close"), font=F(12), text_color=C["faint"], anchor="w",
                     wraplength=460, justify="left").grid(row=4, column=0, sticky="ew", padx=28, pady=(10, 24))
        self._indeterminate = False
        self.encoder_label = ""
        self.update_step("sync", None)
        try:
            self.grab_set()                      # nada de la ventana responde mientras se guarda
        except Exception:
            pass

    def update_step(self, step: str, fraction: Optional[float], speed: Optional[float] = None,
                    eta: Optional[float] = None):
        if not self.winfo_exists():
            return
        text = t(f"save.step_{step}", encoder=self.encoder_label) if step in STEPS else step
        self.lbl_step.configure(text=text)
        if fraction is None:
            if not self._indeterminate:
                self.bar.configure(mode="indeterminate")
                self.bar.start()
                self._indeterminate = True
            self.lbl_detail.configure(text="")
            return
        if self._indeterminate:
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self._indeterminate = False
        self.bar.set(max(0.0, min(1.0, fraction)))
        parts = [f"{fraction * 100:.0f} %"]
        if speed:
            parts.append(f"{speed:.1f}×")
        if eta is not None:
            parts.append(fmt_eta(eta))
        self.lbl_detail.configure(text="   ·   ".join(p for p in parts if p))

    def close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        if self._indeterminate:
            self.bar.stop()
        self.destroy()
