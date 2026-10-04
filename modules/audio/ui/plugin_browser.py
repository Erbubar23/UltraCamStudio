"""
Explorador de plugins VST3 (al estilo del «Add FX» de Reaper).

  - Izquierda, un árbol: Todos, Favoritos, Recientes, Instrumentos, Efectos,
    por Fabricante, por Categoría, carpetas propias y los que no cargan.
  - Arriba, un filtro que busca mientras escribes (varias palabras en cualquier orden;
    «-palabra» excluye).
  - Al centro, la lista con columnas que se ordenan con un clic en el encabezado.
  - Doble clic o Enter agrega el plugin. Clic derecho: favorito, carpetas, mostrar
    en el Explorador. Se puede arrastrar un plugin a una carpeta o a Favoritos.

Toda la lógica (qué hay en cada nodo, búsqueda, organización) está en
plugin_library.PluginLibrary; aquí solo se dibuja.
"""

import os
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Dict, List, Optional

import customtkinter as ctk

from plugin_library import PluginLibrary, Node
from presentation.strings import t
from presentation.theme import C

STYLE = "Plugins.Treeview"


def _setup_style(font_family: str):
    st = ttk.Style()
    try:
        st.theme_use("clam")          # el tema nativo de Windows ignora los colores de fondo
    except tk.TclError:
        pass
    st.configure(STYLE, background=C["panel"], fieldbackground=C["panel"], foreground=C["text2"],
                 rowheight=28, borderwidth=0, relief="flat", font=(font_family, 10))
    st.map(STYLE, background=[("selected", C["raised"])], foreground=[("selected", C["text"])])
    st.configure(f"{STYLE}.Heading", background=C["rail"], foreground=C["muted"], relief="flat",
                 borderwidth=0, font=(font_family, 9, "bold"), padding=(8, 6))
    st.map(f"{STYLE}.Heading", background=[("active", C["raised"])])
    st.layout(STYLE, [("Treeview.treearea", {"sticky": "nswe"})])     # sin borde


class PluginBrowser(ctk.CTkToplevel):
    """mode: "instrument" (elegir el instrumento de un canal) o "effect" (agregar un efecto).
    on_pick(ruta) se llama al elegir; on_change() cuando cambia la organización (guardar)."""

    def __init__(self, app, mode: str, on_pick: Callable[[str], None], on_change: Callable[[], None],
                 title: Optional[str] = None):
        super().__init__(app, fg_color=C["rail"])
        self.app = app
        self.mode = mode
        self.on_pick = on_pick
        self.on_change = on_change
        self.lib: Optional[PluginLibrary] = None
        self.node: Node = ("kind", mode)
        self.rows: List[Dict] = []
        self.sort_col, self.sort_rev = "name", False
        self.drag: Optional[Dict] = None
        self.title(title or t("browser.title_instrument" if mode == "instrument" else "browser.title_effect"))
        self.geometry("1040x640")
        self.minsize(780, 460)
        self.transient(app)
        _setup_style(app.ui_family)
        self._build()
        self.reload()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(80, self._focus_search)

    # ------------------------------------------------------------------ Armado
    def _build(self):
        F = self.app.F
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(top, text=t("browser.filter"), font=F(13, "bold"), text_color=C["muted"]).grid(row=0, column=0, padx=(2, 10))
        # Sin textvariable: con ella CTkEntry no muestra el texto de ayuda
        self.entry = ctk.CTkEntry(top, height=36, corner_radius=9, font=F(14), placeholder_text=t("browser.search"),
                                  fg_color=C["panel"], border_color=C["line2"], text_color=C["text"],
                                  placeholder_text_color=C["faint"])
        self.entry.grid(row=0, column=1, sticky="ew")
        self.entry.bind("<KeyRelease>", self._on_type)
        self.entry.bind("<Down>", lambda _e: self._focus_list())
        self.entry.bind("<Return>", lambda _e: self._pick_first())
        self.count = ctk.CTkLabel(top, text="", font=F(12), text_color=C["muted"], width=140, anchor="e")
        self.count.grid(row=0, column=2, padx=(12, 0))

        mid = tk.PanedWindow(self, orient="horizontal", bg=C["line"], sashwidth=4, bd=0, sashrelief="flat")
        mid.grid(row=1, column=0, sticky="nsew", padx=16)

        # Árbol de carpetas
        left = tk.Frame(mid, bg=C["panel"])
        self.tree = ttk.Treeview(left, style=STYLE, show="tree", selectmode="browse")
        self.tree.column("#0", width=230)
        ysb = ctk.CTkScrollbar(left, command=self.tree.yview, button_color=C["raised"], fg_color=C["panel"])
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        ysb.pack(side="right", fill="y")
        self.tree.tag_configure("drop", background=C["accent_bg"], foreground=C["accent_text"])
        self.tree.bind("<<TreeviewSelect>>", self._on_node)
        self.tree.bind("<Button-3>", self._tree_menu)
        mid.add(left, minsize=180, width=250)

        # Lista de plugins
        right = tk.Frame(mid, bg=C["panel"])
        cols = ("name", "kind", "vendor", "cat")
        self.list = ttk.Treeview(right, style=STYLE, columns=cols, show="headings", selectmode="browse")
        for c, w, lab in (("name", 280, t("browser.col_name")), ("kind", 110, t("browser.col_kind")),
                          ("vendor", 160, t("browser.col_vendor")), ("cat", 170, t("browser.col_cat"))):
            self.list.heading(c, text=lab, anchor="w", command=lambda cc=c: self._sort(cc))
            self.list.column(c, width=w, anchor="w", stretch=c in ("name", "cat"))
        self.list.tag_configure("off", foreground=C["off"])
        self.list.tag_configure("err", foreground=C["warn"])
        lsb = ctk.CTkScrollbar(right, command=self.list.yview, button_color=C["raised"], fg_color=C["panel"])
        self.list.configure(yscrollcommand=lsb.set)
        self.list.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        lsb.pack(side="right", fill="y")
        self.list.bind("<Double-1>", lambda _e: self._pick_selected())
        self.list.bind("<Return>", lambda _e: self._pick_selected())
        self.list.bind("<<TreeviewSelect>>", lambda _e: self._on_item())
        self.list.bind("<Button-3>", self._list_menu)
        self.list.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.list.bind("<B1-Motion>", self._drag_move, add="+")
        self.list.bind("<ButtonRelease-1>", self._drag_end, add="+")
        self.list.bind("<Key-f>", lambda _e: self._toggle_fav())
        mid.add(right, minsize=360)

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 14))
        bot.grid_columnconfigure(0, weight=1)
        self.info = ctk.CTkLabel(bot, text="", font=F(11), text_color=C["faint"], anchor="w", justify="left",
                                 wraplength=520)
        self.info.grid(row=0, column=0, sticky="ew")
        bx = ctk.CTkFrame(bot, fg_color="transparent")
        bx.grid(row=0, column=1, sticky="e")
        self.app._ghost_button(bx, t("browser.rescan"), self._rescan, height=36).pack(side="left", padx=(0, 4))
        self.app._ghost_button(bx, t("browser.file"), self._pick_file, height=36).pack(side="left", padx=(0, 12))
        self.app._outline_button(bx, t("action.cancel"), self.destroy, width=100).pack(side="left", padx=(0, 8))
        self.btn_add = ctk.CTkButton(bx, text=t("browser.add_instrument" if self.mode == "instrument" else "browser.add_effect"),
                                     height=36, corner_radius=9, font=F(13, "bold"), fg_color=C["text"],
                                     hover_color="#FFFFFF", text_color="#141413", text_color_disabled=C["off"],
                                     command=self._pick_selected)
        self.btn_add.pack(side="left")

    def query(self) -> str:
        return "" if self.entry._placeholder_text_active else self.entry.get()

    def set_query(self, text: str):
        self.entry.delete(0, "end")
        if text:
            self.entry.insert(0, text)
        self._fill_list()

    def _on_type(self, e):
        if e.keysym not in ("Down", "Up", "Return", "Escape", "Tab"):
            self._fill_list()

    def _focus_search(self):
        try:
            self.lift()
            self.entry.focus_set()
        except tk.TclError:
            pass

    def _focus_list(self):
        kids = self.list.get_children()
        if kids:
            self.list.focus_set()
            self.list.selection_set(kids[0])
            self.list.focus(kids[0])
        return "break"

    # ------------------------------------------------------------------ Datos
    def reload(self):
        """Vuelve a leer la biblioteca (tras revisar plugins o cambiar carpetas)."""
        self.lib = self.app.plugin_library()
        org = self.lib.org
        last = tuple(org.get(f"last_node_{self.mode}") or ())
        if last and not self._node_exists(last):
            last = ()
        self.node = last or self.node
        self._fill_tree()
        self._fill_list()

    def _node_exists(self, node: Node) -> bool:
        if node[0] in ("all", "fav", "recent", "errors", "kind"):
            return True
        if node[0] == "vendor":
            return node[1] in self.lib.vendors()
        if node[0] == "cat":
            return node[1] in self.lib.category_names()
        if node[0] == "folder":
            return node[1] in self.lib.org["folders"]
        return False

    @staticmethod
    def _iid(node: Node) -> str:
        return "\x1f".join(node)

    @staticmethod
    def _node_of(iid: str) -> Node:
        return tuple(iid.split("\x1f"))

    def _fill_tree(self):
        tr, lib = self.tree, self.lib
        opened = {i for i in ("sec_vendor", "sec_cat", "sec_folder") if tr.exists(i) and tr.item(i, "open")}
        first = not tr.get_children()
        tr.delete(*tr.get_children())

        def n(node):
            return len(lib.in_node(node))

        def add(parent, node, label):
            tr.insert(parent, "end", iid=self._iid(node), text=f"{label}   ({n(node)})")

        add("", ("all",), t("browser.all"))
        add("", ("fav",), "★  " + t("browser.favorites"))
        add("", ("recent",), "🕘  " + t("browser.recent"))
        add("", ("kind", "instrument"), "🎹  " + t("browser.instruments"))
        add("", ("kind", "effect"), "🎛  " + t("browser.effects"))
        for sec, label, items, kind in (("sec_vendor", t("browser.by_vendor"), lib.vendors(), "vendor"),
                                        ("sec_cat", t("browser.by_category"), lib.category_names(), "cat"),
                                        ("sec_folder", t("browser.folders"), lib.folders(), "folder")):
            tr.insert("", "end", iid=sec, text=label, open=(sec in opened) or (first and sec == "sec_folder")
                      or (self.node[0] == kind))
            for v in items:
                add(sec, (kind, v), ("📁  " if kind == "folder" else "") + v)
            if kind == "folder":
                tr.insert(sec, "end", iid="new_folder", text="+  " + t("browser.new_folder"))
        if lib.in_node(("errors",)):
            add("", ("errors",), "⚠  " + t("browser.errors"))
        iid = self._iid(self.node)
        if tr.exists(iid):
            tr.selection_set(iid)
            tr.see(iid)

    def _on_node(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid == "new_folder":
            self._new_folder()
            return
        if iid.startswith("sec_"):
            self.tree.item(iid, open=not self.tree.item(iid, "open"))
            return
        node = self._node_of(iid)
        if node != self.node:
            self.node = node
            self.lib.org[f"last_node_{self.mode}"] = list(node)
            self._fill_list()

    def _fill_list(self):
        if self.lib is None:
            return
        rows = self.lib.search(self.node, self.query())
        key = {"name": lambda i: i["name"].lower(), "kind": lambda i: i["kind_label"],
               "vendor": lambda i: i["vendor"].lower(), "cat": lambda i: ", ".join(i["cats"]).lower()}[self.sort_col]
        if self.node[0] != "recent" or self.sort_col != "name":
            rows.sort(key=key, reverse=self.sort_rev)
        self.rows = rows
        self.list.delete(*self.list.get_children())
        for i, it in enumerate(rows):
            star = "★ " if self.lib.is_favorite(it["path"]) else "    "
            tags = ("err",) if it["kind"] == "error" else (() if self._compatible(it) else ("off",))
            self.list.insert("", "end", iid=str(i), tags=tags,
                             values=(star + it["name"], it["kind_label"], it["vendor"], ", ".join(it["cats"])))
        total = len(self.lib.items)
        self.count.configure(text=t("browser.count", n=len(rows), total=total))
        if self.app.vst_probing:
            self.info.configure(text=t("inst.probing"), text_color=C["accent"])
        elif not total:
            self.info.configure(text=t("browser.empty"), text_color=C["warn"])
        else:
            self._on_item()

    def _sort(self, col):
        self.sort_rev = (not self.sort_rev) if self.sort_col == col else False
        self.sort_col = col
        self._fill_list()

    def _compatible(self, it) -> bool:
        if self.mode == "instrument":
            return it["kind"] == "instrument"
        return it["kind"] in ("effect", None)

    def _selected(self) -> Optional[Dict]:
        sel = self.list.selection()
        return self.rows[int(sel[0])] if sel and int(sel[0]) < len(self.rows) else None

    def _on_item(self):
        it = self._selected()
        ok = it is not None and self._compatible(it)
        self.btn_add.configure(state="normal" if ok else "disabled", fg_color=C["text"] if ok else C["raised"])
        if it is None:
            self.info.configure(text=t("browser.hint"), text_color=C["faint"])
            return
        text = it["path"] + (f"   ·   v{it['version']}" if it["version"] else "")
        folders = self.lib.folders_of(it["path"])
        if folders:
            text += "   ·   📁 " + ", ".join(folders)
        color = C["faint"]
        if not ok:
            text = t("browser.not_instrument" if self.mode == "instrument" else "browser.not_effect", name=it["name"])
            color = C["warn"]
        self.info.configure(text=text, text_color=color)

    # ---------------------------------------------------------------- Elegir
    def _pick(self, it: Dict):
        if not self._compatible(it):
            self._on_item()
            return
        self.lib.touch_recent(it["path"])
        self.on_change()
        path = it["path"]
        self.destroy()
        self.on_pick(path)

    def _pick_selected(self):
        it = self._selected()
        if it is not None:
            self._pick(it)

    def _pick_first(self):
        it = next((r for r in self.rows if self._compatible(r)), None)
        if it is not None:
            self._pick(it)

    def _pick_file(self):
        path = filedialog.askopenfilename(parent=self, title=t("inst.pick_file" if self.mode == "instrument"
                                                               else "ui.settings.elegir_plugin_vst3"),
                                          filetypes=[(t("ui.settings.plugin_vst3"), "*.vst3")])
        if path:
            self.destroy()
            self.on_pick(path)

    def _rescan(self):
        self.info.configure(text=t("inst.probing"), text_color=C["accent"])
        self.app.refresh_audio_devices(lambda: self.winfo_exists() and self.reload())

    # ----------------------------------------------------------- Organización
    def _changed(self):
        self.on_change()
        self._fill_tree()
        self._fill_list()

    def _toggle_fav(self, it=None):
        it = it or self._selected()
        if it is not None:
            self.lib.toggle_favorite(it["path"])
            self._changed()

    def _ask(self, title, text, initial="") -> Optional[str]:
        d = ctk.CTkInputDialog(title=title, text=text, fg_color=C["rail"], button_fg_color=C["raised"],
                               button_hover_color=C["line2"], entry_fg_color=C["panel"], entry_border_color=C["line2"],
                               text_color=C["text"], font=self.app.F(13))
        if initial:
            d.after(120, lambda: (d._entry.insert(0, initial), d._entry.select_range(0, "end")))
        return d.get_input()

    def _new_folder(self, then_add: Optional[Dict] = None):
        name = self._ask(t("browser.new_folder"), t("browser.folder_name"))
        made = self.lib.new_folder(name or "")
        if made and then_add is not None:
            self.lib.add_to_folder(made, then_add["path"])
        if made:
            self.node = ("folder", made) if then_add is None else self.node
        self._changed()

    def _rename_folder(self, name):
        new = self._ask(t("browser.rename_folder"), t("browser.folder_name"), name)
        if new and self.lib.rename_folder(name, new):
            if self.node == ("folder", name):
                self.node = ("folder", new.strip())
            self._changed()

    def _delete_folder(self, name):
        self.lib.delete_folder(name)
        if self.node == ("folder", name):
            self.node = ("all",)
        self._changed()

    def _menu(self) -> tk.Menu:
        return tk.Menu(self, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["raised"],
                       activeforeground=C["text"], bd=0, font=(self.app.ui_family, 10))

    def _list_menu(self, e):
        row = self.list.identify_row(e.y)
        if not row:
            return
        self.list.selection_set(row)
        it = self.rows[int(row)]
        m = self._menu()
        if self._compatible(it):
            m.add_command(label=self.btn_add.cget("text"), command=lambda: self._pick(it))
            m.add_separator()
        fav = self.lib.is_favorite(it["path"])
        m.add_command(label=t("browser.unfav" if fav else "browser.fav"), command=lambda: self._toggle_fav(it))
        sub = self._menu()
        for f in self.lib.folders():
            sub.add_command(label=f, command=lambda ff=f: (self.lib.add_to_folder(ff, it["path"]), self._changed()))
        if self.lib.folders():
            sub.add_separator()
        sub.add_command(label=t("browser.new_folder") + "…", command=lambda: self._new_folder(then_add=it))
        m.add_cascade(label=t("browser.add_to_folder"), menu=sub)
        if self.node[0] == "folder":
            m.add_command(label=t("browser.remove_from_folder", folder=self.node[1]),
                          command=lambda: (self.lib.remove_from_folder(self.node[1], it["path"]), self._changed()))
        m.add_separator()
        m.add_command(label=t("browser.reveal"), command=lambda: self._reveal(it["path"]))
        m.tk_popup(e.x_root, e.y_root)

    def _tree_menu(self, e):
        iid = self.tree.identify_row(e.y)
        m = self._menu()
        if iid and iid.startswith("folder\x1f"):
            name = self._node_of(iid)[1]
            m.add_command(label=t("browser.rename_folder"), command=lambda: self._rename_folder(name))
            m.add_command(label=t("browser.delete_folder"), command=lambda: self._delete_folder(name))
            m.add_separator()
        m.add_command(label=t("browser.new_folder") + "…", command=self._new_folder)
        m.tk_popup(e.x_root, e.y_root)

    @staticmethod
    def _reveal(path):
        import subprocess
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    # ------------------------------------------------ Arrastrar a una carpeta
    def _drag_start(self, e):
        row = self.list.identify_row(e.y)
        self.drag = {"row": row, "x": e.x_root, "y": e.y_root, "moving": False} if row else None

    def _drag_move(self, e):
        d = self.drag
        if not d:
            return
        if not d["moving"] and abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) > 8:
            d["moving"] = True
            self.list.configure(cursor="hand2")
        if d["moving"]:
            self._highlight(self._drop_target(e))

    def _highlight(self, iid: Optional[str]):
        """Marca la carpeta sobre la que se soltaría (sin seleccionarla: eso cambiaría la lista)."""
        old = getattr(self, "_hl", None)
        if old == iid:
            return
        if old and self.tree.exists(old):
            self.tree.item(old, tags=())
        if iid:
            self.tree.item(iid, tags=("drop",))
        self._hl = iid

    def _drag_end(self, e):
        d, self.drag = self.drag, None
        self.list.configure(cursor="")
        self._highlight(None)
        if not d or not d["moving"]:
            return
        target = self._drop_target(e)
        it = self.rows[int(d["row"])] if d["row"] and int(d["row"]) < len(self.rows) else None
        if target and it is not None:
            node = self._node_of(target)
            if node == ("fav",):
                if not self.lib.is_favorite(it["path"]):
                    self.lib.toggle_favorite(it["path"])
            else:
                self.lib.add_to_folder(node[1], it["path"])
        # devolver la selección del árbol al nodo que se estaba viendo
        self._changed()

    def _drop_target(self, e) -> Optional[str]:
        """Fila del árbol bajo el puntero si es Favoritos o una carpeta propia."""
        w = self.winfo_containing(e.x_root, e.y_root)
        if w is not self.tree:
            return None
        iid = self.tree.identify_row(e.y_root - self.tree.winfo_rooty())
        if iid == self._iid(("fav",)) or iid.startswith("folder\x1f"):
            return iid
        return None
