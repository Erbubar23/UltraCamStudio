"""
UltraCam Studio - Módulo Grabación en el marco: el cajón con las tomas recientes (y la
última guardada a mano). Su «Avanzado» (archivo, pistas, sincronía, compresión) está en
modules/recording/ui/settings.py.
"""

from typing import List

from app.module import Module, ModuleSpec, Readiness, Status
from presentation.strings import t
from presentation.theme import ICON


class RecordingModule(Module):
    scrollable = False          # la lista de tomas ya se desplaza sola

    def __init__(self, app):
        super().__init__(app, ModuleSpec("recording", t("mod.recording"), ICON["record"], order=20,
                                         advanced_hint=t("mod.recording.hint")))

    def build_panel(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        self.app._build_takes_panel(parent)

    def on_show(self):
        self.app._refresh_takes()

    def status(self) -> Status:
        st = self.app.rec_state
        if st == "recording":
            return Status("rec", "●")
        if st in ("starting", "saving"):
            return Status("warn", "…")
        return Status()

    def readiness(self) -> List[Readiness]:
        from modules.recording.disk import DISK_MIN_TO_START, disk_free
        free, _ = disk_free(self.app.record_dir_var.get())
        if free is not None and free < DISK_MIN_TO_START:
            return [Readiness(t("ready.disk"), t("mod.recording"), lambda: self.app.open_module("recording", True), True)]
        return []
