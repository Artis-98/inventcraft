"""Frame Analysis: the frame's supports and loads in, how it copes out.

One dialog, as a first look should be: which frame, what it stands on,
what it carries, Run.  The answer is the sag, the worst stress and the
safety factor against yield, the natural frequencies, and every member
ranked by how hard it works, green to red.
"""
from __future__ import annotations

import math
import os
from typing import List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import beams, frame_analysis, frames


def frames_in(doc) -> List[Tuple[str, object]]:
    """Every frame an assembly holds, itself included: (name, document)."""
    out = []
    if getattr(doc, "frame", None) is not None:
        out.append((doc.title, doc))
    for occurrence in getattr(doc, "occurrences", []):
        path = doc.component_path(occurrence)
        if not path or not frames.is_frame(path):
            continue
        try:
            out.append((occurrence.label, frames.open_frame(path)))
        except Exception:
            continue
    return out


class FrameAnalysisDialog(QtWidgets.QDialog):
    def __init__(self, host, found) -> None:
        super().__init__(host)
        self.host = host
        self.found = found
        self.setWindowTitle("Frame Analysis (experimental)")
        self.resize(560, 640)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.frame = QtWidgets.QComboBox(self)
        for name, _doc in found:
            self.frame.addItem(name)
        form.addRow("Frame", self.frame)
        self.support = QtWidgets.QComboBox(self)
        self.support.addItem("Fixed", beams.FIXED)
        self.support.addItem("Pinned", beams.PINNED)
        form.addRow("Lowest joints", self.support)
        self.weight = QtWidgets.QCheckBox("Its own weight", self)
        self.weight.setChecked(True)
        form.addRow("", self.weight)
        self.load = QtWidgets.QDoubleSpinBox(self)
        self.load.setRange(0.0, 1e7)
        self.load.setDecimals(0)
        self.load.setSuffix(" N")
        self.load.setValue(1000.0)
        form.addRow("Load on top, shared", self.load)
        self.wind = QtWidgets.QDoubleSpinBox(self)
        self.wind.setRange(0.0, 80.0)
        self.wind.setSuffix(" m/s")
        form.addRow("Wind speed", self.wind)
        self.wind_dir = QtWidgets.QComboBox(self)
        for label, vec in (("+X", (1, 0, 0)), ("-X", (-1, 0, 0)),
                           ("+Y", (0, 1, 0)), ("-Y", (0, -1, 0))):
            self.wind_dir.addItem(label, vec)
        form.addRow("Wind blowing towards", self.wind_dir)
        self.drag = QtWidgets.QDoubleSpinBox(self)
        self.drag.setRange(0.1, 5.0)
        self.drag.setSingleStep(0.1)
        self.drag.setValue(2.0)
        form.addRow("Drag coefficient", self.drag)
        layout.addLayout(form)

        run = QtWidgets.QPushButton("Run", self)
        run.setDefault(True)
        run.clicked.connect(self.run)
        layout.addWidget(run)
        self.summary = QtWidgets.QLabel("", self)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.summary)
        self.table = QtWidgets.QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Member", "Stress",
                                              "Of yield"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.result = None

    def setup(self) -> frame_analysis.Setup:
        return frame_analysis.Setup(
            support=self.support.currentData(),
            self_weight=self.weight.isChecked(),
            top_load=self.load.value(),
            wind_speed=self.wind.value(),
            wind_direction=tuple(float(c) for c in self.wind_dir.currentData()),
            drag=self.drag.value())

    def run(self) -> None:
        _name, doc = self.found[self.frame.currentIndex()]
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            fm, result, summary = frame_analysis.analyse(doc, self.setup())
        except Exception as exc:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.summary.setText("Cannot analyse it: %s" % exc)
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self.result = (fm, result, summary)
        if result.error:
            self.summary.setText(result.error)
            self.table.setRowCount(0)
            return
        safety = ("%.1f" % result.safety if math.isfinite(result.safety)
                  else "-")
        lines = [
            "Largest deflection: %.2f mm" % result.max_deflection,
            "Highest stress: %.1f MPa, in %s" % (result.max_stress,
                                                 result.max_member),
            "Safety factor against yield: %s" % safety,
        ]
        if result.frequencies:
            lines.append("Natural frequencies: %s Hz" % ", ".join(
                "%.1f" % f for f in result.frequencies))
        if fm.notes:
            lines.append("Note: " + "; ".join(fm.notes))
        self.summary.setText("\n".join(lines))
        self.table.setRowCount(len(summary))
        for row, item in enumerate(summary):
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(
                "%d  %s" % (item.member, item.label)))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(
                "%.1f MPa" % item.stress))
            use = QtWidgets.QTableWidgetItem("%.0f %%"
                                             % (item.utilisation * 100))
            # green, through amber, to red at yield
            u = max(0.0, min(1.0, item.utilisation))
            colour = QtGui.QColor.fromHsvF((1.0 - u) * 0.33, 0.55, 0.95)
            use.setBackground(colour)
            self.table.setItem(row, 2, use)
        self.host.status_message.setText(
            "Frame Analysis: %.2f mm at most, safety factor %s."
            % (result.max_deflection, safety))
