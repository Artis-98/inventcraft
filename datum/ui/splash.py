"""The splash screen shown while InventCraft starts.

A panel with the name, the version and what is loading, and a machine
made in InventCraft standing in front of it, breaking out over its edge.
The picture is a Blender render of the walking excavator in
examples/walking-excavator, made by examples/walking_excavator/
blender_render.py.  Nothing here needs the modeller: it shows before the
heavy modules load, so it has something to say while they do.
"""
import os

from PySide6 import QtCore, QtGui, QtWidgets

BRAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand")
NAVY = QtGui.QColor("#1e2d4a")
NAVY_DEEP = QtGui.QColor("#141f35")
YELLOW = QtGui.QColor("#f5b301")


class Splash(QtWidgets.QWidget):
    W, H = 900, 470                      # the window, panel and machine
    PANEL = QtCore.QRectF(0, 70, 600, 330)

    def __init__(self, version: str = "") -> None:
        super().__init__(None, QtCore.Qt.SplashScreen
                         | QtCore.Qt.FramelessWindowHint
                         | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setFixedSize(self.W, self.H)
        self.version = version
        self.status = "Starting"
        self.machine = QtGui.QPixmap(os.path.join(BRAND, "splash-excavator.png"))
        self.logo = QtGui.QPixmap(os.path.join(BRAND, "inventcraft-128.png"))
        self.maker = QtGui.QPixmap(os.path.join(BRAND, "iiteg-logo-white.png"))
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            box = screen.availableGeometry()
            self.move(box.center() - QtCore.QPoint(self.W // 2, self.H // 2))

    def message(self, text: str) -> None:
        """Say what is loading, and get it on screen now."""
        self.status = text
        self.repaint()
        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ExcludeUserInputEvents)

    def finish(self, window: QtWidgets.QWidget) -> None:
        """Go once the main window is up."""
        QtCore.QTimer.singleShot(250, self.close)

    def paintEvent(self, event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        panel = self.PANEL
        # a soft shadow under the panel, then the panel
        for k in range(10, 0, -1):
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 5))
            p.drawRoundedRect(panel.adjusted(-k, -k + 4, k, k + 4), 10 + k, 10 + k)
        grad = QtGui.QLinearGradient(panel.topLeft(), panel.bottomRight())
        grad.setColorAt(0.0, NAVY)
        grad.setColorAt(1.0, NAVY_DEEP)
        p.setBrush(grad)
        p.drawRoundedRect(panel, 10, 10)
        # a yellow rule along the top, the machine's own paint
        p.setBrush(YELLOW)
        rule = QtGui.QPainterPath()
        rule.addRoundedRect(panel.adjusted(0, 0, 0, -(panel.height() - 10)), 10, 10)
        clip = QtGui.QPainterPath()
        clip.addRect(panel.adjusted(0, 0, 0, -(panel.height() - 6)))
        p.drawPath(rule.intersected(clip))
        # beaver, name, version
        x, y = panel.left() + 34, panel.top() + 38
        if not self.logo.isNull():
            p.drawPixmap(QtCore.QRectF(x, y, 64, 64), self.logo,
                         QtCore.QRectF(self.logo.rect()))
        p.setPen(QtGui.QColor("white"))
        name = QtGui.QFont("Segoe UI", 28)
        name.setWeight(QtGui.QFont.DemiBold)
        p.setFont(name)
        p.drawText(QtCore.QPointF(x + 82, y + 44), "InventCraft")
        small = QtGui.QFont("Segoe UI", 10)
        p.setFont(small)
        p.setPen(QtGui.QColor(255, 255, 255, 170))
        p.drawText(QtCore.QPointF(x + 84, y + 70), "by")
        if not self.maker.isNull():
            # the IITEG wordmark itself, not the name set in a font
            lh = 15.0
            lw = lh * self.maker.width() / self.maker.height()
            p.drawPixmap(QtCore.QRectF(x + 104, y + 58, lw, lh), self.maker,
                         QtCore.QRectF(self.maker.rect()))
        p.setPen(YELLOW)
        ver = QtGui.QFont("Segoe UI", 13)
        ver.setWeight(QtGui.QFont.DemiBold)
        p.setFont(ver)
        p.drawText(QtCore.QPointF(x, y + 120), self.version)
        # what is loading, and whose machine this is
        p.setFont(small)
        p.setPen(QtGui.QColor(255, 255, 255, 200))
        p.drawText(QtCore.QPointF(x, panel.bottom() - 56), self.status + "…")
        p.setPen(QtGui.QColor(255, 255, 255, 110))
        credit = QtGui.QFont("Segoe UI", 8)
        p.setFont(credit)
        p.drawText(QtCore.QPointF(x, panel.bottom() - 26),
                   "Walking excavator designed in InventCraft")
        # the machine, in front of the panel and out over its edge
        if not self.machine.isNull():
            h = self.H - 6
            w = h * self.machine.width() / self.machine.height()
            p.drawPixmap(QtCore.QRectF(self.W - w, 0, w, h), self.machine,
                         QtCore.QRectF(self.machine.rect()))
        p.end()
