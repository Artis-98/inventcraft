"""A title block edited as a sketch, the way Inventor's is.

Double-click the title block on a sheet and it opens here on an open
canvas: draw lines and rectangles, put text where it goes with properties
in it, bring in lines and text from a DXF drawn in AutoCAD, move and
delete what is there. On Finish the block is measured, and its bottom
right corner is the one put on the border's bottom right corner, as
Inventor does, so nothing has to be drawn in any particular place.
"""
from __future__ import annotations

import copy
import math
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import drawing as dwg
from ..core.drawing import Annotation

SNAP_PIXELS = 9.0
ORTHO_DEGREES = 3.0
LINE_PEN = 0.0      # cosmetic: one pixel whatever the zoom


def _q(x: float, y: float) -> QtCore.QPointF:
    """Millimetres, y up, to the scene, y down."""
    return QtCore.QPointF(x, -y)


def _mm(p: QtCore.QPointF):
    return (p.x(), -p.y())


class LineItem(QtWidgets.QGraphicsLineItem):
    def __init__(self, x1, y1, x2, y2) -> None:
        super().__init__(x1, -y1, x2, -y2)
        pen = QtGui.QPen(QtGui.QColor("#1e2329"), LINE_PEN)
        pen.setCosmetic(True)
        pen.setWidthF(1.4)
        self.setPen(pen)
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsSelectable
                      | QtWidgets.QGraphicsItem.ItemIsMovable)

    def ends(self):
        line = self.line()
        p1 = self.mapToScene(line.p1())
        p2 = self.mapToScene(line.p2())
        return _mm(p1) + _mm(p2)


class TextItem(QtWidgets.QGraphicsSimpleTextItem):
    """A title block text: what it says, properties and all, its height in
    millimetres, bold, and which way it is aligned on its point."""

    def __init__(self, field: dwg.TextField) -> None:
        super().__init__()
        self.field = field
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsSelectable
                      | QtWidgets.QGraphicsItem.ItemIsMovable)
        self.refresh()
        self.setPos(_q(field.x, field.y))

    def shown(self) -> str:
        """As Inventor shows a property in a title block: by its name,
        ``<PART NUMBER>``, not by the key it is kept under."""
        text = ("<%s>" % self.field.text if self.field.kind == dwg.PROPERTY
                else self.field.text)
        from .titleblock_ui import PROPERTY_GROUPS
        for _title, items in PROPERTY_GROUPS:
            for label, key in items:
                text = text.replace("<%s>" % key, "<%s>" % label.upper())
        return text

    def refresh(self) -> None:
        font = QtGui.QFont("Arial")
        # a font one unit tall, scaled to the height in millimetres: the
        # scene is in millimetres
        font.setPixelSize(10)
        font.setBold(self.field.bold)
        self.setFont(font)
        self.setText(self.shown())
        self.setScale(self.field.height / 7.2)
        width = self.boundingRect().width() * self.scale()
        shift = {"centre": -width / 2, "right": -width}.get(
            self.field.align, 0.0)
        # placed by the baseline-left corner, as the sheet draws it
        self.setTransformOriginPoint(0, 0)
        self._shift = shift
        self.setBrush(QtGui.QColor("#1e2329"))

    def anchor(self):
        """Where the text stands, in millimetres, as the field keeps it."""
        x, y = _mm(self.pos())
        return x, y

    def paint(self, painter, option, widget=None) -> None:
        painter.save()
        painter.translate(self._shift / max(self.scale(), 1e-9),
                          -self.boundingRect().height() * 0.78)
        super().paint(painter, option, widget)
        painter.restore()


class Canvas(QtWidgets.QGraphicsView):
    """The open sheet a title block is drawn on, in millimetres."""

    def __init__(self, editor: "TitleBlockEditor") -> None:
        super().__init__(editor)
        self.editor = editor
        self.setScene(QtWidgets.QGraphicsScene(-2000, -2000, 4000, 4000,
                                               self))
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setBackgroundBrush(QtGui.QColor("#ffffff"))
        self.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.tool = "select"
        self.start: Optional[QtCore.QPointF] = None
        self.ghost: Optional[QtWidgets.QGraphicsItem] = None
        self._pan: Optional[QtCore.QPoint] = None
        self.scale(4.0, 4.0)

    # -- background: a millimetre grid, every tenth line darker ----------

    def drawBackground(self, painter, rect) -> None:
        super().drawBackground(painter, rect)
        step = 5.0
        left = math.floor(rect.left() / step) * step
        top = math.floor(rect.top() / step) * step
        light = QtGui.QPen(QtGui.QColor("#eef1f4"), 0)
        dark = QtGui.QPen(QtGui.QColor("#d9dee4"), 0)
        x = left
        while x < rect.right():
            painter.setPen(dark if abs(x % 50) < 1e-6 else light)
            painter.drawLine(QtCore.QPointF(x, rect.top()),
                             QtCore.QPointF(x, rect.bottom()))
            x += step
        y = top
        while y < rect.bottom():
            painter.setPen(dark if abs(y % 50) < 1e-6 else light)
            painter.drawLine(QtCore.QPointF(rect.left(), y),
                             QtCore.QPointF(rect.right(), y))
            y += step

    # -- snapping -----------------------------------------------------------

    def snap(self, scene_point: QtCore.QPointF, anchor=None) -> QtCore.QPointF:
        """The point a click means: an end of a line near it, or, drawing,
        square to where the line started when nearly so."""
        reach = SNAP_PIXELS / max(self.transform().m11(), 1e-9)
        best, gap = None, reach
        for item in self.scene().items():
            if isinstance(item, LineItem) and item is not self.ghost:
                x1, y1, x2, y2 = item.ends()
                for p in (_q(x1, y1), _q(x2, y2)):
                    d = math.hypot(p.x() - scene_point.x(),
                                   p.y() - scene_point.y())
                    if d < gap:
                        best, gap = p, d
        if best is not None:
            return best
        if anchor is not None:
            dx = scene_point.x() - anchor.x()
            dy = scene_point.y() - anchor.y()
            angle = math.degrees(math.atan2(abs(dy), abs(dx)))
            if angle < ORTHO_DEGREES:
                return QtCore.QPointF(scene_point.x(), anchor.y())
            if angle > 90 - ORTHO_DEGREES:
                return QtCore.QPointF(anchor.x(), scene_point.y())
        # to a tenth of a millimetre
        return QtCore.QPointF(round(scene_point.x(), 1),
                              round(scene_point.y(), 1))

    # -- mouse --------------------------------------------------------------

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self._drop_ghost()
        self.start = None
        self.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag
                         if tool == "select"
                         else QtWidgets.QGraphicsView.NoDrag)
        self.viewport().setCursor(QtCore.Qt.ArrowCursor if tool == "select"
                                  else QtCore.Qt.CrossCursor)

    def _drop_ghost(self) -> None:
        if self.ghost is not None:
            self.scene().removeItem(self.ghost)
            self.ghost = None

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.MiddleButton:
            self._pan = event.position().toPoint()
            return
        if event.button() == QtCore.Qt.RightButton:
            # ends a chain of lines, as Inventor's right-click Done does
            self.start = None
            self._drop_ghost()
            return
        if self.tool == "select":
            super().mousePressEvent(event)
            return
        point = self.snap(self.mapToScene(event.position().toPoint()),
                          self.start)
        if self.tool == "text":
            self.editor.add_text(_mm(point))
            return
        if self.start is None:
            self.start = point
            return
        if self.tool == "line":
            self.editor.add_line(_mm(self.start) + _mm(point))
            self.start = point          # the next line goes on from here
        elif self.tool == "rect":
            (x1, y1), (x2, y2) = _mm(self.start), _mm(point)
            for seg in ((x1, y1, x2, y1), (x2, y1, x2, y2),
                        (x2, y2, x1, y2), (x1, y2, x1, y1)):
                self.editor.add_line(seg)
            self.start = None
        self._drop_ghost()

    def mouseMoveEvent(self, event) -> None:
        if self._pan is not None:
            now = event.position().toPoint()
            delta = now - self._pan
            self._pan = now
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            return
        if self.start is not None and self.tool in ("line", "rect"):
            point = self.snap(self.mapToScene(event.position().toPoint()),
                              self.start)
            self._drop_ghost()
            pen = QtGui.QPen(QtGui.QColor("#3b82d6"), 0)
            if self.tool == "line":
                self.ghost = self.scene().addLine(QtCore.QLineF(self.start,
                                                                point), pen)
            else:
                self.ghost = self.scene().addRect(
                    QtCore.QRectF(self.start, point).normalized(), pen)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == QtCore.Qt.MiddleButton:
            self._pan = None
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, TextItem):
            self.editor.edit_text(item)
            return
        if event.button() == QtCore.Qt.MiddleButton:
            self.editor.fit()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        factor = 1.2 ** (event.angleDelta().y() / 120.0)
        self.scale(factor, factor)

    def keyPressEvent(self, event) -> None:
        if event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            for item in self.scene().selectedItems():
                self.scene().removeItem(item)
            return
        if event.key() == QtCore.Qt.Key_Escape:
            if self.start is not None:
                self.start = None
                self._drop_ghost()
            else:
                self.editor.set_tool("select")
            return
        super().keyPressEvent(event)


class TitleBlockEditor(QtWidgets.QDialog):
    """The title block's sketch: lines, text, and DXF brought in."""

    TOOLS = (("select", "Select", "select"), ("line", "Line", "line"),
             ("rect", "Rectangle", "rect"), ("text", "Text", "an_text"))

    def __init__(self, parent, controller, doc: dwg.DrawingDocument,
                 name: str) -> None:
        super().__init__(parent)
        from . import icons
        self.controller = controller
        self.doc = doc
        self.name = name
        self.setWindowTitle("Edit Title Block - %s" % name)
        self.resize(1200, 760)
        root = QtWidgets.QVBoxLayout(self)

        bar = QtWidgets.QHBoxLayout()
        self.tool_buttons = {}
        group = QtWidgets.QButtonGroup(self)
        for key, label, icon in self.TOOLS:
            button = QtWidgets.QToolButton()
            button.setText(label)
            button.setIcon(icons.icon(icon, 20))
            button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, k=key: self.set_tool(k))
            group.addButton(button)
            self.tool_buttons[key] = button
            bar.addWidget(button)
        bar.addSpacing(16)
        dxf = QtWidgets.QPushButton("Import DXF...")
        dxf.setToolTip("Bring in the lines and text of a title block drawn "
                       "in AutoCAD; explode blocks there first")
        dxf.clicked.connect(self.import_dxf)
        bar.addWidget(dxf)
        fit = QtWidgets.QPushButton("Fit")
        fit.clicked.connect(self.fit)
        bar.addWidget(fit)
        bar.addStretch(1)
        root.addLayout(bar)

        self.canvas = Canvas(self)
        root.addWidget(self.canvas, 1)

        hint = QtWidgets.QLabel(
            "Draw it anywhere: on Finish its bottom right corner is put on "
            "the border's. Line: click each point, right-click to end. "
            "Double-click text to change it. Delete removes what is "
            "picked. Wheel zooms, middle button pans. Every sheet using "
            "this title block changes with it.")
        hint.setWordWrap(True)
        hint.setProperty("hint", True)
        root.addWidget(hint)

        buttons = QtWidgets.QDialogButtonBox()
        buttons.addButton("Finish", QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load(doc.title_blocks[name])
        self.set_tool("select")
        QtCore.QTimer.singleShot(0, self.fit)

    # -- what is there --------------------------------------------------

    def _load(self, block: dwg.TitleBlock) -> None:
        for line in block.lines:
            self.add_line(line[:4])
        for field in block.fields:
            self.canvas.scene().addItem(TextItem(copy.deepcopy(field)))

    def lines(self) -> List[LineItem]:
        return [i for i in self.canvas.scene().items()
                if isinstance(i, LineItem)]

    def texts(self) -> List[TextItem]:
        return [i for i in self.canvas.scene().items()
                if isinstance(i, TextItem)]

    def add_line(self, seg) -> LineItem:
        item = LineItem(*seg)
        self.canvas.scene().addItem(item)
        return item

    def set_tool(self, tool: str) -> None:
        self.canvas.set_tool(tool)
        self.tool_buttons[tool].setChecked(True)

    def fit(self) -> None:
        items = self.lines() + self.texts()
        if not items:
            return
        rect = QtCore.QRectF()
        for item in items:
            rect = rect.united(item.sceneBoundingRect())
        self.canvas.fitInView(rect.adjusted(-10, -10, 10, 10),
                              QtCore.Qt.KeepAspectRatio)

    # -- text -----------------------------------------------------------

    def _ask(self, field: dwg.TextField) -> bool:
        from .drawing_tools import FormatTextDialog
        from .titleblock_ui import _parse_text
        shown = ("<%s>" % field.text if field.kind == dwg.PROPERTY
                 else field.text)
        note = Annotation(text=shown, size=field.height, bold=field.bold,
                          align=field.align or "left")
        dialog = FormatTextDialog(self, self.controller, None, note)
        dialog.font.setEnabled(False)
        dialog.italic.setEnabled(False)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return False
        text = dialog.text().strip()
        if not text:
            return False
        field.kind, field.text = _parse_text(text)
        field.height = dialog.size.value()
        field.bold = dialog.bold.isChecked()
        field.align = dialog.align.currentData() or "left"
        return True

    def add_text(self, where) -> None:
        field = dwg.TextField("text%d" % (len(self.texts()) + 1), dwg.STATIC,
                              "", x=where[0], y=where[1], height=2.5)
        if self._ask(field):
            self.canvas.scene().addItem(TextItem(field))

    def edit_text(self, item: TextItem) -> None:
        if self._ask(item.field):
            item.refresh()
            item.update()

    # -- DXF ------------------------------------------------------------

    def import_dxf(self) -> None:
        from ..core import dxfread
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Title block DXF", "", "DXF (*.dxf);;All files (*)")
        if not path:
            return
        try:
            found = dxfread.read(path)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Import DXF", str(exc))
            return
        self.take(found)

    def take(self, found) -> None:
        """Lines and text read from a DXF, onto the canvas."""
        for seg in found["lines"]:
            self.add_line(seg)
        for x, y, height, words in found["texts"]:
            self.canvas.scene().addItem(TextItem(dwg.TextField(
                "text%d" % (len(self.texts()) + 1), dwg.STATIC, words,
                x=x, y=y, height=height)))
        self.fit()

    # -- into the drawing -------------------------------------------------

    def block(self) -> dwg.TitleBlock:
        """The sketch as a title block, measured from its own bottom left,
        sized so its bottom right is the corner put on the border's."""
        segs = [item.ends() for item in self.lines()]
        texts = self.texts()
        xs = [v for s in segs for v in (s[0], s[2])]
        ys = [v for s in segs for v in (s[1], s[3])]
        for item in texts:
            x, y = item.anchor()
            xs.append(x)
            ys.append(y)
        old = self.doc.title_blocks[self.name]
        block = dwg.TitleBlock(name=self.name)
        if not xs:
            return block
        x0, y0 = min(xs), min(ys)
        block.width = max(xs) - x0
        block.height = max(ys) - y0
        block.lines = [[s[0] - x0, s[1] - y0, s[2] - x0, s[3] - y0]
                       for s in segs]
        for item in texts:
            field = copy.deepcopy(item.field)
            x, y = item.anchor()
            field.x, field.y = x - x0, y - y0
            block.fields.append(field)
        del old
        return block

    def apply(self) -> None:
        self.doc.title_blocks[self.name] = self.block()
