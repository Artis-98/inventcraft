"""Pipe Corners: a small button on every pipe corner, in the view itself.

While piping mode is on, each corner of the pipes that can be either gets
a chip beside it: a picture of what it is now, a bend or an elbow, and a
small arrow.  Its menu offers the two, with a picture each; choosing one
makes the pipe so (see core/pipe_corners.py).  Nothing else is open, no
window to move out of the way.  The Pipe Corners button turns it on and
off, and Esc turns it off.

The 3D view is a native window Qt cannot paint over, so each chip is a
little frameless window of its own, kept over its corner as the view is
turned, zoomed or panned, and hidden when its corner is out of sight.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import kernel
from .theme import C

COPPER = "#c87f4f"
FOLLOW_MS = 33
WORDS = {"bend": "Bend", "elbow": "Elbow fitting"}


def corner_icon(kind: str, size: int = 22, ratio: float = 1.0) -> QtGui.QIcon:
    """A bend: one smooth curve of tube.  An elbow: the same turn, with a
    socket at each end where the tubes go in."""
    pix = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    s = float(size)
    tube = QtGui.QPen(QtGui.QColor(COPPER), s * 0.2, QtCore.Qt.SolidLine,
                      QtCore.Qt.FlatCap)
    p.setBrush(QtCore.Qt.NoBrush)
    x0, y0 = s * 0.22, s * 0.22          # where the turn's two legs meet
    if kind == "bend":
        # one long smooth sweep, the tube bent round
        p.setPen(tube)
        r = s * 0.62
        p.drawArc(QtCore.QRectF(x0, y0, 2 * r, 2 * r), 90 * 16, 90 * 16)
        p.drawLine(QtCore.QPointF(x0, y0 + r), QtCore.QPointF(x0, s))
        p.drawLine(QtCore.QPointF(x0 + r, y0), QtCore.QPointF(s, y0))
    else:
        # a tight corner and a wide socket ring at each end, where the
        # tubes go in
        p.setPen(tube)
        r = s * 0.22
        p.drawArc(QtCore.QRectF(x0, y0, 2 * r, 2 * r), 90 * 16, 90 * 16)
        p.drawLine(QtCore.QPointF(x0, y0 + r), QtCore.QPointF(x0, s))
        p.drawLine(QtCore.QPointF(x0 + r, y0), QtCore.QPointF(s, y0))
        ring = QtGui.QPen(QtGui.QColor("#8a4f2a"), s * 0.34,
                          QtCore.Qt.SolidLine, QtCore.Qt.FlatCap)
        p.setPen(ring)
        p.drawLine(QtCore.QPointF(x0, s * 0.66), QtCore.QPointF(x0, s * 0.84))
        p.drawLine(QtCore.QPointF(s * 0.66, y0), QtCore.QPointF(s * 0.84, y0))
    p.end()
    return QtGui.QIcon(pix)


class CornerChip(QtWidgets.QWidget):
    """One corner's button: its picture and an arrow, the menu under it."""

    chosen = QtCore.Signal(int, str)

    def __init__(self, parent, index: int, corner) -> None:
        super().__init__(parent, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
                         | QtCore.Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.index, self.corner = index, corner
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.button = QtWidgets.QToolButton(self)
        self.button.setObjectName("CornerChip")
        self.button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.button.setCursor(QtCore.Qt.PointingHandCursor)
        self.button.setIconSize(QtCore.QSize(18, 18))
        self.button.setStyleSheet(
            "QToolButton#CornerChip { background: %s; border: 1px solid %s;"
            " border-radius: 9px; padding: 2px 14px 2px 4px; }"
            "QToolButton#CornerChip:hover { border-color: %s; }"
            "QToolButton#CornerChip::menu-indicator { subcontrol-position:"
            " right center; right: 4px; width: 7px; height: 7px; }"
            % (C.panel, C.border, C.accent))
        ratio = self.devicePixelRatioF() or 1.0
        self.button.setIcon(corner_icon(corner.now, 18, ratio))
        self.button.setToolTip("%s: %s" % (corner.label,
                                           WORDS[corner.now].lower()))
        menu = QtWidgets.QMenu(self.button)
        for choice in corner.choices:
            text = WORDS[choice]
            if choice == "bend" and corner.kind == "bend":
                text += "  " + corner.label.replace("Bend ", "")
            elif choice == "elbow":
                text += "  %.0f°" % corner.angle
            action = menu.addAction(corner_icon(choice, 18, ratio), text)
            action.setCheckable(True)
            action.setChecked(choice == corner.now)
            action.triggered.connect(
                lambda _on=False, c=choice: self.chosen.emit(self.index, c))
        self.button.setMenu(menu)
        row.addWidget(self.button)
        self.adjustSize()


class PipeCornersMode(QtCore.QObject):
    """Piping mode: the chips on every corner, kept over their corners."""

    def __init__(self, host) -> None:
        super().__init__(host)
        self.host = host
        self.active = False
        self.chips: List[CornerChip] = []
        self._corners: List[Tuple[int, Any, Any]] = []
        self._drawn: List[Any] = []
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(FOLLOW_MS)
        self._timer.timeout.connect(self.follow)

    # -- on and off -------------------------------------------------------

    def toggle(self) -> bool:
        if self.active:
            self.stop()
        else:
            self.start()
        return self.active

    def start(self) -> None:
        if getattr(self.host, "assembly", None) is None:
            self._say("Pipe Corners works in an assembly with pipes in it.")
            return
        self.active = True
        viewport = self.host.viewport
        viewport.escape_pressed.connect(self.stop)
        self.reload()
        self._timer.start()
        if not self._corners:
            self._say("There are no pipe corners to choose here: Insert "
                      "Pipe first.")
            self.stop()
            return
        self._say("Pipe corners: click a corner's button to make it a bend "
                  "or an elbow. Esc or Pipe Corners again to finish.")

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        self._timer.stop()
        try:
            self.host.viewport.escape_pressed.disconnect(self.stop)
        except (RuntimeError, TypeError):
            pass
        self._clear()
        self._say("")

    def _say(self, text: str) -> None:
        label = getattr(self.host, "status_message", None)
        if label is not None:
            label.setText(text)

    # -- the corners ------------------------------------------------------

    def reload(self) -> None:
        """The chips as the pipes are now."""
        from ..core import pipe_corners
        from .frames_ui import frame_ids, frame_placement, load_frame
        self._clear()
        doc = self.host.assembly
        for fid in frame_ids(doc):
            try:
                found = pipe_corners.corners(load_frame(doc, fid))
            except Exception:  # noqa: BLE001
                continue
            placement = frame_placement(doc, fid)
            for corner in found:
                if len(corner.choices) < 2:
                    continue
                at = placement.apply_point(corner.point) \
                    if placement is not None else tuple(corner.point)
                self._corners.append((fid, corner, at))
        window = self.host.window() if hasattr(self.host, "window") \
            else self.host
        for i, (_fid, corner, _at) in enumerate(self._corners):
            chip = CornerChip(window, i, corner)
            chip.chosen.connect(self.choose)
            self.chips.append(chip)
        self._mark()
        self.follow()

    def _mark(self) -> None:
        """A dot on each corner, for its chip to sit beside."""
        viewport = self.host.viewport
        viewport.remove_drawn(self._drawn)
        with viewport.collecting() as drawn:
            for _fid, corner, at in self._corners:
                viewport.draw_point(at, C.accent if corner.kind == "bend"
                                    else COPPER, 7.0)
        viewport.on_top(drawn)
        self._drawn = drawn
        viewport.redraw()

    def _clear(self) -> None:
        for chip in self.chips:
            chip.hide()
            chip.deleteLater()
        self.chips, self._corners = [], []
        viewport = getattr(self.host, "viewport", None)
        if viewport is not None and self._drawn:
            viewport.remove_drawn(self._drawn)
            viewport.redraw()
        self._drawn = []

    def follow(self) -> None:
        """Each chip just above and right of its corner, where the view
        has it now; hidden when the corner is out of the view."""
        viewport = self.host.viewport
        if not self.active or not viewport.isVisible():
            for chip in self.chips:
                chip.hide()
            return
        w, h = viewport.width(), viewport.height()
        for chip, (_fid, _corner, at) in zip(self.chips, self._corners):
            try:
                x, y = viewport.project(at)
            except Exception:  # noqa: BLE001
                chip.hide()
                continue
            if not (0 <= x < w and 0 <= y < h):
                chip.hide()
                continue
            spot = viewport.mapToGlobal(QtCore.QPoint(int(x) + 8,
                                                      int(y) - chip.height()
                                                      - 4))
            if chip.pos() != spot:
                chip.move(spot)
            if not chip.isVisible():
                chip.show()

    def choose(self, index: int, want: str) -> bool:
        """Corner ``index`` made a bend or an elbow fitting."""
        from ..core import pipe_corners
        from .frames_ui import frame_changed, load_frame
        fid, corner, _at = self._corners[index]
        if want == corner.now:
            return True
        try:
            frame_doc = load_frame(self.host.assembly, fid)
            problems = pipe_corners.set_corner(frame_doc, corner.point, want)
        except (ValueError, KeyError, kernel.KernelError) as exc:
            self._say(str(exc))
            return False
        frame_changed(self.host, frame_doc)
        self._say("; ".join(problems) if problems else
                  "That corner is %s now." % WORDS[want].lower())
        if self.active:
            self.reload()
        return not problems
