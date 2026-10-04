"""
UltraCam Studio - Módulo Cámaras en el marco.

El cajón tiene dos vistas:
  - Lista: todas las cámaras (webcams, capturadoras, teléfonos), «Conectar un móvil» y, si
    hay un iPhone enchufado por cable, la guía para usarlo.
  - Ajustes de la cámara elegida: al tocar una cámara se abren sus ajustes en tarjetas
    (Formato, Orientación, Cámara) con «← Cámaras» para volver a la lista.
Su «Avanzado» (imagen, calidad del teléfono, cámara virtual) está en modules/cameras/ui/settings.py.

Los controles conservan sus nombres en la ventana (menu_res, seg_fps, rot_box…): los métodos
del mixin (modules/cameras/mixin.py) los muestran, ocultan y actualizan igual que antes.
"""

import webbrowser
from typing import List

import customtkinter as ctk

from app.module import Module, ModuleSpec, Readiness, Status
from modules.cameras import usb_apple
from presentation.strings import t
from presentation.theme import C, ICON, KIND_LONG

DROIDCAM_URL = "https://droidcam.app"
CAMO_URL = "https://reincubate.com/camo/"
APPLE_DEVICES_URL = "ms-windows-store://search/?query=Apple%20Devices"


class AutoNote(ctk.CTkLabel):
    """Aviso que solo ocupa lugar cuando tiene texto (los métodos de la cámara lo vacían o llenan)."""

    def configure(self, require_redraw=False, **kwargs):
        super().configure(require_redraw, **kwargs)
        if "text" in kwargs and self.winfo_manager() in ("grid", "") and getattr(self, "_grid_opts", None):
            if kwargs["text"]:
                self.grid(**self._grid_opts)
            else:
                self.grid_remove()

    def place_note(self, **opts):
        self._grid_opts = opts
        self.grid(**opts)
        if not self.cget("text"):
            self.grid_remove()


class CamerasModule(Module):
    def __init__(self, app):
        super().__init__(app, ModuleSpec("cameras", t("mod.cameras"), ICON["camera"], order=10,
                                         advanced_hint=t("mod.cameras.hint")))
        self.view = "list"
        self.list_view = self.detail_view = self.iphone_box = None

    # ------------------------------------------------------------------ armado
    def _card(self, parent, row, title):
        card = ctk.CTkFrame(parent, fg_color=C["panel"], corner_radius=12, border_width=1, border_color=C["line"])
        card.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        card.grid_columnconfigure(0, weight=1)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 14))
        inner.grid_columnconfigure(0, weight=1)
        self.app._section_label(inner, title).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        return inner

    def _note(self, parent):
        return AutoNote(parent, text="", font=self.app.F(11), text_color=C["faint"], anchor="w",
                        wraplength=320, justify="left")

    def build_panel(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        self.list_view = ctk.CTkFrame(parent, fg_color="transparent")
        self.list_view.grid_columnconfigure(0, weight=1)
        self.detail_view = ctk.CTkFrame(parent, fg_color="transparent")
        self.detail_view.grid_columnconfigure(0, weight=1)
        self._build_list(self.list_view)
        self._build_detail(self.detail_view)
        self.show_list()

    def _build_list(self, v):
        app = self.app
        head = ctk.CTkFrame(v, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(head, text=t("cam.list.title"), font=app.F(13, "bold"), text_color=C["text"]).pack(side="left")
        app.btn_rescan = ctk.CTkButton(head, text=ICON["refresh"], font=app.IF(14), width=30, height=30,
                                       fg_color="transparent", hover_color=C["raised"], text_color=C["muted"],
                                       command=app._force_rescan)
        app.btn_rescan.pack(side="right")
        ctk.CTkLabel(v, text=t("cam.list.hint"), font=app.F(11), text_color=C["faint"], anchor="w", justify="left",
                     wraplength=330).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        app.sources_box = ctk.CTkFrame(v, fg_color="transparent")
        app.sources_box.grid(row=2, column=0, sticky="ew")
        app.sources_box.grid_columnconfigure(0, weight=1)
        app.source_rows = {}
        app.lbl_no_sources = ctk.CTkLabel(app.sources_box, text=t("ui.main.buscando_camaras"), font=app.F(12),
                                          text_color=C["muted"], anchor="w")
        app.lbl_no_sources.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        self.iphone_box = ctk.CTkFrame(v, fg_color="transparent")
        self.iphone_box.grid(row=3, column=0, sticky="ew")
        self.iphone_box.grid_columnconfigure(0, weight=1)
        app.btn_connect = ctk.CTkButton(v, text=f"{ICON['add']}   {t('action.connect_phone')}",
                                        font=ctk.CTkFont(family=app.ui_family, size=13), height=42, corner_radius=10,
                                        anchor="w", fg_color="transparent", border_width=1, border_color=C["line2"],
                                        hover_color=C["raised"], text_color=C["text2"], command=app._open_connect_dialog)
        app.btn_connect.grid(row=4, column=0, sticky="ew", pady=(8, 4))

    def _build_detail(self, v):
        app = self.app
        top = ctk.CTkFrame(v, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(top, text=f"‹  {t('cam.back')}", width=10, height=30, corner_radius=8, font=app.F(12, "bold"),
                      fg_color=C["raised"], hover_color=C["line2"], text_color=C["text"],
                      command=self.show_list).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))
        self.lbl_name = ctk.CTkLabel(top, text="", font=app.F(14, "bold"), text_color=C["text"], anchor="w")
        self.lbl_name.grid(row=0, column=1, sticky="ew")
        self.lbl_kind = ctk.CTkLabel(top, text="", font=app.F(11), text_color=C["muted"], anchor="w")
        self.lbl_kind.grid(row=1, column=1, sticky="ew")

        # ---- Formato: resolución, fps y objetivo
        fmt = self._card(v, 1, t("cam.card.format"))
        app.menu_res = app._option_menu(fmt, ["—"], app._on_res_change)
        app.menu_res.grid(row=1, column=0, sticky="ew")
        app.seg_fps = app._segmented(fmt, [(24, "24"), (30, "30"), (60, "60")], 30, app._on_fps_pick,
                                     font=app.F(12, "bold", mono=True), height=28)
        app.seg_fps.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        app.lbl_fps_note = self._note(fmt)
        app.lbl_fps_note.place_note(row=3, column=0, sticky="ew", pady=(4, 0))
        app.lens_menu = app._option_menu(fmt, ["—"], app._on_lens_change)       # fila 4 (solo teléfonos)

        # ---- Orientación: girar (teléfonos por cable) y horizontal / vertical
        ori = self._card(v, 2, t("cam.card.orientation"))
        app.rot_box = ctk.CTkFrame(ori, fg_color="transparent")                 # fila 6 (solo teléfonos)
        app.rot_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(app.rot_box, text=t("ui.main.girar_imagen"), font=app.F(12), text_color=C["text2"],
                     anchor="w").grid(row=0, column=0, sticky="ew")
        app.seg_rot = app._segmented(app.rot_box, [(0, t("ui.main.sin_girar")), (90, "90°"), (180, "180°"),
                                                   (270, "270°")], 0, app._on_rot_pick, font=app.F(12, "bold"), height=28)
        app.seg_rot.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        app.lbl_rot_note = self._note(app.rot_box)
        app.lbl_rot_note.place_note(row=2, column=0, sticky="ew", pady=(4, 0))
        app.fmt_box = ctk.CTkFrame(ori, fg_color="transparent")
        app.fmt_box.grid(row=7, column=0, sticky="ew", pady=(10, 0))
        app.fmt_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(app.fmt_box, text=t("format.label"), font=app.F(12), text_color=C["text2"],
                     anchor="w").grid(row=0, column=0, sticky="ew")
        app.seg_orient = app._segmented(app.fmt_box, [("h", t("format.horizontal")), ("v", t("format.vertical"))],
                                        "h", app._on_orient_pick, font=app.F(12, "bold"), height=28)
        app.seg_orient.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        app.seg_vmode = app._segmented(app.fmt_box, [("crop", t("vertical.mode.crop")), ("cw", t("vertical.mode.cw")),
                                                     ("ccw", t("vertical.mode.ccw"))],
                                       "crop", app._on_vmode_pick, font=app.F(12, "bold"), height=28)
        app.lbl_fmt_note = self._note(app.fmt_box)
        app.lbl_fmt_note.place_note(row=3, column=0, sticky="ew", pady=(4, 0))

        # ---- Cámara: soltarla para otro programa y el resto de ajustes
        cam = self._card(v, 3, t("cam.card.camera"))
        app.btn_pause_cam = app._outline_button(cam, t("pause.button"), app._toggle_camera_power, height=32)
        app.btn_pause_cam.grid(row=1, column=0, sticky="ew")
        app._ghost_button(cam, t("cam.more"), lambda: app.open_module("cameras", advanced=True),
                          height=30).grid(row=2, column=0, sticky="ew", pady=(6, 0))

    # ---------------------------------------------------------------- vistas
    def show_list(self):
        self.view = "list"
        if self.app._alive(self.detail_view):
            self.detail_view.grid_remove()
            self.list_view.grid(row=0, column=0, sticky="ew")
            self.render_iphone_card()
            self._scroll_top()

    def show_detail(self):
        s = self.app._selected()
        if s is None or not self.app._alive(self.detail_view):
            self.show_list()
            return
        self.view = "detail"
        self.lbl_name.configure(text=s.name if len(s.name) <= 30 else s.name[:29] + "…")
        self.lbl_kind.configure(text=f"{KIND_LONG[s.kind]}" + (f" · {s.meta}" if s.meta else ""))
        self.list_view.grid_remove()
        self.detail_view.grid(row=0, column=0, sticky="ew")
        self._scroll_top()

    def open_detail(self):
        """Desde la etiqueta «4K · 30 fps» de la cabecera: directo a los ajustes de la cámara."""
        self.app.open_module("cameras")
        self.show_detail()

    def _scroll_top(self):
        canvas = getattr(self.app._panels.get("cameras"), "_parent_canvas", None) if hasattr(self.app, "_panels") else None
        if canvas is not None:
            canvas.yview_moveto(0)

    def on_show(self):
        if self.view == "detail":
            self.show_detail()                   # el nombre puede haber cambiado (otra cámara)

    # ------------------------------------------------------- iPhone por cable
    def render_iphone_card(self):
        box = self.iphone_box
        if not self.app._alive(box):
            return
        for w in box.winfo_children():
            w.destroy()
        has_app_cam = any(s.kind == "app" and s.ready for s in self.app.sources)
        if not getattr(self.app, "iphone_usb", False) or has_app_cam:
            return
        app = self.app
        card = ctk.CTkFrame(box, fg_color=C["accent_bg"], corner_radius=12, border_width=1, border_color=C["accent"])
        card.grid(row=0, column=0, sticky="ew", pady=(10, 0))
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=t("cam.iphone.title"), font=app.F(13, "bold"), text_color=C["accent_text"],
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        steps = [t("cam.iphone.step1"), t("cam.iphone.step3")]
        if not usb_apple.apple_driver_installed():
            steps.insert(1, t("cam.iphone.step2"))
        for i, st in enumerate(steps, 1):
            ctk.CTkLabel(card, text=f"{i}.  {st}", font=app.F(12), text_color=C["text2"], anchor="w", justify="left",
                         wraplength=310).grid(row=i, column=0, sticky="ew", padx=14, pady=1)
        acts = ctk.CTkFrame(card, fg_color="transparent")
        acts.grid(row=10, column=0, sticky="ew", padx=10, pady=(8, 12))
        acts.grid_columnconfigure((0, 1), weight=1)
        app._outline_button(acts, "DroidCam", lambda: webbrowser.open(DROIDCAM_URL), height=30, width=10).grid(
            row=0, column=0, sticky="ew", padx=(0, 4))
        app._outline_button(acts, "Camo", lambda: webbrowser.open(CAMO_URL), height=30, width=10).grid(
            row=0, column=1, sticky="ew", padx=(4, 0))
        if len(steps) == 3:
            app._ghost_button(acts, t("cam.iphone.driver"), lambda: webbrowser.open(APPLE_DEVICES_URL),
                              height=28).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ctk.CTkLabel(card, text=t("cam.iphone.note"), font=app.F(11), text_color=C["faint"], anchor="w",
                     justify="left", wraplength=310).grid(row=11, column=0, sticky="ew", padx=14, pady=(0, 12))

    # --------------------------------------------------------------- estado
    def status(self) -> Status:
        s = self.app._selected()
        if s is None or not s.ready or s.waiting:
            return Status("warn", "!")
        return Status()

    def readiness(self) -> List[Readiness]:
        s = self.app._selected()
        if s is None or not s.ready:
            return [Readiness(t("ready.no_camera"), t("mod.cameras"), lambda: self.app.open_module("cameras"), True)]
        return []
