"""
Sistema de temas, estilos, iconos y constructores de widgets para la UI.
"""

from typing import Dict, List, Tuple, Any, Callable, Optional
import customtkinter as ctk
from presentation.strings import t

# =============================================================================
# PALETA DE COLORES
# =============================================================================
C: Dict[str, str] = {
    "bg": "#111113",
    "rail": "#17171A",
    "panel": "#1D1D21",
    "raised": "#26262B",
    "line": "#2A2A2F",
    "line2": "#3A3A40",
    "black": "#0A0A0B",
    "footer": "#0E0E10",
    "text": "#ECEAE4",
    "text2": "#CFCCC4",
    "muted": "#A09D95",
    "faint": "#8A877F",
    "off": "#5E5C57",
    "accent": "#E9B24A",
    "accent_bg": "#2B2419",
    "accent_text": "#F3D9A8",
    "rec": "#E5484D",
    "rec_hover": "#C93A3F",
    "rec_text": "#FF7A7D",
    "ok": "#46C386",
    "ok_bg": "#16271E",
    "ok_line": "#24503A",
    "ok_text": "#BFEBD2",
    "warn": "#F2A65A",
    "ch_sys": "#6EA8FE",
    "ch_in1": "#B48CF2",
    "ch_in2": "#EC7FB6",
}

ICON: Dict[str, str] = {
    "camera": "",
    "phone": "",
    "video": "",
    "hdmi": "",
    "refresh": "",
    "add": "",
    "folder": "",
    "play": "",
    "check": "",
    "warning": "",
    "close": "",
    "copy": "",
    "settings": "",
    "virtual": "",
    "record": "",
    "live": "",
    "info": "",
    "chevron": "",
    "mic": "",
    "power": "",
}

KIND_LABEL: Dict[str, str] = {
    "webcam": "WEBCAM",
    "capture": "HDMI",
    "virtual": "VIRTUAL",
    "app": "APP",
    "android": "ANDROID",
}

KIND_LONG: Dict[str, str] = {
    "webcam": t("ui.theme.webcam_usb"),
    "capture": t("ui.theme.capturadora_hdmi"),
    "virtual": t("ui.theme.camara_virtual"),
    "app": t("ui.theme.telefono_via_app_de_camara"),
    "android": t("ui.theme.movil_android"),
}

ANDROID_RES: List[str] = ["3840x2160", "2560x1440", "1920x1080", "1280x720"]

PRESETS: List[Tuple[str, str, str]] = [
    ("studio", t("ui.theme.estudio"), t("ui.theme.maxima_definicion")),
    ("fluid", t("ui.theme.fluido"), t("ui.theme.prioriza_60_fps")),
    ("music", t("ui.theme.musico"), t("ui.theme.manos_en_movimiento")),
    ("low", t("ui.theme.poca_luz"), t("ui.theme.sala_oscura")),
]

PRESET_VALUES: Dict[str, Dict[str, float]] = {
    "studio": {"brightness": 0.0, "contrast": 1.05, "saturation": 1.05, "sharpness": 1.2},
    "music": {"brightness": 0.0, "contrast": 1.0, "saturation": 1.05, "sharpness": 1.0},
    "low": {"brightness": 0.10, "contrast": 1.15, "saturation": 1.10, "sharpness": 0.6},
}

NORM_OPTIONS: List[Tuple[str, str, str]] = [
    ("ebu_r128", t("ui.theme.para_youtube_y_streaming"), t("ui.theme.14_lufs_volumen_parejo_entre")),
    ("peak", t("ui.theme.solo_evitar_picos"), t("ui.theme.techo_en_1_dbfs")),
    ("none", t("ui.theme.sin_cambios"), t("ui.theme.tal_como_sono_en_la")),
]


def fmt_res(r: str) -> str:
    """Resolución legible para el menú: «1920 × 1080»."""
    return r.replace("x", " × ")


def res_tier(r: str) -> str:
    """Nombre corto de la resolución: 4K, 2K, Full HD, HD (o «480p»). Vale en vertical."""
    try:
        w, h = (int(v) for v in str(r).lower().split("x"))
    except ValueError:
        return str(r)
    long_side, short_side = max(w, h), min(w, h)
    for key, lng, sht in (("4k", 3840, 2160), ("2k", 2560, 1440), ("fhd", 1920, 1080), ("hd", 1280, 720)):
        if long_side >= lng or short_side >= sht:
            return t(f"mode.tier.{key}")
    return t("mode.tier.other", p=short_side)


def fmt_bitrate(b: str) -> str:
    s = str(b).upper().strip()
    return s if s.endswith("M") else f"{s}M"


# =============================================================================
# FÁBRICAS DE WIDGETS
# =============================================================================
def section_label(master, text: str, font: ctk.CTkFont) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text.upper(), font=font, text_color=C["muted"], anchor="w")


def field_label(master, text: str, font: ctk.CTkFont) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text, font=font, text_color=C["text2"], anchor="w")


def ghost_button(master, text: str, command: Callable, font: ctk.CTkFont,
                 width: int = 0, icon: Optional[str] = None, **kw) -> ctk.CTkButton:
    label = f"{text}" if not icon else text
    return ctk.CTkButton(
        master, text=label, command=command, fg_color="transparent",
        hover_color=C["raised"], text_color=C["text2"], font=font,
        height=kw.pop("height", 30), width=width or 10, corner_radius=7, **kw
    )


def outline_button(master, text: str, command: Callable, font: ctk.CTkFont,
                   height: int = 36, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, command=command, fg_color="transparent",
        hover_color=C["raised"], border_width=1, border_color=C["line2"],
        text_color=C["text"], font=font, height=height, corner_radius=9, **kw
    )


def segmented_control(master, options: List[Tuple[Any, str]], current: Any,
                      on_pick: Callable[[Any], None], font: ctk.CTkFont,
                      height: int = 32) -> ctk.CTkFrame:
    """Control segmentado personalizado que permite desactivar opciones individuales."""
    wrap = ctk.CTkFrame(master, fg_color=C["raised"], corner_radius=9)
    buttons = {}
    for i, (value, text) in enumerate(options):
        wrap.grid_columnconfigure(i, weight=1, uniform="seg")
        b = ctk.CTkButton(
            wrap, text=text, height=height, corner_radius=7, font=font,
            command=lambda v=value: on_pick(v)
        )
        b.grid(row=0, column=i, sticky="ew", padx=3, pady=3)
        buttons[value] = b
    wrap.buttons = buttons

    def paint(selected, disabled=()):
        for v, b in buttons.items():
            on = v == selected
            dis = v in disabled
            b.configure(
                fg_color=C["line2"] if on else "transparent",
                hover_color=C["line2"],
                text_color=C["text"] if on else C["muted"],
                text_color_disabled=C["off"],
                state="disabled" if dis else "normal"
            )
    wrap.paint = paint
    paint(current)
    return wrap
