"""Document Settings: what belongs to this file, not to the computer.

Inventor keeps two windows apart.  Application Options are yours, on this
computer: who you are, colours, the mouse.  Document Settings travel in
the file: its units, how it is looked at, a drawing's standard.  Saved
into the Templates folder, a file's settings are what every new file
started from it begins with.
"""

from __future__ import annotations

import os

from PySide6 import QtWidgets

from ..core import fileformat
from . import icons

STYLES = (("shaded_edges", "Shaded with edges"), ("shaded", "Shaded"),
          ("wireframe", "Wireframe"), ("xray", "X-ray"))


class DocumentSettingsDialog(QtWidgets.QDialog):
    def __init__(self, host, document) -> None:
        super().__init__(host)
        self.host = host
        self.document = document
        drawing = hasattr(document, "sheets")
        self.drawing = drawing
        name = os.path.basename(getattr(document, "path", "") or "") \
            or "this document"
        self.setWindowTitle("Document Settings - %s" % name)
        self.setWindowIcon(icons.icon("properties", 24))
        self.setMinimumWidth(440)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(9)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._units_page(), "Units")
        if drawing:
            tabs.addTab(self._drawing_page(), "Drawing")
        else:
            tabs.addTab(self._display_page(), "Display")
        root.addWidget(tabs, 1)

        note = QtWidgets.QLabel(
            "Kept in the file. Save As Template puts a copy in the "
            "Templates folder, so new files start this way.")
        note.setProperty("hint", True)
        note.setWordWrap(True)
        root.addWidget(note)

        row = QtWidgets.QHBoxLayout()
        template = QtWidgets.QPushButton("Save As Template...")
        template.clicked.connect(self._save_template)
        row.addWidget(template)
        row.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
            | QtWidgets.QDialogButtonBox.Apply)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.apply)
        row.addWidget(buttons)
        root.addLayout(row)

    # -- pages --------------------------------------------------------------

    def _units_page(self):
        from ..core import units as unitlib
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.units = QtWidgets.QComboBox()
        for key, label in unitlib.LABELS.items():
            self.units.addItem("%s  (%s)" % (label, key), key)
        self.units.setCurrentIndex(max(0, self.units.findData(
            unitlib.known(getattr(self.document, "units", "mm") or "mm"))))
        self.units.setToolTip("What lengths are shown and typed in")
        form.addRow("Length", self.units)
        angle = QtWidgets.QLabel("Degrees")
        angle.setProperty("hint", True)
        form.addRow("Angle", angle)
        return page

    def _display_page(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        setup = getattr(self.document, "view", None)
        self.style = QtWidgets.QComboBox()
        for key, label in STYLES:
            self.style.addItem(label, key)
        current = (getattr(setup, "style", "") or "shaded_edges")
        self.style.setCurrentIndex(max(0, self.style.findData(current)))
        form.addRow("Visual style", self.style)
        self.ortho = QtWidgets.QComboBox()
        self.ortho.addItem("Orthographic", True)
        self.ortho.addItem("Perspective", False)
        ortho = getattr(setup, "orthographic", None)
        self.ortho.setCurrentIndex(0 if ortho is None or ortho else 1)
        form.addRow("Camera", self.ortho)
        return page

    def _drawing_page(self):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.standard = QtWidgets.QComboBox()
        for key, label in (("ISO", "ISO (metric, first angle)"),
                           ("ANSI", "ANSI (inch, third angle)")):
            self.standard.addItem(label, key)
        self.standard.setCurrentIndex(max(0, self.standard.findData(
            getattr(self.document, "standard", "ISO") or "ISO")))
        form.addRow("Standard", self.standard)
        return page

    # -- applying -----------------------------------------------------------

    def apply(self) -> None:
        host, document = self.host, self.document
        unit = self.units.currentData()
        if unit and unit != getattr(document, "units", "mm"):
            host.change_units(unit)
        if self.drawing:
            standard = self.standard.currentData() or "ISO"
            if standard != getattr(document, "standard", "ISO"):
                document.standard = standard
                document.modified = True
                host.drawing_ui.rebuild()
        else:
            setup = getattr(document, "view", None)
            if setup is not None:
                setup.style = self.style.currentData() or "shaded_edges"
                setup.orthographic = bool(self.ortho.currentData())
                host._show_as_kept()
        host.update_title() if hasattr(host, "update_title") else None

    def accept(self) -> None:
        self.apply()
        super().accept()

    def _save_template(self) -> None:
        self.apply()
        if self.drawing:
            self.host.drawing_ui.save_as_template()
            return
        from ..core import templates
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save As Template", "Template name:")
        if not ok or not name.strip():
            return
        try:
            written = templates.save_copy_as_template(self.document, name)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Save As Template", str(exc))
            return
        self.host.status_message.setStyleSheet("")
        self.host.status_message.setText(
            "Saved the template %s" % os.path.basename(written))


def open_dialog(host) -> None:
    document = host.active_document
    if document is None:
        return
    DocumentSettingsDialog(host, document).exec()


__all__ = ["DocumentSettingsDialog", "open_dialog", "fileformat"]
