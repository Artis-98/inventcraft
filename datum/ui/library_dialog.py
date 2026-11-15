"""Place from Library: Inventor's Place from Content Center.

The library is a tree of categories, shelves and families.  Structural
Shapes is the Frame Generator's own profile library, read from it every
time, so the two always offer the same families and sizes.  Fasteners
come from tables by ISO standard (core/standard_parts.py).  Picking a
family opens the one window every standard part is sized in: its sizes
as a table, and its length when it has one.  The same window opens again
from Change Size on a placed part.  Shelves still empty say so, and
Place Component is there for anything already on disk.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import standard_parts as sp
from . import icons
from .theme import C

ROLE_FAMILY = QtCore.Qt.UserRole + 1
ROLE_ABOUT = QtCore.Qt.UserRole + 2

# shelves still to be filled: category -> [(shelf, what goes there)]
COMING_SHELVES: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("Fasteners", [
        ("Threaded inserts", "Heat set inserts for printed parts"),
    ]),
    ("Shaft parts", [
        ("Pins", "Dowel pins ISO 8734, spring pins"),
        ("Keys", "Parallel keys DIN 6885"),
        ("Retaining rings", "Circlips DIN 471 and DIN 472"),
    ]),
    ("Bearings", [
        ("Ball bearings", "Deep groove 6000, 6200 and 600 series"),
        ("Linear bearings", "LM8UU and the rest of the LM series"),
    ]),
    ("Online libraries", [
        ("GrabCAD and others", "Search a public library and bring the "
                               "model straight in, as STEP"),
    ]),
]

COMING = ("This shelf is being built. Online libraries such as GrabCAD "
          "follow the standard parts.")
# kept for anything that still reads the old name
SHELVES = COMING_SHELVES


class StandardPartDialog(QtWidgets.QDialog):
    """A standard part's size, and its length when it has one: the window
    a family opens in to be placed, and again to be changed."""

    def __init__(self, parent, family: sp.Family, size: str = "",
                 length: float = 0.0, verb: str = "Place") -> None:
        super().__init__(parent)
        self.family = family
        self.chosen: Optional[Dict[str, Any]] = None
        self.setWindowTitle("%s  %s" % (family.name, family.standard))
        self.setWindowIcon(icons.icon("library", 24))
        self.resize(560, 460)
        layout = QtWidgets.QVBoxLayout(self)

        heading = QtWidgets.QLabel("%s, %s" % (family.name,
                                               family.standard), self)
        heading.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(heading)

        self.table = QtWidgets.QTableWidget(len(family.rows),
                                            1 + len(family.columns), self)
        self.table.setHorizontalHeaderLabels(
            ["Size"] + ["%s, mm" % c for c in family.columns])
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for r, row in enumerate(family.rows):
            for c, value in enumerate(row[:1 + len(family.columns)]):
                text = str(value) if c == 0 else "%g" % float(value)
                item = QtWidgets.QTableWidgetItem(text)
                if c:
                    item.setTextAlignment(QtCore.Qt.AlignRight
                                          | QtCore.Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.itemDoubleClicked.connect(lambda _item: self._ok())
        layout.addWidget(self.table, 1)

        form = QtWidgets.QFormLayout()
        self.length = None
        if family.needs_length:
            self.length = QtWidgets.QComboBox(self)
            self.length.setEditable(True)
            for value in family.lengths:
                self.length.addItem("%g" % value)
            self.length.setEditText("%g" % (length or family.default_length))
            self.length.setToolTip("Type any length, or pick a standard one")
            form.addRow("Length, mm", self.length)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(self)
        self.ok = buttons.addButton(verb, QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        sizes = family.sizes()
        start = sizes.index(size) if size in sizes else 0
        if sizes:
            self.table.selectRow(start)

    def size(self) -> str:
        row = self.table.currentRow()
        sizes = self.family.sizes()
        return sizes[row] if 0 <= row < len(sizes) else ""

    def _ok(self) -> None:
        size = self.size()
        if not size:
            return
        length = 0.0
        if self.length is not None:
            try:
                length = float(self.length.currentText().replace(",", "."))
            except ValueError:
                length = 0.0
            if length <= 0:
                QtWidgets.QMessageBox.warning(self, self.windowTitle(),
                                              "The length has to be more "
                                              "than nothing.")
                return
        self.chosen = sp.spec(self.family.id, size, length)
        self.accept()


class LibraryDialog(QtWidgets.QDialog):
    """The library, by category, shelf and family.

    ``chosen`` is the standard part to place once a family has been sized;
    ``place_file`` is set when somebody would rather bring in a file they
    already have: the window closes and Place Component opens.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Place from Library")
        self.setWindowIcon(icons.icon("library", 24))
        self.resize(760, 480)
        self.place_file = False
        self.chosen: Optional[Dict[str, Any]] = None

        layout = QtWidgets.QVBoxLayout(self)
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        layout.addWidget(split, 1)

        self.tree = QtWidgets.QTreeWidget(split)
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(260)
        self._build()

        side = QtWidgets.QWidget(split)
        right = QtWidgets.QVBoxLayout(side)
        right.setContentsMargins(16, 8, 8, 8)
        self.title = QtWidgets.QLabel("Library", side)
        self.title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.title.setWordWrap(True)
        self.about = QtWidgets.QLabel("", side)
        self.about.setWordWrap(True)
        self.about.setStyleSheet("color: %s;" % C.text_dim)
        self.state = QtWidgets.QLabel("", side)
        self.state.setWordWrap(True)
        self.state.setObjectName("LibraryState")
        self.select = QtWidgets.QPushButton(icons.icon("library", 16),
                                            "Select Size...", side)
        self.select.setToolTip("Pick the size and length, then place it")
        self.select.clicked.connect(self._open_family)
        right.addWidget(self.title)
        right.addWidget(self.about)
        right.addSpacing(12)
        right.addWidget(self.state)
        right.addWidget(self.select, 0, QtCore.Qt.AlignLeft)
        right.addStretch(1)
        split.addWidget(self.tree)
        split.addWidget(side)
        split.setStretchFactor(1, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.from_file = QtWidgets.QPushButton(
            icons.icon("import", 16), "Place Component...", self)
        self.from_file.setToolTip("Bring in a part or assembly file you "
                                  "already have")
        self.from_file.clicked.connect(self._from_file)
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.reject)
        buttons.addWidget(self.from_file)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.tree.currentItemChanged.connect(self._show)
        self.tree.itemDoubleClicked.connect(
            lambda item, _c: self._open_family() if item.data(
                0, ROLE_FAMILY) else None)
        first = self.tree.topLevelItem(0)
        if first is not None:
            self.tree.setCurrentItem(first)

    def _branch(self, path: str) -> QtWidgets.QTreeWidgetItem:
        """The tree item for a category path such as Fasteners/Bolts,
        made the first time it is asked for."""
        parent = None
        for name in path.split("/"):
            count = (parent.childCount() if parent is not None
                     else self.tree.topLevelItemCount())
            found = None
            for i in range(count):
                item = (parent.child(i) if parent is not None
                        else self.tree.topLevelItem(i))
                if item.text(0) == name and not item.data(0, ROLE_FAMILY):
                    found = item
                    break
            if found is None:
                found = QtWidgets.QTreeWidgetItem([name])
                found.setIcon(0, icons.icon("open", 16))
                if parent is None:
                    self.tree.addTopLevelItem(found)
                else:
                    parent.addChild(found)
            parent = found
        return parent

    def _build(self) -> None:
        for fam in sp.families():
            shelf = self._branch(fam.category)
            item = QtWidgets.QTreeWidgetItem(
                ["%s  %s" % (fam.standard, fam.name)
                 if fam.standard and fam.standard not in fam.name
                 else fam.name])
            item.setData(0, ROLE_FAMILY, fam.id)
            item.setData(0, ROLE_ABOUT, "%d sizes, %s to %s" % (
                len(fam.rows), fam.sizes()[0] if fam.rows else "",
                fam.sizes()[-1] if fam.rows else ""))
            item.setIcon(0, icons.icon(
                "frame_member" if fam.kind == sp.PROFILE else "library", 16))
            shelf.addChild(item)
        for category, shelves in COMING_SHELVES:
            for name, about in shelves:
                item = self._branch(category + "/" + name)
                item.setData(0, ROLE_ABOUT, about)
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(
                    C.text_dim)))
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(True)

    def _show(self, item, _previous=None) -> None:
        if item is None:
            return
        family_id = item.data(0, ROLE_FAMILY)
        about = item.data(0, ROLE_ABOUT)
        self.title.setText(item.text(0))
        self.select.setVisible(bool(family_id))
        if family_id:
            self.about.setText(str(about or ""))
            self.state.setText("Select Size, or double-click it, to pick "
                               "the size%s and place it." % (
                                   " and length" if sp.family(
                                       family_id).needs_length else ""))
        elif about:
            self.about.setText(str(about))
            self.state.setText(COMING)
        else:
            self.about.setText(", ".join(
                item.child(i).text(0) for i in range(item.childCount())))
            self.state.setText("")

    def _open_family(self) -> None:
        item = self.tree.currentItem()
        family_id = item.data(0, ROLE_FAMILY) if item is not None else None
        if not family_id:
            return
        dialog = StandardPartDialog(self, sp.family(family_id))
        self._sizer = dialog
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.chosen:
            self.chosen = dialog.chosen
            self.accept()
        self._sizer = None

    def _from_file(self) -> None:
        self.place_file = True
        self.accept()
