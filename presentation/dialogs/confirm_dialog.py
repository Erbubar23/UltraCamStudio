"""
Diálogo de confirmación con el tema de la app.

Es el nivel más alto de aviso: solo para decisiones que bloquean o no se pueden
deshacer (cerrar la app, borrar algo). Los botones dicen la acción («Cerrar»,
«Guardar y cerrar»), no «Aceptar», para que se entienda sin leer el texto.
"""

from typing import Callable, List, Optional, Tuple

import customtkinter as ctk

from presentation.theme import C

# (clave, texto, estilo) con estilo "primary", "danger" o "ghost"
Choice = Tuple[str, str, str]


class ConfirmDialog:
    @staticmethod
    def ask(parent: ctk.CTk, title: str, message: str, choices: List[Choice],
            font_fn: Callable[..., ctk.CTkFont], cancel: str = "cancel") -> Optional[str]:
        """Muestra el diálogo y espera. Devuelve la clave elegida, o `cancel` si se
        cierra con la X o con Esc. Enter elige el botón "primary"."""
        result = {"key": cancel}
        win = ctk.CTkToplevel(parent, fg_color=C["rail"])
        win.title(title)
        win.resizable(False, False)
        win.transient(parent)

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=26, pady=(22, 20))
        ctk.CTkLabel(body, text=title, font=font_fn(17, "bold"), text_color=C["text"],
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(body, text=message, font=font_fn(13), text_color=C["text2"], anchor="w",
                     justify="left", wraplength=440).pack(fill="x", pady=(8, 20))

        def pick(key: str):
            result["key"] = key
            win.destroy()

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")
        primary = None
        # Se empaquetan de derecha a izquierda: el último de la lista queda a la derecha.
        for key, label, style in reversed(choices):
            if style == "primary":
                b = ctk.CTkButton(row, text=label, height=38, corner_radius=9, font=font_fn(13, "bold"),
                                  fg_color=C["text"], hover_color="#FFFFFF", text_color="#141413",
                                  command=lambda k=key: pick(k))
                primary = key
            elif style == "danger":
                b = ctk.CTkButton(row, text=label, height=38, corner_radius=9, font=font_fn(13),
                                  fg_color="transparent", border_width=1, border_color=C["rec"],
                                  hover_color="#3A1E20", text_color=C["rec_text"], command=lambda k=key: pick(k))
            else:
                b = ctk.CTkButton(row, text=label, height=38, corner_radius=9, font=font_fn(13),
                                  fg_color="transparent", hover_color=C["raised"], text_color=C["text2"],
                                  command=lambda k=key: pick(k))
            b.pack(side="right", padx=(8, 0))

        win.protocol("WM_DELETE_WINDOW", lambda: pick(cancel))
        win.bind("<Escape>", lambda _e: pick(cancel))
        if primary:
            win.bind("<Return>", lambda _e: pick(primary))

        # Centrado sobre la ventana principal y por delante de ella.
        win.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.after(10, lambda: (win.lift(), win.focus_force()))
        win.grab_set()
        parent.wait_window(win)
        return result["key"]
