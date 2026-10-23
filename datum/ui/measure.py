"""Measure, the Inventor way: two picks, and what lies between them.

Points, edges and faces are all pickable at once, the nearest under the
cursor winning, so a corner gives a point and the middle of a face gives
the face, with no mode to choose first.  One pick says what it is: where a
point is, how long an edge is and its diameter if round, a face's area and
its diameter if round.  Two picks say how far apart they are, the shortest
way, with that distance split into X, Y and Z, and the angle between them
when both are flat faces or straight edges.  A third pick starts again.
In the view a line runs between the two nearest points, with the distance
on it.

M opens it, as in Inventor.  It works in parts and assemblies, where a pick
on a component is measured where the component sits.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import kernel
from ..core import units as unitlib
from . import icons
from .theme import C

PICKS = 2


def closest(a, b) -> Optional[Tuple[float, Tuple[float, ...], Tuple[float, ...]]]:
    """The shortest distance between two shapes, and the two points it is
    between, one on each."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    try:
        probe = BRepExtrema_DistShapeShape(a, b)
        if not probe.IsDone() or probe.NbSolution() < 1:
            return None
        pa, pb = probe.PointOnShape1(1), probe.PointOnShape2(1)
        return (probe.Value(), (pa.X(), pa.Y(), pa.Z()),
                (pb.X(), pb.Y(), pb.Z()))
    except Exception:                                   # noqa: BLE001
        return None


def describe(shape) -> Tuple[str, List[Tuple[str, float, str]]]:
    """What a pick is, and its own measures: (kind, [(name, value, unit
    kind)]) with unit kind "length", "area" or "point"."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
    from OCP.TopoDS import TopoDS

    from ..core.constraints3d import AXIS, frame_from_shape

    kind = shape.ShapeType()
    frame = frame_from_shape(shape)
    if kind == TopAbs_VERTEX:
        return "Point", [("at", 0.0, "point")]
    if kind == TopAbs_EDGE:
        out = [("Length", kernel.edge_length(TopoDS.Edge_s(shape)),
                "length")]
        if frame is not None and frame.kind == AXIS and frame.radius > 0:
            out.append(("Diameter", 2.0 * frame.radius, "length"))
            return "Circular edge", out
        return "Edge", out
    if kind == TopAbs_FACE:
        out = [("Area", kernel.face_area(TopoDS.Face_s(shape)), "area")]
        if frame is not None and frame.kind == AXIS and frame.radius > 0:
            out.append(("Diameter", 2.0 * frame.radius, "length"))
            return "Round face", out
        return "Face", out
    return "Shape", []


def angle_between(a, b) -> Optional[float]:
    """Degrees between two flat faces or two straight edges, else None."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_CurveType
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopoDS import TopoDS

    from ..core.constraints3d import PLANE, frame_from_shape

    def way(shape):
        if shape.ShapeType() == TopAbs_FACE:
            frame = frame_from_shape(shape)
            if frame is not None and frame.kind == PLANE:
                return "face", frame.direction
            return None
        if shape.ShapeType() == TopAbs_EDGE:
            try:
                curve = BRepAdaptor_Curve(TopoDS.Edge_s(shape))
                if curve.GetType() != GeomAbs_CurveType.GeomAbs_Line:
                    return None
                d = curve.Line().Direction()
                return "edge", (d.X(), d.Y(), d.Z())
            except Exception:                           # noqa: BLE001
                return None
        return None

    first, second = way(a), way(b)
    if first is None or second is None or first[0] != second[0]:
        return None
    dot = sum(first[1][i] * second[1][i] for i in range(3))
    dot = max(-1.0, min(1.0, dot))
    if first[0] == "edge":
        dot = abs(dot)              # a line has no way round
    return math.degrees(math.acos(dot))


class MeasureDialog(QtWidgets.QDialog):
    """Two picks, measured: see the module's note."""

    def __init__(self, host, parent=None) -> None:
        super().__init__(parent or host)
        self.host = host
        self.picks: List = []
        self._drawn: List = []
        self.setWindowTitle("Measure")
        self.setWindowIcon(icons.icon("measure", 24))
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint
                            | QtCore.Qt.WindowCloseButtonHint)
        self.setMinimumWidth(320)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        hint = QtWidgets.QLabel(
            "Pick a point, an edge or a face, then a second one. A third "
            "pick starts again.")
        hint.setWordWrap(True)
        hint.setProperty("hint", True)
        layout.addWidget(hint)

        self.readout = QtWidgets.QPlainTextEdit()
        self.readout.setReadOnly(True)
        self.readout.setMinimumHeight(170)
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.readout.setFont(mono)
        layout.addWidget(self.readout, 1)

        row = QtWidgets.QHBoxLayout()
        restart = QtWidgets.QPushButton("Restart")
        restart.setToolTip("Forget both picks")
        restart.clicked.connect(self.restart)
        copy = QtWidgets.QPushButton("Copy")
        copy.setToolTip("Copy what is measured, to paste elsewhere")
        copy.clicked.connect(self.copy)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(restart)
        row.addWidget(copy)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)

        viewport = self.host.viewport
        self._previous_mode = viewport.selection_mode
        viewport.set_selection_mode("measure")
        viewport.clear_selection()
        self.refresh()

    # -- picking --------------------------------------------------------------

    def on_selection(self) -> None:
        """A pick in the view: the next of the two, or a fresh start."""
        shapes = self.host.viewport.selected_shapes()
        if not shapes:
            return
        shape = shapes[-1]
        if len(self.picks) >= PICKS:
            self.picks = []
        if not any(shape.IsSame(p) for p in self.picks):
            self.picks.append(shape)
        self.refresh()

    def restart(self) -> None:
        self.picks = []
        self.host.viewport.clear_selection()
        self.refresh()

    # -- what is shown --------------------------------------------------------

    def _unit(self) -> str:
        document = getattr(self.host, "active_document", None)
        return unitlib.known(getattr(document, "units", "mm") or "mm")

    def lines(self) -> List[str]:
        """The readout, line by line."""
        unit = self._unit()

        def length(v: float) -> str:
            return unitlib.length_text(v, unit, 6)

        def number(v: float) -> str:
            return unitlib.fmt(unitlib.to_unit(v, unit), 6)

        if not self.picks:
            return ["Select geometry in the view: a point, an edge or a "
                    "face."]
        out = []
        for index, shape in enumerate(self.picks):
            kind, measures = describe(shape)
            out.append("%s  %s" % ("First " if index == 0 else "Second",
                                   kind))
            for name, value, sort in measures:
                if sort == "point":
                    p = kernel.shape_centre(shape)
                    out.append("    X %s   Y %s   Z %s" % tuple(
                        number(c) for c in p))
                elif sort == "area":
                    out.append("    %s %s" % (name, unitlib.area_text(
                        value, unit, 6)))
                else:
                    out.append("    %s %s" % (name, length(value)))
        if len(self.picks) == PICKS:
            found = closest(*self.picks)
            out.append("")
            if found is None:
                out.append("These two cannot be measured between.")
            else:
                distance, pa, pb = found
                delta = [pb[i] - pa[i] for i in range(3)]
                out.append("Distance  %s" % length(distance))
                out.append("    dX %s   dY %s   dZ %s" % tuple(
                    number(abs(c)) for c in delta))
                angle = angle_between(*self.picks)
                if angle is not None:
                    out.append("Angle     %s deg" % unitlib.fmt(angle, 4))
        elif len(self.picks) == 1:
            out.append("")
            out.append("Pick a second one to measure between them.")
        return out

    def refresh(self) -> None:
        self.readout.setPlainText("\n".join(self.lines()))
        self._draw()

    def copy(self) -> None:
        QtWidgets.QApplication.clipboard().setText(
            self.readout.toPlainText())

    def _draw(self) -> None:
        """The line between the two nearest points, with the distance on it."""
        viewport = self.host.viewport
        viewport.remove_drawn(self._drawn)
        self._drawn = []
        if len(self.picks) != PICKS:
            viewport.redraw()
            return
        found = closest(*self.picks)
        if found is None:
            viewport.redraw()
            return
        distance, pa, pb = found
        with viewport.collecting() as drawn:
            viewport.draw_point(pa, C.annotation, 4.0)
            viewport.draw_point(pb, C.annotation, 4.0)
            if distance > 1e-9:
                viewport.draw_edge(pa, pb, C.annotation, 2.4, dashed=True)
            middle = [(pa[i] + pb[i]) / 2.0 for i in range(3)]
            viewport.draw_text(unitlib.length_text(distance, self._unit(), 6),
                               middle, C.annotation, 16.0)
        # over the model, as Inventor draws it: a line from corner to
        # corner of a box runs through the box
        viewport.on_top(drawn)
        self._drawn = drawn
        viewport.redraw()

    # -- going ------------------------------------------------------------------

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        viewport = self.host.viewport
        viewport.remove_drawn(self._drawn)
        self._drawn = []
        viewport.set_selection_mode(self._previous_mode or "face")
        viewport.clear_selection()
        if getattr(self.host, "measure_dialog", None) is self:
            self.host.measure_dialog = None
        super().closeEvent(event)
