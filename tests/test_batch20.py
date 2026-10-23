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

# ==========================================================================
print("#126 keyboard shortcuts of your own")

from datum.ui import shortcuts                                      # noqa: E402

keys = {c: a.shortcut().toString() for c, a in win._shortcut_actions.items()}
check("every command in the table has its key on",
      all(keys[c] == shortcuts.normal(k) for c, k in shortcuts.DEFAULTS.items()),
      keys)
check("M measures, V and G move and turn, as Inventor's do",
      keys["measure"] == "M" and keys["free_move"] == "V"
      and keys["free_rotate"] == "G")
check("no two commands share a key by default",
      not shortcuts.clashes(shortcuts.DEFAULTS))

mine = prefs.prefs()
mine.shortcuts = {"extrude": "Ctrl+Shift+E", "fillet": ""}
win.apply_shortcuts()
check("one set in Preferences goes on at once",
      win._shortcut_actions["extrude"].shortcut().toString()
      == "Ctrl+Shift+E")
check("and an emptied one has no key",
      win._shortcut_actions["fillet"].shortcut().isEmpty())
check("the rest keep theirs",
      win._shortcut_actions["revolve"].shortcut().toString() == "R")

dialog = PreferencesDialog()
check("Preferences lists every command",
      dialog.shortcut_table.rowCount() == len(shortcuts.COMMANDS))
check("with the keys in use",
      dialog.shortcut_edits["extrude"].keySequence().toString()
      == "Ctrl+Shift+E")
dialog.shortcut_edits["sketch"].setKeySequence(QtGui.QKeySequence("R"))
dialog._shortcut_set("sketch")
check("keys another command had are taken from it",
      dialog.shortcut_edits["revolve"].keySequence().isEmpty()
      and "Revolve" in dialog.shortcut_note.text(),
      dialog.shortcut_note.text())
dialog.gather()
check("only what differs from the defaults is kept",
      dialog.prefs.shortcuts == {"extrude": "Ctrl+Shift+E", "fillet": "",
                                 "sketch": "R", "revolve": ""},
      dialog.prefs.shortcuts)
dialog.reset_shortcuts()
dialog.gather()
check("Reset to defaults keeps nothing", dialog.prefs.shortcuts == {})
check("and the file round trips", prefs.Preferences.from_dict(
    {"shortcuts": {"extrude": "X"}}).shortcuts == {"extrude": "X"}
      and prefs.Preferences.from_dict({"shortcuts": "nonsense"}).shortcuts
      == {})
dialog.deleteLater()
mine.shortcuts = {}
win.apply_shortcuts()

# ==========================================================================
print("#90 Measure, the Inventor way")

from OCP.TopAbs import TopAbs_VERTEX                               # noqa: E402

win.new_document(prompt=False)
win.new_primitive("box")
pump()
win._active_dialog.commit()
pump()
box = win.document.shape
corners = kernel.explore(box, TopAbs_VERTEX)
low = min(corners, key=lambda v: sum(kernel.shape_centre(v)))
high = max(corners, key=lambda v: sum(kernel.shape_centre(v)))
faces = kernel.faces(box)
top = max(faces, key=lambda f: kernel.shape_centre(f)[2])
bottom = min(faces, key=lambda f: kernel.shape_centre(f)[2])
side = min(faces, key=lambda f: kernel.shape_centre(f)[0])

win._shortcut_actions["measure"].trigger()
pump()
measure = win.measure_dialog
check("M opens Measure", measure is not None and measure.isVisible())
check("and points, edges and faces can all be picked",
      vp.selection_mode == "measure")
check("with nothing picked it says what to do",
      "Select geometry" in measure.readout.toPlainText())

real = vp.selected_shapes


def pick(shape):
    vp.selected_shapes = lambda: [shape]
    win._on_viewport_selection()
    vp.selected_shapes = real
    pump()


pick(high)
text = measure.readout.toPlainText()
check("one point says where it is", "Point" in text and "X 40" in text
      and "Y 30" in text and "Z 20" in text, text)
pick(low)
text = measure.readout.toPlainText()
check("a second point measures straight across to it",
      "Distance  53.85" in text, text)
check("with the X, Y and Z distances",
      "dX 40" in text and "dY 30" in text and "dZ 20" in text, text)
check("and a line between them in the view", bool(measure._drawn))
pick(top)
text = measure.readout.toPlainText()
check("a third pick starts again", text.startswith("First")
      and "Face" in text and "Second" not in text, text)
check("a face says its area", "Area 1200" in text, text)
pick(bottom)
text = measure.readout.toPlainText()
check("two faces: the distance between them", "Distance  20" in text, text)
check("and the angle between them", "Angle     180 deg" in text, text)
pick(side)
pick(top)
text = measure.readout.toPlainText()
check("square faces are at 90", "Angle     90 deg" in text, text)
measure.copy()
check("Copy puts the readout on the clipboard",
      "Angle" in QtWidgets.QApplication.clipboard().text())
measure.restart()
check("Restart forgets both", not measure.picks and not measure._drawn)
measure.close()
pump()
check("closing puts the picking back as it was",
      vp.selection_mode == "face" and win.measure_dialog is None,
      vp.selection_mode)

# ==========================================================================
print("#190 Split: faces, or a solid in two, along a plane or a face")

from datum.core.features import SplitFeature, WorkPlaneFeature     # noqa: E402
from datum.core.naming import RefSet                               # noqa: E402
from datum.ui import icons                                         # noqa: E402

check("it has its icons", all(not icons.icon(n, 24).isNull()
                              for n in ("split", "split_faces",
                                        "split_solid")))
win.new_document(prompt=False)
win.new_primitive("box")
pump()
win._active_dialog.commit()
pump()
level = WorkPlaneFeature()
level.base, level.offset = "XY", "8"
win.document.add_feature(level)
win.rebuild()
pump()
win.new_feature(SplitFeature)
pump()
split = win._active_dialog
check("the Split dialog opens", type(split).__name__ == "SplitDialog")
split.plane.setCurrentIndex(split.plane.findData(level.name))
split.method.set_value("solid")
split.preview()
pump()
names = [b.name for b in win.document.bodies]
check("Split Solid cuts it in two solids", names == ["Solid1", "Solid2"],
      names)
volumes = sorted(round(kernel.volume(b.shape)) for b in win.document.bodies)
check("at the plane", volumes == [9600, 14400], volumes)
split.method.set_value("faces")
split.all_faces.setChecked(True)
split.preview()
pump()
check("Split Faces with All Faces divides every face it crosses",
      len(win.document.bodies) == 1
      and len(kernel.faces(win.document.shape)) == 10,
      len(kernel.faces(win.document.shape)))
split.all_faces.setChecked(False)
base = win.pick_shape()
left = min(kernel.faces(base), key=lambda f: kernel.shape_centre(f)[0])
real_faces = vp.selected_faces
vp.selected_faces = lambda: [left]
split.faces_pick.set_picking(True)
split.on_selection()
vp.selected_faces = real_faces
pump()
check("or only the faces picked", len(kernel.faces(win.document.shape)) == 7,
      len(kernel.faces(win.document.shape)))
# a flat face of the part as the tool: the left end, cutting along X
split.method.set_value("solid")
vp.selected_faces = lambda: [left]
split.tool_pick.set_picking(True)
split.on_selection()
vp.selected_faces = real_faces
pump()
check("a picked face is the tool, and the plane list stands aside",
      len(split.feature.tool) == 1 and not split.plane.isEnabled())
check("which misses the solid it is a face of, and says so",
      "does not cross" in (split.feature.error or ""), split.feature.error)
split._clear_tool()
split.plane.setCurrentIndex(split.plane.findData(level.name))
split.commit()
pump()
check("OK keeps it, saved and read back", any(
    isinstance(f, SplitFeature) and f.mode == "solid"
    for f in win.document.features))
again = Document()
again.load_dict(win.document.to_dict())
again.rebuild()
check("and builds the same from the file",
      [b.name for b in again.bodies] == ["Solid1", "Solid2"],
      [b.name for b in again.bodies])

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all batch 20 tests passed")
sys.exit(0)
