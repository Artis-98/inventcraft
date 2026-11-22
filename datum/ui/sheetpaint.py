"""Drawing a sheet, for whatever it is going onto.

One routine paints a sheet, and it is given a QPainter.  On screen that
painter belongs to a widget; for a PDF it belongs to a QPdfWriter, for an
SVG to a QSvgGenerator, and for paper to a QPrinter.  Because it is the
same routine every time, what comes out of the printer is what was on the
screen - and the PDF is real vector output at true size, not a picture of
the window.

Everything here works in sheet millimetres with Y upwards, the way paper
does.  ``Layout`` holds the one transform that turns that into whatever the
painter underneath is using.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6 import QtCore, QtGui

from ..core import drawing as dwg
from ..core import hlr
from .theme import C
from ..core.drawing import (
    ANGULAR, Annotation, BALLOON, DETAIL, DIAMETER, DIMENSIONS,
    DrawingDocument, LEADER, NOTE, PartsList, RADIUS, SECTION, Sheet, View,
)

PAPER = "#ffffff"
# The chrome's accent is a light silver, which is invisible on paper.  What
# is picked on a sheet gets a colour of its own, dark enough to read white.
SELECTED = C.paper_selected
PAPER_EDGE = "#b8bec6"
SICK = "#c8501e"
STALE = "#b08000"
# a view still waiting for its real lines: outlines, quietly
DRAFT = "#aab2bc"
DRAFT_TEXT = "#5f6b78"

# A hairline still has to be visible on screen when the sheet is zoomed
# out, so every pen is given a floor in device pixels.
MIN_PEN = 0.8


@dataclass
class Layout:
    """Where the sheet sits on the device, and how big."""

    scale: float = 1.0          # device units per sheet millimetre
    offset_x: float = 0.0       # device units
    offset_y: float = 0.0
    height: float = 297.0       # sheet height, for the Y flip

    def to_device(self, x: float, y: float) -> Tuple[float, float]:
        return (self.offset_x + x * self.scale,
                self.offset_y + (self.height - y) * self.scale)

    def to_sheet(self, x: float, y: float) -> Tuple[float, float]:
        return ((x - self.offset_x) / self.scale,
                self.height - (y - self.offset_y) / self.scale)

    def pen_width(self, millimetres: float) -> float:
        return max(MIN_PEN, millimetres * self.scale)


def fit(sheet_width: float, sheet_height: float,
        device_width: float, device_height: float,
        margin: float = 12.0) -> Layout:
    """A layout that puts the whole sheet on the device with room round it."""
    usable_w = max(1.0, device_width - margin * 2)
    usable_h = max(1.0, device_height - margin * 2)
    scale = min(usable_w / max(sheet_width, 1e-6),
                usable_h / max(sheet_height, 1e-6))
    width, height = sheet_width * scale, sheet_height * scale
    return Layout(scale=scale,
                  offset_x=(device_width - width) / 2.0,
                  offset_y=(device_height - height) / 2.0,
                  height=sheet_height)


def exact(sheet_height: float, scale: float = 1.0) -> Layout:
    """A layout at true size, for print and PDF: one millimetre is one."""
    return Layout(scale=scale, offset_x=0.0, offset_y=0.0,
                  height=sheet_height)


# --------------------------------------------------------------- the painting


# what {Model.*} and the like read on the sheet being painted, one per
# thread: a PDF is written on a thread of its own while the window paints
import threading as _threading
_HELD = _threading.local()


def _values() -> Dict[str, str]:
    return getattr(_HELD, "values", {})


def paint(painter: QtGui.QPainter, doc: DrawingDocument, sheet: Sheet,
          layout: Layout, model_properties: Optional[Dict[str, str]] = None,
          with_paper: bool = True, selection: Sequence[int] = (),
          on_screen: bool = False, hidden: Sequence[int] = (),
          title_block: bool = True, phase: str = "all",
          only=None) -> None:
    """Draw one sheet, whole.

    ``phase`` draws a slice of it, in the order the whole is drawn:
    "under" (paper, border, title block), "views", then "over"
    (annotations, sketches, tables).  The canvas keeps the views as a
    picture and paints the two slices round it live, so dragging a
    balloon never strokes a million points again.

    ``hidden`` views are left out, with whatever is pinned to them: the
    ones being changed on screen, drawn there as they will be instead.

    ``model_properties`` may be a dict or a function of the sheet.  The
    canvas has several sheets to hand and resolves each one's model lazily;
    an exporter usually has just the one.  Taking either saves every caller
    from knowing which kind the next one wants.
    """
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
    # one lettering for the whole sheet, on screen and in PDF alike
    lettering = painter.font()
    lettering.setFamily(drawing_font())
    painter.setFont(lettering)
    if callable(model_properties):
        model_properties = model_properties(sheet)
    width, height = sheet.extent()
    # what properties in text read, for the sheet being drawn
    try:
        _HELD.values = dwg.properties_for(doc, sheet, model_properties)
    except Exception:
        _HELD.values = {}

    if phase in ("all", "under"):
        if with_paper:
            _paper(painter, layout, width, height)
        _border(painter, doc, sheet, layout, width, height)
        if title_block:
            _title_block(painter, doc, sheet, layout, width, height,
                         model_properties)
    if phase in ("all", "views"):
        for view in sheet.views:
            if view.id in hidden and not (only and view.id in only):
                continue
            if only is not None and view.id not in only:
                continue
            _view(painter, doc, sheet, view, layout,
                  selected=view.id in selection, on_screen=on_screen)
    if phase not in ("all", "over"):
        return
    for note in sheet.annotations:
        if note.view in hidden:
            continue
        _annotation(painter, doc, sheet, note, layout,
                    selected=note.id in selection)
    for item in sheet.sketches:
        if item.view in hidden or item.id in hidden:
            continue
        _sketch(painter, doc, sheet, item, layout)
    for table in sheet.parts_lists:
        _parts_list(painter, doc, sheet, table, layout,
                    selected=table.id in selection)
        if table.kind == "holes":
            _hole_tags(painter, doc, sheet, table, layout)
    for table in getattr(sheet, "revision_tables", []):
        _revision_table(painter, doc, table, layout,
                        selected=table.id in selection)


def _revision_table(painter, doc, table, layout,
                    selected: bool = False) -> None:
    """Inventor's revision table: hung from its top right corner, the
    heading on top and the history down from it, oldest first."""
    rows = list(getattr(doc, "revisions", []))
    style = doc.styles.get("border", dwg.Style())
    thin = doc.styles.get("dimension", dwg.Style())
    text_style = doc.styles.get("text", dwg.Style())
    colour = SELECTED if selected else style.colour
    x0, y0, x1, y1 = table.box(len(rows))
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.setPen(_pen(layout, style, colour=colour))
    a, b = layout.to_device(x0, y1), layout.to_device(x1, y0)
    painter.drawRect(QtCore.QRectF(a[0], a[1], b[0] - a[0], b[1] - a[1]))
    painter.setPen(_pen(layout, thin, colour=colour))
    for i in range(1, len(rows) + 1):
        y = y1 - i * table.row_height
        painter.drawLine(QtCore.QPointF(*layout.to_device(x0, y)),
                         QtCore.QPointF(*layout.to_device(x1, y)))
    x = x0
    for _key, _head, width in dwg.REVISION_COLUMNS[:-1]:
        x += width
        painter.drawLine(QtCore.QPointF(*layout.to_device(x, y0)),
                         QtCore.QPointF(*layout.to_device(x, y1)))
    lines = [None] + rows
    for index, row in enumerate(lines):
        top = y1 - index * table.row_height
        gap = (table.row_height - table.text_height) / 2.0
        baseline = top - table.row_height + gap + table.text_height * 0.15
        x = x0
        for key, head, width in dwg.REVISION_COLUMNS:
            text = head if row is None else getattr(row, key, "")
            if key in ("rev", "date", "approved"):
                _text(painter, layout, _elide(text, width - 2.0,
                                              table.text_height),
                      x + width / 2.0, baseline, table.text_height,
                      bold=row is None, align="centre",
                      colour=text_style.colour)
            else:
                _text(painter, layout, _elide(text, width - 3.0,
                                              table.text_height),
                      x + 1.6, baseline, table.text_height,
                      bold=row is None, align="left",
                      colour=text_style.colour)
            x += width


def _pen(layout: Layout, style: dwg.Style, dashed: bool = False,
         colour: Optional[str] = None) -> QtGui.QPen:
    pen = QtGui.QPen(QtGui.QColor(colour or style.colour))
    pen.setWidthF(layout.pen_width(style.line_width))
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    if dashed:
        # Dashes are given in multiples of the pen width, which is how
        # ISO 128 gives them too, so they keep their proportions at any
        # zoom: a dashed line 12 widths on and 3 off, a chain line 24 on,
        # 3 off, a dot of half a width and 3 off.
        pen.setDashPattern(CHAIN if dashed == "chain" else DASHED)
    return pen


def _paper(painter: QtGui.QPainter, layout: Layout,
           width: float, height: float) -> None:
    x0, y0 = layout.to_device(0.0, height)
    x1, y1 = layout.to_device(width, 0.0)
    rect = QtCore.QRectF(x0, y0, x1 - x0, y1 - y0)
    painter.fillRect(rect, QtGui.QColor(PAPER))
    pen = QtGui.QPen(QtGui.QColor(PAPER_EDGE))
    pen.setWidthF(1.0)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawRect(rect)


def _border(painter: QtGui.QPainter, doc: DrawingDocument, sheet: Sheet,
            layout: Layout, width: float, height: float) -> None:
    border = doc.borders.get(sheet.border)
    if border is None:
        return
    style = doc.styles.get("border", dwg.Style())
    painter.setPen(_pen(layout, style))
    painter.setBrush(QtCore.Qt.NoBrush)

    x0, y0, x1, y1 = border.frame(width, height)
    a = layout.to_device(x0, y1)
    b = layout.to_device(x1, y0)
    painter.drawRect(QtCore.QRectF(a[0], a[1], b[0] - a[0], b[1] - a[1]))

    if not border.zones:
        return
    # zone letters up the sides and numbers along the top and bottom, the
    # way a big sheet is referred to over the phone
    columns = max(1, int((x1 - x0) // 105) or 1)
    rows = max(1, int((y1 - y0) // 105) or 1)
    for i in range(columns):
        cx = x0 + (x1 - x0) * (i + 0.5) / columns
        for cy, anchor in ((y1 + border.zone_size / 2.0, 0),
                           (y0 - border.zone_size / 2.0, 1)):
            _text(painter, layout, str(i + 1), cx, cy, 2.5, align="centre")
    for j in range(rows):
        cy = y0 + (y1 - y0) * (j + 0.5) / rows
        letter = chr(ord("A") + j)
        for cx in (x0 - border.zone_size / 2.0, x1 + border.zone_size / 2.0):
            _text(painter, layout, letter, cx, cy, 2.5, align="centre")


def _sketch(painter, doc, sheet, item, layout) -> None:
    """A sketch drawn on the sheet or on a view: its lines and text."""
    if not item.sketch:
        return
    ox, oy = sheet.sketch_origin(item)
    pieces, texts = item.drawn()
    painter.setPen(_pen(layout, doc.styles.get("visible", dwg.Style())))
    for x1, y1, x2, y2 in pieces:
        painter.drawLine(QtCore.QPointF(*layout.to_device(ox + x1, oy + y1)),
                         QtCore.QPointF(*layout.to_device(ox + x2, oy + y2)))
    for x, y, size, words, bold, italic, family in texts:
        font = painter.font()
        font.setFamily(family or drawing_font())
        font.setItalic(italic)
        painter.setFont(font)
        cap = size * cap_ratio(family or drawing_font())
        for index, line in enumerate(
                dwg.fill_properties(words, _values()).split(chr(10))):
            _text(painter, layout, line, ox + x,
                  oy + y - index * size * 1.2, cap, bold=bold)
    font = painter.font()
    font.setFamily(drawing_font())
    font.setItalic(False)
    painter.setFont(font)


def _title_block(painter: QtGui.QPainter, doc: DrawingDocument, sheet: Sheet,
                 layout: Layout, width: float, height: float,
                 model_properties: Optional[Dict[str, str]]) -> None:
    block = doc.title_blocks.get(sheet.title_block)
    if block is None:
        return
    border = doc.borders.get(sheet.border)
    x1, y0 = ((border.frame(width, height)[2], border.frame(width, height)[1])
              if border else (width - 10.0, 10.0))
    origin = (x1 - block.width, y0)

    style = doc.styles.get("border", dwg.Style())
    painter.setPen(_pen(layout, style))
    if block.sketch is not None:
        # a block edited as a sketch: its lines, arcs, circles and text,
        # the text's properties filled in
        pieces, texts = block.drawn()
        for x1, y1, x2, y2 in pieces:
            painter.drawLine(
                QtCore.QPointF(*layout.to_device(origin[0] + x1,
                                                 origin[1] + y1)),
                QtCore.QPointF(*layout.to_device(origin[0] + x2,
                                                 origin[1] + y2)))
        values = dwg.properties_for(doc, sheet, model_properties)
        text_style = doc.styles.get("text", dwg.Style())
        painter.setPen(QtGui.QPen(QtGui.QColor(text_style.colour)))
        for x, y, size, words, bold, italic, family in texts:
            font = painter.font()
            font.setFamily(family or drawing_font())
            font.setItalic(italic)
            painter.setFont(font)
            # a sketch text's size is its font's, so drawn as big as the
            # sketch showed it: its capitals that share of it
            cap = size * cap_ratio(family or drawing_font())
            for index, line in enumerate(
                    dwg.fill_properties(words, values).split(chr(10))):
                _text(painter, layout, line, origin[0] + x,
                      origin[1] + y - index * size * 1.2, cap, bold=bold)
        font = painter.font()
        font.setFamily(drawing_font())
        font.setItalic(False)
        painter.setFont(font)
        return
    for line in block.lines:
        a = layout.to_device(origin[0] + line[0], origin[1] + line[1])
        b = layout.to_device(origin[0] + line[2], origin[1] + line[3])
        painter.drawLine(QtCore.QPointF(*a), QtCore.QPointF(*b))

    values = dwg.properties_for(doc, sheet, model_properties)
    text_style = doc.styles.get("text", dwg.Style())
    painter.setPen(QtGui.QPen(QtGui.QColor(text_style.colour)))
    for item in block.fields:
        content = dwg.resolve_field(item, values, sheet)
        if not content:
            continue
        _text(painter, layout, content,
              origin[0] + item.x, origin[1] + item.y,
              item.height, bold=item.bold, align=item.align)


# the lettering of a drawing, as Inventor's DIN standard letters it:
# ISOCPEUR where the computer has it (Autodesk installs it), else Arial
DRAWING_FONTS = ("ISOCPEUR", "osifont", "Arial")
_FONT: Optional[str] = None


def drawing_font() -> str:
    global _FONT
    if _FONT is None:
        have = set(QtGui.QFontDatabase.families())
        _FONT = next((f for f in DRAWING_FONTS if f in have), "Arial")
    return _FONT


def cap_ratio(family: str) -> float:
    """How tall a font's capitals are, against its size."""
    probe = QtGui.QFont(family or drawing_font())
    probe.setPixelSize(100)
    measured = QtGui.QFontMetricsF(probe).capHeight()
    return measured / 100.0 if measured > 1e-6 else 0.7


def _em_for(font: QtGui.QFont, cap_height: float) -> float:
    """The font size whose capitals stand ``cap_height`` device units tall.

    A drawing specifies lettering by the height of a capital, which is not
    the font's size - it is roughly seven tenths of it, and exactly what
    depends on the typeface.  Measuring once and correcting beats guessing.
    """
    probe = QtGui.QFont(font)
    probe.setPixelSize(100)
    measured = QtGui.QFontMetricsF(probe).capHeight()
    ratio = (measured / 100.0) if measured > 1e-6 else 0.7
    return max(1.0, cap_height / ratio)


def _text(painter: QtGui.QPainter, layout: Layout, text: str,
          x: float, y: float, height_mm: float, bold: bool = False,
          align: str = "left", colour: Optional[str] = None,
          turn: float = 0.0) -> None:
    """Text placed by its baseline-left corner, in sheet millimetres.

    ``turn`` is how far round it is written, in degrees anticlockwise:
    the value of a dimension up the page runs up the page with it.
    """
    if not text:
        return
    device = layout.to_device(x, y)
    font = painter.font()
    # Pixels, not points.  A point size is interpreted against the paint
    # device's own DPI, so the same call gives one size on a 96 dpi screen
    # and twelve times that in a 1200 dpi PDF - the drawing would print with
    # the lettering swallowing the sheet.  A pixel size is what the layout
    # already speaks in.
    font.setPixelSize(max(1, int(round(_em_for(font, height_mm
                                              * layout.scale)))))
    font.setBold(bold)
    painter.setFont(font)
    if colour:
        painter.setPen(QtGui.QPen(QtGui.QColor(colour)))

    metrics = QtGui.QFontMetricsF(font)
    dx = 0.0
    if align == "centre":
        dx = -metrics.horizontalAdvance(text) / 2.0
    elif align == "right":
        dx = -metrics.horizontalAdvance(text)
    if turn:
        painter.save()
        painter.translate(device[0], device[1])
        painter.rotate(-turn)
        painter.drawText(QtCore.QPointF(dx, 0.0), text)
        painter.restore()
        return
    painter.drawText(QtCore.QPointF(device[0] + dx, device[1]), text)


# ------------------------------------------------------------------- views


KIND_STYLES = {
    hlr.VISIBLE: ("visible", False),
    hlr.OUTLINE: ("outline", False),
    hlr.SMOOTH: ("smooth", False),
    hlr.HIDDEN: ("hidden", True),
    hlr.BEND: ("centre", "chain"),
    hlr.THREAD: ("thread", False),
}

# ISO 128-20 line types, in pen widths
DASHED = [12.0, 3.0]
CHAIN = [24.0, 3.0, 0.5, 3.0]

# hidden first so a visible line drawn over one wins
DRAW_ORDER = (hlr.HIDDEN, hlr.SMOOTH, hlr.THREAD, hlr.OUTLINE, hlr.VISIBLE,
              hlr.BEND)


def _view(painter: QtGui.QPainter, doc: DrawingDocument, sheet: Sheet,
          view: View, layout: Layout, selected: bool = False,
          on_screen: bool = False) -> None:
    projection = view.projection
    if projection is None or not projection.lines:
        if on_screen:
            _placeholder(painter, doc, view, layout)
        return

    # the fill goes down first, so every edge is drawn over it rather than
    # half-buried by it
    _hatch(painter, doc, view, layout)

    for kind in DRAW_ORDER:
        lines = projection.of_kind(kind)
        if not lines:
            continue
        style_name, dashed = KIND_STYLES.get(kind, ("visible", False))
        style = doc.styles.get(style_name, dwg.Style())
        colour = STALE if view.stale else None
        if on_screen and getattr(view, "draft", False):
            colour = DRAFT
        painter.setPen(_pen(layout, style, dashed, colour))
        if view.breaks:
            # a broken view: what is in a band taken out is not drawn,
            # and the rest closes up round it
            for line in lines:
                for p, q in zip(line.points, line.points[1:]):
                    for a, b in dwg.broken_segments(view, p, q):
                        painter.drawLine(
                            QtCore.QPointF(*layout.to_device(
                                view.x + a[0], view.y + a[1])),
                            QtCore.QPointF(*layout.to_device(
                                view.x + b[0], view.y + b[1])))
            continue
        _stroke_cached(painter, layout, view, projection, kind, lines,
                       on_screen)

    if view.breaks:
        style = doc.styles.get("visible", dwg.Style())
        thin = doc.styles.get("dimension", style)
        painter.setPen(_pen(layout, thin, colour=STALE if view.stale
                            else None))
        for points in dwg.break_lines(view):
            path = QtGui.QPainterPath()
            path.moveTo(QtCore.QPointF(*layout.to_device(
                view.x + points[0][0], view.y + points[0][1])))
            for x, y in points[1:]:
                path.lineTo(QtCore.QPointF(*layout.to_device(view.x + x,
                                                             view.y + y)))
            painter.drawPath(path)

    if view.kind == SECTION and len(view.cut) >= 4:
        _cut_line(painter, doc, sheet, view, layout)
    if view.kind == DETAIL and len(view.centre) >= 2:
        _detail_circle(painter, doc, sheet, view, layout)

    _view_label(painter, doc, sheet, view, layout)
    if on_screen and view.stale and not getattr(view, "draft", False):
        # the model changed since it was drawn: said on the view itself,
        # with what to do about it
        box = projection.box
        _text(painter, layout, "Out of date – right-click, Update View",
              view.x, view.y + box[3] + 2.0, 2.5, align="centre",
              colour=STALE)
    if on_screen and getattr(view, "draft", False):
        # outlines for now: the real lines are being worked out
        _text(painter, layout, "Working out the lines…",
              view.x, view.y, 3.0, align="centre", colour=DRAFT_TEXT)
    if selected and on_screen:
        _highlight(painter, view, layout)


def _local_transform(layout: Layout, view: View) -> QtGui.QTransform:
    """The view's own millimetres, Y up, onto the device."""
    s = layout.scale
    return QtGui.QTransform(s, 0.0, 0.0, -s,
                            layout.offset_x + view.x * s,
                            layout.offset_y + (layout.height - view.y) * s)


def _stroke_true(painter: QtGui.QPainter, lines) -> None:
    """Lines in the view's own millimetres, arcs as arcs."""
    point = QtCore.QPointF
    for line in lines:
        arc = getattr(line, "arc", None)
        if arc is not None:
            cx, cy, r, a0, sweep = arc
            box = QtCore.QRectF(cx - r, cy - r, 2.0 * r, 2.0 * r)
            path = QtGui.QPainterPath()
            # Qt measures its angles with Y down; these are Y up
            if abs(sweep) >= 360.0 - 1e-9:
                path.addEllipse(box)
            else:
                path.arcMoveTo(box, -a0)
                path.arcTo(box, -a0, -sweep)
            painter.drawPath(path)
            continue
        if len(line.points) >= 2:
            painter.drawPolyline(QtGui.QPolygonF(
                [point(x, y) for x, y in line.points]))


# A pen at most this many device pixels wide is drawn as Qt's one pixel
# cosmetic line, which has a fast path eight times quicker than a stroked
# one and looks the same at that width.
HAIRLINE_PX = 1.3
THIN_PX = 3.0


def view_polygons(projection, kind: str, lines=None) -> List:
    """Every line of one kind as (polygon, bounds) in the view's own
    millimetres.  Built once per projection and kept on it: the sheet is
    painted on every pan, zoom and drag, and walking a big assembly's
    million points in Python each time took two seconds a repaint."""
    held = getattr(projection, "_polygons", None)
    stamp = (id(projection.lines), len(projection.lines))
    if held is None or held.get("_stamp") != stamp:
        held = {"_stamp": stamp}
        try:
            projection._polygons = held
        except Exception:
            pass
    out = held.get(kind)
    if out is None:
        out = []
        point = QtCore.QPointF
        for line in (lines if lines is not None
                     else projection.of_kind(kind)):
            pts = line.points
            if len(pts) < 2:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            polygon = QtGui.QPolygonF([point(x, y) for x, y in pts])
            out.append((polygon, min(xs), min(ys), max(xs), max(ys)))
        held[kind] = out
    return out


def _stroke_cached(painter: QtGui.QPainter, layout: Layout, view: View,
                   projection, kind: str, lines,
                   on_screen: bool = False) -> None:
    polygons = view_polygons(projection, kind, lines)
    if not polygons:
        return
    pen = QtGui.QPen(painter.pen())
    device_width = pen.widthF()
    scale = layout.scale or 1.0
    if on_screen and device_width <= HAIRLINE_PX:
        pen.setCosmetic(True)
        pen.setWidthF(1.0)
    elif on_screen and device_width <= THIN_PX:
        # a line a pixel or two wide shows no cap and no join, and
        # stroking them round costs three times as much
        pen.setWidthF(device_width / scale)
        pen.setCapStyle(QtCore.Qt.FlatCap)
        pen.setJoinStyle(QtCore.Qt.BevelJoin)
    else:
        # the lines are in millimetres now, so the pen is too; paper and
        # PDF always get the true width
        pen.setWidthF(device_width / scale)
    painter.save()
    painter.setTransform(_local_transform(layout, view), True)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    if not on_screen:
        # paper, PDF and SVG: every circle and arc seen square on goes out
        # as the true curve, sharp at any size and a fraction of the file
        _stroke_true(painter, lines if lines is not None
                     else projection.of_kind(kind))
        painter.restore()
        return
    draw = painter.drawPolyline
    window = None
    device = painter.device()
    if on_screen and device is not None:
        # only what can be seen: a view zoomed into is mostly off screen
        inverse, ok = painter.transform().inverted()
        if ok:
            r = inverse.mapRect(QtCore.QRectF(0, 0, device.width(),
                                              device.height()))
            pad = 2.0 / scale
            window = (r.left() - pad, r.top() - pad,
                      r.right() + pad, r.bottom() + pad)
    if window is None:
        for item in polygons:
            draw(item[0])
    else:
        wx0, wy0, wx1, wy1 = window
        for polygon, x0, y0, x1, y1 in polygons:
            if x1 >= wx0 and x0 <= wx1 and y1 >= wy0 and y0 <= wy1:
                draw(polygon)
    painter.restore()


def _hatch(painter: QtGui.QPainter, doc: DrawingDocument, view: View,
           layout: Layout) -> None:
    """Fill the faces a section cut through.

    Where the lines go is worked out in ``drawing.hatch_lines`` rather than
    here, so that the screen, the PDF and the DXF all fill a face with the
    same lines.  A solid fill is the one exception: there is nothing to work
    out, so the loops go straight to the brush.
    """
    projection = view.projection
    loops = projection.of_kind(hlr.CUT) if projection else []
    if not loops:
        return
    pattern = dwg.hatch_patterns().get(projection.hatch or "steel")
    if pattern is None or (not pattern.angles and not pattern.solid):
        return

    style = doc.styles.get("hatch", dwg.Style())
    colour = QtGui.QColor(STALE if view.stale else style.colour)

    if pattern.solid:
        path = QtGui.QPainterPath()
        path.setFillRule(QtCore.Qt.OddEvenFill)
        for loop in loops:
            piece = QtGui.QPainterPath()
            piece.moveTo(QtCore.QPointF(*layout.to_device(
                view.x + loop.points[0][0], view.y + loop.points[0][1])))
            for x, y in loop.points[1:]:
                piece.lineTo(QtCore.QPointF(*layout.to_device(view.x + x,
                                                              view.y + y)))
            piece.closeSubpath()
            path.addPath(piece)
        if not path.isEmpty():
            painter.fillPath(path, QtGui.QBrush(colour))
        return

    painter.setPen(_pen(layout, style, colour=colour.name()))
    for a, b in dwg.hatch_segments(loops, pattern):
        painter.drawLine(
            QtCore.QPointF(*layout.to_device(view.x + a[0], view.y + a[1])),
            QtCore.QPointF(*layout.to_device(view.x + b[0], view.y + b[1])))


def _placeholder(painter: QtGui.QPainter, doc: DrawingDocument, view: View,
                 layout: Layout) -> None:
    """A view that could not be drawn still has to be findable and movable."""
    pen = QtGui.QPen(QtGui.QColor(SICK))
    pen.setWidthF(1.2)
    pen.setStyle(QtCore.Qt.DashLine)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    half = 20.0
    a = layout.to_device(view.x - half, view.y + half)
    b = layout.to_device(view.x + half, view.y - half)
    painter.drawRect(QtCore.QRectF(a[0], a[1], b[0] - a[0], b[1] - a[1]))
    _text(painter, layout, view.error or "not drawn",
          view.x, view.y, 3.0, align="centre", colour=SICK)


def _highlight(painter: QtGui.QPainter, view: View, layout: Layout) -> None:
    box = view.projection.box if view.projection else (-20, -20, 20, 20)
    pen = QtGui.QPen(QtGui.QColor(SELECTED))
    pen.setWidthF(1.4)
    pen.setStyle(QtCore.Qt.DashLine)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    pad = 3.0
    a = layout.to_device(view.x + box[0] - pad, view.y + box[3] + pad)
    b = layout.to_device(view.x + box[2] + pad, view.y + box[1] - pad)
    painter.drawRect(QtCore.QRectF(a[0], a[1], b[0] - a[0], b[1] - a[1]))


def _view_label(painter: QtGui.QPainter, doc: DrawingDocument, sheet: Sheet,
                view: View, layout: Layout) -> None:
    if not view.label_visible and not view.scale_visible:
        return
    box = view.projection.box if view.projection else (0, 0, 0, 0)
    style = doc.styles.get("text", dwg.Style())
    # A label belongs under the view, and so does a dimension dragged down
    # there.  Whoever is lower wins the space and the label steps below it,
    # rather than the two being written over each other.
    y = min(view.y + box[1], _lowest(sheet, view) + view.y) - 6.0
    if view.label_visible and view.kind in (SECTION, DETAIL):
        _text(painter, layout, view.label, view.x, y, 5.0, bold=True,
              align="centre", colour=style.colour)
        y -= 6.0
    elif view.label_visible and view.name:
        _text(painter, layout, view.name, view.x, y, 3.5, align="centre",
              colour=style.colour)
        y -= 5.0
    if view.scale_visible:
        scale = doc.view_scale(sheet, view)
        _text(painter, layout, dwg.scale_text(scale), view.x, y, 3.0,
              align="centre", colour=style.colour)


def _lowest(sheet: Sheet, view: View) -> float:
    """How far below a view its own annotations reach, in view millimetres."""
    box = view.projection.box if view.projection else (0.0, 0.0, 0.0, 0.0)
    floor = box[1]
    for note in sheet.annotations_for(view.id):
        offset = (list(note.offset) + [0.0, 0.0])[:2]
        for point in note.points:
            if len(point) >= 2:
                floor = min(floor, point[1] + offset[1])
    return floor


def _cut_line(painter: QtGui.QPainter, doc: DrawingDocument, sheet: Sheet,
              view: View, layout: Layout) -> None:
    """The A-A line drawn across the parent, with its arrows."""
    parent = sheet.view(view.parent)
    if parent is None:
        return
    style = doc.styles.get("section", dwg.Style())
    pen = _pen(layout, style)
    pen.setDashPattern([10.0, 3.0, 2.0, 3.0])
    painter.setPen(pen)

    x1, y1, x2, y2 = view.cut[:4]
    s1 = (parent.x + x1, parent.y + y1)
    s2 = (parent.x + x2, parent.y + y2)
    a = layout.to_device(*s1)
    b = layout.to_device(*s2)
    painter.drawLine(QtCore.QPointF(*a), QtCore.QPointF(*b))

    # Arrows square to the line at both ends, pointing the way the section
    # looks, with the letter past each one.  The model looks from the
    # line's left at what is to its right, so that is the way they point.
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    sight = (uy, -ux)
    shaft = max(6.0, style.arrow_size * 2.4)
    thick = _pen(layout, style)
    thick.setWidthF(thick.widthF() * 2.0)
    for end, out in ((s1, -1.0), (s2, 1.0)):
        painter.setPen(thick)
        stub = (end[0] - ux * out * 3.0, end[1] - uy * out * 3.0)
        painter.drawLine(QtCore.QPointF(*layout.to_device(*end)),
                         QtCore.QPointF(*layout.to_device(*stub)))
        painter.setPen(_pen(layout, style))
        tip = (end[0] + sight[0] * shaft, end[1] + sight[1] * shaft)
        d_end = layout.to_device(*end)
        d_tip = layout.to_device(*tip)
        painter.drawLine(QtCore.QPointF(*d_end), QtCore.QPointF(*d_tip))
        _arrow_head(painter, d_tip, d_tip[0] - d_end[0], d_tip[1] - d_end[1],
                    layout.pen_width(style.arrow_size) * 1.6)
        if view.letter:
            at = (tip[0] + sight[0] * 3.5 + ux * out * 2.5,
                  tip[1] + sight[1] * 3.5 + uy * out * 2.5 - 2.0)
            _text(painter, layout, view.letter, at[0], at[1], 5.0,
                  bold=True, align="centre", colour=style.colour)


def _detail_circle(painter: QtGui.QPainter, doc: DrawingDocument, sheet: Sheet,
                   view: View, layout: Layout) -> None:
    parent = sheet.view(view.parent)
    if parent is None:
        return
    style = doc.styles.get("section", dwg.Style())
    pen = _pen(layout, style)
    pen.setStyle(QtCore.Qt.DashLine)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    centre = layout.to_device(parent.x + view.centre[0],
                              parent.y + view.centre[1])
    radius = view.radius * layout.scale
    painter.drawEllipse(QtCore.QPointF(*centre), radius, radius)
    if view.letter:
        _text(painter, layout, view.letter,
              parent.x + view.centre[0],
              parent.y + view.centre[1] + view.radius + 3.0,
              4.0, bold=True, align="centre", colour=style.colour)


def _balloon(painter, doc, sheet, view, note, layout, at, colour) -> None:
    """An item number in a bubble, on a leader pointing at the part.

    The number comes from the sheet's parts list rather than from the
    balloon, so the two cannot drift apart: renumber the list and every
    balloon on the sheet says the new number on the next repaint.
    """
    if len(note.points) < 1:
        return
    style = doc.styles.get("text", dwg.Style())
    tip = note.points[0]
    ox, oy = (note.offset + [0.0, 0.0])[:2]
    seat = (tip[0] + ox, tip[1] + oy)

    number = str(note.text or doc.balloon_number(sheet, note) or "?")
    # wide enough for the number it actually holds, so "12" does not sit
    # squeezed against the bubble the way a fixed radius makes it
    radius = max(3.6, 2.0 + 1.5 * len(number))

    a, b = at(tip), at(seat)
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    painter.setPen(_pen(layout, doc.styles.get("dimension", dwg.Style()),
                        colour=colour))
    painter.setBrush(QtCore.Qt.NoBrush)
    if length > 1e-6:
        # stop the leader at the bubble rather than running under it
        stop = radius * layout.scale
        if length > stop:
            painter.drawLine(
                QtCore.QPointF(a[0], a[1]),
                QtCore.QPointF(b[0] - dx / length * stop,
                               b[1] - dy / length * stop))
        _arrow_head(painter, a, -dx, -dy,
                    layout.pen_width(style.arrow_size) * 1.2)

    centre = QtCore.QPointF(*at(seat))
    device_r = radius * layout.scale
    painter.setBrush(QtGui.QBrush(QtGui.QColor(PAPER)))
    if note.shape == "hex":
        points = [QtCore.QPointF(
            centre.x() + device_r * math.cos(math.radians(30 + 60 * i)),
            centre.y() + device_r * math.sin(math.radians(30 + 60 * i)))
            for i in range(6)]
        painter.drawPolygon(QtGui.QPolygonF(points))
    elif note.shape == "square":
        painter.drawRect(QtCore.QRectF(centre.x() - device_r,
                                       centre.y() - device_r,
                                       device_r * 2, device_r * 2))
    else:
        painter.drawEllipse(centre, device_r, device_r)
    painter.setBrush(QtCore.Qt.NoBrush)

    # sat on the bubble's middle, not its baseline, so the digits look
    # centred in it rather than resting on the bottom of the circle
    _text(painter, layout, number, view.x + seat[0],
          view.y + seat[1] - style.text_height * 0.36, style.text_height,
          bold=True, align="centre", colour=colour)


def _parts_list(painter: QtGui.QPainter, doc: DrawingDocument, sheet: Sheet,
                table: PartsList, layout: Layout,
                selected: bool = False) -> None:
    """The table of what the assembly is made of.

    Drawn from the bottom up with the heading on top, the way a parts list
    sits above a title block: adding a part pushes the table upwards into
    empty paper instead of down through the block.  A long list wrapped
    into sections is drawn as tables side by side, the first on the left,
    each with its own heading.
    """
    sections = table.sections()
    style = doc.styles.get("border", dwg.Style())
    text_style = doc.styles.get("text", dwg.Style())
    colour = SELECTED if selected else style.colour
    x0, y0 = table.origin()
    if not table.rows and not table.heading:
        return
    span = table.section_width()
    thin = doc.styles.get("dimension", dwg.Style())
    longest = max(len(rows) for rows in sections)
    top = y0 + table.height()
    for number, rows in enumerate(sections):
        left = x0 + number * span
        lines = len(rows) + (1 if table.heading else 0)
        if lines <= 0:
            continue
        height = lines * table.row_height
        # every section hangs from the same top line, headings level, and
        # a short last one leaves its empty paper underneath
        y0 = top - height
        painter.setPen(_pen(layout, style, colour=colour))
        painter.setBrush(QtCore.Qt.NoBrush)
        a = layout.to_device(left, y0 + height)
        b = layout.to_device(left + span, y0)
        painter.drawRect(QtCore.QRectF(a[0], a[1], b[0] - a[0], b[1] - a[1]))

        painter.setPen(_pen(layout, thin, colour=colour))
        for i in range(1, lines):
            y = y0 + i * table.row_height
            painter.drawLine(QtCore.QPointF(*layout.to_device(left, y)),
                             QtCore.QPointF(*layout.to_device(left + span,
                                                              y)))
        x = left
        for column in table.columns[:-1]:
            x += table.column_width(column)
            painter.drawLine(QtCore.QPointF(*layout.to_device(x, y0)),
                             QtCore.QPointF(*layout.to_device(x,
                                                              y0 + height)))

        # the first row sits at the bottom, the heading at the top
        for index, row in enumerate(rows):
            y = y0 + (len(rows) - 1 - index) * table.row_height
            _row_text(painter, layout, table, row, left, y,
                      table.text_height, text_style.colour)
        if table.heading:
            y = y0 + len(rows) * table.row_height
            _row_text(painter, layout, table, None, left, y,
                      table.text_height, text_style.colour, bold=True)
    if table.error and not table.rows:
        _text(painter, layout, table.error, x0 + 1.6,
              top - table.height() / 2.0, table.text_height, colour=SICK)


def _hole_tags(painter, doc, sheet, table, layout) -> None:
    """A hole table's tags beside its holes, and its datum: two short
    arrows out from the point the dimensions are measured from."""
    view = sheet.view(table.view)
    if view is None:
        return
    text_style = doc.styles.get("text", dwg.Style())
    style = doc.styles.get("dimension", dwg.Style())
    h = max(2.0, table.text_height * 0.85)
    for row in table.rows:
        try:
            x = float(row.extra.get("_x", ""))
            y = float(row.extra.get("_y", ""))
        except ValueError:
            continue
        try:
            r = float(row.extra.get("_r", "0") or 0.0)
        except ValueError:
            r = 0.0
        # up and right of the hole, clear of its edge
        clear = r * 0.7071 + 0.8
        _text(painter, layout, row.extra.get("HOLE", ""),
              view.x + x + clear, view.y + y + clear, h,
              colour=text_style.colour)
    ox, oy = view.x + table.datum[0], view.y + table.datum[1]
    pen = _pen(layout, style)
    painter.setPen(pen)
    reach = 8.0
    for ex, ey in ((reach, 0.0), (0.0, reach)):
        tip = layout.to_device(ox + ex, oy + ey)
        painter.drawLine(QtCore.QPointF(*layout.to_device(ox, oy)),
                         QtCore.QPointF(*tip))
        _arrow_head(painter, tip, tip[0] - layout.to_device(ox, oy)[0],
                    tip[1] - layout.to_device(ox, oy)[1],
                    layout.pen_width(style.arrow_size) * 1.2)
    _text(painter, layout, "X", ox + reach + 1.0, oy - 1.0, 2.5,
          colour=style.colour)
    _text(painter, layout, "Y", ox - 1.0, oy + reach + 1.0, 2.5,
          colour=style.colour)


def _row_text(painter, layout, table, row, x0: float, y: float,
              height: float, colour: str, bold: bool = False) -> None:
    """One line of a parts list, each value in its own column."""
    from ..core import bom as bom_module

    x = x0
    baseline = y + (table.row_height - height) / 2.0 + height * 0.15
    for column in table.columns:
        span = table.column_width(column)
        text = (bom_module.heading(column) if row is None
                else row.value(column))
        # numbers in the middle of their box, words against the left of it
        if column in ("item", "qty"):
            _text(painter, layout, text, x + span / 2.0, baseline, height,
                  bold=bold, align="centre", colour=colour)
        else:
            _text(painter, layout, _elide(text, span - 3.0, height),
                  x + 1.6, baseline, height, bold=bold, align="left",
                  colour=colour)
        x += span


def _elide(text: str, width_mm: float, height_mm: float) -> str:
    """Cut text that will not fit its column, rather than let it run over."""
    if not text:
        return ""
    # a rough average character width for the font, which is enough: the
    # point is to keep a long description out of the next column, not to
    # fill the box to the last hundredth of a millimetre
    per = height_mm * 0.78
    room = max(1, int(width_mm / per))
    return text if len(text) <= room else text[:max(1, room - 1)] + "…"


def _arrow_head(painter: QtGui.QPainter, tip: Sequence[float],
                dx: float, dy: float, size: float) -> None:
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return
    ux, uy = dx / length, dy / length
    back = (tip[0] - ux * size, tip[1] - uy * size)
    side = (-uy * size * 0.32, ux * size * 0.32)
    head = QtGui.QPolygonF([
        QtCore.QPointF(tip[0], tip[1]),
        QtCore.QPointF(back[0] + side[0], back[1] + side[1]),
        QtCore.QPointF(back[0] - side[0], back[1] - side[1]),
    ])
    painter.setBrush(QtGui.QBrush(painter.pen().color()))
    painter.drawPolygon(head)
    painter.setBrush(QtCore.Qt.NoBrush)


# ------------------------------------------------------------- annotations


def _annotation(painter: QtGui.QPainter, doc: DrawingDocument, sheet: Sheet,
                note: Annotation, layout: Layout,
                selected: bool = False) -> None:
    view = sheet.view(note.view)
    if view is None:
        return
    if view.breaks:
        # drawn where the broken view puts it, reading the true value
        note = dwg.broken_note(note, view, doc.view_scale(sheet, view))
    style = doc.styles.get("dimension", dwg.Style())
    colour = SICK if note.sick else (SELECTED if selected
                                     else style.colour)

    def at(point: Sequence[float]) -> Tuple[float, float]:
        return layout.to_device(view.x + point[0], view.y + point[1])

    painter.setPen(_pen(layout, style, colour=colour))
    painter.setBrush(QtCore.Qt.NoBrush)

    if note.kind in (dwg.CENTRE_MARK, dwg.CENTRELINE):
        _centre_mark(painter, doc, note, layout, at, colour)
        return
    if note.kind in (NOTE, LEADER):
        _note(painter, doc, view, note, layout, at, colour)
        return
    if note.kind == BALLOON:
        _balloon(painter, doc, sheet, view, note, layout, at, colour)
        return
    if note.kind == dwg.WELD:
        _weld(painter, doc, view, note, layout, at, colour)
        return
    if note.kind in (dwg.SURFACE, dwg.FCF, dwg.DATUM_ID):
        _symbol(painter, doc, view, note, layout, at, colour)
        return
    if note.kind in (RADIUS, DIAMETER):
        _radial(painter, doc, sheet, view, note, layout, at, colour)
        return
    if note.kind == ANGULAR:
        _angular(painter, doc, sheet, view, note, layout, at, colour)
        return
    if note.kind == dwg.ORDINATE and note.axis:
        _ordinate(painter, doc, sheet, view, note, layout, at, colour)
        return
    _linear(painter, doc, sheet, view, note, layout, at, colour)


def _ordinate(painter, doc, sheet, view, note, layout, at, colour) -> None:
    """One ordinate: a leader from the point out to where the set lines
    up, and its distance from the datum at the end, as Inventor draws
    them: up the page for one measured across it, across for one up it."""
    if len(note.points) < 2:
        return
    style = doc.styles.get("dimension", dwg.Style())
    p = note.points[1]
    ox, oy = (list(note.offset) + [0.0, 0.0])[:2]
    if note.axis == "x":
        end = (p[0], p[1] + oy)
        way = (0.0, 1.0 if oy >= 0 else -1.0)
    else:
        end = (p[0] + ox, p[1])
        way = (1.0 if ox >= 0 else -1.0, 0.0)
    gap = 1.0
    if math.dist(p, end) > gap:
        painter.drawLine(
            QtCore.QPointF(*at((p[0] + way[0] * gap, p[1] + way[1] * gap))),
            QtCore.QPointF(*at(end)))
    scale = doc.view_scale(sheet, view)
    text = note.caption(scale)
    reach = len(text) * _size(style, note) * 0.32 + 1.0
    if note.axis == "x":
        _text(painter, layout, text, view.x + end[0] - 0.4,
              view.y + end[1] + way[1] * reach, _size(style, note),
              align="centre", colour=colour, turn=90.0)
    else:
        _text(painter, layout, text, view.x + end[0] + way[0] * reach,
              view.y + end[1] - _size(style, note) * 0.4,
              _size(style, note), align="centre", colour=colour)


def _size(style, note) -> float:
    """A dimension's text height: its own, set in Edit Dimension, or the
    dimension style's."""
    own = getattr(note, "size", 0.0) or 0.0
    return own if own > 0 else style.text_height


def _linear(painter, doc, sheet, view, note, layout, at, colour) -> None:
    """A distance, with witness lines back to the points it measures."""
    if len(note.points) < 2:
        return
    style = doc.styles.get("dimension", dwg.Style())
    p1, p2 = note.points[0], note.points[1]
    a, b, label = dwg.dimension_line(note)
    witness = ((p1[0], p1[1]), (p2[0], p2[1]))

    painter.drawLine(QtCore.QPointF(*at(a)), QtCore.QPointF(*at(b)))
    # Extension lines, the way a drawing has them: a small gap off the
    # part, so they do not read as part of it, and on a little past the
    # dimension line, so the arrow has something to land on
    gap, past = 1.0, 1.5
    for start, end in zip(witness, (a, b)):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= gap:
            continue
        ux, uy = dx / length, dy / length
        painter.drawLine(
            QtCore.QPointF(*at((start[0] + ux * gap, start[1] + uy * gap))),
            QtCore.QPointF(*at((end[0] + ux * past, end[1] + uy * past))))

    size = layout.pen_width(style.arrow_size) * 1.4
    da = at(a)
    db = at(b)
    _arrow_head(painter, da, da[0] - db[0], da[1] - db[1], size)
    _arrow_head(painter, db, db[0] - da[0], db[1] - da[1], size)

    scale = doc.view_scale(sheet, view)
    # the value sits along its line, just off it, the way it reads: across
    # the page for one across it, up the page for one up it, and along a
    # slanting one, never upside down
    angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    if angle > 90.0 + 1e-6:
        angle -= 180.0
    elif angle <= -90.0 + 1e-6:
        angle += 180.0
    lift = math.radians(angle + 90.0)
    # the points are in the view's own millimetres; text is placed on the
    # sheet, so it has to be carried across like every line above it
    _text(painter, layout, note.caption(scale),
          view.x + label[0] + math.cos(lift) * 1.2,
          view.y + label[1] + math.sin(lift) * 1.2,
          _size(style, note), align="centre", colour=colour, turn=angle)


def _radial(painter, doc, sheet, view, note, layout, at, colour) -> None:
    if len(note.points) < 2:
        return
    style = doc.styles.get("dimension", dwg.Style())
    centre, rim = note.points[0], note.points[1]
    ox, oy = (note.offset + [0.0, 0.0])[:2]
    tip = at(rim)
    tail = at((rim[0] + ox, rim[1] + oy))
    painter.drawLine(QtCore.QPointF(*tip), QtCore.QPointF(*tail))
    _arrow_head(painter, tip, tip[0] - tail[0], tip[1] - tail[1],
                layout.pen_width(style.arrow_size) * 1.4)
    scale = doc.view_scale(sheet, view)
    _text(painter, layout, note.caption(scale),
          view.x + rim[0] + ox, view.y + rim[1] + oy + 1.2,
          _size(style, note), align="left", colour=colour)


def _angular(painter, doc, sheet, view, note, layout, at, colour) -> None:
    if len(note.points) >= 4:
        _between_lines(painter, doc, view, note, layout, at, colour)
        return
    if len(note.points) < 3:
        return
    style = doc.styles.get("dimension", dwg.Style())
    a, vertex, b = note.points[0], note.points[1], note.points[2]
    radius = max(6.0, (note.offset + [0.0, 12.0])[1])
    start = math.atan2(a[1] - vertex[1], a[0] - vertex[0])
    end = math.atan2(b[1] - vertex[1], b[0] - vertex[0])
    for point in (a, b):
        painter.drawLine(QtCore.QPointF(*at(vertex)), QtCore.QPointF(*at(point)))

    steps = 24
    path = QtGui.QPainterPath()
    sweep = end - start
    while sweep > math.pi:
        sweep -= 2 * math.pi
    while sweep < -math.pi:
        sweep += 2 * math.pi
    for i in range(steps + 1):
        angle = start + sweep * i / steps
        point = at((vertex[0] + math.cos(angle) * radius,
                    vertex[1] + math.sin(angle) * radius))
        if i == 0:
            path.moveTo(QtCore.QPointF(*point))
        else:
            path.lineTo(QtCore.QPointF(*point))
    painter.drawPath(path)

    mid = start + sweep / 2.0
    _text(painter, layout, note.caption(1.0),
          view.x + vertex[0] + math.cos(mid) * (radius + 3.0),
          view.y + vertex[1] + math.sin(mid) * (radius + 3.0),
          _size(style, note), align="centre", colour=colour)


def _between_lines(painter, doc, view, note, layout, at, colour) -> None:
    """The angle between two lines: an arc across it, at the label."""
    found = dwg.between_lines(note.points, note.offset)
    if found is None:
        return
    style = doc.styles.get("dimension", dwg.Style())
    vertex, first, second, degrees = found
    ox, oy = (note.offset + [0.0, 0.0])[:2]
    radius = max(4.0, math.hypot(ox, oy))
    start = math.atan2(first[1], first[0])
    sweep = math.atan2(first[0] * second[1] - first[1] * second[0],
                       first[0] * second[0] + first[1] * second[1])
    steps = 32
    path = QtGui.QPainterPath()
    for i in range(steps + 1):
        angle = start + sweep * i / steps
        point = at((vertex[0] + math.cos(angle) * radius,
                    vertex[1] + math.sin(angle) * radius))
        if i == 0:
            path.moveTo(QtCore.QPointF(*point))
        else:
            path.lineTo(QtCore.QPointF(*point))
    painter.drawPath(path)
    # each line carried out to the arc where it stops short of it
    for (x, y), pair in ((first, note.points[0:2]), (second, note.points[2:4])):
        reach = max(math.hypot(p[0] - vertex[0], p[1] - vertex[1])
                    for p in pair)
        if reach < radius:
            near = max(pair, key=lambda p: (p[0] - vertex[0]) * x
                       + (p[1] - vertex[1]) * y)
            painter.drawLine(QtCore.QPointF(*at(near)), QtCore.QPointF(
                *at((vertex[0] + x * (radius + 1.5),
                     vertex[1] + y * (radius + 1.5)))))
    size = layout.pen_width(style.arrow_size) * 1.4
    for angle, turn in ((start, 1.0), (start + sweep, -1.0)):
        tip = at((vertex[0] + math.cos(angle) * radius,
                  vertex[1] + math.sin(angle) * radius))
        # the arrow lies along the arc, pointing out at the line
        tangent = (-math.sin(angle) * turn * math.copysign(1.0, sweep),
                   math.cos(angle) * turn * math.copysign(1.0, sweep))
        _arrow_head(painter, tip, -tangent[0], tangent[1], size)
    middle = start + sweep / 2.0
    _text(painter, layout, note.caption(1.0),
          view.x + vertex[0] + math.cos(middle) * (radius + 3.5),
          view.y + vertex[1] + math.sin(middle) * (radius + 3.5),
          _size(style, note), align="centre", colour=colour)


def _weld(painter, doc, view, note, layout, at, colour) -> None:
    """ISO 2553: an arrow to the joint, a reference line, the weld's
    symbol on it (under the line for the arrow side, over it for the
    other), its size before and its length after; a circle at the knee
    for all round, a flag for a weld made on site."""
    if not note.points:
        return
    style = doc.styles.get("dimension", dwg.Style())
    h = doc.styles.get("text", dwg.Style()).text_height \
        * (getattr(note, "scale", 1.0) or 1.0)
    pen = _pen(layout, style, colour=colour)
    kind, size, length, flags = dwg.weld_parts(note.text)
    p = note.points[0]
    ox, oy = (list(note.offset) + [0.0, 0.0])[:2]
    if getattr(note, "flip", False):
        # mirrored: the arrow comes in from the other side, and the
        # reference line runs back the other way from its knee
        ox = -ox
    knee = (p[0] + ox, p[1] + oy)
    way = 1.0 if ox >= 0 else -1.0
    span = 8.0 + h * 0.62 * (len(size) + len(length)) + h * 2.0
    end = (knee[0] + way * span, knee[1])

    def line(a, b):
        painter.setPen(pen)
        painter.drawLine(QtCore.QPointF(*at(a)), QtCore.QPointF(*at(b)))

    line(p, knee)
    tip, tail = at(p), at(knee)
    _arrow_head(painter, tip, tip[0] - tail[0], tip[1] - tail[1],
                layout.pen_width(style.arrow_size) * 1.4)
    line(knee, end)
    side = 1.0 if "other" in flags else -1.0      # over the line, or under
    s = h * 1.2
    mid = knee[0] + way * (3.0 + h * 0.62 * len(size) + s)
    if kind == "fillet":
        line((mid - s / 2, knee[1]), (mid - s / 2, knee[1] + side * s))
        line((mid - s / 2, knee[1] + side * s), (mid + s / 2, knee[1]))
    elif kind == "v_butt":
        line((mid - s / 2, knee[1] + side * s), (mid, knee[1]))
        line((mid, knee[1]), (mid + s / 2, knee[1] + side * s))
    elif kind == "bevel":
        line((mid - s / 2, knee[1]), (mid - s / 2, knee[1] + side * s))
        line((mid - s / 2, knee[1]), (mid + s / 2, knee[1] + side * s))
    elif kind == "square_butt":
        line((mid - s / 4, knee[1]), (mid - s / 4, knee[1] + side * s))
        line((mid + s / 4, knee[1]), (mid + s / 4, knee[1] + side * s))
    elif kind == "plug":
        a = at((mid - s / 2, knee[1] + side * s * 0.6))
        b = at((mid + s / 2, knee[1]))
        painter.setPen(pen)
        painter.drawRect(QtCore.QRectF(QtCore.QPointF(*a),
                                       QtCore.QPointF(*b)).normalized())
    else:       # spot: a circle on the line
        r = s * 0.45 * layout.scale
        painter.setPen(pen)
        painter.drawEllipse(QtCore.QPointF(*at((mid, knee[1]))), r, r)
    base = knee[1] + (side * s * 0.25 if side > 0 else -s * 0.9)
    if size:
        _text(painter, layout, size, view.x + mid - way * (s / 2 + 1.0),
              view.y + base, h, align="right" if way > 0 else "left",
              colour=colour)
    if length:
        _text(painter, layout, length, view.x + mid + way * (s / 2 + 1.0),
              view.y + base, h, align="left" if way > 0 else "right",
              colour=colour)
    if "all_around" in flags:
        r = h * 0.55 * layout.scale
        painter.setPen(pen)
        painter.drawEllipse(QtCore.QPointF(*at(knee)), r, r)
    if "field" in flags:
        top = (knee[0], knee[1] + h * 2.2)
        line(knee, top)
        flag = [at(top), at((knee[0] + way * h * 1.4, top[1] - h * 0.45)),
                at((knee[0], top[1] - h * 0.9))]
        painter.setBrush(QtGui.QColor(colour))
        painter.drawPolygon(QtGui.QPolygonF(
            [QtCore.QPointF(*c) for c in flag]))
        painter.setBrush(QtCore.Qt.NoBrush)


def _symbol(painter, doc, view, note, layout, at, colour) -> None:
    """Surface texture, a feature control frame or a datum identifier,
    drawn the ISO way, standing on the edge it was put on or at the end
    of a leader from it."""
    if not note.points:
        return
    style = doc.styles.get("dimension", dwg.Style())
    text_style = doc.styles.get("text", dwg.Style())
    grow = getattr(note, "scale", 1.0) or 1.0
    h = text_style.text_height * grow
    pen = _pen(layout, style, colour=colour)
    p = note.points[0]
    ox, oy = (list(note.offset) + [0.0, 0.0])[:2]
    base = (p[0] + ox, p[1] + oy)
    turn = float(getattr(note, "turn", 0.0) or 0.0)
    flip = bool(getattr(note, "flip", False))
    cos_t, sin_t = math.cos(math.radians(turn)), math.sin(math.radians(turn))

    def T(q):
        """A point of the symbol as drawn upright, turned and mirrored
        about where it stands (#368)."""
        dx, dy = q[0] - base[0], q[1] - base[1]
        if flip:
            dx = -dx
        return (base[0] + dx * cos_t - dy * sin_t,
                base[1] + dx * sin_t + dy * cos_t)

    def line(a, b):
        painter.setPen(pen)
        painter.drawLine(QtCore.QPointF(*at(a)), QtCore.QPointF(*at(b)))

    def tline(a, b):
        line(T(a), T(b))

    def cell_box(a, b):
        corners = [T(a), T((b[0], a[1])), T(b), T((a[0], b[1]))]
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawPolygon(QtGui.QPolygonF(
            [QtCore.QPointF(*at(c)) for c in corners]))

    def text(words, left, right_end, y, height, centre=False):
        """Words in the symbol's own frame, between ``left`` and
        ``right_end`` along it on the baseline ``y``: turned with it,
        never mirrored, and never upside down, as Inventor keeps them."""
        middle = T(((left + right_end) / 2.0, y + height / 2.0))
        reads = (turn + 180.0) % 360.0 - 180.0
        if reads > 90.0:
            reads -= 180.0
        elif reads <= -90.0:
            reads += 180.0
        up = (-math.sin(math.radians(reads)), math.cos(math.radians(reads)))
        spot = (middle[0] - up[0] * height / 2.0,
                middle[1] - up[1] * height / 2.0)
        _text(painter, layout, words, view.x + spot[0], view.y + spot[1],
              height, align="centre", colour=colour, turn=reads)

    if note.kind == dwg.SURFACE:
        if math.hypot(ox, oy) > 1e-6:
            line(p, base)
            tip, tail = at(p), at(base)
            _arrow_head(painter, tip, tip[0] - tail[0], tip[1] - tail[1],
                        layout.pen_width(style.arrow_size) * 1.4)
        size = h * 1.6
        left = (base[0] - size * 0.58, base[1] + size)
        right = (base[0] + size * 1.15, base[1] + size * 2.0)
        tline(base, left)
        tline(base, right)
        if note.shape == dwg.SURFACE_REMOVAL:
            # the bar that closes the triangle: machined
            tline(left, (base[0] + size * 0.58, base[1] + size))
        elif note.shape == dwg.SURFACE_NO_REMOVAL:
            centre = at(T((base[0], base[1] + size * 0.62)))
            r = size * 0.36 * layout.scale
            painter.setPen(pen)
            painter.drawEllipse(QtCore.QPointF(*centre), r, r)
        if note.text:
            reach = len(note.text) * h * 0.62 + 1.0
            tline(right, (right[0] + reach, right[1]))
            text(note.text, right[0] + 0.6, right[0] + reach - 0.4,
                 right[1] + 0.8, h)
        return

    if note.kind == dwg.DATUM_ID:
        box = h * 2.4
        # the filled triangle standing on the edge, and the box out from it
        tri = h * 0.9
        way = (ox, oy) if math.hypot(ox, oy) > 1e-6 else (0.0, 1.0)
        n = math.hypot(*way)
        ux, uy = way[0] / n, way[1] / n
        sx, sy = -uy, ux
        apex = (p[0] + ux * tri, p[1] + uy * tri)
        corners = [at((p[0] + sx * tri * 0.6, p[1] + sy * tri * 0.6)),
                   at((p[0] - sx * tri * 0.6, p[1] - sy * tri * 0.6)),
                   at(apex)]
        painter.setPen(pen)
        painter.setBrush(QtGui.QColor(colour))
        painter.drawPolygon(QtGui.QPolygonF(
            [QtCore.QPointF(*c) for c in corners]))
        painter.setBrush(QtCore.Qt.NoBrush)
        centre = (p[0] + ux * (max(n, tri) + box / 2.0),
                  p[1] + uy * (max(n, tri) + box / 2.0))
        line(apex, (centre[0] - ux * box / 2.0, centre[1] - uy * box / 2.0))
        a = at((centre[0] - box / 2.0, centre[1] + box / 2.0))
        b = at((centre[0] + box / 2.0, centre[1] - box / 2.0))
        painter.setPen(pen)
        painter.drawRect(QtCore.QRectF(a[0], a[1], b[0] - a[0], b[1] - a[1]))
        _text(painter, layout, note.text or "A", view.x + centre[0],
              view.y + centre[1] - h * 0.5, h, align="centre", colour=colour)
        return

    # a feature control frame: a leader to the feature, then its boxes
    cells = dwg.fcf_cells(note.text)
    if not cells:
        return
    if math.hypot(ox, oy) > 1e-6:
        line(p, base)
        tip, tail = at(p), at(base)
        _arrow_head(painter, tip, tip[0] - tail[0], tip[1] - tail[1],
                    layout.pen_width(style.arrow_size) * 1.4)
    tall = h * 2.4
    x = base[0]
    top, bottom = base[1] + tall / 2.0, base[1] - tall / 2.0
    widths = [tall if index == 0 else max(tall, len(cell) * h * 0.78 + 2.0)
              for index, cell in enumerate(cells)]
    # A frame reads left to right whichever way it is put: mirrored, or
    # turned past upright, it runs back from the leader with its cells
    # taken in the other order, so the characteristic still comes first.
    backwards = (-1.0 if flip else 1.0) * cos_t < -1e-9
    order = list(enumerate(cells))
    if backwards:
        order.reverse()
    for index, cell in order:
        width = widths[index]
        cell_box((x, top), (x + width, bottom))
        text(cell, x, x + width, base[1] - h * 0.5,
             h * (1.15 if index == 0 else 1.0), centre=True)
        x += width


def _centre_mark(painter, doc, note, layout, at, colour) -> None:
    if not note.points:
        return
    style = doc.styles.get("centre", dwg.Style())
    pen = _pen(layout, style, colour=colour)
    pen.setDashPattern([8.0, 2.0, 1.5, 2.0])
    painter.setPen(pen)
    if note.kind == dwg.CENTRELINE and len(note.points) >= 2:
        painter.drawLine(QtCore.QPointF(*at(note.points[0])),
                         QtCore.QPointF(*at(note.points[1])))
        return
    centre = note.points[0]
    reach = max(3.0, note.value or 6.0)
    for dx, dy in ((reach, 0.0), (0.0, reach)):
        painter.drawLine(
            QtCore.QPointF(*at((centre[0] - dx, centre[1] - dy))),
            QtCore.QPointF(*at((centre[0] + dx, centre[1] + dy))))


def _note(painter, doc, view, note, layout, at, colour) -> None:
    style = doc.styles.get("text", dwg.Style())
    if not note.points:
        return
    anchor = note.points[0]
    ox, oy = (note.offset + [0.0, 0.0])[:2]
    if note.kind == LEADER and len(note.points) >= 1:
        painter.drawLine(QtCore.QPointF(*at(anchor)),
                         QtCore.QPointF(*at((anchor[0] + ox, anchor[1] + oy))))
        tip = at(anchor)
        tail = at((anchor[0] + ox, anchor[1] + oy))
        _arrow_head(painter, tip, tip[0] - tail[0], tip[1] - tail[1],
                    layout.pen_width(style.arrow_size) * 1.4)
    # Format Text's font, size and look; the properties in it filled in
    height = note.size or style.text_height
    text = dwg.fill_properties(note.text or "", _values())
    font = painter.font()
    if note.font:
        font.setFamily(note.font)
    font.setItalic(note.italic)
    painter.setFont(font)
    x = view.x + anchor[0] + ox
    y = view.y + anchor[1] + oy + 1.2
    if note.kind == LEADER:
        # the landing: a short line under the text, as Inventor's leader
        land = at((anchor[0] + ox, anchor[1] + oy))
        painter.drawLine(QtCore.QPointF(*land),
                         QtCore.QPointF(land[0] + 3.0 * layout.scale,
                                        land[1]))
        x += 4.0
        y -= 1.2 + height * 0.3
    for index, line in enumerate(text.split(chr(10))):
        _text(painter, layout, line, x, y - index * height * 1.5, height,
              bold=note.bold, align=note.align or "left", colour=colour)
    font.setItalic(False)
    painter.setFont(font)
