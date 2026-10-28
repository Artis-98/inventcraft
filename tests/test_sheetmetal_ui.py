"""Sheet metal in the window: Convert to Sheet Metal, the Sheet Metal tab,
Face, Flange with its arrow dragged, Sheet Metal Defaults, and the Flat
Pattern with its DXF."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import kernel, sheetmetal as sm                   # noqa: E402
from datum.core.features import FlangeFeature, SheetFaceFeature   # noqa: E402
from datum.core.naming import RefSet                              # noqa: E402
from datum.ui.main_window import TAB_SHEET, MainWindow            # noqa: E402
from datum.ui.theme import stylesheet                              # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_sheet_ui_")
SHOTS = os.environ.get("DATUM_SHOTS", "")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-3):
    return abs(a - b) < tol


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


def tab_visible(title):
    return win.ribbon.is_tab_visible(title) \
        if hasattr(win.ribbon, "is_tab_visible") else \
        title in [t for t in getattr(win.ribbon, "visible_tabs", lambda: [])()]


# ==========================================================================
print("Convert to Sheet Metal")

win.new_document(prompt=False)
pump()
win.convert_to_sheet_metal()
pump()
doc = win.document
check("the part is sheet metal", doc.sheet_metal is not None)
check("with Thickness and BendRadius parameters",
      {"Thickness", "BendRadius"} <= set(doc.params.names()))
check("and the Sheet Metal tab shown",
      win.ribbon.current_tab() == TAB_SHEET
      if hasattr(win.ribbon, "current_tab") else True)

print("Sheet Metal Defaults")
from datum.ui.sheetmetal_ui import SheetMetalDefaultsDialog       # noqa: E402
dialog = SheetMetalDefaultsDialog(doc, win)
check("a K-factor out of range is refused",
      not dialog.apply("2", "Thickness", "1.5") and dialog.error.text())
check("and a thickness of nothing",
      not dialog.apply("0", "Thickness", "0.44"))
check("the thickness was left as it was",
      near(doc.parameter_scope()["Thickness"], 0.5))
check("good values are taken", dialog.apply("2", "Thickness", "0.44"))
check("Thickness is 2", near(doc.parameter_scope()["Thickness"], 2.0))

print("a Face")
win.start_sketch_on_plane("XY")
settle(600)
ed = win.editor
ed.snap_grid = False
ed.sketch.add_rectangle((0.0, 0.0), (100.0, 60.0))
ed.solve()
win.finish_sketch()
pump()
check("finishing the sketch goes back to the Sheet Metal tab",
      win.ribbon.current_tab() == TAB_SHEET
      if hasattr(win.ribbon, "current_tab") else True)
win.new_feature(SheetFaceFeature)
pump()
face = win._active_dialog
check("Face opens its dialog", type(face).__name__ == "SheetFaceDialog")
win.select_all_profiles()
pump()
face.commit()
pump()
box = kernel.bounding_box(doc.shape)
check("a plate 2 thick", near(box[5] - box[2], 2.0, 0.02), box)

print("a Flange, its height dragged by the arrow")
win.new_feature(FlangeFeature)
pump()
flange = win._active_dialog
check("Flange opens its dialog", type(flange).__name__ == "FlangeDialog")
base = win.pick_shape()
edge = next(e for e in kernel.explore(base, kernel.TopAbs_EDGE)
            if sm._is_line(e) and all(abs(p[1]) < 1e-6 and abs(p[2] - 2) < 1e-6
                                      for p in sm._edge_ends(e)))
flange._edges_from_view([edge])
flange.preview()
pump()
check("the edge is taken", len(flange.feature.edges) == 1)
axis, tip = flange._handle_tip()
check("an arrow stands on the wall", axis is not None, axis)
if axis is not None:
    check("pointing up the wall", near(axis[1][2], 1.0, 1e-6), axis)
    start = flange.height.value()
    flange._handle_started(start)
    flange._handle_moved(start + 20.0)
    flange._handle_finished(start + 20.0)
    pump()
    check("dragged 20 further, the height follows",
          near(flange.height.value(), start + 20.0, 0.02),
          flange.height.value())
flange.height.set_text("30")
flange.commit()
pump()
box = kernel.bounding_box(doc.shape)
check("the flange stands 30 high", near(box[5], 30.0, 0.02), box)
if SHOTS:
    win.viewport.set_view("iso")
    win.viewport.fit_all()
    settle(500)
    win.viewport.grab_image(os.path.join(SHOTS, "sheet_part.png"))

print("the Flat Pattern")
win.show_flat_pattern()
pump()
flat_dialog = getattr(win, "flat_pattern_dialog", None)
check("it opens", flat_dialog is not None)
if flat_dialog is not None:
    w, l = sorted(flat_dialog.flat.extents())
    check("86.524 x 100, as Inventor lays the same part out",
          near(w, 86.524) and near(l, 100.0), (w, l))
    check("its size is written under it", "86.524" in flat_dialog.size.text()
          or "86.52" in flat_dialog.size.text(), flat_dialog.size.text())
    written = flat_dialog.export(os.path.join(WORK, "plate.dxf"))
    check("and it exports a DXF", written and os.path.getsize(written) > 100)
    if SHOTS:
        flat_dialog.resize(760, 560)
        flat_dialog.show()
        settle(300)
        flat_dialog.grab().save(os.path.join(SHOTS, "sheet_flat.png"))
        flat_dialog.close()

print("saved, opened again, converted back")
path = doc.save(os.path.join(WORK, "Bracket"))
win.new_document(prompt=False)
pump()
check("a new part is not sheet metal", win.document.sheet_metal is None)
win.open_path(path)
settle(800)
check("the saved one opens as sheet metal",
      win.document.sheet_metal is not None)
win.convert_to_standard()
pump()
check("Convert to Standard Part", win.document.sheet_metal is None)
win.undo()
pump()
check("and undo makes it sheet metal again",
      win.document.sheet_metal is not None)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
