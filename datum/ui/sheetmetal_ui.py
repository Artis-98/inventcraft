"""Sheet metal's windows: Sheet Metal Defaults, and the Flat Pattern.

The features themselves, Face and Flange, have their dialogs with the
others in dialogs.py; these two are about the part as a whole.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import kernel, sheetmetal
from ..core import units as unitlib
from .theme import C


class SheetMetalDefaultsDialog(QtWidgets.QDialog):
    """Sheet Metal Defaults: the thickness, the bend radius and the
    K-factor every sheet metal feature starts from.  The first two are the
    Thickness and BendRadius parameters, so they can be typed as
    expressions and used anywhere else in the part."""

    def __init__(self, doc, parent=None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Sheet Metal Defaults")
        form = QtWidgets.QFormLayout(self)
        params = {p.name: p for p in doc.params}
        self.thickness = QtWidgets.QLineEdit(
            params["Thickness"].expression if "Thickness" in params else "")
        form.addRow("Thickness (%s)" % doc.units, self.thickness)
        self.radius = QtWidgets.QLineEdit(
            params["BendRadius"].expression if "BendRadius" in params
            else "Thickness")
        form.addRow("Bend Radius (%s)" % doc.units, self.radius)
        self.k = QtWidgets.QLineEdit(doc.sheet_metal.k_factor)
        self.k.setToolTip("Where the neutral fibre lies through the "
                          "thickness, 0 to 1: how long a bend is when "
                          "laid flat.  Inventor's default is 0.44.")
        form.addRow("K-Factor", self.k)
        self.error = QtWidgets.QLabel("")
        self.error.setStyleSheet("color: %s;" % C.error)
        form.addRow(self.error)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            self)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return (self.thickness.text().strip(), self.radius.text().strip(),
                self.k.text().strip())

    def _apply(self) -> None:
        if self.apply(*self.values()):
            self.accept()

    def apply(self, thickness: str, radius: str, k: str) -> bool:
        """Write the defaults into the part; False, saying why, when one
        of them does not work out."""
        from ..core.params import ExpressionError, evaluate
        try:
            value = float(evaluate(k, self.doc.parameter_scope()))
        except (ExpressionError, ValueError) as exc:
            self.error.setText("K-Factor: %s" % exc)
            return False
        if not 0.0 <= value <= 1.0:
            self.error.setText("The K-Factor must be between 0 and 1.")
            return False
        params = self.doc.params
        old = {p.name: p.expression for p in params}
        try:
            params.set_expression("Thickness", thickness or "0")
            params.set_expression("BendRadius", radius or "0")
            scope = self.doc.parameter_scope()
            if scope.get("Thickness", 0.0) <= 0:
                raise ExpressionError("the thickness must be more than 0")
            if scope.get("BendRadius", -1.0) < 0:
                raise ExpressionError("the bend radius cannot be negative")
        except (ExpressionError, KeyError) as exc:
            for name in ("Thickness", "BendRadius"):
                if name in old:
                    params.set_expression(name, old[name])
            self.error.setText(str(exc))
            return False
        self.doc.sheet_metal.k_factor = k
        self.doc.modified = True
        return True


class FlatView(QtWidgets.QWidget):
    """The flat pattern drawn to fit: the outline, and the bend lines
    dashed down the middle of each bend."""

    def __init__(self, flat: sheetmetal.FlatPattern, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(520, 360)
        self.loops: List[List[Tuple[float, float]]] = []
        self.bends = [(a, b) for a, b, _angle in flat.bends]
        self.box = flat.box()
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_Line
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopoDS import TopoDS
        for edge in kernel.explore(flat.outline(), TopAbs_EDGE):
            curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
            a, b = curve.FirstParameter(), curve.LastParameter()
            steps = 1 if curve.GetType() == GeomAbs_Line else 32
            points = []
            for i in range(steps + 1):
                p = curve.Value(a + (b - a) * i / steps)
                points.append((p.X(), p.Y()))
            self.loops.append(points)

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor(C.panel))
        x0, y0, x1, y1 = self.box
        w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
        margin = 24
        scale = min((self.width() - 2 * margin) / w,
                    (self.height() - 2 * margin) / h)
        ox = (self.width() - w * scale) / 2
        oy = (self.height() - h * scale) / 2

        def at(p):
            return QtCore.QPointF(ox + (p[0] - x0) * scale,
                                  self.height() - oy - (p[1] - y0) * scale)

        pen = QtGui.QPen(QtGui.QColor(C.text), 1.6)
        painter.setPen(pen)
        for points in self.loops:
            painter.drawPolyline(QtGui.QPolygonF([at(p) for p in points]))
        dashed = QtGui.QPen(QtGui.QColor(C.accent), 1.2,
                            QtCore.Qt.DashDotLine)
        painter.setPen(dashed)
        for a, b in self.bends:
            painter.drawLine(at(a), at(b))
        painter.end()


class FlatPatternDialog(QtWidgets.QDialog):
    """The Flat Pattern: the sheet laid out, its size, and a DXF of it to
    cut from."""

    def __init__(self, doc, flat: sheetmetal.FlatPattern,
                 parent=None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.flat = flat
        self.setWindowTitle("Flat Pattern")
        layout = QtWidgets.QVBoxLayout(self)
        self.view = FlatView(flat, self)
        layout.addWidget(self.view, 1)
        length, width = flat.extents()
        units = doc.units
        self.size = QtWidgets.QLabel(
            "Flat extents: %s x %s, %s thick, %d bend(s), K-Factor %s" % (
                unitlib.length_text(length, units),
                unitlib.length_text(width, units),
                unitlib.length_text(flat.thickness, units),
                len(flat.bends), doc.sheet_metal.k_factor))
        layout.addWidget(self.size)
        row = QtWidgets.QHBoxLayout()
        self.bend_lines = QtWidgets.QCheckBox("Bend lines in the DXF")
        self.bend_lines.setChecked(True)
        self.bend_lines.setToolTip("On a layer of their own, "
                                   "BEND_CENTERLINE, to mark rather than cut")
        row.addWidget(self.bend_lines)
        row.addStretch(1)
        export = QtWidgets.QPushButton("Export DXF...")
        export.clicked.connect(self.export)
        row.addWidget(export)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        self.resize(760, 560)

    def export(self, path: Optional[str] = None) -> Optional[str]:
        if not path:
            start = os.path.splitext(getattr(self.doc, "path", "") or
                                     "Flat Pattern")[0] + " flat.dxf"
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Export Flat Pattern", start, "DXF (*.dxf)")
        if not path:
            return None
        written = sheetmetal.flat_to_dxf(self.flat, path,
                                         self.bend_lines.isChecked(),
                                         self.doc.units)
        self.size.setText(self.size.text().split("  |")[0]
                          + "  |  saved %s" % os.path.basename(written))
        return written
