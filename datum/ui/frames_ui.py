"""The Frame Generator's windows: Insert Frame, and the Profile Library.

Insert Frame is laid out as Inventor's is (read from it through UI
Automation): the geometry to place members on, the member (category,
standard, family, size, material, Merge Frame Members), and its
orientation (the nine points, rotate, offsets A and B, mirror), with OK,
Apply and Cancel.  Lines are picked as Inventor picks them: straight off
the view, any visible sketch of any part placed here, by a click or by a
box dragged over them, and the window says how many are selected.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from PySide6 import QtCore, QtWidgets

from ..core import frames, kernel, materials
from .theme import C

PICK_PIXELS = 12
DRAG_PIXELS = 5

# a picked line: (the occurrence its part is placed as, its sketch, the line)
LineKey = Tuple[int, int, int]


def _clip(ax, ay, bx, by, x0, y0, x1, y1) -> bool:
    """Whether the segment a b passes through the box (Liang and Barsky)."""
    t0, t1 = 0.0, 1.0
    dx, dy = bx - ax, by - ay
    for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0),
                 (dy, y1 - ay)):
        if p == 0:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return False
    return True


class InsertFrameDialog(QtWidgets.QDialog):
    """Insert Frame: members on the lines picked in the view."""

    def __init__(self, host, parent=None) -> None:
        super().__init__(parent or host)
        self.host = host
        self.setWindowTitle("Insert Frame")
        self.setModal(False)
        self._drawn: List[Any] = []
        self._lines: Dict[LineKey, Any] = {}
        self._picked: List[LineKey] = []
        self._press: Optional[QtCore.QPoint] = None
        self._boxing = False
        layout = QtWidgets.QVBoxLayout(self)

        # -- input geometry: what is picked in the view
        group = QtWidgets.QGroupBox("Input Geometry")
        box = QtWidgets.QVBoxLayout(group)
        hint = QtWidgets.QLabel("Click sketch lines in the view, or drag a "
                                "box over them. Left to right takes what is "
                                "inside, right to left what it touches. "
                                "Click a picked line again to drop it.")
        hint.setWordWrap(True)
        box.addWidget(hint)
        row = QtWidgets.QHBoxLayout()
        self.count = QtWidgets.QLabel("")
        row.addWidget(self.count, 1)
        clear = QtWidgets.QPushButton("Clear")
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        box.addLayout(row)
        layout.addWidget(group)

        # -- frame member
        group = QtWidgets.QGroupBox("Frame Member")
        form = QtWidgets.QFormLayout(group)
        self.category = QtWidgets.QComboBox()
        form.addRow("Category", self.category)
        self.standard = QtWidgets.QComboBox()
        form.addRow("Standard", self.standard)
        self.family = QtWidgets.QComboBox()
        form.addRow("Family", self.family)
        self.size = QtWidgets.QComboBox()
        form.addRow("Size", self.size)
        self.material = QtWidgets.QComboBox()
        self.material.addItem("As the part comes", "")
        for name in sorted(materials.library().materials):
            self.material.addItem(name, name)
        form.addRow("Material", self.material)
        self.merge = QtWidgets.QCheckBox("Merge Frame Members")
        self.merge.setToolTip("Lines running on in one straight line become "
                              "one member")
        form.addRow("", self.merge)
        layout.addWidget(group)

        # -- orientation
        group = QtWidgets.QGroupBox("Orientation")
        form = QtWidgets.QFormLayout(group)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(2)
        self.anchor_buttons: Dict[str, QtWidgets.QToolButton] = {}
        anchors = QtWidgets.QButtonGroup(self)
        for i, key in enumerate(frames.ANCHORS):
            button = QtWidgets.QToolButton()
            button.setCheckable(True)
            button.setFixedSize(22, 22)
            button.setToolTip("The line runs through the profile's %s" % {
                "t": "top", "m": "middle", "b": "bottom"}[key[0]] + (
                " %s" % {"l": "left", "c": "centre", "r": "right"}[key[1]]
                if key != "mc" else " centre"))
            anchors.addButton(button)
            grid.addWidget(button, i // 3, i % 3)
            self.anchor_buttons[key] = button
        self.anchor_buttons["mc"].setChecked(True)
        holder = QtWidgets.QWidget()
        holder.setLayout(grid)
        form.addRow("Placement", holder)
        self.rotate = QtWidgets.QDoubleSpinBox()
        self.rotate.setRange(-360, 360)
        self.rotate.setSuffix(" deg")
        form.addRow("Rotate", self.rotate)
        self.offset_a = QtWidgets.QDoubleSpinBox()
        self.offset_a.setRange(-10000, 10000)
        self.offset_a.setSuffix(" mm")
        form.addRow("Offset A", self.offset_a)
        self.offset_b = QtWidgets.QDoubleSpinBox()
        self.offset_b.setRange(-10000, 10000)
        self.offset_b.setSuffix(" mm")
        form.addRow("Offset B", self.offset_b)
        self.mirror = QtWidgets.QCheckBox("Mirror Frame Member")
        form.addRow("", self.mirror)
        layout.addWidget(group)

        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Apply
            | QtWidgets.QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.Apply).setText("Apply")
        buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.apply)
        layout.addWidget(buttons)

        self.category.currentIndexChanged.connect(lambda _i: self._standards())
        self.standard.currentIndexChanged.connect(lambda _i: self._families())
        self.family.currentIndexChanged.connect(lambda _i: self._sizes())

        self.reload_lines()
        self._fill_categories()
        viewport = getattr(host, "viewport", None)
        if viewport is not None:
            viewport.installEventFilter(self)
        self.finished.connect(lambda _r: self._close())

    # -- the geometry ------------------------------------------------------

    @property
    def doc(self):
        return self.host.assembly

    def reload_lines(self) -> None:
        """Every line of every sketch that shows, where it sits now."""
        controller = getattr(self.host, "assembly_ui", None)
        try:
            self._lines = controller.component_sketch_lines() \
                if controller is not None else {}
        except Exception:
            self._lines = {}
        self._picked = [k for k in self._picked if k in self._lines]
        if not self._lines:
            self.message.setText("Place a skeleton first: a part with a "
                                 "sketch of lines in it, the sketch visible.")
        self._changed()

    def candidates(self) -> Dict[LineKey, Any]:
        return dict(self._lines)

    def picked(self) -> List[LineKey]:
        return list(self._picked)

    def toggle_line(self, key: LineKey) -> None:
        if key in self._picked:
            self._picked.remove(key)
        else:
            self._picked.append(key)
        self._changed()

    def add_lines(self, keys) -> None:
        for key in keys:
            if key not in self._picked:
                self._picked.append(key)
        self._changed()

    def clear(self) -> None:
        self._picked = []
        self._changed()

    def _changed(self) -> None:
        n = len(self._picked)
        self.count.setText("No lines selected" if not n else
                           "1 line selected" if n == 1 else
                           "%d lines selected" % n)
        self._redraw()

    def _screen(self, key: LineKey):
        viewport = self.host.viewport
        a, b = self._lines[key]
        return viewport.project(a), viewport.project(b)

    def line_at(self, x: int, y: int) -> Optional[LineKey]:
        """The sketch line nearest a click in the view, within reach."""
        best, best_d = None, PICK_PIXELS
        for key in self._lines:
            (ax, ay), (bx, by) = self._screen(key)
            dx, dy = bx - ax, by - ay
            span = dx * dx + dy * dy
            t = 0.0 if span == 0 else max(0.0, min(1.0, (
                (x - ax) * dx + (y - ay) * dy) / span))
            d = ((x - (ax + t * dx)) ** 2 + (y - (ay + t * dy)) ** 2) ** 0.5
            if d < best_d:
                best, best_d = key, d
        return best

    def lines_in_box(self, start: QtCore.QPoint,
                     end: QtCore.QPoint) -> List[LineKey]:
        """The lines a dragged box takes: left to right those wholly in it,
        right to left those it touches, as a selection box does."""
        x0, x1 = sorted((start.x(), end.x()))
        y0, y1 = sorted((start.y(), end.y()))
        crossing = end.x() < start.x()
        out = []
        for key in self._lines:
            (ax, ay), (bx, by) = self._screen(key)
            inside = all(x0 <= x <= x1 and y0 <= y <= y1
                         for x, y in ((ax, ay), (bx, by)))
            if inside or (crossing and _clip(ax, ay, bx, by,
                                             x0, y0, x1, y1)):
                out.append(key)
        return out

    def eventFilter(self, obj, event) -> bool:
        """While the window is open the left button picks lines; the view
        turns and pans as it always does with the others."""
        if not self.isVisible():
            return False
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonPress \
                and event.button() == QtCore.Qt.LeftButton:
            self._press = event.position().toPoint()
            self._boxing = False
            return True
        if kind == QtCore.QEvent.MouseMove and self._press is not None \
                and event.buttons() & QtCore.Qt.LeftButton:
            pos = event.position().toPoint()
            if self._boxing or (pos - self._press).manhattanLength() \
                    >= DRAG_PIXELS:
                self._boxing = True
                try:
                    obj._draw_selection_box(self._press, pos)
                except Exception:
                    pass
            return True
        if kind == QtCore.QEvent.MouseButtonRelease \
                and event.button() == QtCore.Qt.LeftButton \
                and self._press is not None:
            pos = event.position().toPoint()
            if self._boxing:
                try:
                    obj._clear_selection_box()
                except Exception:
                    pass
                self.add_lines(self.lines_in_box(self._press, pos))
            else:
                key = self.line_at(pos.x(), pos.y())
                if key is not None:
                    self.toggle_line(key)
            self._press = None
            self._boxing = False
            return True
        return False

    def _redraw(self) -> None:
        """The picked lines lit up over everything; the rest are drawn
        already, with the parts' sketches."""
        viewport = getattr(self.host, "viewport", None)
        if viewport is None:
            return
        viewport.remove_drawn(self._drawn)
        self._drawn = []
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.gp import gp_Pnt
        with viewport.collecting() as drawn:
            for key in self._picked:
                a, b = self._lines[key]
                if sum((a[i] - b[i]) ** 2 for i in range(3)) < 1e-18:
                    continue
                edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge()
                viewport.draw_shape(edge, C.accent, 4.0)
        viewport.on_top(drawn)
        self._drawn = drawn
        viewport.redraw()

    def _close(self) -> None:
        viewport = getattr(self.host, "viewport", None)
        if viewport is not None:
            viewport.removeEventFilter(self)
            viewport.remove_drawn(self._drawn)
            self._drawn = []
            viewport.redraw()

    # -- the member ----------------------------------------------------------

    def _fill_categories(self) -> None:
        self._families_all = frames.families()
        self.category.blockSignals(True)
        self.category.clear()
        for name in dict.fromkeys(f.category or "Other"
                                  for f in self._families_all):
            self.category.addItem(name)
        self.category.blockSignals(False)
        self._standards()

    def _standards(self) -> None:
        self.standard.blockSignals(True)
        self.standard.clear()
        category = self.category.currentText()
        for name in dict.fromkeys(f.standard or f.name
                                  for f in self._families_all
                                  if (f.category or "Other") == category):
            self.standard.addItem(name)
        self.standard.blockSignals(False)
        self._families()

    def _families(self) -> None:
        self.family.blockSignals(True)
        self.family.clear()
        for f in self._families_all:
            if (f.category or "Other") == self.category.currentText() \
                    and (f.standard or f.name) == self.standard.currentText():
                self.family.addItem(f.name, f.id)
        self.family.blockSignals(False)
        self._sizes()

    def _sizes(self) -> None:
        self.size.clear()
        fid = self.family.currentData()
        fam = next((f for f in self._families_all if f.id == fid), None)
        if fam is not None:
            self.size.addItems(fam.sizes())

    def choose(self, family_id: str, size: str) -> bool:
        """Set the member to a family and size, as picking them would."""
        fam = next((f for f in self._families_all if f.id == family_id),
                   None)
        if fam is None:
            return False
        self.category.setCurrentText(fam.category or "Other")
        self.standard.setCurrentText(fam.standard or fam.name)
        self.family.setCurrentIndex(self.family.findData(family_id))
        self.size.setCurrentText(size)
        return self.size.currentText() == size

    def anchor(self) -> str:
        return next(k for k, b in self.anchor_buttons.items()
                    if b.isChecked())

    # -- doing it --------------------------------------------------------------

    def apply(self) -> bool:
        doc = self.doc
        picked = self.picked()
        if not picked:
            self.message.setText("Pick the lines to put members on.")
            return False
        if not doc.path:
            self.message.setText("Save the assembly first: the frame's "
                                 "files go beside it.")
            return False
        # one frame per skeleton, as Inventor makes one per skeleton: the
        # lines are put in by sketch, each sketch's into the same frame
        groups: Dict[Tuple[int, int], List[int]] = {}
        for oid, sid, lid in picked:
            groups.setdefault((oid, sid), []).append(lid)
        problems: List[str] = []
        made = []
        doc.push_undo()
        for (oid, sid), line_ids in groups.items():
            skeleton = doc.occurrence(oid)
            if skeleton is None:
                continue
            existing = next((o for o in doc.occurrences
                             if o.follows == skeleton.id), None)
            try:
                frame_doc, _occurrence, wrong = frames.insert(
                    doc, skeleton, sid, line_ids,
                    self.family.currentData(), self.size.currentText(),
                    anchor=self.anchor(), offset_a=self.offset_a.value(),
                    offset_b=self.offset_b.value(),
                    rotate=self.rotate.value(),
                    mirror=self.mirror.isChecked(),
                    merge=self.merge.isChecked(),
                    material=self.material.currentData() or "",
                    frame_occurrence=existing)
            except (ValueError, KeyError, kernel.KernelError) as exc:
                problems.append(str(exc))
                continue
            problems += wrong
            made.append(frame_doc)
        if not made:
            self.message.setStyleSheet("color: %s;" % C.error)
            self.message.setText("; ".join(problems) or "Nothing was made.")
            return False
        doc.save(doc.path)
        self.host.assembly_ui.rebuild()
        self.message.setStyleSheet("" if not problems
                                   else "color: %s;" % C.error)
        self.message.setText("; ".join(problems) if problems else "; ".join(
            "%s has %d member(s)." % (os.path.basename(f.path),
                                      len(f.frame.members))
            for f in dict((id(f), f) for f in made).values()))
        self._picked = []
        self.reload_lines()
        return not problems

    def _ok(self) -> None:
        if not self.picked() or self.apply():
            self.accept()


class ProfileLibraryDialog(QtWidgets.QDialog):
    """The profile library: its families and each one's table of sizes.
    Those that come with InventCraft are read only; copy one, or start a
    new family, to have your own."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Profile Library")
        self.resize(820, 520)
        layout = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        left.addWidget(self.tree, 1)
        row = QtWidgets.QHBoxLayout()
        for text, slot in (("New", self.new_family), ("Copy", self.copy),
                           ("Delete", self.delete)):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        left.addLayout(row)
        layout.addLayout(left, 1)
        right = QtWidgets.QVBoxLayout()
        self.title = QtWidgets.QLabel("")
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        right.addWidget(self.title)
        self.table = QtWidgets.QTableWidget()
        right.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.add_row = QtWidgets.QPushButton("Add Size")
        self.add_row.clicked.connect(self._add_row)
        self.remove_row = QtWidgets.QPushButton("Remove Size")
        self.remove_row.clicked.connect(self._remove_row)
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        row.addWidget(self.add_row)
        row.addWidget(self.remove_row)
        row.addStretch(1)
        row.addWidget(self.save_button)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        right.addLayout(row)
        self.message = QtWidgets.QLabel("")
        right.addWidget(self.message)
        layout.addLayout(right, 2)
        self.current: Optional[frames.ProfileFamily] = None
        self.tree.currentItemChanged.connect(lambda item, _o: self._show(item))
        self.fill()

    def fill(self, select: str = "") -> None:
        self.tree.clear()
        groups: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        chosen = None
        for fam in frames.families():
            category = fam.category or "Other"
            if category not in groups:
                groups[category] = QtWidgets.QTreeWidgetItem(self.tree,
                                                             [category])
                groups[category].setExpanded(True)
            item = QtWidgets.QTreeWidgetItem(groups[category], [
                fam.name + ("" if not fam.builtin else "  (built in)")])
            item.setData(0, QtCore.Qt.UserRole, fam.id)
            if fam.id == select or chosen is None:
                chosen = item
        if chosen is not None:
            self.tree.setCurrentItem(chosen)

    def _show(self, item) -> None:
        fid = item.data(0, QtCore.Qt.UserRole) if item is not None else None
        if not fid:
            return
        self.current = frames.family(fid)
        fam = self.current
        self.title.setText("%s   %s   %d sizes" % (fam.name, fam.standard,
                                                   len(fam.rows)))
        self.table.clear()
        self.table.setColumnCount(1 + len(fam.columns))
        self.table.setHorizontalHeaderLabels(["Size"] + fam.columns)
        self.table.setRowCount(len(fam.rows))
        for r, row in enumerate(fam.rows):
            for c, value in enumerate(row):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(
                    str(value)))
        editable = not fam.builtin
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.AllEditTriggers if editable
            else QtWidgets.QAbstractItemView.NoEditTriggers)
        for button in (self.add_row, self.remove_row, self.save_button):
            button.setEnabled(editable)

    def _add_row(self) -> None:
        self.table.insertRow(self.table.rowCount())

    def _remove_row(self) -> None:
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())

    def table_rows(self) -> List[List[Any]]:
        rows = []
        for r in range(self.table.rowCount()):
            cells = [(self.table.item(r, c).text().strip()
                      if self.table.item(r, c) else "")
                     for c in range(self.table.columnCount())]
            if not cells[0]:
                continue
            row = [cells[0]]
            for value in cells[1:]:
                try:
                    row.append(float(value))
                except ValueError:
                    raise ValueError("%s: %r is not a number" % (cells[0],
                                                                value))
            rows.append(row)
        return rows

    def save(self) -> bool:
        if self.current is None or self.current.builtin:
            return False
        try:
            self.current.rows = self.table_rows()
            frames.save_family(self.current)
        except ValueError as exc:
            self.message.setText(str(exc))
            return False
        self.message.setText("Saved.")
        self.fill(self.current.id)
        return True

    def copy(self, name: str = "") -> Optional[frames.ProfileFamily]:
        """Your own copy of the family showing, to change as you like."""
        if self.current is None:
            return None
        if not name:
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Copy Family", "Name:", text=self.current.name + " copy")
            if not ok or not name.strip():
                return None
        fam = frames.ProfileFamily.from_dict(self.current.to_dict())
        fam.id = _slug(name)
        fam.name = name.strip()
        fam.builtin = False
        frames.save_family(fam)
        self.fill(fam.id)
        return fam

    def new_family(self, name: str = "", kind: str = "",
                   source: str = "") -> Optional[frames.ProfileFamily]:
        """A family of your own: a kind that comes with InventCraft, or a
        closed sketch in a part of yours, its parameters the table's
        columns."""
        if not kind:
            kinds = ["Square tube", "Equal angle", "Sketch in a part"]
            choice, ok = QtWidgets.QInputDialog.getItem(
                self, "New Family", "Shape:", kinds, 0, False)
            if not ok:
                return None
            kind = {"Square tube": "square_tube", "Equal angle": "angle",
                    "Sketch in a part": "sketch"}[choice]
        if kind == "sketch" and not source:
            source, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "The profile's part", "", "Parts (*.icpart *.pdat)")
            if not source:
                return None
        if not name:
            name, ok = QtWidgets.QInputDialog.getText(self, "New Family",
                                                      "Name:")
            if not ok or not name.strip():
                return None
        columns = (frames.sketch_parameters(source) if kind == "sketch"
                   else frames.COLUMNS[kind])
        fam = frames.ProfileFamily(_slug(name), name.strip(), "",
                                   frames.CATEGORIES[kind], kind, columns,
                                   [], source)
        frames.save_family(fam)
        self.fill(fam.id)
        return fam

    def delete(self) -> None:
        if self.current is None or self.current.builtin:
            return
        frames.delete_family(self.current.id)
        self.current = None
        self.fill()


def _slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") \
        or "family"
