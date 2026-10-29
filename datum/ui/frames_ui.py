"""The Frame Generator's windows: Insert Frame and Change Frame, the end
treatments, and the Profile Library.

Insert Frame is laid out as Inventor's is (read from it through UI
Automation): the geometry to place members on, the member (category,
standard, family, size, material, Merge Frame Members), and its
orientation (the nine points, rotate, offsets A and B, mirror), with OK,
Apply and Cancel.  Lines are picked as Inventor picks them: straight off
the view, any visible sketch of any part placed here, by a click or by a
box dragged over them, and the window says how many are selected.  Change
Frame is the same window on members already made, picked the same way or
in the tree.  While any of them is open, what it would make is drawn over
the model in see-through green, as Extrude previews.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from PySide6 import QtCore, QtWidgets

from ..core import frames, kernel, materials
from .theme import C

PICK_PIXELS = 12
DRAG_PIXELS = 5
PREVIEW = "#4ee08a"         # what a command will make, as Extrude shows it
PREVIEW_MS = 120

# a picked line: (the occurrence its part is placed as, its sketch, the
# line); a picked member: ("m", its frame's occurrence, its id)
LineKey = Tuple[Any, int, int]


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


# the frame that is itself the assembly open, Frame0003 opened or stepped
# into, where a frame placed in an assembly is known by its occurrence
SELF = -1


def frame_occurrences(doc) -> List[Any]:
    """The frames placed in an assembly."""
    out = []
    for occurrence in getattr(doc, "occurrences", []):
        path = doc.component_path(occurrence)
        if path and path.lower().endswith(".icasm") and frames.is_frame(path):
            out.append(occurrence)
    return out


def frame_ids(doc) -> List[int]:
    """Every frame to be had here: the assembly itself when it is one,
    else the frames placed in it."""
    if getattr(doc, "frame", None) is not None:
        return [SELF]
    return [o.id for o in frame_occurrences(doc)]


def load_frame(doc, frame_oid: int):
    """The frame assembly to change: the one open in the window when it
    is, so the two cannot part ways, else read from its file."""
    if frame_oid == SELF:
        return doc
    occurrence = doc.occurrence(frame_oid)
    path = doc.component_path(occurrence) if occurrence else None
    if not path:
        raise ValueError("the frame's file cannot be found")
    return frames.open_frame(path)


def frame_placement(doc, frame_oid: int):
    """Where a frame sits here; None for the frame open itself."""
    occurrence = doc.occurrence(frame_oid) if frame_oid != SELF else None
    return occurrence.placement if occurrence is not None else None


def frame_location(doc, frame_oid: int):
    from OCP.TopLoc import TopLoc_Location
    placement = frame_placement(doc, frame_oid)
    return placement.location() if placement is not None \
        else TopLoc_Location()


def frame_changed(host, frame_doc) -> None:
    """The view brought up to a frame just changed: the frame itself
    built again when it is open, then the assembly round it."""
    live = getattr(host, "_live_document", None)
    if frame_doc is not host.assembly and live is not None \
            and frame_doc.path and live(frame_doc.path) is frame_doc:
        frame_doc.rebuild()
    host.assembly_ui.rebuild()


def member_shapes(doc, frame_oid: int) -> Dict[int, Any]:
    """{member id: its part where it sits in the view}, as last built."""
    try:
        frame_doc = load_frame(doc, frame_oid)
    except (ValueError, OSError):
        return {}
    fd = getattr(frame_doc, "frame", None)
    if fd is None:
        return {}
    location = frame_location(doc, frame_oid)
    out = {}
    for member in fd.members:
        occurrence = frame_doc.occurrence(member.occurrence) \
            if member.occurrence else None
        if occurrence is None or occurrence.suppressed \
                or not occurrence.visible:
            continue
        shape = occurrence.shape
        if shape is None or shape.IsNull():
            path = frame_doc.component_path(occurrence)
            try:
                shape = doc.library.shape(path) if path else None
            except Exception:
                shape = None
        if shape is None or shape.IsNull():
            continue
        out[member.id] = shape.Moved(location.Multiplied(
            occurrence.placement.location()))
    return out


def member_at(host, x: int, y: int,
              frame_oid: Optional[int] = None) -> Tuple[int, int]:
    """(frame, member) under a point in the view, the nearest to the eye;
    (0, 0) when no frame member is there."""
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    doc = host.assembly
    ray = host.viewport.ray_at(x, y) if doc is not None else None
    if ray is None:
        return 0, 0
    line = gp_Lin(gp_Pnt(*ray[0]), gp_Dir(*ray[1]))
    best = None
    for fid in ([frame_oid] if frame_oid is not None else frame_ids(doc)):
        for mid, shape in member_shapes(doc, fid).items():
            hit = IntCurvesFace_ShapeIntersector()
            hit.Load(shape, 1e-6)
            hit.Perform(line, -1e12, 1e12)
            for i in range(1, hit.NbPnt() + 1):
                w = hit.WParameter(i)
                if best is None or w < best[0]:
                    best = (w, fid, mid)
    return (best[1], best[2]) if best else (0, 0)


def member_of_occurrence(doc, occurrence_id: int) -> int:
    """The member a part placed in the frame open here is, or 0."""
    fd = getattr(doc, "frame", None)
    if fd is None:
        return 0
    return next((m.id for m in fd.members if m.occurrence == occurrence_id),
                0)


class PickingDialog(QtWidgets.QDialog):
    """A Frame Generator window that picks in the view: line or member
    segments under a click, or in a dragged box, and a see-through green
    picture of what it will make."""

    def __init__(self, host, parent=None) -> None:
        super().__init__(parent or host)
        self.host = host
        self.setModal(False)
        self._drawn: List[Any] = []
        self._ghosts: List[Any] = []
        self._lines: Dict[Any, Any] = {}
        self._reach: Dict[Any, float] = {}
        self._press: Optional[QtCore.QPoint] = None
        self._boxing = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(PREVIEW_MS)
        self._timer.timeout.connect(self.draw_preview)

    @property
    def doc(self):
        return self.host.assembly

    def _listen(self) -> None:
        viewport = getattr(self.host, "viewport", None)
        if viewport is not None:
            viewport.installEventFilter(self)
        self.finished.connect(lambda _r: self._close())

    def _member_segments(self, only_frame: int = 0) -> None:
        """Every member of the frames placed here as the line down its
        middle, to be picked like a sketch line."""
        self._lines, self._reach = {}, {}
        for fid in frame_ids(self.doc):
            if only_frame and fid != only_frame:
                continue
            try:
                frame_doc = load_frame(self.doc, fid)
                axes = frames.member_axes(frame_doc)
            except Exception:
                continue
            placement = frame_placement(self.doc, fid)
            for mid, (a, b, reach) in axes.items():
                key = ("m", fid, mid)
                self._lines[key] = (placement.apply_point(a),
                                    placement.apply_point(b)) \
                    if placement is not None else (a, b)
                self._reach[key] = reach

    def _screen(self, key):
        viewport = self.host.viewport
        a, b = self._lines[key]
        return viewport.project(a), viewport.project(b)

    def _pixels(self, mm: float) -> float:
        viewport = self.host.viewport
        try:
            span = viewport.view_span()
            return mm * viewport.width() / span if span > 0 else 0.0
        except Exception:
            return 0.0

    def line_at(self, x: int, y: int):
        """The line or member nearest a click in the view, within reach."""
        best, best_d = None, None
        for key in self._lines:
            (ax, ay), (bx, by) = self._screen(key)
            dx, dy = bx - ax, by - ay
            span = dx * dx + dy * dy
            t = 0.0 if span == 0 else max(0.0, min(1.0, (
                (x - ax) * dx + (y - ay) * dy) / span))
            d = ((x - (ax + t * dx)) ** 2 + (y - (ay + t * dy)) ** 2) ** 0.5
            reach = max(PICK_PIXELS, self._pixels(self._reach.get(key, 0.0)))
            if d <= reach and (best_d is None or d < best_d):
                best, best_d = key, d
        return best

    def lines_in_box(self, start: QtCore.QPoint, end: QtCore.QPoint) -> List:
        """What a dragged box takes: left to right those wholly in it,
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

    # what a click or a box does, for each window to say
    def clicked(self, key, pos: QtCore.QPoint) -> None:
        pass

    def boxed(self, keys: List) -> None:
        pass

    def picked_keys(self) -> List:
        return []

    def eventFilter(self, obj, event) -> bool:
        """While the window is open the left button picks; the view turns
        and pans as it always does with the others."""
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
                self.boxed(self.lines_in_box(self._press, pos))
            else:
                self.clicked(self.line_at(pos.x(), pos.y()), pos)
            self._press = None
            self._boxing = False
            return True
        return False

    def _redraw(self) -> None:
        """The picked lines lit up over everything."""
        viewport = getattr(self.host, "viewport", None)
        if viewport is None:
            return
        viewport.remove_drawn(self._drawn)
        self._drawn = []
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.gp import gp_Pnt
        with viewport.collecting() as drawn:
            for key in self.picked_keys():
                if key not in self._lines:
                    continue
                a, b = self._lines[key]
                if sum((a[i] - b[i]) ** 2 for i in range(3)) < 1e-18:
                    continue
                edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge()
                viewport.draw_shape(edge, C.accent, 4.0)
        viewport.on_top(drawn)
        self._drawn = drawn
        viewport.redraw()

    # -- the green picture -------------------------------------------------

    def schedule_preview(self) -> None:
        self._timer.start()

    def preview_solids(self) -> List[Any]:
        return []

    def draw_preview(self) -> int:
        """What the window will make, see-through green over the model.
        Returns how many solids it drew."""
        viewport = getattr(self.host, "viewport", None)
        if viewport is None:
            return 0
        self._clear_ghosts()
        try:
            solids = self.preview_solids()
        except Exception:
            solids = []
        with viewport.collecting() as drawn:
            for solid in solids:
                viewport.draw_ghost(solid, PREVIEW, 0.6)
        self._ghosts = drawn
        viewport.redraw()
        return len(solids)

    def _clear_ghosts(self) -> None:
        viewport = getattr(self.host, "viewport", None)
        if viewport is not None and self._ghosts:
            viewport.remove_drawn(self._ghosts)
        self._ghosts = []

    def _close(self) -> None:
        self._timer.stop()
        viewport = getattr(self.host, "viewport", None)
        if viewport is not None:
            viewport.removeEventFilter(self)
            viewport.remove_drawn(self._drawn)
            self._drawn = []
            self._clear_ghosts()
            viewport.redraw()


class InsertFrameDialog(PickingDialog):
    """Insert Frame: members on the lines picked in the view.  Given
    ``change`` (a frame's occurrence and members of it), Change Frame:
    the same window on members already made."""

    def __init__(self, host, parent=None,
                 change: Optional[Tuple[int, List[int]]] = None) -> None:
        super().__init__(host, parent)
        self.changing = change is not None
        self.frame_oid = change[0] if change else 0
        self.setWindowTitle("Change Frame" if self.changing
                            else "Insert Frame")
        self._picked: List[Any] = []
        self._initial: Dict[str, Any] = {}
        layout = QtWidgets.QVBoxLayout(self)

        # -- input geometry: what is picked in the view
        group = QtWidgets.QGroupBox("Frame Members" if self.changing
                                    else "Input Geometry")
        box = QtWidgets.QVBoxLayout(group)
        hint = QtWidgets.QLabel(
            "Click members in the view or the tree to add or drop them, "
            "or drag a box over them." if self.changing else
            "Click sketch lines in the view, or drag a box over them. Left "
            "to right takes what is inside, right to left what it touches. "
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
        if not self.changing:
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
            button.toggled.connect(lambda _on: self.schedule_preview())
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
        self.size.currentIndexChanged.connect(lambda _i:
                                              self.schedule_preview())
        for spin in (self.rotate, self.offset_a, self.offset_b):
            spin.valueChanged.connect(lambda _v: self.schedule_preview())
        self.mirror.toggled.connect(lambda _on: self.schedule_preview())
        self.merge.toggled.connect(lambda _on: self.schedule_preview())

        self._fill_categories()
        if self.changing:
            self._member_segments()
            self._picked = [("m", self.frame_oid, mid) for mid in change[1]
                            if ("m", self.frame_oid, mid) in self._lines]
            self._take_member_values()
        else:
            self.reload_lines()
        self._changed()
        self._listen()

    # -- the geometry ------------------------------------------------------

    def reload_lines(self) -> None:
        """Every line of every sketch that shows, where it sits now."""
        if self.changing:
            self._member_segments()
            self._picked = [k for k in self._picked if k in self._lines]
            self._changed()
            return
        controller = getattr(self.host, "assembly_ui", None)
        try:
            self._lines = controller.component_sketch_lines() \
                if controller is not None else {}
        except Exception:
            self._lines = {}
        self._reach = {}
        self._picked = [k for k in self._picked if k in self._lines]
        if not self._lines:
            self.message.setText("Place a skeleton first: a part with a "
                                 "sketch of lines in it, the sketch visible.")
        self._changed()

    def candidates(self) -> Dict[Any, Any]:
        return dict(self._lines)

    def picked(self) -> List[Any]:
        return list(self._picked)

    def picked_keys(self) -> List[Any]:
        return self.picked()

    def picked_members(self) -> List[int]:
        return [k[2] for k in self._picked]

    def toggle_line(self, key) -> None:
        if key in self._picked:
            self._picked.remove(key)
        else:
            if self.changing and self._picked and key[1] != self._picked[0][1]:
                # one frame at a time, as Change Frame works on one
                self.message.setText("Those are another frame's members.")
                return
            self._picked.append(key)
        self._changed()

    def add_lines(self, keys) -> None:
        for key in keys:
            if key not in self._picked:
                if self.changing and self._picked \
                        and key[1] != self._picked[0][1]:
                    continue
                self._picked.append(key)
        self._changed()

    def clicked(self, key, pos) -> None:
        if key is not None:
            self.toggle_line(key)

    def boxed(self, keys) -> None:
        self.add_lines(keys)

    def clear(self) -> None:
        self._picked = []
        self._changed()

    def _changed(self) -> None:
        n = len(self._picked)
        what = "member" if self.changing else "line"
        self.count.setText("No %ss selected" % what if not n else
                           "1 %s selected" % what if n == 1 else
                           "%d %ss selected" % (n, what))
        if self.changing and self._picked:
            self.frame_oid = self._picked[0][1]
        self._redraw()
        self.schedule_preview()

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
        self.size.blockSignals(True)
        self.size.clear()
        fid = self.family.currentData()
        fam = next((f for f in self._families_all if f.id == fid), None)
        if fam is not None:
            self.size.addItems(fam.sizes())
        self.size.blockSignals(False)
        self.schedule_preview()

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

    def values(self) -> Dict[str, Any]:
        """The member as the window has it now."""
        return {"family": self.family.currentData(),
                "size": self.size.currentText(), "anchor": self.anchor(),
                "offset_a": self.offset_a.value(),
                "offset_b": self.offset_b.value(),
                "rotate": self.rotate.value(),
                "mirror": self.mirror.isChecked(),
                "material": self.material.currentData() or ""}

    def _take_member_values(self) -> None:
        """Change Frame opens on the first picked member as it is; only
        what is then changed is changed, on every member picked."""
        if not self._picked:
            return
        try:
            fd = load_frame(self.doc, self.frame_oid).frame
        except Exception:
            return
        member = fd.member(self._picked[0][2])
        if member is None:
            return
        self.choose(member.family, member.size)
        self.anchor_buttons.get(member.anchor,
                                self.anchor_buttons["mc"]).setChecked(True)
        self.rotate.setValue(member.rotate)
        self.offset_a.setValue(member.offset_a)
        self.offset_b.setValue(member.offset_b)
        self.mirror.setChecked(member.mirror)
        index = self.material.findData(member.material)
        self.material.setCurrentIndex(max(0, index))
        self._initial = self.values()

    def changes(self) -> Dict[str, Any]:
        """What has been changed since the window opened on the members."""
        now = self.values()
        return {k: v for k, v in now.items() if self._initial.get(k) != v}

    # -- the green picture -------------------------------------------------

    def preview_solids(self) -> List[Any]:
        if not self._picked:
            return []
        if self.changing:
            frame_doc = load_frame(self.doc, self.frame_oid)
            solids = frames.member_world_solids(
                frame_doc, self.picked_members(), self.changes())
            location = frame_location(self.doc, self.frame_oid)
            return [s.Moved(location) for s in solids.values()]
        groups: Dict[Tuple[int, int], List[int]] = {}
        for oid, sid, lid in self._picked:
            groups.setdefault((oid, sid), []).append(lid)
        out = []
        v = self.values()
        for (oid, sid), line_ids in groups.items():
            occurrence = self.doc.occurrence(oid)
            if occurrence is None:
                continue
            out += frames.preview_solids(
                self.doc, occurrence, {sid: line_ids}, v["family"],
                v["size"], anchor=v["anchor"], offset_a=v["offset_a"],
                offset_b=v["offset_b"], rotate=v["rotate"],
                mirror=v["mirror"], merge=self.merge.isChecked())
        return out

    # -- doing it --------------------------------------------------------------

    def apply(self) -> bool:
        doc = self.doc
        picked = self.picked()
        if not picked:
            self.message.setText("Pick the members to change." if
                                 self.changing else
                                 "Pick the lines to put members on.")
            return False
        if self.changing:
            return self._apply_change()
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
            v = self.values()
            try:
                frame_doc, _occurrence, wrong = frames.insert(
                    doc, skeleton, sid, line_ids, v["family"], v["size"],
                    anchor=v["anchor"], offset_a=v["offset_a"],
                    offset_b=v["offset_b"], rotate=v["rotate"],
                    mirror=v["mirror"], merge=self.merge.isChecked(),
                    material=v["material"], frame_occurrence=existing)
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

    def _apply_change(self) -> bool:
        changes = self.changes()
        if not changes:
            self.message.setText("Nothing has been changed.")
            return True
        try:
            frame_doc = load_frame(self.doc, self.frame_oid)
            problems = frames.change_members(frame_doc, self.picked_members(),
                                             **changes)
        except (ValueError, KeyError, kernel.KernelError) as exc:
            self.message.setStyleSheet("color: %s;" % C.error)
            self.message.setText(str(exc))
            return False
        frame_changed(self.host, frame_doc)
        self._initial = self.values()
        self.message.setStyleSheet("" if not problems
                                   else "color: %s;" % C.error)
        n = len(self.picked_members())
        self.message.setText("; ".join(problems) if problems else
                             "%d member%s changed." % (n, "" if n == 1
                                                       else "s"))
        self.reload_lines()
        return not problems

    def _ok(self) -> None:
        if not self.picked() or self.apply():
            self.accept()


# -------------------------------------------------------- end treatments

# for each: its title, the picks it takes (a label each, the second the
# members the first are cut against), and what it asks for
TREATMENT_SETUP = {
    "miter": ("Miter", ["Frame members, two by two"], ),
    "corner": ("Corner Joint", ["Members to trim", "Member to trim to"]),
    "trim_face": ("Trim - Extend To Face", ["Frame members"]),
    "notch": ("Notch", ["Members to notch", "Notching member"]),
    "lengthen": ("Lengthen - Shorten Frame Member", ["Frame members"]),
}


class EndTreatmentDialog(PickingDialog):
    """Miter, Corner Joint, Trim - Extend To Face, Notch or Lengthen -
    Shorten: the members picked in the view (or the tree), what the
    treatment asks for, a green picture of the members as it leaves them,
    and OK, Apply and Cancel."""

    def __init__(self, host, kind: str, frame_oid: int = 0,
                 member_ids=(), parent=None) -> None:
        super().__init__(host, parent)
        if kind not in TREATMENT_SETUP:
            raise ValueError("there is no end treatment %s" % kind)
        self.kind = kind
        self.frame_oid = frame_oid
        title, slots = TREATMENT_SETUP[kind][0], TREATMENT_SETUP[kind][1]
        self.setWindowTitle(title)
        self.slots: List[List[int]] = [[] for _ in slots]
        self.active = 0
        self.face: Optional[Tuple[Tuple[float, ...], Tuple[float, ...]]] = None
        layout = QtWidgets.QVBoxLayout(self)

        group = QtWidgets.QGroupBox("Selection")
        box = QtWidgets.QVBoxLayout(group)
        self.slot_buttons: List[QtWidgets.QPushButton] = []
        picks = QtWidgets.QButtonGroup(self)
        for i, label in enumerate(slots):
            button = QtWidgets.QPushButton(label)
            button.setCheckable(True)
            button.setToolTip("Then click members in the view, or drag a "
                              "box over them")
            picks.addButton(button)
            button.clicked.connect(lambda _c, i=i: self.set_active(i))
            box.addWidget(button)
            self.slot_buttons.append(button)
        if kind == "trim_face":
            button = QtWidgets.QPushButton("Face")
            button.setCheckable(True)
            button.setToolTip("Then click a flat face in the view")
            picks.addButton(button)
            button.clicked.connect(lambda _c: self.set_active(len(slots)))
            box.addWidget(button)
            self.slot_buttons.append(button)
        self.slot_buttons[0].setChecked(True)
        layout.addWidget(group)

        group = QtWidgets.QGroupBox("Modify")
        form = QtWidgets.QFormLayout(group)
        self.gap = QtWidgets.QDoubleSpinBox()
        self.gap.setRange(-1000, 1000)
        self.gap.setDecimals(3)
        self.gap.setSuffix(" mm")
        self.split = QtWidgets.QCheckBox("Split the gap between both")
        self.split.setChecked(True)
        self.extend = QtWidgets.QCheckBox("Run the other on to the outside")
        self.extend.setChecked(True)
        self.side = QtWidgets.QComboBox()
        for label, key in (("At the end", "b"), ("At the start", "a"),
                           ("Both ends, half each", "both")):
            self.side.addItem(label, key)
        if kind == "miter":
            form.addRow("Gap", self.gap)
            form.addRow("", self.split)
        elif kind == "corner":
            form.addRow("Gap", self.gap)
            form.addRow("", self.extend)
        elif kind == "trim_face":
            self.gap.setToolTip("How far short of the face it stops")
            form.addRow("Offset", self.gap)
        elif kind == "notch":
            form.addRow("Gap", self.gap)
        elif kind == "lengthen":
            self.gap.setToolTip("Longer by this; less than 0 shortens")
            form.addRow("Extension", self.gap)
            form.addRow("", self.side)
        layout.addWidget(group)
        for w in (self.gap,):
            w.valueChanged.connect(lambda _v: self.schedule_preview())
        for w in (self.split, self.extend):
            w.toggled.connect(lambda _on: self.schedule_preview())
        self.side.currentIndexChanged.connect(lambda _i:
                                              self.schedule_preview())

        self.count = QtWidgets.QLabel("")
        layout.addWidget(self.count)
        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Apply
            | QtWidgets.QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.apply)
        layout.addWidget(buttons)

        self._member_segments()
        for mid in member_ids:
            if ("m", frame_oid, mid) in self._lines:
                self.slots[0].append(mid)
        if self.slots[0] and len(self.slots) > 1:
            # the tree's picks are the members to cut; next, what against
            self.set_active(1)
        self._changed()
        self._listen()

    def set_active(self, index: int) -> None:
        self.active = index
        if index < len(self.slot_buttons):
            self.slot_buttons[index].setChecked(True)

    def picked_keys(self) -> List[Any]:
        return [("m", self.frame_oid, mid) for slot in self.slots
                for mid in slot]

    def _take(self, key) -> None:
        if key is None or key[0] != "m":
            return
        if self.frame_oid and key[1] != self.frame_oid:
            self.message.setText("Those are another frame's members: an "
                                 "end treatment joins members of one frame.")
            return
        self.frame_oid = key[1]
        slot = self.slots[self.active]
        if key[2] in slot:
            slot.remove(key[2])
        else:
            for other in self.slots:
                if key[2] in other:
                    other.remove(key[2])
            slot.append(key[2])

    def clicked(self, key, pos) -> None:
        if self.kind == "trim_face" and self.active == len(self.slots):
            self.pick_face(pos.x(), pos.y())
            return
        self._take(key)
        self._changed()

    def boxed(self, keys) -> None:
        if self.active >= len(self.slots):
            return
        for key in keys:
            if key[0] == "m" and key[2] not in self.slots[self.active]:
                self._take(key)
        self._changed()

    def pick(self, member_ids, slot: int = 0) -> None:
        """Members put in a pick, as clicking them would."""
        self.set_active(slot)
        for mid in member_ids:
            frame_oid = self.frame_oid or next(
                (k[1] for k in self._lines if k[0] == "m" and k[2] == mid), 0)
            self._take(("m", frame_oid, mid))
        self._changed()

    def pick_face(self, x: int, y: int) -> bool:
        """The flat face under a click, from anything placed here, as the
        plane to trim or extend to, in the frame's coordinates."""
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Plane
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        ray = self.host.viewport.ray_at(x, y)
        if ray is None:
            return False
        origin, direction = ray
        line = gp_Lin(gp_Pnt(*origin), gp_Dir(*direction))
        best = None
        for occurrence in self.doc.occurrences:
            if occurrence.suppressed or not occurrence.visible:
                continue
            shape = occurrence.placed()
            if shape is None:
                continue
            hit = IntCurvesFace_ShapeIntersector()
            hit.Load(shape, 1e-6)
            hit.Perform(line, -1e12, 1e12)
            for i in range(1, hit.NbPnt() + 1):
                w = hit.WParameter(i)
                if best is None or w < best[0]:
                    best = (w, hit.Face(i))
        if best is None:
            self.message.setText("There is no face there.")
            return False
        surface = BRepAdaptor_Surface(best[1])
        if surface.GetType() != GeomAbs_Plane:
            self.message.setText("That face is not flat: pick a flat one.")
            return False
        plane = surface.Plane()
        p, n = plane.Location(), plane.Axis().Direction()
        self.set_face((p.X(), p.Y(), p.Z()), (n.X(), n.Y(), n.Z()))
        return True

    def set_face(self, point, normal) -> None:
        """The plane to trim or extend to, given in the assembly."""
        import numpy as np
        placement = frame_placement(self.doc, self.frame_oid) \
            if self.frame_oid else None
        if placement is not None:
            m = placement.matrix()
            pos = np.asarray(placement.position, float)
            point = tuple(float(c) for c in m.T @ (np.asarray(point, float)
                                                   - pos))
            normal = tuple(float(c) for c in m.T @ np.asarray(normal, float))
        self.face = (tuple(point), tuple(normal))
        self._changed()

    def _changed(self) -> None:
        parts = []
        for label, slot in zip(TREATMENT_SETUP[self.kind][1], self.slots):
            parts.append("%s: %d" % (label, len(slot)))
        if self.kind == "trim_face":
            parts.append("Face: %s" % ("picked" if self.face else "none"))
        self.count.setText("   ".join(parts))
        self._redraw()
        self.schedule_preview()

    def treatment(self) -> Tuple[List[int], List[int], Dict[str, Any]]:
        """The members, the ones they are cut against, and the values."""
        gap = self.gap.value()
        members = list(self.slots[0])
        others = list(self.slots[1]) if len(self.slots) > 1 else []
        params: Dict[str, Any] = {}
        if self.kind == "miter":
            params = {"gap": gap, "split": self.split.isChecked()}
        elif self.kind == "corner":
            params = {"gap": gap, "extend": self.extend.isChecked()}
        elif self.kind == "trim_face":
            params = {"offset": gap}
            if self.face is not None:
                params["point"] = list(self.face[0])
                params["normal"] = list(self.face[1])
        elif self.kind == "notch":
            params = {"gap": gap}
        elif self.kind == "lengthen":
            params = {"amount": gap, "side": self.side.currentData()}
        return members, others, params

    def preview_solids(self) -> List[Any]:
        members, others, params = self.treatment()
        if not members or not self.frame_oid:
            return []
        ready = {"miter": len(members) >= 2 and not len(members) % 2,
                 "corner": bool(others), "notch": bool(others),
                 "trim_face": "point" in params}.get(self.kind, True)
        frame_doc = load_frame(self.doc, self.frame_oid)
        extra = frames.Treatment(id=0, kind=self.kind, members=members,
                                 others=others, params=params) \
            if ready else None
        solids = frames.member_world_solids(frame_doc, members + others,
                                            extra=extra)
        location = frame_location(self.doc, self.frame_oid)
        return [s.Moved(location) for s in solids.values()]

    def apply(self) -> bool:
        members, others, params = self.treatment()
        if not members:
            self.message.setText("Pick the members first.")
            return False
        try:
            frame_doc = load_frame(self.doc, self.frame_oid)
            _t, problems = frames.add_treatment(frame_doc, self.kind,
                                                members, others, **params)
        except (ValueError, KeyError, kernel.KernelError) as exc:
            self.message.setStyleSheet("color: %s;" % C.error)
            self.message.setText(str(exc))
            return False
        frame_changed(self.host, frame_doc)
        self.message.setStyleSheet("" if not problems
                                   else "color: %s;" % C.error)
        self.message.setText("; ".join(problems) if problems else
                             "%s done." % self.windowTitle())
        self.slots = [[] for _ in self.slots]
        self.face = None
        self._member_segments()
        self.set_active(0)
        self._changed()
        return not problems

    def _ok(self) -> None:
        if not self.slots[0] or self.apply():
            self.accept()


def remove_end_treatments(host, frame_oid: int, member_ids) -> int:
    """Remove End Treatments on members picked in the tree."""
    frame_doc = load_frame(host.assembly, frame_oid)
    gone = frames.remove_treatments(frame_doc, list(member_ids))
    frame_changed(host, frame_doc)
    return gone


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
