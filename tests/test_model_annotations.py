"""Model annotations: dimensions and hole notes on the 3D part (#269).

Asked for on GitHub (issue 10): Inventor's Annotate tab, with dimensions on
the model and Hole/Thread notes.  A plate with a counterbored hole gets a
thickness dimension between its two big faces, a length on one edge, a
diameter on a round edge, and a hole note on the bore.  They are saved
with the part, follow it when it changes, and say so when what they
measured is gone.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface  # noqa: E402
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder, GeomAbs_Line  # noqa: E402
from OCP.TopoDS import TopoDS  # noqa: E402
from PySide6 import QtWidgets  # noqa: E402

from datum.core import annotations as notes  # noqa: E402
from datum.core import kernel  # noqa: E402
from datum.core.document import Document  # noqa: E402
from datum.core.features import (  # noqa: E402
    HoleFeature, PrimitiveFeature, SketchFeature,
)
from datum.core.sketch import Sketch, SketchPlane  # noqa: E402
from datum.ui.main_window import MainWindow, TAB_MODEL_ANNOTATE  # noqa: E402
from datum.ui.theme import stylesheet  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_annotations_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1300, 850)
win.show()
app.processEvents()


def pump(n=6):
    for _ in range(n):
        app.processEvents()


def built(test, seconds=20.0):
    """Wait for a rebuild the window may have handed to a worker."""
    import time
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if test():
            return True
        time.sleep(0.05)
    return False


# a 100 x 60 x 10 plate with a counterbored hole
doc = Document()
block = PrimitiveFeature()
block.kind = "box"
block.a, block.b, block.c = "100", "60", "10"
doc.add_feature(block)
points = SketchFeature()
points.sketch = Sketch(SketchPlane((0, 0, 10), (0, 0, 1), (1, 0, 0), "Top"),
                       "Holes")
points.sketch.add_circle((50, 30), 3.3)
doc.add_feature(points)
hole = HoleFeature()
hole.sketch_id = points.id
hole.diameter = "6.6"
hole.hole_type = "counterbore"
hole.cb_diameter = "11"
hole.cb_depth = "6.8"
hole.through = True
doc.add_feature(hole)
doc.rebuild()
path = doc.save(os.path.join(WORK, "plate.icpart"))

win.open_path(path)
pump()
part = win.document
check("the plate opened with its hole", part.shape is not None
      and any(BRepAdaptor_Surface(TopoDS.Face_s(f)).GetType()
              == GeomAbs_Cylinder for f in kernel.faces(part.shape)))
check("parts have an Annotate tab",
      win.ribbon.tab(TAB_MODEL_ANNOTATE) is not None)


def click(*shapes):
    """What the view hands over when these are clicked, one at a time."""
    for shape in shapes:
        # handed over once: the tool clears the selection as it takes it,
        # which asks again, and then there is nothing
        held = [shape]
        win.viewport.selected_shapes = lambda: [held.pop()] if held else []
        win._on_viewport_selection()
        del win.viewport.selected_shapes
        pump(2)


faces = kernel.faces(part.shape)
top = max(faces, key=lambda f: kernel.shape_centre(f)[2])
bottom = min(faces, key=lambda f: kernel.shape_centre(f)[2])
long_edge = next(e for e in kernel.edges(part.shape)
                 if BRepAdaptor_Curve(e).GetType() == GeomAbs_Line
                 and abs(kernel.edge_length(e) - 100.0) < 1e-6)
bore = min((f for f in faces
            if BRepAdaptor_Surface(TopoDS.Face_s(f)).GetType()
            == GeomAbs_Cylinder),
           key=lambda f: BRepAdaptor_Surface(TopoDS.Face_s(f))
           .Cylinder().Radius())
rim = next(e for e in kernel.edges(part.shape)
           if BRepAdaptor_Curve(e).GetType() == GeomAbs_Circle
           and abs(BRepAdaptor_Curve(e).Circle().Radius() - 5.5) < 1e-6)

print("a thickness: top face to bottom face")
win.model_annotate.start("dim")
click(top, bottom)
check("one dimension", len(part.annotations) == 1)
check("reads 10", part.annotations[0].display == "10",
      part.annotations[0].display)

print("a length: one edge and Enter")
click(long_edge)
check("waits for Enter", len(part.annotations) == 1)
win.model_annotate.accept_single()
check("reads 100", part.annotations[-1].display == "100",
      part.annotations[-1].display)

print("a diameter: one round edge")
click(rim)
check("reads Ø11", part.annotations[-1].display == "Ø11",
      part.annotations[-1].display)
win._on_escape()
check("Esc ends the tool", not win.model_annotate.active)

print("a hole note on the bore")
win.model_annotate.start("hole")
click(bore)
note = part.annotations[-1]
check("is a hole note", note.kind == notes.HOLE)
check("reads like the drawing's", note.display.startswith("Ø6.6 THRU")
      and "CBORE Ø11 DEPTH 6.8" in note.display, note.display)
win._on_escape()

print("in the tree")
root = win.browser.topLevelItem(0)
from datum.ui.browser import ROLE_KIND  # noqa: E402
folder = next((root.child(i) for i in range(root.childCount())
               if root.child(i).data(0, ROLE_KIND) == "annotations"), None)
check("an Annotations folder with four", folder is not None
      and folder.childCount() == 4,
      folder.childCount() if folder else None)

print("the plate gets longer")
part.features[0].a = "120"
win.rebuild()
built(lambda: abs(kernel.bounding_box(win.document.shape)[3] - 120.0) < 0.01)
win._draw_visible_sketches()
check("the length reads 120", part.annotations[1].display == "120",
      part.annotations[1].display)
check("the thickness still 10", part.annotations[0].display == "10",
      part.annotations[0].display)

print("text and tolerance")
win.model_annotate.action("toggle", part.annotations[1].id)
check("one hidden", part.annotations[1].hidden)
part.annotations[0].tolerance = "±0.1"
part.annotations[0].text = "<> PLATE"
notes.evaluate(part.annotations[0], part.shape)
check("wrapped", part.annotations[0].display == "10 PLATE ±0.1",
      part.annotations[0].display)

print("saved and opened again")
win.save_document()
again = Document.load(path)
again.rebuild()
check("four come back", len(again.annotations) == 4)
notes.evaluate_all(again)
check("still measuring", [a.display for a in again.annotations][0]
      == "10 PLATE ±0.1", [a.display for a in again.annotations])
check("hidden stays hidden", again.annotations[1].hidden)

print("the hole goes")
part.features[2].suppressed = True
win.rebuild()
built(lambda: len(kernel.faces(win.document.shape)) == 6)
win._draw_visible_sketches()
check("its note is lost, not wrong", part.annotations[3].lost)
check("the diameter on its counterbore too", part.annotations[2].lost)
check("the thickness still fine", not part.annotations[0].lost)

print("delete")
win.model_annotate.action("delete", part.annotations[3].id)
check("three left", len(part.annotations) == 3)
win.undo()
pump()
check("undo brings it back", len(win.document.annotations) == 4)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
