"""
UltraCam Studio - Módulo Transmisión › Avanzado: sincronía en vivo y codificador.

Mixin del panel de ajustes (app/settings_panel.py): usa sus utilidades (h1, card, note).
"""

import customtkinter as ctk

from modules.streaming.encoder import pick_encoder
from presentation.strings import t

ENCODER_LABEL = {"h264_nvenc": "GPU NVIDIA (NVENC)", "h264_qsv": "gráficos Intel (Quick Sync)",
                 "h264_amf": "GPU AMD (AMF)", "libx264": "procesador (x264)"}


class StreamingSettings:
    def _sec_live(self, b):
        app = self.app
        store = app.settings.setdefault("streaming", {})
        self.h1(b, t("adv.streaming.live"), t("live.adv.intro"))

        c = self.card(b, 2, t("live.adv.sync"))
        self.note(c, t("live.adv.sync_note"), 1, color=self.C["text"], pady=(0, 8))
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        val = ctk.CTkLabel(row, text="", font=app.F(12, mono=True), text_color=self.C["text"])
        val.grid(row=0, column=1, sticky="e")

        def on_delay(v, save=True):
            ms = int(round(float(v) / 10) * 10)
            val.configure(text=f"{ms} ms")
            if save:
                store["audio_delay_ms"] = ms
                app._save_settings()
        s = ctk.CTkSlider(row, from_=0, to=800, number_of_steps=80, height=16, fg_color=self.C["line"],
                          progress_color=self.C["accent"], button_color=self.C["text"], button_hover_color="#FFFFFF",
                          command=on_delay)
        s.set(int(store.get("audio_delay_ms", 0)))
        s.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        on_delay(s.get(), save=False)
        self.note(c, t("live.adv.sync_apply"), 3, color=self.C["text"])

        c2 = self.card(b, 3, t("live.adv.encoder"))
        enc = pick_encoder(app._encoders or [])
        self.note(c2, t("live.adv.encoder_note", enc=ENCODER_LABEL.get(enc, enc)), 1, color=self.C["text"], pady=(0, 0))

        c3 = self.card(b, 4, t("live.adv.how"))
        self.note(c3, t("live.adv.how_note"), 1, color=self.C["text"], pady=(0, 0))
