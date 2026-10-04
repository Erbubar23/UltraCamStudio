"""Pruebas del marco (app/): bus de eventos, contrato de módulos y reglas de la arquitectura."""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestEventBus(unittest.TestCase):
    def test_emit_reaches_every_subscriber_even_if_one_fails(self):
        from app.bus import EventBus
        errors, got = [], []
        bus = EventBus(report=lambda ev, e: errors.append((ev, str(e))))
        bus.on("x", lambda **d: got.append(("a", d)))
        bus.on("x", lambda **d: 1 / 0)
        bus.on("x", lambda **d: got.append(("c", d)))
        bus.emit("x", n=1)
        self.assertEqual(got, [("a", {"n": 1}), ("c", {"n": 1})])
        self.assertEqual(errors[0][0], "x")

    def test_unsubscribe(self):
        from app.bus import EventBus
        got = []
        bus = EventBus()
        off = bus.on("x", lambda **d: got.append(d))
        off()
        off()                                   # dos veces no falla
        bus.emit("x", n=1)
        self.assertEqual(got, [])


class TestModuleContract(unittest.TestCase):
    def test_defaults(self):
        from app.module import Module, ModuleSpec, Status

        class Simple(Module):
            def build_panel(self, parent):
                pass

        class WithAdvanced(Simple):
            def build_advanced(self, parent):
                pass
        spec = ModuleSpec("x", "X", "•")
        self.assertFalse(Simple(None, spec).has_advanced())
        self.assertTrue(WithAdvanced(None, spec).has_advanced())
        self.assertEqual(Simple(None, spec).status(), Status())
        self.assertEqual(Simple(None, spec).readiness(), [])


class TestStringsCatalog(unittest.TestCase):
    def test_no_key_is_defined_twice(self):
        """Una clave repetida pisa en silencio a la anterior (pasó con «live.on»: el indicador de
        señal de la cámara mostraba el texto de la transmisión)."""
        with open(os.path.join(ROOT, "presentation", "strings.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        dupes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                seen = set()
                for k in node.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        if k.value in seen:
                            dupes.append(f"{k.value} (línea {k.lineno})")
                        seen.add(k.value)
        self.assertEqual(dupes, [])


class TestArchitecture(unittest.TestCase):
    def test_modules_do_not_import_each_other(self):
        """Regla del plan: cada módulo se puede trabajar por separado. Un módulo solo
        importa de su propia carpeta, del marco (app/) o de lo compartido."""
        base = os.path.join(ROOT, "modules")
        offenders = []
        for name in sorted(os.listdir(base)):
            folder = os.path.join(base, name)
            if not os.path.isdir(folder) or name.startswith("__"):
                continue
            for dirpath, _dirs, files in os.walk(folder):
                for f in files:
                    if not f.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, f)
                    with open(path, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read())
                    for node in ast.walk(tree):
                        mods = []
                        if isinstance(node, ast.ImportFrom) and node.module:
                            mods = [node.module]
                        elif isinstance(node, ast.Import):
                            mods = [a.name for a in node.names]
                        for m in mods:
                            parts = m.split(".")
                            if parts[0] == "modules" and len(parts) > 1 and parts[1] != name:
                                offenders.append(f"{os.path.relpath(path, ROOT)} → {m}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
