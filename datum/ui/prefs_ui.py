"""Preferences: the window for the things that belong to the person.

Inventor calls this Application Options, and the distinction it draws is
the one that matters: a document holds what is true about the design, and
this holds what is true about whoever is looking at it.  Your name belongs
in the first kind, because a part that says who drew it is stating a fact
about the part.  The colour of the background belongs in the second, and
has no business travelling inside a file somebody else will open.
"""

from __future__ import annotations

from typing import Dict

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import prefs as core_prefs
from . import icons
from .theme import C, apply_colours, as_hex, current_theme, shipped


class ColourButton(QtWidgets.QPushButton):
    """A swatch that opens the colour picker."""

    picked = QtCore.Signal(str)

    def __init__(self, colour: str, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(52, 22)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._colour = colour
        self._paint()
        self.clicked.connect(self._choose)

    def colour(self) -> str:
        return self._colour

    def set_colour(self, colour: str) -> None:
        self._colour = colour
        self._paint()

    def _paint(self) -> None:
        pixmap = QtGui.QPixmap(38, 14)
        pixmap.fill(QtGui.QColor(self._colour))
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor(C.border_light))
        painter.drawRect(0, 0, 37, 13)
        painter.end()
        self.setIcon(QtGui.QIcon(pixmap))
        self.setIconSize(pixmap.size())

    def _choose(self) -> None:
        chosen = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self._colour), self, "Choose colour")
        if chosen.isValid():
            self.set_colour(chosen.name())
            self.picked.emit(self._colour)


class PreferencesDialog(QtWidgets.QDialog):
    """Who you are, and how you want it to look."""

    # display changes are live, so the window behind can repaint itself
    display_changed = QtCore.Signal()

    COLOURS = (
        ("bg_top", "Background, top"),
        ("bg_bottom", "Background, bottom"),
        ("sketch_line", "Sketch: fully constrained"),
        ("sketch_free", "Sketch: still free to move"),
        ("sketch_construction", "Sketch: construction"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.prefs = core_prefs.prefs()
        self.setWindowTitle("Preferences")
        self.setWindowIcon(icons.icon("edit", 24))
        self.setMinimumWidth(520)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(9)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._general_page(), "General")
        tabs.addTab(self._display_page(), "Display")
        root.addWidget(tabs, 1)

        where = QtWidgets.QLabel("Kept in %s" % core_prefs.config_path())
        where.setProperty("hint", True)
        where.setWordWrap(True)
        root.addWidget(where)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
            | QtWidgets.QDialogButtonBox.Apply)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.apply)
        root.addWidget(buttons)

    # -- pages --------------------------------------------------------------

    def _general_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)

        note = QtWidgets.QLabel(
            "Stamped onto every new part, assembly and drawing, where a "
            "title block and a parts list can ask for it. Documents that "
            "already say who drew them are left alone.")
        note.setWordWrap(True)
        note.setProperty("hint", True)
        form.addRow(note)

        self.name_edit = QtWidgets.QLineEdit(self.prefs.name)
        self.name_edit.setPlaceholderText("the name that appears as Designer")
        form.addRow("Name", self.name_edit)

        self.initials_edit = QtWidgets.QLineEdit(self.prefs.initials)
        self.initials_edit.setMaxLength(6)
        self.initials_edit.setPlaceholderText("for revision tables")
        form.addRow("Initials", self.initials_edit)

        self.company_edit = QtWidgets.QLineEdit(self.prefs.company)
        self.company_edit.setPlaceholderText("appears in the title block")
        form.addRow("Company", self.company_edit)

        from ..core import units as unitlib
        self.units_combo = QtWidgets.QComboBox()
        for key, label in unitlib.LABELS.items():
            self.units_combo.addItem("%s  (%s)" % (label, key), key)
        self.units_combo.setCurrentIndex(
            max(0, self.units_combo.findData(self.prefs.units)))
        self.units_combo.setToolTip(
            "What new parts and assemblies are drawn in. A document's own "
            "units are changed from the unit in the status bar.")
        form.addRow("Units for new documents", self.units_combo)

        self.versions_spin = QtWidgets.QSpinBox()
        self.versions_spin.setRange(-1, 999)
        self.versions_spin.setSpecialValueText("All")
        self.versions_spin.setValue(self.prefs.old_versions)
        self.versions_spin.setToolTip(
            "Every save first copies the file it replaces into an "
            "OldVersions folder beside it, numbered, so an older copy can "
            "be opened if something goes wrong. This many are kept; 0 "
            "keeps none.")
        form.addRow("Old versions kept on save", self.versions_spin)
        return page

    def _display_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        note = QtWidgets.QLabel(
            "Yours, not the document's: these travel with the application "
            "and never inside a file.")
        note.setWordWrap(True)
        note.setProperty("hint", True)
        outer.addWidget(note)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItem("Light", core_prefs.THEME_LIGHT)
        self.theme_combo.addItem("Dark", core_prefs.THEME_DARK)
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(self.prefs.theme)))
        self.theme_combo.setToolTip(
            "Takes effect the next time InventCraft starts. The colours "
            "below belong to the scheme in use now, and each scheme keeps "
            "its own.")
        form.addRow("Colour scheme", self.theme_combo)
        self.colour_buttons: Dict[str, ColourButton] = {}
        for key, label in self.COLOURS:
            button = ColourButton(as_hex(getattr(C, key)))
            button.picked.connect(lambda _c: self.apply())
            self.colour_buttons[key] = button
            form.addRow(label, button)
        self.orbit_combo = QtWidgets.QComboBox()
        self.orbit_combo.addItem("Free", core_prefs.ORBIT_FREE)
        self.orbit_combo.addItem("Turntable, Z always up",
                                 core_prefs.ORBIT_TURNTABLE)
        self.orbit_combo.setToolTip(
            "Free turns about any axis. Turntable spins about Z and tilts, "
            "and never lays the model on its side.")
        self.orbit_combo.setCurrentIndex(
            max(0, self.orbit_combo.findData(self.prefs.orbit)))
        form.addRow("Orbit", self.orbit_combo)
        outer.addLayout(form)

        mouse = QtWidgets.QGroupBox("Mouse")
        mform = QtWidgets.QFormLayout(mouse)
        mform.setSpacing(8)
        self.scheme_combo = QtWidgets.QComboBox()
        for name, orbit, pan in core_prefs.MOUSE_SCHEMES:
            self.scheme_combo.addItem(name, (orbit, pan))
        self.scheme_combo.addItem("Your own", None)
        self.scheme_combo.setToolTip(
            "A ready-made set. Change either button below and it becomes "
            "your own.")
        mform.addRow("Buttons like", self.scheme_combo)

        labels = {
            core_prefs.MOUSE_RIGHT: "Right button",
            core_prefs.MOUSE_SHIFT_MIDDLE: "Wheel button with Shift",
            core_prefs.MOUSE_MIDDLE: "Wheel button",
            core_prefs.MOUSE_LEFT: "Left button",
        }
        self.mouse_orbit_combo = QtWidgets.QComboBox()
        for key in core_prefs.ORBIT_BUTTONS:
            self.mouse_orbit_combo.addItem(labels[key], key)
        self.mouse_pan_combo = QtWidgets.QComboBox()
        for key in core_prefs.PAN_BUTTONS:
            self.mouse_pan_combo.addItem(labels[key], key)
        for combo in (self.mouse_orbit_combo, self.mouse_pan_combo):
            combo.setToolTip(
                "On the left button a drag moves the view and a click still "
                "selects; the selection box is then Shift and the left "
                "button.")
        mform.addRow("Orbit with", self.mouse_orbit_combo)
        mform.addRow("Pan with", self.mouse_pan_combo)
        self.zoom_reversed_box = QtWidgets.QCheckBox(
            "Reverse the wheel's zoom")
        self.zoom_reversed_box.setChecked(self.prefs.zoom_reversed)
        mform.addRow("Zoom", self.zoom_reversed_box)
        outer.addWidget(mouse)

        self._set_mouse(self.prefs.mouse_orbit, self.prefs.mouse_pan)
        self.scheme_combo.currentIndexChanged.connect(self._scheme_picked)
        self.mouse_orbit_combo.currentIndexChanged.connect(
            lambda _i: self._mouse_changed(self.mouse_orbit_combo))
        self.mouse_pan_combo.currentIndexChanged.connect(
            lambda _i: self._mouse_changed(self.mouse_pan_combo))

        outer.addStretch(1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        reset = QtWidgets.QPushButton("Reset to defaults")
        reset.clicked.connect(self.reset_colours)
        row.addWidget(reset)
        outer.addLayout(row)
        return page

    # -- the mouse ----------------------------------------------------------

    def _set_mouse(self, orbit: str, pan: str) -> None:
        """Show these two buttons, and the ready-made set they are, if any."""
        for combo in (self.scheme_combo, self.mouse_orbit_combo,
                      self.mouse_pan_combo):
            combo.blockSignals(True)
        self.mouse_orbit_combo.setCurrentIndex(
            max(0, self.mouse_orbit_combo.findData(orbit)))
        self.mouse_pan_combo.setCurrentIndex(
            max(0, self.mouse_pan_combo.findData(pan)))
        scheme = self.scheme_combo.findData((orbit, pan))
        self.scheme_combo.setCurrentIndex(
            scheme if scheme >= 0 else self.scheme_combo.count() - 1)
        for combo in (self.scheme_combo, self.mouse_orbit_combo,
                      self.mouse_pan_combo):
            combo.blockSignals(False)

    def _scheme_picked(self, _index: int) -> None:
        pair = self.scheme_combo.currentData()
        if pair:
            self._set_mouse(pair[0], pair[1])

    def _mouse_changed(self, changed: QtWidgets.QComboBox) -> None:
        """One button cannot do both: the other moves out of its way."""
        orbit = self.mouse_orbit_combo.currentData()
        pan = self.mouse_pan_combo.currentData()
        if orbit == pan:
            if changed is self.mouse_orbit_combo:
                pan = next(k for k in core_prefs.PAN_BUTTONS if k != orbit)
            else:
                orbit = next(k for k in core_prefs.ORBIT_BUTTONS
                             if k != pan)
        self._set_mouse(orbit, pan)

    # -- saving -------------------------------------------------------------

    def reset_colours(self) -> None:
        for key, button in self.colour_buttons.items():
            button.set_colour(as_hex(shipped(key)))
        self.apply()

    def gather(self) -> None:
        self.prefs.name = self.name_edit.text().strip()
        self.prefs.initials = self.initials_edit.text().strip()
        self.prefs.company = self.company_edit.text().strip()
        self.prefs.units = self.units_combo.currentData() or "mm"
        self.prefs.orbit = (self.orbit_combo.currentData()
                            or core_prefs.ORBIT_FREE)
        self.prefs.mouse_orbit = (self.mouse_orbit_combo.currentData()
                                  or core_prefs.MOUSE_RIGHT)
        self.prefs.mouse_pan = (self.mouse_pan_combo.currentData()
                                or core_prefs.MOUSE_MIDDLE)
        self.prefs.zoom_reversed = self.zoom_reversed_box.isChecked()
        self.prefs.old_versions = self.versions_spin.value()
        # only what differs from the shipped palette is written, so a
        # retuned default reaches everybody who never touched it
        self.prefs.set_colours_for(current_theme(), {
            key: button.colour() for key, button in self.colour_buttons.items()
            if button.colour().lower() != as_hex(shipped(key)).lower()})
        self.prefs.theme = (self.theme_combo.currentData()
                            or core_prefs.THEME_LIGHT)

    def apply(self) -> None:
        self.gather()
        self.prefs.save()
        apply_colours(self.prefs.colours_for(current_theme()))
        self.display_changed.emit()

    def accept(self) -> None:
        self.apply()
        super().accept()


def open_dialog(parent, on_display_change=None) -> None:
    """Show Preferences, applying anything it changes as it is changed."""
    dialog = PreferencesDialog(parent)
    if on_display_change is not None:
        dialog.display_changed.connect(on_display_change)
    dialog.exec()
