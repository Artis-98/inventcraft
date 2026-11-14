"""Adaptive projection through the window, edited in place (#319).

The cover is edited in place inside the assembly.  Its sketch is opened,
Project Geometry armed, and the plate's hole edge, ghosted round the
cover, is clicked.  That makes an adaptive link in the assembly.  Back
out, the plate is moved, and the cover's projected circle follows it.
The component menu's Adaptive turns it off and on.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from OCP.BRepAdaptor import BRepAdaptor_Curve  # noqa: E402
from OCP.GeomAbs import GeomAbs_Circle  # noqa: E402
from PySide6 import QtCore, QtWidgets  # noqa: E402

from datum.core import kernel  # noqa: E402
from datum.core.assembly import AssemblyDocument  # noqa: E402
from datum.core.document import Document  # noqa: E402
from datum.core.features import (  # noqa: E402
    ExtrudeFeature, PrimitiveFeature, SketchFeature,
)
from datum.core.sketch import Sketch, SketchPlane  # noqa: E402
from datum.ui.main_window import MainWindow  # noqa: E402
from datum.ui.theme import stylesheet  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_adaptive_ui_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


# -- the files -----------------------------------------------------------
plate_doc = Document()
block = PrimitiveFeature()
block.kind = "box"
block.a, block.b, block.c = "80", "60", "6"
plate_doc.add_feature(block)
hole = SketchFeature()
hole.sketch = Sketch(SketchPlane((0, 0, 6), (0, 0, 1), (1, 0, 0), "Top"),
                     "Hole")
hole.sketch.add_circle((40, 30), 8)
plate_doc.add_feature(hole)
cut = ExtrudeFeature()
cut.sketch_id = hole.id
cut.operation = "cut"
cut.extent = "through_all"
plate_doc.add_feature(cut)
plate_doc.rebuild()
plate = plate_doc.save(os.path.join(WORK, "plate.icpart"))

cover_doc = Document()
slab = PrimitiveFeature()
slab.kind = "box"
slab.a, slab.b, slab.c = "80", "60", "4"
cover_doc.add_feature(slab)
follow = SketchFeature()
follow.sketch = Sketch(SketchPlane((0, 0, 4), (0, 0, 1), (1, 0, 0), "Top"),
                       "Follow")
cover_doc.add_feature(follow)
cover_doc.rebuild()
cover = cover_doc.save(os.path.join(WORK, "cover.icpart"))

asm = AssemblyDocument()
first = asm.place(plate)
second = asm.place(cover)
second.grounded = True
first.grounded = False
second.placement.position = [0.0, 0.0, 6.0]
path = asm.save(os.path.join(WORK, "stack.icasm"))

# -- the window ------------------------------------------------------------
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


win.open_assembly(path)
pump()
doc = win.assembly
plate_occ = doc.occurrences[0]
cover_occ = doc.occurrences[1]
check("the assembly opened", doc is not None and len(doc.occurrences) == 2)

print("edit the cover in place and open its sketch")
win.edit_in_place(cover_occ.id)
pump()
check("editing the cover", win.in_place and win.document.path
      and os.path.basename(win.document.path) == "cover.icpart")
check("the plate is ghosted, tagged with its component",
      any(g.get("occurrence") == plate_occ.id for g in win._ghosts))
win.edit_sketch(follow.id)
pump()
win.viewport.set_view("top")
win.viewport.fit_all() if hasattr(win.viewport, "fit_all") else None
pump()
win.project_geometry()
check("Project Geometry is armed", win.editor.tool == "project")

ghost = next(g for g in win._ghosts if g.get("occurrence") == plate_occ.id)
ring = next(e for e in kernel.edges(ghost["shape"])
            if BRepAdaptor_Curve(e).GetType() == GeomAbs_Circle
            and abs(kernel.shape_centre(e)[2] + 0.0) < 1e-6)
curve = BRepAdaptor_Curve(ring)
p = curve.Value(curve.FirstParameter())
x, y = win.viewport.project((p.X(), p.Y(), p.Z()))
win.viewport.selected_shapes = lambda: []
win.viewport._press_pos = QtCore.QPoint(int(round(x)), int(round(y)))
win._project_picked_edge()
del win.viewport.selected_shapes
pump()
check("a link was made in the assembly", len(doc.adaptive) == 1,
      doc.adaptive)
sketch = win.document.feature(follow.id).sketch
record = sketch.projections[-1] if sketch.projections else None
check("the sketch has the circle, tied to the link",
      record is not None and doc.adaptive
      and record.source == {"adaptive": doc.adaptive[0].id},
      record.source if record else None)
check("it says so", "adaptive" in win.status_message.text(),
      win.status_message.text())


def circle():
    sk = win._in_place_document(cover).feature(follow.id).sketch
    rec = next(r for r in sk.projections if "adaptive" in r.source)
    entity = sk.entities[rec.entities[0]]
    c = sk.points[entity.points[0]]
    return round(c.x, 3), round(c.y, 3), round(entity.radius, 3)


check("over the plate's hole", circle() == (40.0, 30.0, 8.0), circle())

win.finish_sketch()
pump()
win.finish_in_place()
pump()

print("the plate moves")
plate_occ.placement.position = [12.0, -6.0, 0.0]
win.assembly_ui.rebuild()
pump()
check("the circle follows", circle() == (52.0, 24.0, 8.0), circle())

print("Adaptive off from the component menu")
win.assembly_ui.toggle_adaptive(cover_occ.id)
pump()
check("the link is off", not doc.adaptive[0].adaptive)
plate_occ.placement.position = [0.0, 0.0, 0.0]
win.assembly_ui.rebuild()
pump()
check("the circle stays", circle() == (52.0, 24.0, 8.0), circle())
win.assembly_ui.toggle_adaptive(cover_occ.id)
pump()
check("on again, it catches up", circle() == (40.0, 30.0, 8.0), circle())

print("saved")
win.save_document()
pump()
back = AssemblyDocument.load(path)
check("the link is in the file", len(back.adaptive) == 1)
alone = Document.load(cover)
alone.rebuild()
rec = next(r for r in alone.feature(follow.id).sketch.projections
           if "adaptive" in r.source)
check("the cover was saved with its circle", not rec.stale)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
