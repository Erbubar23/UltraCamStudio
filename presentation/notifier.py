"""
Avisos de la app, en tres niveles:

  toast(texto)            Algo que ya pasó y no pide nada («Toma guardada»). Se va solo.
  banner(clave, texto)    Un estado que requiere atención («Queda poco espacio»). Se queda
                          hasta que se resuelve (clear) o la persona lo cierra. La misma
                          clave reemplaza al aviso anterior: nunca se apilan repetidos.
  ConfirmDialog           Solo decisiones que bloquean o no se pueden deshacer
                          (presentation/dialogs/confirm_dialog.py).

Todos dejan además una línea en el pie de la ventana, como historial breve. Los textos
salen del catálogo (presentation/strings.py); el detalle técnico va al registro.
"""

from typing import Callable, Dict, Iterable, Optional, Tuple

import customtkinter as ctk

from presentation.theme import C, ICON

# nivel -> (fondo, borde, texto, icono)
_STYLE = {
    "info": (C["panel"], C["line2"], C["text2"], None),
    "success": (C["ok_bg"], C["ok_line"], C["ok_text"], ICON["check"]),
    "warn": (C["accent_bg"], "#5A4524", C["accent_text"], ICON["warning"]),
    "error": ("#2A1618", "#5C2A2D", C["rec_text"], ICON["warning"]),
}

Action = Tuple[str, Callable[[], None]]


class Notifier:
    TOAST_MS = 3500

    def __init__(self, host: ctk.CTkFrame, font_fn: Callable[..., ctk.CTkFont],
                 icon_font_fn: Callable[..., ctk.CTkFont],
                 on_footer: Optional[Callable[[str, str], None]] = None):
        self.host = host
        self.F = font_fn
        self.IF = icon_font_fn
        self.on_footer = on_footer or (lambda _text, _level: None)
        self._toast: Optional[ctk.CTkFrame] = None
        self._toast_text = ""
        self._toast_timer = None
        self._banners: Dict[str, Tuple[ctk.CTkFrame, str]] = {}
        self._labels = []
        host.bind("<Configure>", lambda _e: self._rewrap())
        self._refresh()

    # ------------------------------------------------------------------ API
    def toast(self, text: str, level: str = "success", duration_ms: Optional[int] = None):
        self.on_footer(text, level)
        if self._toast is not None and self._toast_text == text:
            self._restart_toast_timer(duration_ms)       # repetido: solo se alarga
            return
        self._drop_toast()
        self._toast = self._build(text, level, actions=(), on_close=None)
        self._toast_text = text
        first = next(iter(self._banners.values()), (None,))[0]
        self._toast.pack(fill="x", pady=(0, 6), **({"before": first} if first is not None else {}))
        self._restart_toast_timer(duration_ms)
        self._refresh()

    def banner(self, key: str, text: str, level: str = "warn", actions: Iterable[Action] = (),
               dismissible: bool = True):
        current = self._banners.get(key)
        if current is not None and current[1] == text:
            return                                      # ya está a la vista: sin repetirlo
        self.on_footer(text, level)
        if current is not None:
            current[0].destroy()
        frame = self._build(text, level, actions, on_close=(lambda k=key: self.clear(k)) if dismissible else None)
        frame.pack(fill="x", pady=(0, 6))
        self._banners[key] = (frame, text)
        self._refresh()

    def clear(self, key: str):
        current = self._banners.pop(key, None)
        if current is not None:
            current[0].destroy()
            self._refresh()

    def has(self, key: str) -> bool:
        return key in self._banners

    def status(self, text: str, level: str = "info"):
        """Solo la línea del pie: para lo que conviene saber pero no merece un aviso."""
        self.on_footer(text, level)

    # ------------------------------------------------------------- interno
    def _build(self, text: str, level: str, actions: Iterable[Action], on_close) -> ctk.CTkFrame:
        bg, border, fg, icon = _STYLE.get(level, _STYLE["info"])
        frame = ctk.CTkFrame(self.host, fg_color=bg, corner_radius=9, border_width=1, border_color=border)
        frame.grid_columnconfigure(1, weight=1)
        if icon:
            ctk.CTkLabel(frame, text=icon, font=self.IF(14), text_color=fg, width=20).grid(
                row=0, column=0, padx=(12, 0), pady=8, sticky="n")
        label = ctk.CTkLabel(frame, text=text, font=self.F(13), text_color=fg, anchor="w", justify="left")
        label.grid(row=0, column=1, sticky="ew", padx=10, pady=8)
        self._labels.append(label)
        if on_close:
            ctk.CTkButton(frame, text=ICON["close"], font=self.IF(11), width=28, height=26, fg_color="transparent",
                          hover_color=C["raised"], text_color=fg, command=on_close).grid(
                row=0, column=2, padx=(0, 6), pady=6, sticky="n")
        actions = list(actions)
        if actions:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.grid(row=1, column=1, columnspan=2, sticky="w", padx=4, pady=(0, 8))
            for text_btn, cmd in actions:
                ctk.CTkButton(row, text=text_btn, command=cmd, height=28, corner_radius=7, font=self.F(12, "bold"),
                              fg_color="transparent", border_width=1, border_color=border, hover_color=C["raised"],
                              text_color=fg).pack(side="left", padx=(6, 0))
        self._rewrap(label)
        return frame

    def _rewrap(self, only=None):
        width = max(self.host.winfo_width() - 110, 300)
        alive = []
        for label in ([only] if only else self._labels):
            try:
                label.configure(wraplength=width)
                alive.append(label)
            except Exception:
                pass                                    # etiqueta de un aviso ya cerrado
        if only is None:
            self._labels = alive

    def _restart_toast_timer(self, duration_ms):
        if self._toast_timer:
            try:
                self.host.after_cancel(self._toast_timer)
            except (ValueError, KeyError):
                pass
        self._toast_timer = self.host.after(duration_ms or self.TOAST_MS, self._drop_toast)

    def _drop_toast(self):
        if self._toast is not None:
            self._toast.destroy()
            self._toast = None
            self._toast_text = ""
        self._toast_timer = None
        self._refresh()

    def _refresh(self):
        if self._toast is not None or self._banners:
            self.host.grid()
        else:
            self.host.grid_remove()
