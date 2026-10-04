"""Pruebas del marco por módulos (app/frame.py): visibilidad de módulos opcionales, «listo para
grabar» y a qué módulo va cada sección de los antiguos ajustes."""
import unittest
from unittest.mock import MagicMock, patch

from app.module import ModuleSpec, Readiness, Module


class _Mod(Module):
    def __init__(self, app, key, optional=False, fixed=False, issues=None, order=0):
        super().__init__(app, ModuleSpec(key, key.title(), "•", order=order, optional=optional, fixed=fixed))
        self.issues = issues or []

    def build_panel(self, parent):
        pass

    def readiness(self):
        return self.issues


def _app(**mods):
    from app.frame import FrameMixin
    app = MagicMock()
    app.settings = {}
    app.modules = mods
    app._drawer_module = None
    for name in ("_modules_cfg", "module_visible", "toggle_module", "ready_check"):
        setattr(app, name, getattr(FrameMixin, name).__get__(app))
    return app


class TestModuleVisibility(unittest.TestCase):
    def test_optional_modules_start_hidden_and_turn_on_with_one_click(self):
        app = _app()
        app.modules = {"cameras": _Mod(app, "cameras"), "streaming": _Mod(app, "streaming", optional=True)}
        self.assertTrue(app.module_visible("cameras"))
        self.assertFalse(app.module_visible("streaming"), "opcional: oculto hasta activarlo")
        self.assertFalse(app.module_visible("nope"))
        app.toggle_module("streaming", True)
        self.assertTrue(app.module_visible("streaming"))
        self.assertEqual(app.settings["modules"]["enabled"], ["streaming"])
        app._save_settings.assert_called()
        app._build_rail_buttons.assert_called()
        app._drawer_module = "streaming"
        app.toggle_module("streaming")                 # sin valor: alterna
        self.assertFalse(app.module_visible("streaming"))
        app.close_drawer.assert_called_once()          # se ocultó con su cajón abierto


class TestReadyCheck(unittest.TestCase):
    def test_blocking_issue_stops_and_shows_the_fix(self):
        fix = MagicMock()
        app = _app()
        app.modules = {"cameras": _Mod(app, "cameras", issues=[Readiness("Elige una cámara", "Cámaras", fix, True)])}
        self.assertFalse(app.ready_check())
        args = app.notify.banner.call_args
        self.assertEqual(args.args[1], "Elige una cámara")
        self.assertEqual(args.kwargs["actions"], [("Cámaras", fix)])

    def test_warning_asks_and_can_record_anyway(self):
        fix = MagicMock()
        app = _app()
        app.modules = {"audio": _Mod(app, "audio", fixed=True,
                                     issues=[Readiness("Sin audio", "+ Agregar", fix, False)])}
        with patch("presentation.dialogs.confirm_dialog.ConfirmDialog.ask", return_value="go"):
            self.assertTrue(app.ready_check())
        with patch("presentation.dialogs.confirm_dialog.ConfirmDialog.ask", return_value="fix"):
            self.assertFalse(app.ready_check())
        fix.assert_called_once()
        with patch("presentation.dialogs.confirm_dialog.ConfirmDialog.ask", return_value=None):
            self.assertFalse(app.ready_check())       # cerró el diálogo: no se graba

    def test_hidden_modules_do_not_block(self):
        app = _app()
        app.modules = {"streaming": _Mod(app, "streaming", optional=True,
                                         issues=[Readiness("Falta una clave", "", None, True)])}
        self.assertTrue(app.ready_check())


class TestSettingsSections(unittest.TestCase):
    def test_every_old_section_has_a_module(self):
        """Lo que antes abría Configuración › X sigue llegando a su sitio (FX, «Audio…», avisos)."""
        from app.settings_panel import MODULE_SECTIONS, SECTION_MODULE, SettingsPanel
        for old in ("general", "video", "audio", "channels", "recording", "vcam", "advanced"):
            self.assertIn(old, SECTION_MODULE)
        self.assertEqual(SECTION_MODULE["channels"], "audio")
        self.assertEqual(SECTION_MODULE["vcam"], "cameras")
        for mod, secs in MODULE_SECTIONS.items():
            for sec, _label in secs:
                self.assertTrue(callable(getattr(SettingsPanel, f"_sec_{sec}", None)), sec)

    def test_same_source_is_static(self):
        """Al repartir los ajustes por módulos se perdió el @staticmethod y la sección Canales fallaba."""
        from modules.audio.ui.settings import AudioSettings
        self.assertTrue(AudioSettings._same_source({"kind": "main", "ch": [0, 1]}, {"kind": "main", "ch": [0, 1]}))
        self.assertFalse(AudioSettings._same_source({"kind": "main", "ch": [0]}, {"kind": "device"}))


if __name__ == "__main__":
    unittest.main()
