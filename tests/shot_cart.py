"""The welding cart's pictures for the website, from the real window.

Usage:  python tests/shot_cart.py [out_dir] [which ...]

Builds nothing: run examples/build_cart.py first.  Each picture opens the
cart's own files the way a user would, so what the site shows is what the
software does.  ``which`` picks some of: assembly, frame, sheetmetal, part,
cam (all of them when none is given).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from PySide6 import QtCore, QtGui, QtWidgets                   # noqa: E402

from datum.ui import icons                                     # noqa: E402
from datum.ui.main_window import MainWindow                    # noqa: E402
from datum.ui.theme import stylesheet                          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CART = os.environ.get("DATUM_CART_OUT") or os.path.join(ROOT, "examples",
                                                     "weld-cart")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "site", "img")
WHICH = set(sys.argv[2:]) or {"assembly", "frame", "sheetmetal", "part",
                              "cam"}
os.makedirs(OUT, exist_ok=True)

app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
app.setWindowIcon(icons.app_icon())
win = MainWindow()
win.resize(1600, 958)
win.show()


def pump(n=4):
    for _ in range(n):
        app.processEvents()


def settle(ms=600):
    timer = QtCore.QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 20)


def shot(name, *popups):
    pump()
    win.viewport.redraw()
    pump()
    chrome = win.grab()
    scratch = os.path.join(OUT, "_vp.png")
    win.viewport.grab_image(scratch)
    image = QtGui.QImage(scratch)
    painter = QtGui.QPainter(chrome)
    if not image.isNull():
        origin = win.viewport.mapTo(win, QtCore.QPoint(0, 0))
        painter.drawImage(QtCore.QRect(origin.x(), origin.y(),
                                       win.viewport.width(),
                                       win.viewport.height()), image)
    for popup in popups:
        # a dialog floats over the window: painted where it stands
        at = popup.mapToGlobal(QtCore.QPoint(0, 0)) - win.mapToGlobal(
            QtCore.QPoint(0, 0))
        painter.drawPixmap(at, popup.grab())
    painter.end()
    try:
        os.remove(scratch)
    except OSError:
        pass
    path = os.path.join(OUT, name + ".png")
    chrome.save(path)
    print("%-14s %d x %d" % (name, chrome.width(), chrome.height()))


def look(view="iso", zoom=1.0):
    win.viewport.set_view(view)
    settle(450)
    win.viewport.fit_all()
    settle(450)
    if zoom != 1.0:
        win.viewport.zoom_by(zoom) if hasattr(win.viewport, "zoom_by") \
            else None
        settle(300)


def hide_skeleton():
    """The skeleton's sketch lines are drawn over the frame they made:
    for a picture of the cart they are put out of sight."""
    asm = win.assembly
    for occurrence in asm.occurrences:
        if occurrence.label.startswith("Cart Skeleton"):
            occurrence.visible = False
    win.assembly_ui.rebuild()
    settle(600)


def go():
    cart = os.path.join(CART, "Welding Cart.icasm")
    if "assembly" in WHICH:
        win.open_path(cart)
        settle(2500)
        hide_skeleton()
        win.assembly_ui.browser.expandToDepth(0)
        look("iso")
        win.viewport.view.SetZoom(1.1, True)
        win.viewport.view.Pan(0, 45)
        settle(300)
        shot("cart")
    if "frame" in WHICH:
        # the frame on its own, its members in the tree, and Change Frame
        # on the top four showing them a size up in green
        from datum.core import frames
        from datum.ui import frames_ui
        path = os.path.join(CART, "Welding Cart", "Frame0001",
                            "Frame0001.icasm")
        win.open_path(path)
        settle(1500)
        tree = win.assembly_ui.browser
        tree.expandToDepth(0)
        look("iso")
        # moved over to the left, clear of the window that will stand on
        # the right
        win.viewport.view.SetZoom(0.92, True)
        win.viewport.view.Pan(-170, 0)
        settle(300)
        fd = win.assembly.frame
        top = [m.id for m in fd.members
               if m.sketch == fd.members[4].sketch][:4]
        dialog = win.frame_action("change", frames_ui.SELF, top)
        settle(600)
        dialog.size.setCurrentText("40 x 40 x 3")
        dialog.adjustSize()
        vp = win.viewport
        corner = vp.mapToGlobal(QtCore.QPoint(vp.width(), 0))
        dialog.move(corner.x() - dialog.width() - 110, corner.y() + 20)
        settle(900)
        dialog.draw_preview()
        settle(400)
        shot("frame", dialog)
        dialog.close()
    if "sheetmetal" in WHICH:
        win.open_path(os.path.join(CART, "Bottle Tray.icpart"))
        settle(1200)
        win.browser.expandAll()
        look("iso")
        shot("sheetmetal")
    if "part" in WHICH:
        win.open_path(os.path.join(CART, "MIG Welder.icpart"))
        settle(1200)
        win.browser.expandAll()
        look("iso")
        shot("welder")
    if "cam" in WHICH:
        win.open_path(os.path.join(CART, "Cart Plates.iccam"))
        settle(1500)
        look("top")
        shot("plates")
    print("DONE")
    app.quit()


QtCore.QTimer.singleShot(1500, go)
sys.exit(app.exec())
