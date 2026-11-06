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
