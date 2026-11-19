"""Render: a quick ray traced picture of the model, to look at and save.

OpenCASCADE's ray tracer runs on the graphics card, so a picture with
real shadows takes a second, not minutes.  The view is rendered as it is
framed in the window; the window only picks the size and a few looks.
"""

from __future__ import annotations

import os
import tempfile
import time

from PySide6 import QtCore, QtGui, QtWidgets

SIZES = (("As the window", 0, 0), ("1920 x 1080", 1920, 1080),
         ("2560 x 1440", 2560, 1440), ("3840 x 2160 (4K)", 3840, 2160),
         ("1080 x 1080", 1080, 1080))


class RenderDialog(QtWidgets.QDialog):
    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent)
        self.viewport = viewport
        self.setWindowTitle("Render")
        self.resize(900, 640)
        self.path = ""

        self.picture = QtWidgets.QLabel()
        self.picture.setAlignment(QtCore.Qt.AlignCenter)
        self.picture.setMinimumSize(480, 320)
        self.picture.setStyleSheet("background: #ffffff;")

        self.size_box = QtWidgets.QComboBox()
        for label, _w, _h in SIZES:
            self.size_box.addItem(label)
        self.size_box.setCurrentIndex(0)
        self.shadows = QtWidgets.QCheckBox("Shadows")
        self.shadows.setChecked(True)
        self.reflections = QtWidgets.QCheckBox("Reflections")
        self.edges = QtWidgets.QCheckBox("Edges")
        self.white = QtWidgets.QCheckBox("White background")
        self.white.setChecked(True)
        for box in (self.shadows, self.reflections, self.edges, self.white):
            box.toggled.connect(self.start)
        self.size_box.currentIndexChanged.connect(self.start)

        self.status = QtWidgets.QLabel("")
        again = QtWidgets.QPushButton("Render Again")
        again.setToolTip("After turning the model round in the window")
        again.clicked.connect(self.start)
        self.save_btn = QtWidgets.QPushButton("Save Image...")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save)
        copy = QtWidgets.QPushButton("Copy")
        copy.clicked.connect(self.copy)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)

        options = QtWidgets.QHBoxLayout()
        options.addWidget(QtWidgets.QLabel("Size"))
        options.addWidget(self.size_box)
        for box in (self.shadows, self.reflections, self.edges, self.white):
            options.addWidget(box)
        options.addStretch(1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.status, 1)
        for b in (again, copy, self.save_btn, close):
            buttons.addWidget(b)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(options)
        layout.addWidget(self.picture, 1)
        layout.addLayout(buttons)
        self._image = QtGui.QImage()

    def start(self) -> None:
        """Render the view as it is now."""
        _label, w, h = SIZES[self.size_box.currentIndex()]
        folder = os.path.join(tempfile.gettempdir(), "datum-render")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "render-%d.png" % int(time.time() * 1000))
        self.status.setText("Rendering...")
        QtWidgets.QApplication.processEvents()
        started = time.perf_counter()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            ok = self.viewport.render_image(
                path, w, h, shadows=self.shadows.isChecked(),
                reflections=self.reflections.isChecked(),
                edges=self.edges.isChecked(), white=self.white.isChecked())
        except Exception as exc:                        # noqa: BLE001
            ok = False
            self.status.setText("Could not render: %s" % exc)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if not ok or not os.path.exists(path):
            if not self.status.text().startswith("Could not"):
                self.status.setText("The graphics card could not ray trace "
                                    "this view.")
            return
        self.path = path
        self._image = QtGui.QImage(path)
        self.status.setText("%d x %d, %.1f s" % (
            self._image.width(), self._image.height(),
            time.perf_counter() - started))
        self.save_btn.setEnabled(True)
        self._show()

    def _show(self) -> None:
        if self._image.isNull():
            return
        shown = QtGui.QPixmap.fromImage(self._image).scaled(
            self.picture.size(), QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation)
        self.picture.setPixmap(shown)

    def resizeEvent(self, event) -> None:                # noqa: N802
        super().resizeEvent(event)
        self._show()

    def copy(self) -> None:
        if not self._image.isNull():
            QtWidgets.QApplication.clipboard().setImage(self._image)
            self.status.setText("Copied to the clipboard.")

    def save(self) -> None:
        if self._image.isNull():
            return
        window = self.parent()
        doc = getattr(window, "document", None)
        base = os.path.dirname(getattr(doc, "path", "") or "") \
            or os.path.expanduser("~")
        name = os.path.splitext(os.path.basename(
            getattr(doc, "path", "") or "render"))[0] or "render"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Image", os.path.join(base, name + ".png"),
            "PNG image (*.png);;JPEG image (*.jpg)")
        if path:
            self._image.save(path)
            self.status.setText("Saved %s." % os.path.basename(path))
