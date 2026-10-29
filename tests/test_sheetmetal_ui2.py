"""Sheet metal in the window, part two: a STEP body converted from a
picked base face, the Flat Pattern environment with its own tab, tree and
Bend Perforation, its DXF, and the Hem, Fold, Contour Flange and Corner
Seam dialogs."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox                   # noqa: E402

from datum.core import fileio, kernel, sheetmetal as sm            # noqa: E402
from datum.core.features import (                                 # noqa: E402
    ContourFlangeFeature, CornerSeamFeature, FlangeFeature, FoldFeature,
    HemFeature, ImportFeature, SheetFaceFeature,
)
from datum.ui import sheetmetal_ui                                 # noqa: E402
from datum.ui.main_window import TAB_FLAT, TAB_SHEET, MainWindow   # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_sheet_ui2_")
SHOTS = os.environ.get("DATUM_SHOTS", "")
T = 2.0


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-3):
    return abs(a - b) < tol


def edge_where(shape, test):
    for e in kernel.explore(shape, kernel.TopAbs_EDGE):
        if sm._is_line(e) and all(test(p) for p in sm._edge_ends(e)):
            return e
    return None


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()


def pump(n=4):
    for _ in range(n):
        app.processEvents()


def settle(ms=400):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


# ==========================================================================
print("a STEP body, converted from its base face")

plate = BRepPrimAPI_MakeBox(100, 60, T).Shape()
bracket = sm.flange(plate, edge_where(plate, lambda p: abs(p[2] - T) < 1e-9
                                      and abs(p[1]) < 1e-9), T, 2.0, 90, 30)
step = os.path.join(WORK, "bracket.stp")
fileio.write_step(bracket, step)
win.new_document(prompt=False)
pump()
feature = ImportFeature()
feature.path = step
win.document.add_feature(feature)
win.rebuild()
pump()
win.convert_to_sheet_metal()
pump()
dialog = getattr(win, "convert_dialog", None)
check("a body asks for its base face first", dialog is not None
      and dialog.isVisible() and win.document.sheet_metal is None)
side = max((f for f in kernel.faces(win.document.shape)
            if sm._kind(f) != sm.GeomAbs_Plane), key=kernel.face_area)
check("a curved face is turned down, saying why",
      not dialog.take_face(side) and "not flat" in dialog.prompt.text())
top = max((f for f in kernel.faces(win.document.shape)
           if sm._kind(f) == sm.GeomAbs_Plane
           and near(kernel.bounding_box(f)[2], T, 1e-6)
           and near(kernel.bounding_box(f)[5], T, 1e-6)),
          key=kernel.face_area)
check("the top face is taken", dialog.take_face(top))
check("and the thickness measured from it, 2",
      dialog.thickness.text() == "2", dialog.thickness.text())
dialog.accept()
pump()
check("converted, at that thickness", win.document.sheet_metal is not None
      and near(win.document.parameter_scope()["Thickness"], 2.0))
check("on that base face", bool(win.document.sheet_metal.base))
check("the Sheet Metal tab is up", win.ribbon.current_tab() == TAB_SHEET)

# ==========================================================================
print("the Flat Pattern environment")

check("Flat Pattern lays it flat in the view", win.enter_flat())
pump()
check("with its own tab", win.ribbon.current_tab() == TAB_FLAT)
shown = win.viewport._model_shape
box = kernel.bounding_box(shown)
check("the view shows the flat, 2 thick and 86.524 x 100",
      near(box[5] - box[2], 2.0, 0.02)
      and sorted([round(box[3] - box[0], 1), round(box[4] - box[1], 1)])
      == [86.5, 100.0], [round(c, 3) for c in box])


def tree_texts():
    out = []

    def walk(item):
        for i in range(item.childCount()):
            out.append(item.child(i).text(0))
            walk(item.child(i))
    walk(win.browser.topLevelItem(0))
    return out


check("the tree has the Flat Pattern after the part",
      "Flat Pattern" in tree_texts(), tree_texts())

print("Bend Perforation")
sheetmetal_ui.BendPerforationDialog.exec = \
    lambda self: QtWidgets.QDialog.Accepted
check("one is added", win.edit_flat_feature(-1))
pump()
features = win.document.sheet_metal.flat_features
check("to the flat pattern's own tree",
      len(features) == 1 and "Bend Perforation1" in tree_texts(),
      tree_texts())
dialog = win.perforation_dialog
check("its preview counts the slots", "slot(s)" in dialog.message.text(),
      dialog.message.text())
loops = kernel.explore(win._flat.outline(), kernel.TopAbs_WIRE)
check("the flat in the view has the slots in it", len(loops) > 1,
      len(loops))
if SHOTS:
    win.viewport.fit_all()
    settle(400)
    win.viewport.grab_image(os.path.join(SHOTS, "flat_perforated.png"))
check("the default is the open trapezoid", dialog.style.value() == "trapezoid")

print("a pattern of your own, from a sketch")
from datum.core.features import SketchFeature                     # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                 # noqa: E402
pattern = SketchFeature(name="My pattern")
pattern.sketch = Sketch(SketchPlane(), "My pattern")
pattern.sketch.add_line((0.0, 0.0), (8.0, 0.0))
pattern.sketch.add_line((8.0, 0.0), (11.0, 3.0))
win.document.add_feature(pattern)
own = sheetmetal_ui.BendPerforationDialog(
    win.document, sm.FlatFeature(), win)
check("Take Pattern takes it", own.take_pattern(pattern.id)
      and own.style.value() == "custom" and own.feature.custom,
      own.message.text())
check("and shows it on the flat", "slot(s)" in own.message.text(),
      own.message.text())
own.reject()
win.document.features.remove(pattern)
win.rebuild()
pump()

win.show_flat_pattern()
pump()
written = win.flat_pattern_dialog.export(os.path.join(WORK, "bracket.dxf"))
text = open(written).read()
check("the DXF has the outline, the slots and the bend line",
      text.count("OUTER_PROFILE") > 8 and "BEND_CENTERLINE" in text)
win._flat_requested("suppress", 0)
pump()
check("suppressed, the slots go", features[0].suppressed and len(
    kernel.explore(win._flat.outline(), kernel.TopAbs_WIRE)) == 1)
win.undo()
pump()
check("and Ctrl+Z brings them back",
      not win.document.sheet_metal.flat_features[0].suppressed)
win.exit_flat()
pump()
check("Go to Folded Part shows the bent part again",
      not win.flat_mode and kernel.bounding_box(
          win.viewport._model_shape)[5] > 20)

# ==========================================================================
print("the new features' dialogs")


def plate_part():
    win.new_document(prompt=False)
    pump()
    win.convert_to_sheet_metal()
    win.document.params.set_expression("Thickness", "2")
    win.start_sketch_on_plane("XY")
    settle(500)
    win.editor.sketch.add_rectangle((0.0, 0.0), (100.0, 60.0))
    win.editor.solve()
    win.finish_sketch()
    pump()
    win.new_feature(SheetFaceFeature)
    pump()
    win.select_all_profiles()
    win._active_dialog.commit()
    pump()


plate_part()
win.new_feature(HemFeature)
pump()
hem = win._active_dialog
check("Hem opens its dialog", type(hem).__name__ == "HemDialog")
hem._edges_from_view([edge_where(win.pick_shape(),
                                 lambda p: abs(p[2] - T) < 1e-9
                                 and abs(p[1]) < 1e-9)])
hem.kind.set_value("rolled")
hem._kind_changed("rolled")         # what a click on it does
pump()
check("a new kind takes its own defaults",
      hem.first.text() == "Thickness" and hem.second.text() == "180",
      (hem.first.text(), hem.second.text()))
hem.first.set_text("3")
hem.commit()
pump()
check("a rolled hem, Inventor's volume 13513.274",
      near(kernel.volume(win.document.shape), 13513.274, 0.01),
      kernel.volume(win.document.shape))

plate_part()
win.start_sketch_on_plane("XY")
settle(500)
win.editor.sketch.add_line((0.0, 30.0), (100.0, 30.0))
win.finish_sketch()
pump()
win.new_feature(FoldFeature)
pump()
fold = win._active_dialog
check("Fold opens its dialog, the line found",
      type(fold).__name__ == "FoldDialog" and fold.line.count() == 1)
fold.commit()
pump()
check("folded: the sheet's plane is the sketch's, so it bends down, "
      "12037.699", near(kernel.volume(win.document.shape), 12037.699, 0.01),
      (kernel.volume(win.document.shape),
       win.document.features[-1].error))

win.new_document(prompt=False)
pump()
win.convert_to_sheet_metal()
win.document.params.set_expression("Thickness", "2")
win.start_sketch_on_plane("XZ")
settle(500)
sk = win.editor.sketch
sk.add_line((0.0, 30.0), (0.0, 0.0))
sk.add_line((0.0, 0.0), (40.0, 0.0))
sk.add_line((40.0, 0.0), (40.0, 30.0))
win.editor.solve()
win.finish_sketch()
pump()
win.new_feature(ContourFlangeFeature)
pump()
contour = win._active_dialog
check("Contour Flange opens its dialog",
      type(contour).__name__ == "ContourFlangeDialog")
contour.width.set_text("100")
contour.commit()
pump()
check("a U channel, Inventor's 20284.956",
      near(kernel.volume(win.document.shape), 20284.956, 0.01),
      (kernel.volume(win.document.shape), win.document.features[-1].error))

plate_part()
for test in (lambda p: abs(p[1]) < 1e-9, lambda p: abs(p[0]) < 1e-9):
    win.new_feature(FlangeFeature)
    pump()
    dialog = win._active_dialog
    dialog._edges_from_view([edge_where(win.pick_shape(),
                                        lambda p, t=test: abs(p[2] - T) < 1e-9
                                        and t(p))])
    dialog.height.set_text("30")
    dialog.commit()
    pump()
win.new_feature(CornerSeamFeature)
pump()
seam = win._active_dialog
check("Corner Seam opens its dialog",
      type(seam).__name__ == "CornerSeamDialog")
base = win.pick_shape()
seam._edges_from_view([
    edge_where(base, lambda p: abs(p[0]) < 1e-9 and abs(p[1] - 2) < 1e-9),
    # the second flange's wall ends the relief, the thickness, past the
    # first's bend
    edge_where(base, lambda p: abs(p[0] - 2) < 1e-9 and abs(p[1] - 6) < 1e-9)])
seam.commit()
pump()
together = sm.flanges(plate, [
    edge_where(plate, lambda p: abs(p[2] - T) < 1e-9 and abs(p[1]) < 1e-9),
    edge_where(plate, lambda p: abs(p[2] - T) < 1e-9 and abs(p[0]) < 1e-9)],
    T, 2.0, 90, 30)
check("the corner closed as one Flange on both closes it",
      near(kernel.volume(win.document.shape), kernel.volume(together), 0.01),
      (kernel.volume(win.document.shape), win.document.features[-1].error))
if SHOTS:
    win.viewport.set_view("iso")
    win.viewport.fit_all()
    settle(500)
    win.viewport.grab_image(os.path.join(SHOTS, "corner_seam.png"))

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
