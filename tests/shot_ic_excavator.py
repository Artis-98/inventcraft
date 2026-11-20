"""The walking excavator pictures for ic.iiteg.com, from the real window.

Usage:  python tests/shot_ic_excavator.py <picture> [out_dir]

    part      02_part.png       the dished wheel rim, one part
    assembly  04_assembly.png   the whole machine
    inplace   05_inplace.png    a cylinder barrel edited in place
    bom       06_bom.png        its bill of materials
    iclogic   27_iclogic.png    a leg's sliders driving the model
    drawing   30_drawing_weldment.png  the boom's shop drawing

One picture a process, so every one starts from a clean window.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from PySide6 import QtCore, QtGui, QtWidgets                   # noqa: E402

from datum.core import rules                                   # noqa: E402
from datum.ui import icons                                     # noqa: E402
from datum.ui.main_window import MainWindow                    # noqa: E402
from datum.ui.theme import stylesheet                          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "examples", "walking-excavator")
WHICH = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "build", "ic-shots")
os.makedirs(OUT, exist_ok=True)

app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
app.setWindowIcon(icons.app_icon())
win = MainWindow()
win.resize(1600, 958)
win.show()


def settle(ms=600):
    timer = QtCore.QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 20)


def save(name, dialog=None):
    """The window as it is, its 3D view drawn in, a dialog over it."""
    settle(300)
    scratch = os.path.join(OUT, "_vp.png")
    win.viewport.grab_image(scratch)
    picture = win.grab()
    painter = QtGui.QPainter(picture)
    rendered = QtGui.QImage(scratch)
    if not rendered.isNull():
        origin = win.viewport.mapTo(win, QtCore.QPoint(0, 0))
        painter.drawImage(QtCore.QRect(origin.x(), origin.y(), win.viewport.width(),
                                       win.viewport.height()), rendered)
    if dialog is not None:
        painter.drawPixmap(win.mapFromGlobal(dialog.mapToGlobal(QtCore.QPoint(0, 0))),
                           dialog.grab())
    painter.end()
    if os.path.exists(scratch):
        os.remove(scratch)
    path = os.path.join(OUT, name)
    picture.save(path)
    print(name, picture.width(), "x", picture.height())


def aim(direction, scale=1.0, pan=(0, 0)):
    """Look along ``direction`` and fill the view."""
    vp = win.viewport
    vp.set_show_origin(False)
    vp.set_view("iso")
    settle(200)
    d = direction
    vp.view.SetProj(-d[0], -d[1], -d[2])
    vp.view.SetUp(0, 0, 1)
    vp.fit_all()
    settle(300)
    vp.view.SetZoom(scale)
    if pan != (0, 0):
        vp.view.Pan(*pan)
    vp.view.Redraw()
    settle(400)


def open_machine():
    win.open_path(os.path.join(MODEL, "Walking Excavator.icasm"))
    settle(4000)
    rules.trust_document(win.assembly)
    win.rules_panel.refresh()
    win.assembly_ui.browser.expandToDepth(0)
    win.status_message.setStyleSheet("")
    win.status_message.setText("Walking Excavator.icasm: 100 components, 561 parts")
    settle(300)


def part():
    win.open_path(os.path.join(MODEL, "parts", "Wheel rim 30in dished.icpart"))
    settle(2500)
    aim((-0.55, -0.95, -0.6), 0.85)
    save("02_part.png")


def assembly():
    open_machine()
    aim((-0.95, -0.75, -0.42), 0.95)
    save("04_assembly.png")


def inplace():
    open_machine()
    aim((-0.95, -0.75, -0.42), 0.95)
    target = next(o for o in win.assembly.occurrences if o.ref.label == "boom ram barrel")
    win.edit_in_place(target.id)
    settle(2500)
    save("05_inplace.png")


def bom():
    from datum.ui import bom_ui
    open_machine()
    aim((-0.95, -0.75, -0.42), 0.82, (-330, 0))
    dialog = bom_ui.BomDialog(win, win.assembly, win.session, win.assembly.library)
    dialog.tabs.setCurrentIndex(1)
    dialog.resize(930, 600)
    dialog.show()
    settle(600)
    dialog.move(win.mapToGlobal(QtCore.QPoint(win.width() - dialog.width() - 24, 196)))
    settle(400)
    save("06_bom.png", dialog)


def iclogic():
    from datum.ui.rules_ui import FormDialog
    open_machine()
    aim((-0.95, -0.75, -0.42), 0.82, (-260, 0))
    ass = win.assembly
    taken = {}

    def show(document, caption, rows):
        dialog = FormDialog(win, document, caption, rows)

        def drive():
            # a leg lifted and steered, live, the form still open
            sys.path.insert(0, ROOT)
            from examples.walking_excavator.controls import control_sets
            lows = {k: (lo, st) for _, k, lo, hi, st, lb in control_sets()["Leg controls FL"]}
            for name, value in (("lift_FL", 34), ("spread_FL", 38), ("steer_FL", 12)):
                lo, st = lows[name]
                dialog.widgets[name].setValue(round((value - lo) / st))
            dialog._pending.stop()
            dialog._rebuild()
            settle(800)
            dialog.move(win.mapToGlobal(QtCore.QPoint(win.width() - dialog.width() - 30, 170)))
            settle(400)
            save("27_iclogic.png", dialog)
            taken["ok"] = True
            dialog.reject()
        # the test harness rejects modal dialogs, so it is shown and driven
        # here instead of run modally
        dialog.show()
        settle(500)
        drive()
        return False
    rules.show_form = show
    rule = next(r for r in ass.rules.rules if r.name == "Leg controls FL")
    result = rules.run(rule, ass)
    assert taken.get("ok"), "the form was not shown: %s %s" % (result.ok, result.error)


def drawing():
    win.open_path(os.path.join(MODEL, "drawings", "Boom Weldment.icdraw"))
    settle(5000)
    ui = getattr(win, "drawing_ui", None)
    if ui is not None and hasattr(ui, "fit_sheet"):
        ui.fit_sheet()
    settle(1500)
    save("30_drawing_weldment.png")


{"part": part, "assembly": assembly, "inplace": inplace, "bom": bom, "iclogic": iclogic,
 "drawing": drawing}[WHICH]()
win.hide()
win.viewport.shutdown()
