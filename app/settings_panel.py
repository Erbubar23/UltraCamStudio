"""
UltraCam Studio - Panel de ajustes («Avanzado» de cada módulo).

Antes era la ventana de Configuración. Ahora se monta dentro del cajón del módulo y muestra
solo las secciones de ese módulo; cada sección vive en la carpeta de su módulo
(modules/<m>/ui/settings.py) y aquí se combinan. Conserva la interfaz de la ventana
(show, refresh, on_stats, on_fx_loaded, on_midi…), así quien la usaba no cambia.
"""

from typing import Dict, List, Optional, Tuple

import customtkinter as ctk

from presentation.strings import t
from presentation.theme import C
from modules.general.ui.settings import GeneralSettings
from modules.cameras.ui.settings import CamerasSettings
from modules.recording.ui.settings import RecordingSettings
from modules.audio.ui.settings import AudioSettings
from modules.streaming.ui.settings import StreamingSettings

NONE = t("ui.settings.ninguno")
WRAP = 330                     # ancho del texto dentro del cajón

# Secciones de «Avanzado» de cada módulo, en orden
MODULE_SECTIONS: Dict[str, List[Tuple[str, str]]] = {
    "cameras": [("video", t("adv.cameras.video")), ("vcam", t("adv.cameras.vcam"))],
    "audio": [("channels", t("adv.audio.channels")), ("audio", t("adv.audio.device")),
              ("plugins", t("adv.audio.plugins"))],
    "recording": [("recording", t("adv.recording.file"))],
    "general": [("general", t("adv.general.data")), ("diagnostics", t("adv.general.diagnostics"))],
    "streaming": [("live", t("adv.streaming.live"))],
}
SECTION_MODULE = {sec: mod for mod, secs in MODULE_SECTIONS.items() for sec, _ in secs}
SECTION_MODULE["advanced"] = "audio"           # nombre de la versión anterior
SECTION_ALIAS = {"advanced": "plugins"}


class SettingsPanel(GeneralSettings, CamerasSettings, RecordingSettings, AudioSettings, StreamingSettings,
                    ctk.CTkFrame):
    def __init__(self, parent, app, module: str):
        self.C = C
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.module = module
        self.sections = MODULE_SECTIONS[module]
        self.section = self.sections[0][0]
        self.sel_channel: Optional[str] = None
        # «Toca una tecla para asignar»: canal que espera la nota y el aviso que se muestra
        self.learn_cid: Optional[str] = None
        self.learn_msg_cid: Optional[str] = None
        self.learn_msg = ""
        self._learn_timeout = None
        self.wrap = WRAP
        self.stat_labels: Dict[str, ctk.CTkLabel] = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.nav = None
        if len(self.sections) > 1:
            self.nav = app._segmented(self, self.sections, self.section, lambda k: self.show(k),
                                      height=28, font=app.F(12, "bold"))
            self.nav.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=C["raised"])
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ Marco
    def close(self):
        try:
            if self.learn_cid is not None:
                self.app.audio_engine.midi_learn(False)
            self.app._on_settings_closed()
        finally:
            self.destroy()

    def show(self, section: str = None, channel_id: Optional[str] = None):
        section = SECTION_ALIAS.get(section, section)
        if section and section in dict(self.sections):
            self.section = section
        if channel_id:
            self.sel_channel = channel_id
        if self.nav is not None:
            self.nav.paint(self.section)
        self._render()

    def refresh(self, section: Optional[str] = None):
        section = SECTION_ALIAS.get(section, section)
        if section is None or section == self.section:
            self._render()

    def _render(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.stat_labels = {}
        getattr(self, f"_sec_{self.section}")(self.body)
        self.body._parent_canvas.yview_moveto(0)

    # ------------------------------------------------------------ Utilidades
    def h1(self, parent, text, sub=None, row=0):
        ctk.CTkLabel(parent, text=text, font=self.app.F(17, "bold"), text_color=self.C["text"],
                     anchor="w").grid(row=row, column=0, sticky="ew", pady=(2, 2))
        if sub:
            ctk.CTkLabel(parent, text=sub, font=self.app.F(12), text_color=self.C["muted"], anchor="w",
                         wraplength=self.wrap, justify="left").grid(row=row + 1, column=0, sticky="ew", pady=(0, 12))

    def card(self, parent, row, title=None, pady=(0, 12)):
        c = ctk.CTkFrame(parent, fg_color=self.C["panel"], corner_radius=12, border_width=1, border_color=self.C["line"])
        c.grid(row=row, column=0, sticky="ew", pady=pady)
        c.grid_columnconfigure(0, weight=1)
        inner = ctk.CTkFrame(c, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=14, pady=14)
        inner.grid_columnconfigure(0, weight=1)
        if title:
            self.app._section_label(inner, title).grid(row=0, column=0, sticky="ew", pady=(0, 10))
        return inner

    def note(self, parent, text, row, color=None, pady=(4, 0), wrap=None):
        ctk.CTkLabel(parent, text=text, font=self.app.F(12), text_color=color or self.C["faint"], anchor="w",
                     wraplength=wrap or self.wrap, justify="left").grid(row=row, column=0, sticky="ew", pady=pady)

    def field(self, parent, label, widget_fn, row):
        """Fila «etiqueta: control»: la etiqueta arriba y el control debajo (el cajón es angosto)."""
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row, column=0, sticky="ew", pady=4)
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text=label, font=self.app.F(12), text_color=self.C["text2"],
                     anchor="w").grid(row=0, column=0, sticky="w")
        w = widget_fn(f)
        w.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        return w

    def menu(self, parent, values, current, command):
        m = self.app._option_menu(parent, values or [NONE], command)
        m.set(current if current in (values or []) else (values[0] if values else NONE))
        return m
