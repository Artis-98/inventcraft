"""Place from Library: where standard parts will come from.

Inventor has Place from Content Center beside Place: bolts, nuts, washers,
pins, bearings and steel sections, picked by standard and size and dropped
straight into the assembly.  This is the same place in InventCraft.  The
shelves are laid out already; what fills them comes in stages, generated
standard parts first and then online libraries such as GrabCAD, so the
window says plainly what is there today and what is on its way, and offers
Place Component for anything already on disk.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from PySide6 import QtCore, QtWidgets

from . import icons
from .theme import C

# category -> its shelves, each (name, what goes there)
SHELVES: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("Fasteners", [
        ("Bolts", "Hex head bolts and screws, ISO 4014 and ISO 4017"),
        ("Socket head screws", "ISO 4762, countersunk ISO 10642"),
        ("Nuts", "Hex nuts ISO 4032, nylon insert, flange nuts"),
        ("Washers", "Plain washers ISO 7089, spring and lock washers"),
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
    ("Steel sections", [
        ("Angles", "Equal and unequal angles"),
        ("Box sections", "Square and rectangular hollow sections"),
        ("Flat bar", "Flats by width and thickness"),
    ]),
    ("Online libraries", [
        ("GrabCAD and others", "Search a public library and bring the "
                               "model straight in, as STEP"),
    ]),
]

COMING = ("This shelf is being built. Standard parts are generated to size "
          "first: bolts, nuts and washers lead. Online libraries such as "
          "GrabCAD follow.")


class LibraryDialog(QtWidgets.QDialog):
    """The library, by category and shelf.

    ``place_file`` is set when somebody would rather bring in a file they
    already have: the window closes and Place Component opens.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Place from Library")
        self.setWindowIcon(icons.icon("library", 24))
        self.resize(720, 440)
        self.place_file = False

        layout = QtWidgets.QVBoxLayout(self)
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        layout.addWidget(split, 1)

        self.tree = QtWidgets.QTreeWidget(split)
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(210)
        self._about: Dict[int, str] = {}
        for category, shelves in SHELVES:
            top = QtWidgets.QTreeWidgetItem([category])
            top.setIcon(0, icons.icon("library", 16))
            self.tree.addTopLevelItem(top)
            for name, about in shelves:
                child = QtWidgets.QTreeWidgetItem([name])
                child.setData(0, QtCore.Qt.UserRole, about)
                top.addChild(child)
            top.setExpanded(True)

        side = QtWidgets.QWidget(split)
        right = QtWidgets.QVBoxLayout(side)
        right.setContentsMargins(16, 8, 8, 8)
        self.title = QtWidgets.QLabel("Library", side)
        self.title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.about = QtWidgets.QLabel("", side)
        self.about.setWordWrap(True)
        self.about.setStyleSheet("color: %s;" % C.text_dim)
        self.state = QtWidgets.QLabel(COMING, side)
        self.state.setWordWrap(True)
        self.state.setObjectName("LibraryState")
        right.addWidget(self.title)
        right.addWidget(self.about)
        right.addSpacing(12)
        right.addWidget(self.state)
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
        first = self.tree.topLevelItem(0)
        if first is not None and first.childCount():
            self.tree.setCurrentItem(first.child(0))

    def _show(self, item, _previous=None) -> None:
        if item is None:
            return
        about = item.data(0, QtCore.Qt.UserRole)
        self.title.setText(item.text(0))
        if about:
            self.about.setText(str(about))
        else:
            self.about.setText(", ".join(
                item.child(i).text(0) for i in range(item.childCount())))

    def _from_file(self) -> None:
        self.place_file = True
        self.accept()
