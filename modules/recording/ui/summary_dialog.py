"""
Diálogo de resumen tras finalizar una grabación de video y audio.
"""

import os
from typing import Dict, Any, Callable
import customtkinter as ctk
from presentation.theme import C, ICON, ghost_button, outline_button
from presentation.strings import t


class TakeSummaryDialog:
    """Ventana modal informativa con los datos técnicos de la toma guardada."""

    @staticmethod
    def show(parent: ctk.CTk, res: Dict[str, Any], multitrack: bool,
             channel_colors: Dict[str, str], font_fn: Callable[..., ctk.CTkFont],
             icon_font_fn: Callable[..., ctk.CTkFont], on_reveal: Callable[[str], None],
             on_play: Callable[[str], None]) -> ctk.CTkToplevel:
        win = ctk.CTkToplevel(parent, fg_color=C["rail"])
        win.title(t("ui.summary.toma_guardada"))
        win.geometry("540x560")
        win.resizable(False, False)
        win.transient(parent)

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=28, pady=24)

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x")

        ctk.CTkLabel(
            top, text=ICON["check"], font=icon_font_fn(20), text_color=C["ok"],
            fg_color=C["ok_bg"], corner_radius=12, width=42, height=42
        ).pack(side="left", padx=(0, 14))

        tt = ctk.CTkFrame(top, fg_color="transparent")
        tt.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(tt, text=t("ui.summary.toma_guardada"), font=font_fn(20, "bold"), text_color=C["text"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            tt, text=os.path.basename(res.get("final_path", "")),
            font=font_fn(12, mono=True), text_color=C["muted"], anchor="w"
        ).pack(anchor="w")

        stats = ctk.CTkFrame(body, fg_color="transparent")
        stats.pack(fill="x", pady=(20, 0))
        stats.grid_columnconfigure((0, 1), weight=1, uniform="s")

        stat_items = [
            (t("ui.summary.tamano"), f"{res.get('file_size_mb', 0)} MB"),
            (t("ui.summary.listo_en"), f"{res.get('render_time_s', 0)} s"),
        ]
        for i, (k, v) in enumerate(stat_items):
            cell = ctk.CTkFrame(stats, fg_color=C["panel"], corner_radius=10)
            cell.grid(row=0, column=i, sticky="ew", padx=(0, 5) if i == 0 else (5, 0))
            ctk.CTkLabel(cell, text=k, font=font_fn(12), text_color=C["muted"]).pack(anchor="w", padx=12, pady=(10, 0))
            ctk.CTkLabel(cell, text=v, font=font_fn(17, mono=True), text_color=C["text"]).pack(anchor="w", padx=12, pady=(2, 10))

        clip = res.get("clipping_detected", False)
        ctk.CTkLabel(
            body,
            text=(t("ui.summary.hubo_saturacion_en_algun_momento")
                  if clip else t("ui.summary.sin_saturacion_el_audio_nunca")),
            font=font_fn(13), text_color=C["accent_text"] if clip else C["ok_text"],
            fg_color=C["accent_bg"] if clip else C["ok_bg"], corner_radius=10, anchor="w",
            wraplength=460, justify="left", height=44
        ).pack(fill="x", pady=(16, 0))

        ctk.CTkLabel(body, text=t("ui.summary.pistas_dentro_del_mp4"), font=font_fn(11, "bold"), text_color=C["muted"]).pack(anchor="w", pady=(18, 6))

        tracks = ctk.CTkFrame(body, fg_color="transparent", border_width=1, border_color=C["line"], corner_radius=10)
        tracks.pack(fill="x")

        rows = [(t("ui.summary.mezcla_final"), C["text"])]
        if multitrack:
            rows += [(parent["name"], channel_colors.get(parent["name"], C["text2"])) for parent in res.get("tracks", [])]

        for i, (name, col) in enumerate(rows, 1):
            r = ctk.CTkFrame(tracks, fg_color="transparent", height=36)
            r.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(r, text=str(i), font=font_fn(12, mono=True), text_color=C["faint"], width=16).pack(side="left")
            ctk.CTkFrame(r, width=8, height=8, corner_radius=2, fg_color=col).pack(side="left", padx=10)
            ctk.CTkLabel(r, text=name, font=font_fn(13), text_color=C["text"]).pack(side="left")

        if res.get("stems_dir"):
            ctk.CTkLabel(
                body, text=t("summary.stems_in", folder=os.path.basename(res['stems_dir'])),
                font=font_fn(12), text_color=C["faint"], anchor="w"
            ).pack(anchor="w", pady=(8, 0))

        act = ctk.CTkFrame(body, fg_color="transparent")
        act.pack(side="bottom", fill="x")

        ghost_button(act, t("ui.summary.nueva_toma"), win.destroy, font_fn(12), height=40).pack(side="left")

        final_path = res.get("final_path", "")
        ctk.CTkButton(
            act, text=t("ui.summary.mostrar_en_la_carpeta"),
            command=lambda: (on_reveal(final_path), win.destroy()),
            height=40, corner_radius=10, fg_color=C["text"], hover_color="#FFFFFF",
            text_color="#141413", font=font_fn(14, "bold")
        ).pack(side="right")

        outline_button(
            act, t("ui.summary.reproducir"), lambda: on_play(final_path),
            font_fn(13), height=40, width=110
        ).pack(side="right", padx=10)

        return win
