"""The Standards drop down of the library windows.

A button that opens a list of the standards bodies the library has
parts from, ISO, DIN, EN, ASME and the rest, each with a tick.  Untick
one and its families leave the window; the choice is kept for next time
and shared by Place from Library and the Profile Library, so somebody
who only ever uses ISO and EN parts sets it once.  The list stays open
while it is being ticked.
"""
from __future__ import annotations

from typing import Dict, Iterable, List

from PySide6 import QtCore, QtWidgets

from ..core import prefs
from ..core.stdlib import body

NAMES = {"ISO": "ISO, international", "EN": "EN, European",
         "DIN": "DIN, German", "ASME": "ASME, American inch",
         "ASTM": "ASTM, American", "BS": "BS, British", "IS": "IS, Indian",
         "GOST": "GOST, Russian", "SAE": "SAE", "JIS": "JIS, Japanese",
         "GB": "GB, Chinese", "Other": "Others and your own"}
ORDER = list(NAMES)


class _StayOpen(QtWidgets.QMenu):
    """A menu that does not close when a tick is clicked."""

    def mouseReleaseEvent(self, event) -> None:
        action = self.activeAction()
        if action is not None and action.isCheckable() and action.isEnabled():
            action.trigger()
            return
        super().mouseReleaseEvent(event)


class StandardsFilter(QtWidgets.QToolButton):
    """Which standards to show.  ``changed`` fires after every tick."""

    changed = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.setToolTip("Show only the standards you use")
        self._menu = _StayOpen(self)
        self.setMenu(self._menu)
        self._actions: Dict[str, QtWidgets.QAction] = {}
        self.hidden = set(prefs.prefs().hidden_standards)
        self.set_standards([])

    def set_standards(self, standards: Iterable[str]) -> None:
        """The standards there are to choose from, as the families name
        them; each is counted under its body."""
        counts: Dict[str, int] = {}
        for standard in standards:
            name = body(standard)
            counts[name] = counts.get(name, 0) + 1
        self._menu.clear()
        self._actions = {}
        every = self._menu.addAction("Show all")
        every.triggered.connect(lambda: self._set_all(True))
        only = self._menu.addAction("Show none")
        only.triggered.connect(lambda: self._set_all(False))
        self._menu.addSeparator()
        for name in sorted(counts, key=lambda n: (ORDER.index(n)
                                                  if n in ORDER else 99, n)):
            action = self._menu.addAction("%s   %d" % (NAMES.get(name, name),
                                                       counts[name]))
            action.setCheckable(True)
            action.setChecked(name not in self.hidden)
            action.toggled.connect(
                lambda on, n=name: self._toggle(n, on))
            self._actions[name] = action
        self._label()

    def shows(self, standard: str) -> bool:
        return body(standard) not in self.hidden

    def _toggle(self, name: str, on: bool) -> None:
        if on:
            self.hidden.discard(name)
        else:
            self.hidden.add(name)
        self._save()

    def _set_all(self, on: bool) -> None:
        for name, action in self._actions.items():
            action.blockSignals(True)
            action.setChecked(on)
            action.blockSignals(False)
            if on:
                self.hidden.discard(name)
            else:
                self.hidden.add(name)
        self._save()

    def _save(self) -> None:
        settings = prefs.prefs()
        settings.hidden_standards = sorted(self.hidden)
        try:
            settings.save()
        except OSError:
            pass
        self._label()
        self.changed.emit()

    def _label(self) -> None:
        shown: List[str] = [n for n in self._actions if n not in self.hidden]
        if not self._actions or len(shown) == len(self._actions):
            text = "Standards: all"
        elif not shown:
            text = "Standards: none"
        elif len(shown) <= 3:
            text = "Standards: " + ", ".join(shown)
        else:
            text = "Standards: %d of %d" % (len(shown), len(self._actions))
        self.setText(text + "  ")
