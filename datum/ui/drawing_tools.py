"""Annotate tools on a drawing, as Inventor's: each picks on a view, puts
one thing on the sheet, and stays on for the next until Esc.

Centre Mark takes a circle; Centerline two points, a centre line between
them; Centerline Bisector two lines, the centre line halfway between;
Hole and Thread a hole, then where its note goes; Text a place and Leader
Text an arrow point and a place, both through Format Text.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import drawing as dwg
from ..core import views as viewgen
from ..core.drawing import Annotation
from . import drawpick

OVERHANG = 2.0      # how far a centre line runs past what it marks, mm


class PickTool:
    """Picks on a view, one kind of thing at a time, for an annotation."""

    PICK_PIXELS = 8.0
    kinds: Tuple[str, ...] = (drawpick.CIRCLE,)
    wanted = 1
    name = ""
    prompts: Tuple[str, ...] = ("",)

    def __init__(self, controller, sheet) -> None:
        self.controller = controller
        self.sheet = sheet
        self.picks: List[drawpick.Item] = []
        self.hot: Optional[drawpick.Item] = None
        self.cursor = None
        self._scale = 1.0
        self.say()

    # -- picking ----------------------------------------------------------

    def _under(self, point):
        only = self.picks[0].view if self.picks else None
        return drawpick.nearest(self.sheet, point,
                                self.PICK_PIXELS / max(self._scale, 1e-9),
                                only_view=only, kinds=self.kinds)

    def press(self, point, device) -> None:
        self._scale = self.controller.canvas.layout().scale
        item = self._under(point)
        if item is None or any(item.same(p) for p in self.picks):
            return
        self.picks.append(item)
        if len(self.picks) >= self.wanted:
            self.make(point)
            self.picks = []
        self.say()
        self.controller.canvas.update()

    def move(self, point, device, held: bool) -> None:
        self._scale = self.controller.canvas.layout().scale
        self.cursor = (point[0], point[1])
        self.hot = self._under(point)

    def release(self, point, device) -> None:
        pass

    def right_click(self, point, device) -> bool:
        if self.picks:
            self.picks = []
            self.say()
            return True
        return False

    def escape(self) -> bool:
        if self.picks:
            self.picks = []
            self.say()
            self.controller.canvas.update()
            return True
        return False

    def cursor_shape(self, point, device):
        return QtCore.Qt.CrossCursor

    def say(self) -> None:
        host = self.controller.host
        host.status_message.setStyleSheet("")
        host.status_message.setText("%s: %s Esc when done." % (
            self.name, self.prompts[min(len(self.picks),
                                        len(self.prompts) - 1)]))

    def close(self) -> None:
        pass

    # -- drawing what is picked ---------------------------------------------

    def paint(self, painter: QtGui.QPainter, layout) -> None:
        self._scale = layout.scale
        for item in self.picks:
            self._paint_item(painter, layout, item, "#3b82d6", 2.4)
        if self.hot is not None and not any(self.hot.same(p)
                                            for p in self.picks):
            self._paint_item(painter, layout, self.hot, "#e08a1e", 2.0)

    def _paint_item(self, painter, layout, item, colour, width) -> None:
        view = self.sheet.view(item.view)
        if view is None:
            return

        def at(p):
            return QtCore.QPointF(*layout.to_device(view.x + p[0],
                                                    view.y + p[1]))
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(QtGui.QColor(colour), width))
        painter.setBrush(QtCore.Qt.NoBrush)
        if item.kind == drawpick.LINE:
            painter.drawLine(at(item.a), at(item.b))
        elif item.kind == drawpick.CIRCLE:
            r = item.radius * layout.scale
            painter.drawEllipse(at(item.a), r, r)
        else:
            painter.setBrush(QtGui.QColor(colour))
            painter.drawEllipse(at(item.a), 3.5, 3.5)
        painter.restore()

    # -- what it makes ------------------------------------------------------

    def make(self, point) -> None:
        raise NotImplementedError

    def _add(self, note: Annotation) -> None:
        doc = self.controller.document
        doc.push_undo()
        doc.add_annotation(self.sheet, note)
        doc.modified = True
        self.controller.canvas.update()
        self.controller.browser.refresh()
        self.controller.host.update_title()


class CentreMarkTool(PickTool):
    """Inventor's Center Mark: click a circle or an arc, a cross on it."""

    name = "Center Mark"
    prompts = ("click a circle or an arc to mark its centre.",)

    def make(self, point) -> None:
        circle = self.picks[0]
        self._add(Annotation(kind=dwg.CENTRE_MARK, view=circle.view,
                             points=[list(circle.a)],
                             value=circle.radius + OVERHANG))


class CentrelineTool(PickTool):
    """Inventor's Centerline: two points, a centre line between them."""

    name = "Centerline"
    kinds = (drawpick.POINT, drawpick.CIRCLE)
    wanted = 2
    prompts = ("click the first point, or a circle for its centre.",
               "click the second point.")

    def make(self, point) -> None:
        a, b = self.picks[0].a, self.picks[1].a
        length = math.dist(a, b)
        if length < 1e-6:
            return
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        self._add(Annotation(
            kind=dwg.CENTRELINE, view=self.picks[0].view,
            points=[[a[0] - ux * OVERHANG, a[1] - uy * OVERHANG],
                    [b[0] + ux * OVERHANG, b[1] + uy * OVERHANG]]))


def bisector(first, second):
    """The centre line halfway between two lines: down the middle of two
    parallel ones, along the overlap and a little past; between two that
    meet, along the line halving their angle."""
    (a0, a1), (b0, b1) = (first.a, first.b), (second.a, second.b)
    ua = (a1[0] - a0[0], a1[1] - a0[1])
    la = math.hypot(*ua)
    lb = math.dist(b0, b1)
    if la < 1e-9 or lb < 1e-9:
        return None
    ua = (ua[0] / la, ua[1] / la)
    ub = ((b1[0] - b0[0]) / lb, (b1[1] - b0[1]) / lb)
    if ua[0] * ub[0] + ua[1] * ub[1] < 0:
        b0, b1 = b1, b0
        ub = (-ub[0], -ub[1])
    cross = ua[0] * ub[1] - ua[1] * ub[0]
    if abs(cross) < 1e-6:
        # parallel: the line down the middle, over both of them
        mid = ((a0[0] + b0[0]) / 2, (a0[1] + b0[1]) / 2)
        ts = [(p[0] - mid[0]) * ua[0] + (p[1] - mid[1]) * ua[1]
              for p in (a0, a1, b0, b1)]
        lo, hi = min(ts) - OVERHANG, max(ts) + OVERHANG
        return ([mid[0] + ua[0] * lo, mid[1] + ua[1] * lo],
                [mid[0] + ua[0] * hi, mid[1] + ua[1] * hi])
    # meeting: from where they meet, along the halving direction
    d = (b0[0] - a0[0], b0[1] - a0[1])
    t = (d[0] * ub[1] - d[1] * ub[0]) / cross
    meet = (a0[0] + ua[0] * t, a0[1] + ua[1] * t)
    half = (ua[0] + ub[0], ua[1] + ub[1])
    lh = math.hypot(*half)
    half = (half[0] / lh, half[1] / lh)
    reach = max(la, lb)
    return ([meet[0], meet[1]],
            [meet[0] + half[0] * reach, meet[1] + half[1] * reach])


class BisectorTool(PickTool):
    """Inventor's Centerline Bisector: two lines, the centre line between."""

    name = "Centerline Bisector"
    kinds = (drawpick.LINE,)
    wanted = 2
    prompts = ("click the first line.", "click the second line.")

    def make(self, point) -> None:
        found = bisector(self.picks[0], self.picks[1])
        if found is not None:
            self._add(Annotation(kind=dwg.CENTRELINE,
                                 view=self.picks[0].view,
                                 points=[found[0], found[1]]))


SET_SPACING = 7.0     # between the lines of a baseline set, mm on the sheet


def set_point(item) -> Tuple[float, float]:
    """Where one pick of a dimension set stands: a corner where it is, a
    circle at its centre, a line at its middle."""
    if item.kind == drawpick.LINE:
        return ((item.a[0] + item.b[0]) / 2.0, (item.a[1] + item.b[1]) / 2.0)
    return (item.a[0], item.a[1])


def dimension_set(kind: str, points, place) -> List[Annotation]:
    """Inventor's Baseline Set, Chain Set and Ordinate Set, worked out.

    ``points`` are the picks in the view's own millimetres, the first one
    the datum for a baseline or an ordinate set; ``place`` is where the
    set was dropped.  Dropped above or below the picks, the set measures
    across the page; beside them, up it.  Returns the dimensions, each a
    plain linear or ordinate one that can be moved and edited on its own.
    """
    if len(points) < 2 and kind != dwg.ORDINATE:
        return []
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    over = not (min(ys) <= place[1] <= max(ys))      # above or below
    aside = not (min(xs) <= place[0] <= max(xs))     # left or right
    if over != aside:
        axis = "x" if over else "y"
    else:
        # dropped in a corner, or among them: the way they spread most
        axis = ("x" if max(xs) - min(xs) >= max(ys) - min(ys) else "y")
    k = 0 if axis == "x" else 1
    other = 1 - k
    datum = points[0]
    rest = sorted(points[1:], key=lambda p: abs(p[k] - datum[k]))
    out: List[Annotation] = []
    if kind == "baseline":
        sign = 1.0 if place[other] >= datum[other] else -1.0
        for index, p in enumerate(rest):
            if abs(p[k] - datum[k]) < 1e-6:
                continue
            reach = place[other] - datum[other] + sign * SET_SPACING * index
            offset = [0.0, reach] if axis == "x" else [reach, 0.0]
            out.append(Annotation(kind=dwg.LINEAR, points=[list(datum),
                                                           list(p)],
                                  offset=offset, axis=axis))
    elif kind == "chain":
        ordered = sorted(points, key=lambda p: p[k])
        for p, q in zip(ordered, ordered[1:]):
            if abs(q[k] - p[k]) < 1e-6:
                continue
            reach = place[other] - p[other]
            offset = [0.0, reach] if axis == "x" else [reach, 0.0]
            out.append(Annotation(kind=dwg.LINEAR, points=[list(p), list(q)],
                                  offset=offset, axis=axis))
    elif kind == dwg.ORDINATE:
        for p in [datum] + rest:
            reach = place[other] - p[other]
            offset = [0.0, reach] if axis == "x" else [reach, 0.0]
            out.append(Annotation(kind=dwg.ORDINATE,
                                  points=[list(datum), list(p)],
                                  offset=offset, axis=axis))
    return out


class DimensionSetTool(PickTool):
    """Inventor's Baseline, Chain and Ordinate: click the corners, holes
    or edges in order, the first one the datum, right-click Continue, then
    click where the set goes.  Stays on for the next set until Esc."""

    kinds = (drawpick.POINT, drawpick.CIRCLE, drawpick.LINE)
    wanted = 10 ** 6
    titles = {"baseline": "Baseline", "chain": "Chain",
              dwg.ORDINATE: "Ordinate"}

    def __init__(self, controller, sheet, kind: str) -> None:
        self.kind = kind
        self.name = self.titles.get(kind, "Dimension Set")
        self.placing = False
        super().__init__(controller, sheet)

    def say(self) -> None:
        host = self.controller.host
        host.status_message.setStyleSheet("")
        if self.placing:
            text = "click where the set goes."
        elif not self.picks:
            text = ("click the %s, then the rest in turn."
                    % ("origin" if self.kind == dwg.ORDINATE else
                       "first corner, hole or edge"))
        else:
            text = ("%d picked. Click more, or right-click to Continue."
                    % len(self.picks))
        host.status_message.setText("%s: %s Esc when done." % (self.name,
                                                               text))

    def press(self, point, device) -> None:
        self._scale = self.controller.canvas.layout().scale
        if self.placing:
            self._place(point)
            return
        super().press(point, device)

    def right_click(self, point, device) -> bool:
        # Inventor's Continue: the picks are done, place the set
        if self.picks and not self.placing:
            needed = 1 if self.kind == dwg.ORDINATE else 2
            if len(self.picks) >= needed:
                self.placing = True
                self.say()
                return True
        return super().right_click(point, device)

    def escape(self) -> bool:
        if self.placing:
            self.placing = False
            self.say()
            return True
        return super().escape()

    def _place(self, point) -> None:
        view = self.sheet.view(self.picks[0].view)
        if view is None:
            return
        local = (point[0] - view.x, point[1] - view.y)
        made = dimension_set(self.kind,
                             [set_point(p) for p in self.picks], local)
        self.picks = []
        self.placing = False
        if made:
            doc = self.controller.document
            doc.push_undo()
            for note in made:
                note.view = view.id
                self.controller._anchor_exact(doc, self.sheet, view, note)
                note.value = note.measure()
                doc.add_annotation(self.sheet, note)
            doc.modified = True
            self.controller.canvas.update()
            self.controller.browser.refresh()
            self.controller.host.update_title()
        self.say()

    def paint(self, painter, layout) -> None:
        super().paint(painter, layout)
        if not self.placing or self.cursor is None or not self.picks:
            return
        view = self.sheet.view(self.picks[0].view)
        if view is None:
            return
        local = (self.cursor[0] - view.x, self.cursor[1] - view.y)
        preview = dimension_set(self.kind,
                                [set_point(p) for p in self.picks], local)
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#3b82d6"), 1.2,
                                  QtCore.Qt.DashLine))
        for note in preview:
            if note.kind == dwg.ORDINATE:
                p = note.points[1]
                end = ((p[0], p[1] + note.offset[1]) if note.axis == "x"
                       else (p[0] + note.offset[0], p[1]))
                ends = (p, end)
            else:
                a, b, _label = dwg.dimension_line(note)
                ends = (a, b)
            painter.drawLine(
                QtCore.QPointF(*layout.to_device(view.x + ends[0][0],
                                                 view.y + ends[0][1])),
                QtCore.QPointF(*layout.to_device(view.x + ends[1][0],
                                                 view.y + ends[1][1])))
        painter.restore()


class RetrieveTool:
    """Inventor's Retrieve Model Annotations: click a view, then tick
    which of the part's own dimensions and notes come onto it."""

    name = "Retrieve"

    def __init__(self, controller, sheet) -> None:
        self.controller = controller
        self.sheet = sheet
        self.say()

    def say(self) -> None:
        host = self.controller.host
        host.status_message.setStyleSheet("")
        host.status_message.setText(
            "Retrieve: click a view to bring the part's model dimensions "
            "and notes onto it. Esc when done.")

    def view_at(self, point):
        for view in reversed(self.sheet.views):
            projection = view.projection
            if projection is None:
                continue
            box = projection.box
            local = (point[0] - view.x, point[1] - view.y)
            if box[0] - 2 <= local[0] <= box[2] + 2 and \
                    box[1] - 2 <= local[1] <= box[3] + 2:
                return view
        return None

    def press(self, point, device) -> None:
        view = self.view_at(point)
        if view is None:
            return
        found = self.controller.retrieve_candidates(self.sheet, view)
        host = self.controller.host
        if not found:
            host.status_message.setText(
                "Retrieve: this view shows none of the part's model "
                "annotations at their true size. Try a view that looks at "
                "them square on.")
            return
        dialog = RetrieveDialog(host, found)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        made = self.controller.retrieve_into(self.sheet, view,
                                             dialog.chosen())
        host.status_message.setText(
            "Retrieve: %d brought onto %s. Click another view, or Esc."
            % (made, view.label))

    def move(self, point, device, held: bool) -> None:
        pass

    def release(self, point, device) -> None:
        pass

    def right_click(self, point, device) -> bool:
        return False

    def escape(self) -> bool:
        return False

    def cursor_shape(self, point, device):
        return QtCore.Qt.PointingHandCursor

    def paint(self, painter, layout) -> None:
        pass

    def close(self) -> None:
        pass


class RetrieveDialog(QtWidgets.QDialog):
    """Which model annotations to bring onto the view, all ticked."""

    def __init__(self, parent, found) -> None:
        super().__init__(parent)
        self.setWindowTitle("Retrieve Model Annotations")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "The part's own dimensions and notes this view shows at their "
            "true size:", self))
        self.list = QtWidgets.QListWidget(self)
        for model_note, note in found:
            item = QtWidgets.QListWidgetItem(
                "%s   %s" % (model_note.label(), model_note.display))
            item.setData(QtCore.Qt.UserRole, model_note.id)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def chosen(self):
        return [self.list.item(i).data(QtCore.Qt.UserRole)
                for i in range(self.list.count())
                if self.list.item(i).checkState() == QtCore.Qt.Checked]


class SymbolTool(PickTool):
    """Inventor's Surface Texture, Feature Control Frame and Datum
    Identifier: click the edge, corner or hole it belongs to, set what it
    says, and it stands there.  Stays on for the next until Esc."""

    kinds = (drawpick.LINE, drawpick.POINT, drawpick.CIRCLE)
    titles = {dwg.SURFACE: "Surface Texture",
              dwg.FCF: "Feature Control Frame",
              dwg.DATUM_ID: "Datum Identifier",
              dwg.WELD: "Weld Symbol"}

    def __init__(self, controller, sheet, kind: str) -> None:
        self.kind = kind
        self.name = self.titles.get(kind, "Symbol")
        self.prompts = ("click the edge it is about.",)
        super().__init__(controller, sheet)

    def make(self, point) -> None:
        item = self.picks[0]
        view = self.sheet.view(item.view)
        if view is None:
            return
        local = (point[0] - view.x, point[1] - view.y)
        if item.kind == drawpick.LINE:
            on = drawpick.foot(local, item.a, item.b)
        elif item.kind == drawpick.CIRCLE:
            dx, dy = local[0] - item.a[0], local[1] - item.a[1]
            d = math.hypot(dx, dy) or 1.0
            on = (item.a[0] + dx / d * item.radius,
                  item.a[1] + dy / d * item.radius)
        else:
            on = item.a
        values = self.controller.symbol_values(self.kind, self.sheet)
        if values is None:
            return
        self.controller.add_symbol(self.sheet, view, self.kind, on, **values)


class SymbolDialog(QtWidgets.QDialog):
    """What a symbol says: a surface's roughness and process, a frame's
    characteristic, tolerance and datums, or a datum's letter."""

    def __init__(self, parent, kind: str, letter: str = "A") -> None:
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle(SymbolTool.titles.get(kind, "Symbol"))
        form = QtWidgets.QFormLayout(self)
        if kind == dwg.SURFACE:
            self.process = QtWidgets.QComboBox(self)
            for key, label in ((dwg.SURFACE_ANY, "Basic"),
                               (dwg.SURFACE_REMOVAL,
                                "Material removal required"),
                               (dwg.SURFACE_NO_REMOVAL,
                                "Material removal prohibited")):
                self.process.addItem(label, key)
            self.process.setCurrentIndex(1)
            self.value = QtWidgets.QLineEdit("Ra 3.2", self)
            form.addRow("Surface type", self.process)
            form.addRow("Roughness", self.value)
        elif kind == dwg.FCF:
            self.characteristic = QtWidgets.QComboBox(self)
            for key, label, glyph in dwg.GDT:
                self.characteristic.addItem("%s  %s" % (glyph, label), key)
            self.characteristic.setCurrentIndex(
                [k for k, _l, _g in dwg.GDT].index("position"))
            self.diameter = QtWidgets.QCheckBox("\u00d8 zone", self)
            self.diameter.setChecked(True)
            self.tolerance = QtWidgets.QLineEdit("0.1", self)
            self.datums = [QtWidgets.QLineEdit(t, self)
                           for t in ("A", "B", "")]
            form.addRow("Characteristic", self.characteristic)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.diameter)
            row.addWidget(self.tolerance)
            form.addRow("Tolerance", row)
            for name, edit in zip(("Primary", "Secondary", "Tertiary"),
                                  self.datums):
                edit.setMaxLength(4)
                form.addRow("%s datum" % name, edit)
        elif kind == dwg.WELD:
            self.weld = QtWidgets.QComboBox(self)
            for key, label in dwg.WELDS:
                self.weld.addItem(label, key)
            self.size = QtWidgets.QLineEdit("a4", self)
            self.length = QtWidgets.QLineEdit("", self)
            self.length.setPlaceholderText("all along")
            self.other = QtWidgets.QCheckBox("On the other side", self)
            self.around = QtWidgets.QCheckBox("All round", self)
            self.field = QtWidgets.QCheckBox("Welded on site", self)
            form.addRow("Weld", self.weld)
            form.addRow("Size", self.size)
            form.addRow("Length", self.length)
            for box in (self.other, self.around, self.field):
                form.addRow("", box)
        else:
            self.letter = QtWidgets.QLineEdit(letter, self)
            self.letter.setMaxLength(3)
            form.addRow("Datum", self.letter)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        if self.kind == dwg.SURFACE:
            return {"text": self.value.text().strip(),
                    "shape": self.process.currentData()}
        if self.kind == dwg.FCF:
            zone = ("\u00d8" if self.diameter.isChecked() else "") + \
                self.tolerance.text().strip()
            cells = [self.characteristic.currentData(), zone]
            cells += [d.text().strip().upper() for d in self.datums
                      if d.text().strip()]
            return {"text": "|".join(cells)}
        if self.kind == dwg.WELD:
            flags = [name for name, box in (("other", self.other),
                                            ("all_around", self.around),
                                            ("field", self.field))
                     if box.isChecked()]
            return {"text": "|".join([self.weld.currentData(),
                                      self.size.text().strip(),
                                      self.length.text().strip(),
                                      ",".join(flags)])}
        return {"text": self.letter.text().strip().upper() or "A"}


def view_under(sheet, point):
    """The view whose box a sheet point is in, and the point in that view's
    own unbroken millimetres; the top one where they overlap."""
    for view in reversed(sheet.views):
        projection = view.projection
        if projection is None:
            continue
        box = projection.box
        local = dwg.unshown(view, (point[0] - view.x, point[1] - view.y))
        if box[0] - 3 <= local[0] <= box[2] + 3 and \
                box[1] - 3 <= local[1] <= box[3] + 3:
            return view, local
    return None


def paint_view_box(painter, layout, view, colour="#3b82d6") -> None:
    """A view picked for a tool: its box, dashed round it."""
    if view is None or view.projection is None:
        return
    box = view.projection.box
    lo = dwg.shown(view, (box[0], box[1]))
    hi = dwg.shown(view, (box[2], box[3]))
    painter.save()
    painter.setPen(QtGui.QPen(QtGui.QColor(colour), 1.2, QtCore.Qt.DashLine))
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawRect(QtCore.QRectF(
        QtCore.QPointF(*layout.to_device(view.x + lo[0] - 3,
                                         view.y + lo[1] - 3)),
        QtCore.QPointF(*layout.to_device(view.x + hi[0] + 3,
                                         view.y + hi[1] + 3))).normalized())
    painter.restore()


class ViewTool:
    """A tool that starts by clicking a view's box, the way Inventor's
    view commands do, and goes on from there."""

    name = ""

    def __init__(self, controller, sheet) -> None:
        self.controller = controller
        self.sheet = sheet
        self.view = None
        self.cursor = None
        # a view already selected is the one meant
        chosen = controller.canvas.selected_views
        if chosen:
            self.view = sheet.view(chosen[-1])
            if self.view is not None and self.view.projection is None:
                self.view = None
        self.say()

    def prompt(self) -> str:
        return ""

    def say(self) -> None:
        host = self.controller.host
        host.status_message.setStyleSheet("")
        host.status_message.setText("%s: %s Esc to step back."
                                    % (self.name, self.prompt()))

    def local(self, point):
        view = self.view
        return dwg.unshown(view, (point[0] - view.x, point[1] - view.y))

    def sheet_point(self, local):
        view = self.view
        at = dwg.shown(view, local)
        return (view.x + at[0], view.y + at[1])

    def press(self, point, device) -> None:
        if self.view is None:
            found = view_under(self.sheet, point)
            if found is not None:
                self.view = found[0]
                self.say()
                self.controller.canvas.update()
            return
        self.pressed(point)
        self.say()
        self.controller.canvas.update()

    def pressed(self, point) -> None:
        raise NotImplementedError

    def move(self, point, device, held: bool) -> None:
        self.cursor = (point[0], point[1])

    def release(self, point, device) -> None:
        pass

    def right_click(self, point, device) -> bool:
        return self.escape()

    def back(self) -> bool:
        """One step back; False when there was nothing to undo."""
        if self.view is not None:
            self.view = None
            return True
        return False

    def escape(self) -> bool:
        if self.back():
            self.say()
            self.controller.canvas.update()
            return True
        return False

    def cursor_shape(self, point, device):
        return QtCore.Qt.CrossCursor

    def paint(self, painter, layout) -> None:
        if self.view is None:
            if self.cursor is not None:
                found = view_under(self.sheet, self.cursor)
                if found is not None:
                    paint_view_box(painter, layout, found[0], "#e08a1e")
            return
        paint_view_box(painter, layout, self.view)

    def close(self) -> None:
        pass


def snapped_angle(sheet, view, angle: float, tolerance: float = 3.0) -> float:
    """A direction in degrees, pulled onto the nearest 45 or onto square
    from an edge of the view when it is within a few degrees of one."""
    wanted = [k * 45.0 for k in range(8)]
    for item in drawpick.items(view):
        if item.kind != drawpick.LINE:
            continue
        edge = math.degrees(math.atan2(item.b[1] - item.a[1],
                                       item.b[0] - item.a[0]))
        wanted += [edge + 90.0, edge - 90.0]
    best, gap = angle, tolerance
    for target in wanted:
        off = (angle - target + 180.0) % 360.0 - 180.0
        if abs(off) < gap:
            best, gap = target, abs(off)
    return best


class AuxiliaryTool(ViewTool):
    """Inventor's Auxiliary, the way the Projected view is placed: click a
    view, then drag out from it in any direction and click.  The new view
    looks at the part from that side, so a sloping face can be seen square
    on; the direction snaps square to the view's edges and to 45s."""

    name = "Auxiliary View"

    def prompt(self) -> str:
        if self.view is None:
            return "click the view to project from."
        return "move out from it in the direction to look, and click."

    def spot(self, point):
        """Where the view goes for a cursor here, and the angle handed to
        the auxiliary view: square to the direction it was dragged."""
        parent = self.view
        dx, dy = point[0] - parent.x, point[1] - parent.y
        reach = math.hypot(dx, dy)
        if reach < 1e-6:
            return None
        heading = snapped_angle(self.sheet, parent,
                                math.degrees(math.atan2(dy, dx)))
        rad = math.radians(heading)
        x = parent.x + math.cos(rad) * reach
        y = parent.y + math.sin(rad) * reach
        return (x, y), heading - 90.0

    def pressed(self, point) -> None:
        found = self.spot(point)
        if found is None:
            return
        (x, y), angle = found
        self.controller.create_auxiliary(self.view.id, x, y, angle)

    def paint(self, painter, layout) -> None:
        super().paint(painter, layout)
        if self.view is None or self.cursor is None:
            return
        found = self.spot(self.cursor)
        if found is None:
            return
        (x, y), _angle = found
        parent = self.view
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#3b82d6"), 1.2,
                                  QtCore.Qt.DashLine))
        painter.drawLine(QtCore.QPointF(*layout.to_device(parent.x,
                                                          parent.y)),
                         QtCore.QPointF(*layout.to_device(x, y)))
        box = parent.projection.box
        w = (box[2] - box[0]) / 2.0
        h = (box[3] - box[1]) / 2.0
        r = max(6.0, min(w, h))
        painter.drawRect(QtCore.QRectF(
            QtCore.QPointF(*layout.to_device(x - r, y + r)),
            QtCore.QPointF(*layout.to_device(x + r, y - r))).normalized())
        painter.restore()


class SectionTool(ViewTool):
    """Inventor's Section: click the view to cut, then draw the cut line
    as in a sketch, two clicks at any angle, then drag the new view out
    to one side of the line and click.  The section is only as wide as
    the line, so a short line makes a small section."""

    name = "Section View"
    SNAP_PIXELS = 8.0

    def __init__(self, controller, sheet) -> None:
        self.points: List[Tuple[float, float]] = []
        super().__init__(controller, sheet)

    def prompt(self) -> str:
        if self.view is None:
            return "click the view to cut."
        if not self.points:
            return "click where the cut line starts."
        if len(self.points) == 1:
            return "click where it ends."
        return "move the view to the side to look from, and click."

    def back(self) -> bool:
        if self.points:
            self.points.pop()
            return True
        return super().back()

    def _snapped(self, point):
        """The point in the view's millimetres, onto a corner or a centre
        near it, and the second one level or plumb when nearly so."""
        scale = self.controller.canvas.layout().scale
        found = drawpick.nearest(self.sheet, point,
                                 self.SNAP_PIXELS / max(scale, 1e-9),
                                 only_view=self.view.id,
                                 kinds=(drawpick.POINT, drawpick.CIRCLE))
        local = self.local(point)
        if found is not None:
            local = tuple(found.a[:2])
        elif self.points:
            a = self.points[0]
            dx, dy = local[0] - a[0], local[1] - a[1]
            angle = math.degrees(math.atan2(dy, dx))
            for target in (0.0, 90.0, 180.0, -90.0, -180.0):
                if abs(angle - target) < 4.0:
                    length = math.hypot(dx, dy)
                    rad = math.radians(target)
                    local = (a[0] + math.cos(rad) * length,
                             a[1] + math.sin(rad) * length)
                    break
        return (float(local[0]), float(local[1]))

    def spot(self, point):
        """The two ends ordered so the model reads them the right way
        round, and where the view goes, out square from the line."""
        a, b = self.points
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        local = self.local(point)
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        reach = (local[0] - mid[0]) * nx + (local[1] - mid[1]) * ny
        if abs(reach) < 1e-6:
            reach = -1e-6
        # The model looks from the line's left (its normal) at what lies
        # to its right.  First angle puts the view on the side away from
        # where it is looked from, third angle on the same side.
        third = getattr(self.controller.document, "angle",
                        dwg.FIRST_ANGLE) == dwg.THIRD_ANGLE
        if (reach > 0) != third:
            a, b = b, a
        at = self.sheet_point(mid)
        return (a, b), (at[0] + nx * reach, at[1] + ny * reach)

    def pressed(self, point) -> None:
        if len(self.points) < 2:
            p = self._snapped(point)
            if self.points and math.dist(p, self.points[0]) < 1.0:
                return
            self.points.append(p)
            return
        (a, b), (x, y) = self.spot(point)
        made = self.controller.create_section(self.view.id, a, b, x, y)
        self.points = []
        if made is not None:
            self.view = None

    def paint(self, painter, layout) -> None:
        super().paint(painter, layout)
        if self.view is None:
            return
        painter.save()
        pen = QtGui.QPen(QtGui.QColor("#3b82d6"), 1.6)
        pen.setDashPattern([8.0, 3.0, 2.0, 3.0])
        painter.setPen(pen)
        drawn = [self.sheet_point(p) for p in self.points]
        if len(self.points) == 1 and self.cursor is not None:
            drawn.append(self.sheet_point(self._snapped(self.cursor)))
        if len(drawn) == 2:
            painter.drawLine(QtCore.QPointF(*layout.to_device(*drawn[0])),
                             QtCore.QPointF(*layout.to_device(*drawn[1])))
        for p in drawn:
            painter.setBrush(QtGui.QColor("#3b82d6"))
            painter.drawEllipse(QtCore.QPointF(*layout.to_device(*p)),
                                3.0, 3.0)
        if len(self.points) == 2 and self.cursor is not None:
            (a, b), (x, y) = self.spot(self.cursor)
            half = math.dist(a, b) / 2.0
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor("#3b82d6"), 1.2,
                                      QtCore.Qt.DashLine))
            mid = self.sheet_point(((a[0] + b[0]) / 2.0,
                                    (a[1] + b[1]) / 2.0))
            painter.drawLine(QtCore.QPointF(*layout.to_device(*mid)),
                             QtCore.QPointF(*layout.to_device(x, y)))
            r = max(6.0, half)
            painter.drawRect(QtCore.QRectF(
                QtCore.QPointF(*layout.to_device(x - r, y + r)),
                QtCore.QPointF(*layout.to_device(x + r, y - r))).normalized())
        painter.restore()


class CropTool(ViewTool):
    """Inventor's Crop: click the view, then two corners of a rectangle;
    only what is inside it is kept on the view."""

    name = "Crop"

    def __init__(self, controller, sheet) -> None:
        self.corner = None
        super().__init__(controller, sheet)

    def prompt(self) -> str:
        if self.view is None:
            return "click the view to crop."
        if self.corner is None:
            return "click one corner of what to keep."
        return "click the opposite corner."

    def back(self) -> bool:
        if self.corner is not None:
            self.corner = None
            return True
        return super().back()

    def pressed(self, point) -> None:
        here = self.local(point)
        if self.corner is None:
            self.corner = here
            return
        a, b = self.corner, here
        if abs(a[0] - b[0]) < 1.0 or abs(a[1] - b[1]) < 1.0:
            return
        view = self.view
        self.corner = None
        self.view = None
        self.controller.crop_view(self.sheet, view,
                                  [a[0], a[1], b[0], b[1]])

    def paint(self, painter, layout) -> None:
        super().paint(painter, layout)
        if self.view is None or self.corner is None or self.cursor is None:
            return
        a = self.sheet_point(self.corner)
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#3b82d6"), 1.4))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(QtCore.QRectF(
            QtCore.QPointF(*layout.to_device(*a)),
            QtCore.QPointF(*layout.to_device(*self.cursor))).normalized())
        painter.restore()


class DetailTool(ViewTool):
    """Inventor's Detail: click the view, then the middle of what to
    enlarge, then how far round it reaches, then where the detail goes.
    Each click can be taken back with Esc."""

    name = "Detail"
    # how much bigger than its parent a detail is drawn
    ENLARGE = 2.0

    def __init__(self, controller, sheet) -> None:
        self.centre = None          # in the parent's own mm
        self.radius = None
        super().__init__(controller, sheet)

    def prompt(self) -> str:
        if self.view is None:
            return "click the view to take a detail of."
        if self.centre is None:
            return "click the middle of what to enlarge."
        if self.radius is None:
            return "click how far round it the detail reaches."
        return "click where the detail view goes."

    def back(self) -> bool:
        if self.radius is not None:
            self.radius = None
            return True
        if self.centre is not None:
            self.centre = None
            return True
        return super().back()

    def pressed(self, point) -> None:
        here = self.local(point)
        if self.centre is None:
            self.centre = here
            return
        if self.radius is None:
            reach = math.hypot(here[0] - self.centre[0],
                               here[1] - self.centre[1])
            if reach < 1.0:
                return
            self.radius = reach
            return
        view, centre, radius = self.view, self.centre, self.radius
        self.view = self.centre = self.radius = None
        self.controller.create_detail(self.sheet, view, centre, radius,
                                      point[0], point[1])

    def paint(self, painter, layout) -> None:
        super().paint(painter, layout)
        if self.view is None or self.centre is None:
            return
        middle = self.sheet_point(self.centre)
        radius = self.radius
        if radius is None and self.cursor is not None:
            here = self.local(self.cursor)
            radius = math.hypot(here[0] - self.centre[0],
                                here[1] - self.centre[1])
        if not radius:
            return
        painter.save()
        pen = QtGui.QPen(QtGui.QColor("#3b82d6"), 1.4)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        c = QtCore.QPointF(*layout.to_device(*middle))
        r = radius * layout.scale
        painter.drawEllipse(c, r, r)
        if self.radius is not None and self.cursor is not None:
            # where it will go, the size it will be
            pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(pen)
            at = QtCore.QPointF(*layout.to_device(*self.cursor))
            big = r * self.ENLARGE
            painter.drawEllipse(at, big, big)
        painter.restore()


class BreakTool:
    """Inventor's Break: click a view where the band to take out starts,
    then where it ends.  Spread across the page it shortens the view that
    way, up the page the other.  Stays on for the next until Esc."""

    name = "Break"

    def __init__(self, controller, sheet) -> None:
        self.controller = controller
        self.sheet = sheet
        self.first = None           # (view, point in its own unbroken mm)
        self.cursor = None
        self.say()

    def say(self) -> None:
        host = self.controller.host
        host.status_message.setStyleSheet("")
        host.status_message.setText(
            "Break: click the view where the part to leave out starts."
            if self.first is None else
            "Break: click where it ends. Esc when done.")

    def view_at(self, point):
        for view in reversed(self.sheet.views):
            projection = view.projection
            if projection is None:
                continue
            box = projection.box
            local = dwg.unshown(view, (point[0] - view.x, point[1] - view.y))
            if box[0] - 3 <= local[0] <= box[2] + 3 and \
                    box[1] - 3 <= local[1] <= box[3] + 3:
                return view, local
        return None

    def press(self, point, device) -> None:
        if self.first is None:
            found = self.view_at(point)
            if found is not None:
                self.first = found
                self.say()
            return
        view, start = self.first
        end = dwg.unshown(view, (point[0] - view.x, point[1] - view.y))
        self.first = None
        dx, dy = abs(end[0] - start[0]), abs(end[1] - start[1])
        axis = 0 if dx >= dy else 1
        lo, hi = sorted((start[axis], end[axis]))
        self.controller._break(self.sheet, view, axis, lo, hi)
        self.say()

    def move(self, point, device, held: bool) -> None:
        self.cursor = point

    def release(self, point, device) -> None:
        pass

    def right_click(self, point, device) -> bool:
        return False

    def escape(self) -> bool:
        if self.first is not None:
            self.first = None
            self.say()
            return True
        return False

    def cursor_shape(self, point, device):
        return QtCore.Qt.CrossCursor

    def paint(self, painter, layout) -> None:
        if self.first is None or self.cursor is None:
            return
        view, start = self.first
        a = dwg.shown(view, start)
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#3b82d6"), 1.2,
                                  QtCore.Qt.DashLine))
        p = QtCore.QPointF(*layout.to_device(view.x + a[0], view.y + a[1]))
        q = QtCore.QPointF(*layout.to_device(*self.cursor))
        painter.drawRect(QtCore.QRectF(p, q).normalized())
        painter.restore()

    def close(self) -> None:
        pass


class BreakOutTool(BreakTool):
    """Inventor's Break Out: click round the area to open on a view,
    corner by corner, right-click to close it, then say how deep."""

    name = "Break Out"

    def __init__(self, controller, sheet) -> None:
        self.points = []
        super().__init__(controller, sheet)

    def say(self) -> None:
        host = self.controller.host
        host.status_message.setStyleSheet("")
        host.status_message.setText(
            "Break Out: click round the area to open, corner by corner."
            if not getattr(self, "points", None) else
            "Break Out: %d corners. Click more, or right-click to close it."
            % len(self.points))

    def press(self, point, device) -> None:
        if not self.points:
            found = self.view_at(point)
            if found is None:
                return
            self.first = found
            self.points.append(found[1])
        else:
            view = self.first[0]
            self.points.append(dwg.unshown(
                view, (point[0] - view.x, point[1] - view.y)))
        self.say()
        self.controller.canvas.update()

    def right_click(self, point, device) -> bool:
        if len(self.points) < 3:
            return False
        view = self.first[0]
        loop = [list(p) for p in self.points]
        self.points = []
        self.first = None
        self.controller.break_out(self.sheet, view, loop)
        self.say()
        return True

    def escape(self) -> bool:
        if self.points:
            self.points = []
            self.first = None
            self.say()
            return True
        return False

    def paint(self, painter, layout) -> None:
        if not self.points:
            return
        view = self.first[0]
        drawn = [QtCore.QPointF(*layout.to_device(
            view.x + dwg.shown(view, p)[0], view.y + dwg.shown(view, p)[1]))
            for p in self.points]
        if self.cursor is not None:
            drawn.append(QtCore.QPointF(*layout.to_device(*self.cursor)))
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#3b82d6"), 1.4))
        painter.drawPolygon(QtGui.QPolygonF(drawn))
        painter.restore()


class HoleNoteTool(PickTool):
    """Inventor's Hole and Thread: click a hole, then where its note goes.

    The note is read off the model: the diameter, THRU or the depth, a
    counterbore, and how many holes the same on the view, ``4x Ø8 THRU``.
    """

    name = "Hole and Thread"
    prompts = ("click a hole.", "click where the note goes.")

    def press(self, point, device) -> None:
        self._scale = self.controller.canvas.layout().scale
        if not self.picks:
            item = self._under(point)
            if item is None:
                return
            text = self._note_for(item)
            if not text:
                self.controller.host.status_message.setText(
                    "Hole and Thread: that is not a hole seen end on.")
                return
            self.picks = [item]
            self._text = text
            self.say()
            return
        hole = self.picks[0]
        view = self.sheet.view(hole.view)
        local = (point[0] - view.x, point[1] - view.y)
        angle = math.atan2(local[1] - hole.a[1], local[0] - hole.a[0])
        tip = [hole.a[0] + hole.radius * math.cos(angle),
               hole.a[1] + hole.radius * math.sin(angle)]
        self._add(Annotation(kind=dwg.LEADER, view=hole.view, points=[tip],
                             offset=[local[0] - tip[0], local[1] - tip[1]],
                             text=self._text))
        self.picks = []
        self.say()

    def _note_for(self, item) -> str:
        controller = self.controller
        doc = controller.document
        view = self.sheet.view(item.view)
        shape = controller.generator.model_of(doc, self.sheet, view)
        if shape is None or view.projection is None:
            return ""
        try:
            direction, up = controller.generator.orientation(
                doc, self.sheet, view)
        except Exception:
            return ""
        scale = doc.view_scale(self.sheet, view)
        return viewgen.hole_note_at(shape, direction, up,
                                    view.projection.centre, scale, item.a)

    def paint(self, painter, layout) -> None:
        super().paint(painter, layout)
        if self.picks and self.cursor is not None:
            hole = self.picks[0]
            view = self.sheet.view(hole.view)
            if view is None:
                return
            painter.save()
            painter.setPen(QtGui.QPen(QtGui.QColor("#3b82d6"), 1.2,
                                      QtCore.Qt.DashLine))
            painter.drawLine(
                QtCore.QPointF(*layout.to_device(view.x + hole.a[0],
                                                 view.y + hole.a[1])),
                QtCore.QPointF(*layout.to_device(*self.cursor)))
            painter.drawText(QtCore.QPointF(
                *layout.to_device(*self.cursor)) + QtCore.QPointF(6, -6),
                self._text)
            painter.restore()


def nearest_view(sheet, point):
    """The view a point on the sheet belongs with: the one it is on, or
    the nearest."""
    best, gap = None, math.inf
    for view in sheet.views:
        box = view.projection.box if view.projection is not None else (
            -10, -10, 10, 10)
        dx = max(box[0] - (point[0] - view.x), 0, (point[0] - view.x) - box[2])
        dy = max(box[1] - (point[1] - view.y), 0, (point[1] - view.y) - box[3])
        d = math.hypot(dx, dy)
        if d < gap:
            best, gap = view, d
    return best


class TextTool:
    """Inventor's Text: click where it goes, then write it in Format Text.
    Leader Text first takes the point the arrow points at."""

    name = "Text"
    leader = False

    def __init__(self, controller, sheet) -> None:
        self.controller = controller
        self.sheet = sheet
        self.tip = None
        self.cursor = None
        self.say()

    def say(self) -> None:
        host = self.controller.host
        host.status_message.setStyleSheet("")
        if self.leader and self.tip is None:
            host.status_message.setText(
                "Leader Text: click what the arrow points at. Esc when done.")
        else:
            host.status_message.setText(
                "%s: click where the text goes. Esc when done." % self.name)

    def press(self, point, device) -> None:
        if not self.sheet.views:
            self.controller.host.status_message.setText(
                "Place a view first: text is kept with a view.")
            return
        if self.leader and self.tip is None:
            self.tip = (point[0], point[1])
            self.say()
            return
        anchor = self.tip if self.leader else (point[0], point[1])
        view = nearest_view(self.sheet, anchor)
        dialog = FormatTextDialog(self.controller.host, self.controller,
                                  self.sheet)
        if dialog.exec() != QtWidgets.QDialog.Accepted or \
                not dialog.text().strip():
            self.tip = None
            self.say()
            return
        local = [anchor[0] - view.x, anchor[1] - view.y]
        note = Annotation(kind=dwg.LEADER if self.leader else dwg.NOTE,
                          view=view.id, points=[local],
                          offset=([point[0] - anchor[0], point[1] - anchor[1]]
                                  if self.leader else [0.0, 0.0]),
                          text=dialog.text())
        dialog.style_into(note)
        doc = self.controller.document
        doc.push_undo()
        doc.add_annotation(self.sheet, note)
        doc.modified = True
        self.controller.canvas.update()
        self.tip = None
        self.say()

    def move(self, point, device, held: bool) -> None:
        self.cursor = (point[0], point[1])

    def release(self, point, device) -> None:
        pass

    def right_click(self, point, device) -> bool:
        if self.tip is not None:
            self.tip = None
            self.say()
            return True
        return False

    def escape(self) -> bool:
        return self.right_click(None, None)

    def cursor_shape(self, point, device):
        return QtCore.Qt.IBeamCursor if not (self.leader and self.tip is None) \
            else QtCore.Qt.CrossCursor

    def paint(self, painter, layout) -> None:
        if self.tip is not None and self.cursor is not None:
            painter.save()
            painter.setPen(QtGui.QPen(QtGui.QColor("#3b82d6"), 1.2))
            painter.drawLine(QtCore.QPointF(*layout.to_device(*self.tip)),
                             QtCore.QPointF(*layout.to_device(*self.cursor)))
            painter.restore()

    def close(self) -> None:
        pass


class LeaderTextTool(TextTool):
    name = "Leader Text"
    leader = True


class FormatTextDialog(QtWidgets.QDialog):
    """Inventor's Format Text: the text, its font, size and look, and
    properties to put in it, from the model, the drawing or the sheet."""

    def __init__(self, parent, controller, sheet,
                 note: Optional[Annotation] = None) -> None:
        super().__init__(parent)
        from .titleblock_ui import PROPERTY_GROUPS
        self.setWindowTitle("Format Text")
        layout = QtWidgets.QVBoxLayout(self)

        row = QtWidgets.QHBoxLayout()
        self.font = QtWidgets.QFontComboBox()
        self.font.setCurrentFont(QtGui.QFont(
            (note.font if note and note.font else "Arial")))
        self.size = QtWidgets.QDoubleSpinBox()
        self.size.setRange(1.0, 50.0)
        self.size.setDecimals(1)
        self.size.setSuffix(" mm")
        self.size.setValue(note.size if note and note.size else 3.5)
        self.bold = QtWidgets.QToolButton()
        self.bold.setText("B")
        self.bold.setCheckable(True)
        self.bold.setStyleSheet("font-weight: bold;")
        self.italic = QtWidgets.QToolButton()
        self.italic.setText("I")
        self.italic.setCheckable(True)
        self.italic.setStyleSheet("font-style: italic;")
        if note is not None:
            self.bold.setChecked(note.bold)
            self.italic.setChecked(note.italic)
        self.align = QtWidgets.QComboBox()
        for key, label in (("left", "Left"), ("centre", "Centre"),
                           ("right", "Right")):
            self.align.addItem(label, key)
        if note is not None:
            self.align.setCurrentIndex(max(0, self.align.findData(
                note.align or "left")))
        for widget in (self.font, self.size, self.bold, self.italic,
                       self.align):
            row.addWidget(widget)
        layout.addLayout(row)

        props = QtWidgets.QHBoxLayout()
        self.group = QtWidgets.QComboBox()
        self._groups = PROPERTY_GROUPS
        for title, _items in PROPERTY_GROUPS:
            self.group.addItem(title)
        self.prop = QtWidgets.QComboBox()
        self.group.currentIndexChanged.connect(self._fill)
        self._fill(0)
        add = QtWidgets.QPushButton("Add")
        add.setToolTip("Put the property into the text at the cursor")
        add.clicked.connect(self._insert)
        props.addWidget(QtWidgets.QLabel("Type"))
        props.addWidget(self.group)
        props.addWidget(QtWidgets.QLabel("Property"))
        props.addWidget(self.prop, 1)
        props.addWidget(add)
        layout.addLayout(props)

        self.edit = QtWidgets.QPlainTextEdit(note.text if note else "")
        self.edit.setMinimumSize(460, 160)
        layout.addWidget(self.edit, 1)
        self.font.currentFontChanged.connect(lambda _f: self._look())
        self.bold.toggled.connect(lambda _b: self._look())
        self.italic.toggled.connect(lambda _b: self._look())
        self._look()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.edit.setFocus()

    def _fill(self, index: int) -> None:
        self.prop.clear()
        for label, key in self._groups[max(0, index)][1]:
            self.prop.addItem(label, key)

    def _insert(self) -> None:
        self.edit.insertPlainText("<%s>" % self.prop.currentData())
        self.edit.setFocus()

    def _look(self) -> None:
        font = QtGui.QFont(self.font.currentFont())
        font.setPointSize(11)
        font.setBold(self.bold.isChecked())
        font.setItalic(self.italic.isChecked())
        self.edit.setFont(font)

    def text(self) -> str:
        return self.edit.toPlainText()

    def style_into(self, note: Annotation) -> None:
        note.font = self.font.currentFont().family()
        note.size = self.size.value()
        note.bold = self.bold.isChecked()
        note.italic = self.italic.isChecked()
        note.align = self.align.currentData() or "left"
