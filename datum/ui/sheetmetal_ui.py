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


class SheetMetalConvertDialog(QtWidgets.QDialog):
    """Convert to Sheet Metal for a part that has a body already, a STEP
    file opened: Inventor asks for the base face, measures the thickness
    from it and shows Sheet Metal Defaults with that thickness in."""

    def __init__(self, doc, parent=None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.face = None
        self.setWindowTitle("Convert to Sheet Metal")
        self.setModal(False)
        form = QtWidgets.QFormLayout(self)
        self.prompt = QtWidgets.QLabel("Select the base face in the view.")
        self.prompt.setWordWrap(True)
        form.addRow(self.prompt)
        self.thickness = QtWidgets.QLineEdit("")
        self.thickness.setEnabled(False)
        form.addRow("Thickness (%s)" % doc.units, self.thickness)
        self.radius = QtWidgets.QLineEdit("Thickness")
        form.addRow("Bend Radius (%s)" % doc.units, self.radius)
        self.k = QtWidgets.QLineEdit(sheetmetal.DEFAULT_K)
        self.k.setToolTip("Where the neutral fibre lies through the "
                          "thickness, 0 to 1. Inventor's default is 0.44.")
        form.addRow("K-Factor", self.k)
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            self)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)

    def take_face(self, face) -> bool:
        """A face picked in the view: the base face, if it is flat."""
        from ..core.features import plane_from_face
        from ..core.kernel import KernelError
        if plane_from_face(face) is None:
            self.prompt.setText("That face is not flat. Select a flat face "
                                "of the sheet.")
            return False
        try:
            measured = sheetmetal.measure(self.doc, face)
        except KernelError as exc:
            self.prompt.setText("Cannot measure from that face: %s" % exc)
            return False
        self.face = face
        self.thickness.setText(("%.4f" % measured).rstrip("0").rstrip("."))
        self.thickness.setEnabled(True)
        self.prompt.setText("Base face picked: the sheet is %s thick. "
                            "Another face picks again." % unitlib.length_text(
                                measured, self.doc.units))
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)
        return True

    def values(self):
        return (self.thickness.text().strip() or None,
                self.radius.text().strip() or "Thickness",
                self.k.text().strip() or sheetmetal.DEFAULT_K)


class BendPerforationDialog(QtWidgets.QDialog):
    """A Bend Perforation of the flat pattern: slots down the bend lines
    with bridges of sheet between them, so a plate cut flat on the plasma
    table bends by hand.  The flat in the view shows it as it is typed."""

    STYLES = [("trapezoid", "sm_perforation_trapezoid",
               "Cuts along the bend line, their ends angled off it: open "
               "trapezoids, every other one turned to the other side"),
              ("zigzag", "sm_perforation", "V shaped slots"),
              ("straight", "sm_perforation_straight",
               "Straight slots along the bend line"),
              ("custom", "sketch", "Your own: one repeat drawn in a sketch, "
               "its X axis the bend line")]

    def __init__(self, doc, feature, parent=None) -> None:
        super().__init__(parent)
        from .widgets import SegmentedControl
        self.doc = doc
        self.feature = feature
        self.host = parent
        self.setWindowTitle(feature.name)
        form = QtWidgets.QFormLayout(self)
        self.style = SegmentedControl(self.STYLES)
        self.style.set_value(feature.style)
        form.addRow("Style", self.style)
        self.fields = {}
        for key, label, tip in (
                ("width", "Slot width", "What the cutter leaves: the "
                 "plasma's kerf, or more"),
                ("slot", "Slot length", "Each slot along the bend, before "
                 "it is evened out over the bend's length"),
                ("bridge", "Bridge", "The sheet left between two slots: "
                 "the attachment points"),
                ("margin", "End margin", "Sheet left whole at each end of "
                 "the bend"),
                ("depth", "Zigzag depth", "How far a V shaped slot reaches "
                 "off the bend line"),
                ("leg", "Leg length", "A trapezoid's angled ends: how long"),
                ("angle", "Leg angle", "A trapezoid's angled ends: degrees "
                 "off the bend line; past 90 they turn back in"),
                ("bends", "Bends", "all, or the bends by number: 1, 3")):
            edit = QtWidgets.QLineEdit(getattr(feature, key))
            edit.setToolTip(tip)
            edit.textChanged.connect(self._changed)
            form.addRow(label, edit)
            self.fields[key] = edit
        self.alternate = QtWidgets.QCheckBox("Every other one to the "
                                             "other side")
        self.alternate.setChecked(feature.alternate)
        self.alternate.toggled.connect(lambda _on: self._changed())
        form.addRow("", self.alternate)
        # a custom pattern, taken from a sketch of the part
        row = QtWidgets.QHBoxLayout()
        self.sketches = QtWidgets.QComboBox()
        for sketch_feature in getattr(doc, "sketch_features", lambda: [])():
            self.sketches.addItem(sketch_feature.name, sketch_feature.id)
        row.addWidget(self.sketches, 1)
        take = QtWidgets.QPushButton("Take Pattern")
        take.setToolTip("Draw one repeat of the pattern in a sketch, the "
                        "sketch's X axis the bend line, and take it here")
        take.clicked.connect(self.take_pattern)
        row.addWidget(take)
        form.addRow("From sketch", row)
        self.style.changed.connect(lambda _k: self._changed())
        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        form.addRow(self.message)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            self)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self._cancel)
        form.addRow(buttons)
        self._changed()

    def take_pattern(self, sketch_id: int = 0) -> bool:
        """The custom pattern, from a sketch's lines."""
        from ..core.kernel import KernelError
        sketch_id = sketch_id or int(self.sketches.currentData() or 0)
        owner = self.doc.feature(sketch_id) if sketch_id else None
        sketch = getattr(owner, "sketch", None)
        if sketch is None:
            self.message.setText("Pick the sketch with the pattern in it.")
            return False
        try:
            self.feature.custom = sheetmetal.pattern_from_sketch(sketch)
        except KernelError as exc:
            self.message.setStyleSheet("color: %s;" % C.error)
            self.message.setText(str(exc))
            return False
        self.style.set_value("custom")
        return self._changed()

    def _store(self) -> None:
        self.feature.style = self.style.value()
        self.feature.alternate = self.alternate.isChecked()
        for key, edit in self.fields.items():
            setattr(self.feature, key, edit.text().strip())

    def _changed(self, *_args) -> bool:
        """Try it on the flat, and show it there."""
        from ..core.kernel import KernelError
        self._store()
        try:
            base = sheetmetal.flat_pattern(self.doc)
            flat = self.feature.apply(base, self.doc.parameter_scope())
        except (KernelError, ValueError, Exception) as exc:
            self.message.setStyleSheet("color: %s;" % C.error)
            self.message.setText(str(exc))
            return False
        slots = sum(len(kernel.explore(f, sheetmetal.TopAbs_WIRE)) - 1
                    for f in flat.faces)
        self.message.setStyleSheet("")
        self.message.setText("%d slot(s) down %d bend(s)."
                             % (slots, len(self.feature.chosen(
                                 len(base.bends)))))
        viewport = getattr(self.host, "viewport", None)
        if viewport is not None and flat.solid is not None:
            viewport.set_shape(flat.solid, keep_camera=True)
        return True

    def _ok(self) -> None:
        if self._changed():
            self.accept()

    def _cancel(self) -> None:
        self.reject()
        if self.host is not None and hasattr(self.host, "rebuild"):
            self.host.rebuild()
