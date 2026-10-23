"""0.3.1: the ten locked changes.

Every save keeps the file it replaces in OldVersions.  An extrude's
distance is dragged with an arrow in the view.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets                       # noqa: E402

from datum.core import kernel, oldversions, prefs                  # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import ExtrudeFeature                     # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_batch20_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1500, 900)
win.show()
app.processEvents()
ed = win.editor
vp = win.viewport
NONE = QtCore.Qt.NoModifier
LEFT = QtCore.Qt.LeftButton


def pump(n=6):
    for _ in range(n):
        app.processEvents()


def settle(ms=500):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


def mouse(kind, pos, button, buttons, mods=NONE):
    p = QtCore.QPointF(*pos)
    QtWidgets.QApplication.sendEvent(vp, QtGui.QMouseEvent(
        kind, p, vp.mapToGlobal(p), button, buttons, mods))


def sketched_rectangle(w=40.0, h=30.0):
    """A new part with one rectangle on XY, and the extrude dialog open."""
    win.new_document(prompt=False)
    pump()
    win.start_sketch_on_plane("XY")
    settle(800)
    ed.snap_grid = False
    ed.set_tool("rect")
    ed._on_click(0.0, 0.0, NONE)
    ed._on_click(w, h, NONE)
    ed.set_tool("select")
    win.finish_sketch()
    pump()
    win.new_feature(ExtrudeFeature)
    pump()
    dialog = win._active_dialog
    win.select_all_profiles()
    pump()
    return dialog


# ==========================================================================
print("#208 every save keeps the file it replaces, in OldVersions")

doc = Document()
target = doc.save(os.path.join(WORK, "Bracket"))
check("the first save makes nothing old", oldversions.versions(target) == [])
doc.save(target)
kept = oldversions.versions(target)
check("the second keeps the first, as Bracket.0001",
      [os.path.basename(p) for _n, p in kept] == ["Bracket.0001.icpart"],
      kept)
check("in an OldVersions folder beside it",
      os.path.dirname(kept[0][1]) == os.path.join(WORK, "OldVersions"))
for _ in range(3):
    doc.save(target)
kept = oldversions.versions(target)
check("by default one is kept, the newest",
      [n for n, _p in kept] == [4], kept)
mine = prefs.prefs()
mine.old_versions = 3
for _ in range(4):
    doc.save(target)
check("Preferences decides how many: three",
      [n for n, _p in oldversions.versions(target)] == [6, 7, 8],
      oldversions.versions(target))
mine.old_versions = 0
doc.save(target)
check("none kept with 0, and the old ones are left alone",
      [n for n, _p in oldversions.versions(target)] == [6, 7, 8])
mine.old_versions = -1
for _ in range(5):
    doc.save(target)
check("every one kept with All",
      len(oldversions.versions(target)) == 8, oldversions.versions(target))
check("an old version still opens",
      Document.load(oldversions.versions(target)[0][1]) is not None)
mine.old_versions = 1
check("the setting round trips", prefs.Preferences.from_dict(
    {"old_versions": -1}).old_versions == -1
      and prefs.Preferences.from_dict({}).old_versions == 1
      and prefs.Preferences.from_dict({"old_versions": "x"}).old_versions
      == 1)
from datum.ui.prefs_ui import PreferencesDialog                     # noqa: E402

dialog = PreferencesDialog()
check("and Preferences offers it", dialog.versions_spin.value() == 1
      and dialog.versions_spin.specialValueText() == "All")
dialog.versions_spin.setValue(5)
dialog.gather()
check("a value set there is kept", dialog.prefs.old_versions == 5)
dialog.prefs.old_versions = 1
dialog.deleteLater()

# ==========================================================================
print("#212 an arrow in the view drags the extrude's distance")

dialog = sketched_rectangle()
dialog.distance.set_text("10")
dialog.preview()
vp.set_view("iso")
vp.fit_all()
settle(600)
dialog.preview()
pump()
check("the arrow is drawn", bool(dialog._handle_drawn))
check("and the view knows it can be grabbed",
      vp.drag_handle == dialog._handle_hit)
axis, tip = dialog._handle_tip()
check("it stands on the end of the extrusion, over the profile's middle",
      axis is not None and near(tip[0], 20.0, 1e-6) and near(tip[1], 15.0)
      and near(tip[2], 10.0), tip)
length = max(2.0, vp.view_span() * 0.11)
grab = vp.project((tip[0], tip[1], tip[2] + length * 0.5))
check("a press on it is a grab", dialog._handle_hit(*grab) is not None)
away = vp.project((tip[0] + 30.0, tip[1] - 30.0, tip[2]))
check("a press away from it is not", dialog._handle_hit(*away) is None)

to = vp.project((tip[0], tip[1], 25.0 + length * 0.5))
mouse(QtCore.QEvent.MouseButtonPress, grab, LEFT, LEFT)
for step in range(1, 6):
    x = grab[0] + (to[0] - grab[0]) * step / 5.0
    y = grab[1] + (to[1] - grab[1]) * step / 5.0
    mouse(QtCore.QEvent.MouseMove, (x, y), QtCore.Qt.NoButton, LEFT)
    pump(2)
mouse(QtCore.QEvent.MouseButtonRelease, to, LEFT, QtCore.Qt.NoButton)
pump()
settle(300)
check("dragging it up sets the distance it is dragged to",
      near(dialog.distance.value(), 25.0, 0.6), dialog.distance.value())
check("written into the field as a plain number",
      dialog.distance.edit.text().replace(".", "", 1).isdigit(),
      dialog.distance.edit.text())
check("and the part being previewed followed",
      near(kernel.volume(win.document.shape), 40 * 30 * 25, 40 * 30 * 0.6),
      kernel.volume(win.document.shape))

back = vp.project((tip[0], tip[1], -12.0 + length * 0.5))
_axis, tip = dialog._handle_tip()
grab = vp.project((tip[0], tip[1], tip[2] + length * 0.5))
mouse(QtCore.QEvent.MouseButtonPress, grab, LEFT, LEFT)
mouse(QtCore.QEvent.MouseMove, back, QtCore.Qt.NoButton, LEFT)
pump(2)
mouse(QtCore.QEvent.MouseButtonRelease, back, LEFT, QtCore.Qt.NoButton)
pump()
settle(300)
check("pulled back through the sketch it turns round, as Inventor's does",
      dialog.direction.value() == "flipped", dialog.direction.value())
check("with the distance it was pulled to",
      near(dialog.distance.value(), 12.0, 0.6), dialog.distance.value())
dialog.direction.set_value("symmetric")
dialog.distance.set_text("20")
dialog.preview()
pump()
_axis, tip = dialog._handle_tip()
check("a symmetric one has its arrow half way out",
      near(tip[2], 10.0, 1e-6), tip)
dialog.extent.setCurrentIndex(dialog.extent.findData("through_all"))
pump()
check("Through All has no distance, so no arrow",
      not dialog._handle_drawn and dialog._handle_hit(*grab) is None)
dialog.extent.setCurrentIndex(dialog.extent.findData("distance"))
dialog.direction.set_value("default")
dialog.distance.set_text("8")
dialog.commit()
pump()
check("OK keeps the dragged feature",
      near(kernel.volume(win.document.shape), 40 * 30 * 8, 1.0),
      kernel.volume(win.document.shape))
check("and the arrow goes with the dialog",
      vp.drag_handle is None and not dialog._handle_drawn)

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all batch 20 tests passed")
sys.exit(0)
