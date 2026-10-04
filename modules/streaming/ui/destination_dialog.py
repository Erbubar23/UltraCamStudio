"""
UltraCam Studio - Agregar o editar un destino de transmisión (centro de cuentas).

Eliges la plataforma y pegas la clave; el servidor se completa solo cuando la plataforma lo
publica (YouTube, Twitch, Facebook) y se pide cuando cada cuenta tiene el suyo (Kick,
TikTok, Instagram). La clave se oculta al escribirla y se guarda cifrada (accounts.py).
"""

from typing import Callable, Dict, Optional

import customtkinter as ctk

from modules.streaming.platforms import PLATFORMS, get, ingest_url
from presentation.strings import t
from presentation.theme import C


class DestinationDialog(ctk.CTkToplevel):
    def __init__(self, app, accounts, dest: Optional[Dict], on_done: Callable[[], None], platform: str = None):
        super().__init__(app, fg_color=C["rail"])
        self.app, self.accounts, self.dest, self.on_done = app, accounts, dest, on_done
        self.title(t("live.dest.title"))
        self.geometry("460x520")
        self.resizable(False, False)
        self.transient(app)
        self.grid_columnconfigure(0, weight=1)
        F = app.F
        names = [p.name for p in PLATFORMS.values()]
        cur = get(dest["platform"]).name if dest else (get(platform).name if platform else names[0])

        def label(text, row):
            ctk.CTkLabel(self, text=text, font=F(12), text_color=C["text"], anchor="w").grid(
                row=row, column=0, sticky="ew", padx=20, pady=(12, 2))
        ctk.CTkLabel(self, text=t("live.dest.edit") if dest else t("live.dest.new"), font=F(18, "bold"),
                     text_color=C["text"], anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        label(t("live.dest.platform"), 1)
        self.menu = app._option_menu(self, names, self._on_platform)
        self.menu.set(cur)
        self.menu.grid(row=2, column=0, sticky="ew", padx=20)
        self.help = ctk.CTkLabel(self, text="", font=F(11), text_color=C["text2"], anchor="w", justify="left",
                                 wraplength=410)
        self.help.grid(row=3, column=0, sticky="ew", padx=20, pady=(4, 0))
        label(t("live.dest.name"), 4)
        self.e_name = self._entry(5)
        label(t("live.dest.server"), 6)
        self.e_server = self._entry(7)
        label(t("live.dest.key"), 8)
        kf = ctk.CTkFrame(self, fg_color="transparent")
        kf.grid(row=9, column=0, sticky="ew", padx=20)
        kf.grid_columnconfigure(0, weight=1)
        self.e_key = ctk.CTkEntry(kf, height=34, corner_radius=8, fg_color=C["raised"], border_color=C["line2"],
                                  text_color=C["text"], font=F(13), show="•",
                                  placeholder_text=t("live.dest.key_keep") if dest else "")
        self.e_key.grid(row=0, column=0, sticky="ew")
        app._ghost_button(kf, t("live.dest.show"), self._toggle_show, height=34).grid(row=0, column=1, padx=(6, 0))
        self.err = ctk.CTkLabel(self, text="", font=F(12), text_color=C["warn"], anchor="w", wraplength=410)
        self.err.grid(row=10, column=0, sticky="ew", padx=20, pady=(8, 0))
        acts = ctk.CTkFrame(self, fg_color="transparent")
        acts.grid(row=11, column=0, sticky="ew", padx=20, pady=(14, 18))
        ctk.CTkButton(acts, text=t("live.dest.save"), height=36, corner_radius=9, font=F(13, "bold"),
                      fg_color=C["text"], hover_color="#FFFFFF", text_color="#141413", command=self._save).pack(side="right")
        app._ghost_button(acts, t("action.cancel"), self.destroy, height=36).pack(side="right", padx=8)
        if dest:
            ctk.CTkButton(acts, text=t("live.dest.delete"), height=36, corner_radius=9, font=F(13), fg_color="transparent",
                          border_width=1, border_color=C["rec"], hover_color="#3A1E20", text_color=C["rec_text"],
                          command=self._delete).pack(side="left")
        if dest:
            self.err.configure(text=t("live.dest.key_keep"), text_color=C["text2"])   # el campo vacío conserva la clave
            self.e_name.insert(0, dest.get("name", ""))
            self.e_server.insert(0, dest.get("server", ""))
        self._on_platform(cur, fill=not dest)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(80, lambda: (self.lift(), self.e_key.focus_set()))

    def _entry(self, row):
        e = ctk.CTkEntry(self, height=34, corner_radius=8, fg_color=C["raised"], border_color=C["line2"],
                         text_color=C["text"], font=self.app.F(13))
        e.grid(row=row, column=0, sticky="ew", padx=20)
        return e

    def _platform_key(self) -> str:
        name = self.menu.get()
        return next(p.key for p in PLATFORMS.values() if p.name == name)

    def _on_platform(self, name, fill=True):
        p = get(self._platform_key())
        self.help.configure(text=p.help + ("  " + t("live.dest.vertical") if p.orientation == "v" else ""))
        if fill:
            self.e_server.delete(0, "end")
            self.e_server.insert(0, p.server)
            self.e_name.delete(0, "end")
            self.e_name.insert(0, p.name)

    def _toggle_show(self):
        self.e_key.configure(show="" if self.e_key.cget("show") else "•")

    def _save(self):
        key = self.e_key.get().strip()
        server = self.e_server.get().strip()
        if not ingest_url(server, key or "x"):
            self.err.configure(text=t("live.dest.bad_server"), text_color=C["warn"])
            return
        if not key and not self.dest:
            self.err.configure(text=t("live.dest.need_key"), text_color=C["warn"])
            return
        self.accounts.save(self._platform_key(), self.e_name.get(), server, key or None,
                           did=self.dest["id"] if self.dest else None)
        self.destroy()
        self.on_done()

    def _delete(self):
        self.accounts.remove(self.dest["id"])
        self.destroy()
        self.on_done()
