"""
UltraCam Studio - Biblioteca de plugins VST3 (como el explorador de FX de Reaper)

Reúne lo que se sabe de cada plugin (nombre, tipo, fabricante, categoría; ver
vst_probe) con lo que organiza la persona: favoritos, recientes y carpetas propias.
El explorador (modules/audio/ui/plugin_browser.py) solo dibuja lo que da esta
clase, así la búsqueda y el orden se pueden probar sin interfaz.

Las rutas se guardan normalizadas (os.path.normcase) para que la misma carpeta de
plugins escrita con otras mayúsculas no duplique nada.
"""

import os
import unicodedata
from typing import Dict, List, Optional, Tuple

MAX_RECENT = 20

# Subcategorías VST3 (Steinberg) → etiqueta para el árbol «Categoría»
CATEGORY_ES = {
    "synth": "Sintetizador", "sampler": "Sampler", "drum": "Batería", "piano": "Piano",
    "external": "Externo", "distortion": "Distorsión / Amp", "reverb": "Reverb", "delay": "Delay",
    "modulation": "Modulación", "eq": "Ecualizador", "dynamics": "Dinámica", "filter": "Filtro",
    "analyzer": "Analizador", "pitch shift": "Afinación", "restoration": "Restauración",
    "spatial": "Espacial", "surround": "Surround", "tools": "Utilidades", "mastering": "Mastering",
    "generator": "Generador", "network": "Red", "up-downmix": "Mezcla de canales",
}

KIND_ES = {"instrument": "Instrumento", "effect": "Efecto", "error": "No carga", None: "Sin revisar"}

# Grupos del selector rápido de instrumentos, en orden de prioridad: un plugin marcado
# «Instrument|Sampler|Synth» (Kontakt) cae en Samplers. Por categoría VST3 y, si no la
# declara, por palabras del nombre.
INSTRUMENT_GROUPS = ("piano", "drums", "sampler", "synth")
_GROUP_CATEGORY = {"piano": "piano", "drums": "drum", "sampler": "sampler", "synth": "synth"}
_GROUP_WORDS = {
    "piano": ("piano", "keys", "rhodes", "wurli", "organ", "organo"),
    "drums": ("drum", "bateria", "percussion", "kit", "808"),
    "sampler": ("sampler", "kontakt", "sfz", "soundfont", "orchestra", "strings"),
    "synth": ("synth", "sintetizador", "analog", "pad", "bass"),
}

Node = Tuple[str, ...]      # ("all",) ("fav",) ("recent",) ("kind", k) ("vendor", v) ("cat", c) ("folder", nombre) ("errors",)


def key_of(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)) if path else ""


def categories(category: Optional[str]) -> List[str]:
    """«Fx|Analyzer|EQ» → ["Analizador", "Ecualizador"]. Lo que no se conoce se muestra tal cual."""
    out = []
    for part in (category or "").split("|"):
        p = part.strip()
        if not p or p.lower() in ("fx", "instrument", "stereo", "mono", "ambisonics", "only rt", "only offline"):
            continue
        label = CATEGORY_ES.get(p.lower(), p)
        if label not in out:
            out.append(label)
    return out


def _fold(text: str) -> str:
    """Minúsculas y sin tildes, para que «distorsion» encuentre «Distorsión»."""
    return "".join(c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn")


def instrument_group(it: Dict) -> str:
    """"piano" | "drums" | "sampler" | "synth" | "other" para el selector rápido."""
    cats = [c.strip().lower() for c in (it.get("category") or "").split("|")]
    for g in INSTRUMENT_GROUPS:
        if _GROUP_CATEGORY[g] in cats:
            return g
    name = _fold(it.get("name", ""))
    for g in INSTRUMENT_GROUPS:
        if any(w in name for w in _GROUP_WORDS[g]):
            return g
    return "other"


class PluginLibrary:
    def __init__(self, plugins: List[Dict], probe: Dict[str, Dict], org: Optional[Dict] = None):
        """plugins: lista de scan_vst3 ({"name", "path"}); probe: caché de vst_probe;
        org: {"favorites": [...], "folders": {nombre: [...]}, "recent": [...]} (se modifica en el lugar)."""
        self.org = org if org is not None else {}
        self.org.setdefault("favorites", [])
        self.org.setdefault("folders", {})
        self.org.setdefault("recent", [])
        self.items: List[Dict] = []
        for p in plugins:
            info = probe.get(os.path.normcase(p["path"])) or {}
            kind = info.get("kind")
            it = {
                "path": p["path"], "key": key_of(p["path"]),
                "name": info.get("name") or p["name"], "kind": kind,
                "vendor": info.get("vendor") or "", "category": info.get("category") or "",
                "version": info.get("version") or "", "cats": categories(info.get("category")),
            }
            it["kind_label"] = KIND_ES.get(kind, KIND_ES[None])
            # También la categoría original en inglés («synth», «reverb»), como se busca en Reaper
            it["haystack"] = _fold(" ".join([it["name"], p["name"], it["vendor"], it["kind_label"],
                                             it["category"].replace("|", " ")] + it["cats"]))
            self.items.append(it)
        self.items.sort(key=lambda i: i["name"].lower())
        self.by_key = {i["key"]: i for i in self.items}

    # ---------------------------------------------------------------- Árbol
    def vendors(self) -> List[str]:
        return sorted({i["vendor"] for i in self.items if i["vendor"]}, key=str.lower)

    def category_names(self) -> List[str]:
        return sorted({c for i in self.items for c in i["cats"]}, key=str.lower)

    def folders(self) -> List[str]:
        return sorted(self.org["folders"], key=str.lower)

    def in_node(self, node: Node) -> List[Dict]:
        kind = node[0]
        if kind == "all":
            return list(self.items)
        if kind == "fav":
            return self._ordered(self.org["favorites"], sort=True)
        if kind == "recent":
            return self._ordered(self.org["recent"], sort=False)
        if kind == "kind":
            return [i for i in self.items if i["kind"] == node[1]]
        if kind == "vendor":
            return [i for i in self.items if i["vendor"] == node[1]]
        if kind == "cat":
            return [i for i in self.items if node[1] in i["cats"]]
        if kind == "folder":
            return self._ordered(self.org["folders"].get(node[1], []), sort=True)
        if kind == "errors":
            return [i for i in self.items if i["kind"] == "error"]
        return []

    def _ordered(self, keys: List[str], sort: bool) -> List[Dict]:
        out = [self.by_key[k] for k in keys if k in self.by_key]
        return sorted(out, key=lambda i: i["name"].lower()) if sort else out

    def search(self, node: Node, query: str, only_kind: Optional[str] = None) -> List[Dict]:
        """Como el filtro de Reaper: cada palabra debe aparecer en el nombre, fabricante,
        tipo o categoría (en cualquier orden, sin importar tildes ni mayúsculas).
        Una palabra con «-» adelante excluye: «reverb -plate»."""
        words = _fold(query).split()
        need = [w for w in words if not w.startswith("-")]
        avoid = [w[1:] for w in words if w.startswith("-") and len(w) > 1]
        out = []
        for it in self.in_node(node):
            if only_kind and it["kind"] != only_kind:
                continue
            h = it["haystack"]
            if all(w in h for w in need) and not any(w in h for w in avoid):
                out.append(it)
        return out

    def instruments(self, query: str = "", group: Optional[str] = None) -> List[Dict]:
        """Instrumentos que coinciden con la búsqueda, del grupo pedido (None = todos)."""
        found = self.search(("all",), query, only_kind="instrument")
        return [i for i in found if group is None or instrument_group(i) == group]

    def quick(self, node: Node, kind: str, limit: int = 6) -> List[Dict]:
        """Recientes o favoritos de un tipo, para los accesos directos."""
        return [i for i in self.in_node(node) if i["kind"] == kind][:limit]

    # ---------------------------------------------------------- Organización
    def is_favorite(self, path: str) -> bool:
        return key_of(path) in self.org["favorites"]

    def toggle_favorite(self, path: str) -> bool:
        k = key_of(path)
        fav = self.org["favorites"]
        if k in fav:
            fav.remove(k)
            return False
        fav.append(k)
        return True

    def touch_recent(self, path: str):
        k = key_of(path)
        rec = self.org["recent"]
        if k in rec:
            rec.remove(k)
        rec.insert(0, k)
        del rec[MAX_RECENT:]

    def new_folder(self, name: str) -> Optional[str]:
        name = (name or "").strip()
        if not name or name in self.org["folders"]:
            return None
        self.org["folders"][name] = []
        return name

    def rename_folder(self, old: str, new: str) -> bool:
        new = (new or "").strip()
        f = self.org["folders"]
        if old not in f or not new or new in f:
            return False
        f[new] = f.pop(old)
        return True

    def delete_folder(self, name: str):
        self.org["folders"].pop(name, None)

    def add_to_folder(self, name: str, path: str):
        lst = self.org["folders"].setdefault(name, [])
        k = key_of(path)
        if k not in lst:
            lst.append(k)

    def remove_from_folder(self, name: str, path: str):
        lst = self.org["folders"].get(name, [])
        k = key_of(path)
        if k in lst:
            lst.remove(k)

    def folders_of(self, path: str) -> List[str]:
        k = key_of(path)
        return [n for n in self.folders() if k in self.org["folders"][n]]
