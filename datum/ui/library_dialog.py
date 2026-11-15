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

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import prefs
from ..core import standard_parts as sp
from . import icons
from .theme import C

ROLE_FAMILY = QtCore.Qt.UserRole + 1
ROLE_ABOUT = QtCore.Qt.UserRole + 2
ROLE_PATH = QtCore.Qt.UserRole + 3
ROLE_FILE = QtCore.Qt.UserRole + 4

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


MY_FOLDERS = "My Folders"


def natural(name: str):
    """Sorting by the numbers in a name as numbers: M6, M8, M10."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", name)]


class _Folder:
    """One folder of the library: its folders, its families, the files in
    it when it is a folder on disk, and what it is for when still empty."""

    def __init__(self, name: str, path: str, disk: str = "") -> None:
        self.name = name
        self.path = path
        self.folders: Dict[str, "_Folder"] = {}
        self.families: List[sp.Family] = []
        self.files: List[str] = []
        self.about = ""
        # a folder of your own: read from disk when it is first opened
        self.disk = disk
        self.loaded = not disk

    def folder(self, name: str, disk: str = "") -> "_Folder":
        if name not in self.folders:
            self.folders[name] = _Folder(
                name, (self.path + "/" + name) if self.path else name, disk)
        return self.folders[name]

    def load(self) -> None:
        """What is in a folder on disk: its folders, and the parts,
        assemblies and STEP files a library can place."""
        if self.loaded:
            return
        self.loaded = True
        try:
            entries = sorted(os.scandir(self.disk),
                             key=lambda e: natural(e.name))
        except OSError:
            self.about = "This folder cannot be read: %s" % self.disk
            return
        for entry in entries:
            if entry.name.startswith(".") or entry.name == "OldVersions":
                continue
            if entry.is_dir():
                self.folder(entry.name, entry.path)
            elif sp.placeable(entry.name):
                self.files.append(entry.path)

    def empty(self) -> bool:
        if self.disk:
            return False
        return not self.families and all(f.empty()
                                         for f in self.folders.values())


def family_label(fam: sp.Family) -> str:
    """The standard on one line and what it is on the next, the standard
    said once even when the family's name starts with it."""
    name = fam.name
    if fam.standard and name.startswith(fam.standard):
        name = name[len(fam.standard):].strip()
    return "%s\n%s" % (fam.standard, name) if fam.standard else name


def library_tree(own: Optional[List[str]] = None) -> _Folder:
    """The library as folders: Structural Shapes from the Frame Generator,
    Fasteners from the ISO tables, your own folders from disk, and the
    shelves still to come."""
    if own is None:
        own = list(prefs.prefs().library_folders)
    root = _Folder("Library", "")
    for fam in sp.families():
        here = root
        for name in fam.category.split("/"):
            here = here.folder(name)
        here.families.append(fam)
    mine = root.folder(MY_FOLDERS)
    mine.about = ("Your own folders of parts, assemblies and STEP files, "
                  "a bought in bolt library say. Add Folder puts one here.")
    for path in own:
        name = os.path.basename(os.path.normpath(path)) or path
        while name in mine.folders:
            name += " (2)"
        mine.folder(name, path)
    for category, shelves in COMING_SHELVES:
        for name, about in shelves:
            root.folder(category).folder(name).about = about
    return root


def _file_icon(path: str, size: int = 40) -> QtGui.QIcon:
    """A part's own picture when its file has one, else its kind's icon."""
    from ..core import fileformat

    extension = os.path.splitext(path)[1].lower()
    if extension in sp.NATIVE:
        try:
            data = fileformat.thumbnail_of(path)
        except Exception:
            data = None
        if data:
            picture = QtGui.QPixmap()
            if picture.loadFromData(data):
                return QtGui.QIcon(picture)
        return icons.icon("pattern" if extension == ".icasm" else "box",
                          size)
    return icons.icon("import", size)


class LibraryDialog(QtWidgets.QDialog):
    """The library, browsed like folders on disk, as Inventor's Content
    Center is: the folders on the left, what is in the open one on the
    right.  A folder opens with a double-click, into its folders or its
    families; Back and Up go the other way.  A family picked is placed
    with Place, or a double-click, through its size window; a file from
    one of your own folders is placed as it is, a STEP file as a part.

    ``chosen`` is the standard part to place once a family has been sized,
    ``chosen_file`` the file picked in one of your folders; ``place_file``
    is set when somebody would rather browse for a file: the window
    closes and Place Component opens.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Place from Library")
        self.setWindowIcon(icons.icon("library", 24))
        self.resize(900, 540)
        self.place_file = False
        self.chosen: Optional[Dict[str, Any]] = None
        self.chosen_file = ""
        self.root = library_tree()
        self.current = self.root
        self._history: List[str] = []

        layout = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.back = QtWidgets.QToolButton(self)
        self.back.setText("<")
        self.back.setToolTip("Back")
        self.back.clicked.connect(self.go_back)
        self.up = QtWidgets.QToolButton(self)
        self.up.setText("Up")
        self.up.setToolTip("The folder this one is in")
        self.up.clicked.connect(self.go_up)
        self.where = QtWidgets.QLabel("", self)
        self.where.setStyleSheet("font-weight: 600;")
        bar.addWidget(self.back)
        bar.addWidget(self.up)
        bar.addSpacing(6)
        bar.addWidget(self.where, 1)
        layout.addLayout(bar)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        layout.addWidget(split, 1)
        self.tree = QtWidgets.QTreeWidget(split)
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self._items: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._fill_tree(self.root, None)
        self.tree.itemClicked.connect(
            lambda item, _c: self.open_folder(item.data(0, ROLE_PATH)))
        # clicked or chosen with the keys, not whatever is current when the
        # window first shows, so it opens at the top of the library
        self.tree.itemActivated.connect(
            lambda item, _c: self.open_folder(item.data(0, ROLE_PATH)))

        side = QtWidgets.QWidget(split)
        right = QtWidgets.QVBoxLayout(side)
        right.setContentsMargins(6, 0, 0, 0)
        self.view = QtWidgets.QListWidget(side)
        self.view.setViewMode(QtWidgets.QListView.IconMode)
        self.view.setIconSize(QtCore.QSize(40, 40))
        self.view.setGridSize(QtCore.QSize(190, 112))
        self.view.setTextElideMode(QtCore.Qt.ElideNone)
        self.view.setResizeMode(QtWidgets.QListView.Adjust)
        self.view.setMovement(QtWidgets.QListView.Static)
        self.view.setWordWrap(True)
        self.view.itemDoubleClicked.connect(self._double_clicked)
        self.view.currentItemChanged.connect(self._picked)
        self.about = QtWidgets.QLabel("", side)
        self.about.setWordWrap(True)
        self.about.setStyleSheet("color: %s;" % C.text_dim)
        right.addWidget(self.view, 1)
        right.addWidget(self.about)
        split.addWidget(self.tree)
        split.addWidget(side)
        split.setStretchFactor(1, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.from_file = QtWidgets.QPushButton(
            icons.icon("open", 16), "Browse for File...", self)
        self.from_file.setToolTip("Place a part or assembly file from "
                                  "anywhere, through Place Component")
        self.from_file.clicked.connect(self._from_file)
        self.add_folder = QtWidgets.QPushButton(
            icons.icon("open", 16), "Add Folder...", self)
        self.add_folder.setToolTip(
            "One of your own folders of parts, assemblies or STEP files, "
            "under My Folders, kept for next time")
        self.add_folder.clicked.connect(self._add_folder)
        self.remove_folder = QtWidgets.QPushButton("Remove Folder", self)
        self.remove_folder.setToolTip(
            "Take this folder out of the library; nothing on disk is "
            "touched")
        self.remove_folder.clicked.connect(self._remove_folder)
        self.place = QtWidgets.QPushButton(icons.icon("library", 16),
                                           "Place...", self)
        self.place.setToolTip("Place what is picked: a family through its "
                              "size window, a file as it is")
        self.place.setDefault(True)
        self.place.clicked.connect(self._place_picked)
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.reject)
        buttons.addWidget(self.from_file)
        buttons.addWidget(self.add_folder)
        buttons.addWidget(self.remove_folder)
        buttons.addStretch(1)
        buttons.addWidget(self.place)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.open_folder("", remember=False)

    # -- the folders -------------------------------------------------------

    def _fill_tree(self, folder: _Folder, parent) -> None:
        for child in folder.folders.values():
            if child.path in self._items:
                continue
            item = QtWidgets.QTreeWidgetItem([child.name])
            item.setData(0, ROLE_PATH, child.path)
            item.setIcon(0, icons.icon("open", 16))
            if child.disk:
                item.setToolTip(0, child.disk)
                # it may have folders in it, read when it is opened
                item.setChildIndicatorPolicy(
                    QtWidgets.QTreeWidgetItem.ShowIndicator)
            elif child.empty() and child.name != MY_FOLDERS:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(C.text_dim)))
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            self._items[child.path] = item
            self._fill_tree(child, item)

    def folder_at(self, path: str) -> Optional[_Folder]:
        here = self.root
        for name in [p for p in (path or "").split("/") if p]:
            here.load()
            here = here.folders.get(name)
            if here is None:
                return None
        here.load()
        return here

    def open_folder(self, path: str, remember: bool = True) -> None:
        """Show what is in a folder, as the right hand side."""
        folder = self.folder_at(path)
        if folder is None:
            return
        if remember and folder is not self.current:
            self._history.append(self.current.path)
        self.current = folder
        self.where.setText("Library" + "".join(
            "  >  " + p for p in folder.path.split("/") if p))
        self.back.setEnabled(bool(self._history))
        self.up.setEnabled(bool(folder.path))
        self.remove_folder.setVisible(self._own_root(folder) is not None)
        item = self._items.get(folder.path)
        if item is not None:
            # a folder on disk just read: its folders join the tree
            self._fill_tree(folder, item)
            if not folder.folders:
                item.setChildIndicatorPolicy(
                    QtWidgets.QTreeWidgetItem.DontShowIndicatorWhenChildless)
        if item is not None and self.tree.currentItem() is not item:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(item)
            item.setExpanded(True)
            self.tree.blockSignals(False)
        self.view.clear()
        for child in folder.folders.values():
            entry = QtWidgets.QListWidgetItem(icons.icon("open", 40),
                                              child.name)
            entry.setData(ROLE_PATH, child.path)
            entry.setSizeHint(QtCore.QSize(180, 104))
            entry.setToolTip(child.disk or child.about or child.name)
            if child.empty() and child.name != MY_FOLDERS:
                entry.setForeground(QtGui.QBrush(QtGui.QColor(C.text_dim)))
            self.view.addItem(entry)
        for fam in folder.families:
            entry = QtWidgets.QListWidgetItem(
                icons.icon("frame_member" if fam.kind == sp.PROFILE
                           else "library", 40), family_label(fam))
            entry.setData(ROLE_FAMILY, fam.id)
            entry.setSizeHint(QtCore.QSize(180, 104))
            entry.setToolTip("%s, %d sizes" % (fam.name, len(fam.rows)))
            self.view.addItem(entry)
        for path in folder.files:
            entry = QtWidgets.QListWidgetItem(
                _file_icon(path), os.path.basename(path))
            entry.setData(ROLE_FILE, path)
            entry.setSizeHint(QtCore.QSize(180, 104))
            entry.setToolTip(path)
            self.view.addItem(entry)
        if folder.about and not folder.families and not folder.files \
                and not any(not f.empty() for f in folder.folders.values()):
            self.about.setText(folder.about if folder.disk
                               or folder.name == MY_FOLDERS
                               else "%s\n\n%s" % (folder.about, COMING))
        else:
            self.about.setText("")
        self._picked(None)

    def _own_root(self, folder: _Folder) -> Optional[str]:
        """The folder of your own a folder is, or is inside: its key under
        My Folders; None for the standard library."""
        parts = folder.path.split("/")
        if len(parts) >= 2 and parts[0] == MY_FOLDERS:
            return parts[1]
        return None

    def go_back(self) -> None:
        if self._history:
            self.open_folder(self._history.pop(), remember=False)

    def go_up(self) -> None:
        if self.current.path:
            self.open_folder(self.current.path.rpartition("/")[0])

    def _double_clicked(self, entry) -> None:
        if entry.data(ROLE_FAMILY) or entry.data(ROLE_FILE):
            self.view.setCurrentItem(entry)
            self._place_picked()
        elif entry.data(ROLE_PATH) is not None:
            self.open_folder(entry.data(ROLE_PATH))

    def _picked(self, entry, _previous=None) -> None:
        family_id = entry.data(ROLE_FAMILY) if entry is not None else None
        path = entry.data(ROLE_FILE) if entry is not None else None
        self.place.setEnabled(bool(family_id or path))
        if family_id:
            fam = sp.family(family_id)
            self.about.setText("%s: %d sizes, %s to %s. Place, or a "
                               "double-click, to pick the size%s." % (
                                   family_label(fam).replace("\n", ", "),
                                   len(fam.rows),
                                   fam.sizes()[0] if fam.rows else "",
                                   fam.sizes()[-1] if fam.rows else "",
                                   " and length" if fam.needs_length
                                   else ""))
        elif path:
            foreign = os.path.splitext(path)[1].lower() in sp.FOREIGN
            self.about.setText(
                "%s. Place, or a double-click, puts it in the assembly%s."
                % (path, ", as a part holding its body" if foreign else ""))

    def selected_family(self) -> str:
        entry = self.view.currentItem()
        return str(entry.data(ROLE_FAMILY) or "") if entry else ""

    def selected_file(self) -> str:
        entry = self.view.currentItem()
        return str(entry.data(ROLE_FILE) or "") if entry else ""

    def _place_picked(self) -> None:
        if self.selected_file():
            self.chosen_file = self.selected_file()
            self.accept()
            return
        self._open_family()

    def _open_family(self) -> None:
        family_id = self.selected_family()
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

    # -- your own folders --------------------------------------------------

    def add_own_folder(self, path: str) -> None:
        """Keep a folder of your own in the library, and open it."""
        settings = prefs.prefs()
        path = os.path.normpath(path)
        if not any(os.path.normcase(p) == os.path.normcase(path)
                   for p in settings.library_folders):
            settings.library_folders.append(path)
            settings.save()
        self._rebuild()
        mine = self.root.folders[MY_FOLDERS]
        name = next((n for n, f in mine.folders.items()
                     if os.path.normcase(f.disk) == os.path.normcase(path)),
                    "")
        self.open_folder(MY_FOLDERS + "/" + name if name else MY_FOLDERS)

    def remove_own_folder(self, name: str) -> None:
        mine = self.root.folders[MY_FOLDERS]
        folder = mine.folders.get(name)
        if folder is None:
            return
        settings = prefs.prefs()
        settings.library_folders = [
            p for p in settings.library_folders
            if os.path.normcase(os.path.normpath(p))
            != os.path.normcase(os.path.normpath(folder.disk))]
        settings.save()
        self._rebuild()
        self.open_folder(MY_FOLDERS, remember=False)

    def _rebuild(self) -> None:
        self.root = library_tree()
        self.current = self.root
        self._history = []
        self.tree.clear()
        self._items = {}
        self._fill_tree(self.root, None)

    def _add_folder(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Add a Folder to the Library")
        if path:
            self.add_own_folder(path)

    def _remove_folder(self) -> None:
        name = self._own_root(self.current)
        if name:
            self.remove_own_folder(name)
