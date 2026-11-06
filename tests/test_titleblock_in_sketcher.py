"""Sketching on a drawing, as Inventor does, with the part's own sketch
editor and Sketch tab, in place on the sheet:

* the title block, edited where it is, back on every sheet at Finish, its
  bottom right corner on the border's;
* Start Sketch, then a click on the sheet: a sketch of the sheet's own;
* Start Sketch, then a click on a view: the view's sketch, which moves with
  it, and whose Project Geometry takes that view's lines only.

They live in the drawing alone.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                           # noqa: E402

from datum.core import dxf                                      # noqa: E402
from datum.ui.main_window import TAB_SKETCH, MainWindow          # noqa: E402
from datum.ui.titleblock_ui import block_rect                    # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_dsketch_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def pump(n=30):
    for _ in range(n):
        app.processEvents()


win = MainWindow()
win.resize(1400, 900)
win.show()
win.new_document(prompt=False)
win.new_primitive("box")
win._active_dialog.commit()
win.document.path = os.path.join(WORK, "Block.icpart")
win.save_document()
win.new_drawing(prompt=False)
win.drawing.path = os.path.join(WORK, "S.icdraw")
win.save_document()
pump()
drawing = win.drawing
sheet = drawing.active()
ui = win.drawing_ui
tabs_before = len(win.session.documents)

print("the title block, in place on the sheet")
name = sheet.title_block
ui.edit_title_block()
pump()
check("the Sketch tab, on the drawing, no tab of its own",
      win.editor.active and win.ribbon._buttons[TAB_SKETCH].isVisible()
      and len(win.session.documents) == tabs_before
      and win.session.active.document is drawing)
sk = win.editor.sketch
check("with the block's lines and text, properties and all",
      len(sk.entities) >= 10 and any("<Model.PartNumber>" in t.text
                                     for t in sk.texts.values()))
win.editor.begin_change()
sk.add_circle((300.0, 20.0), 10.0)
win.editor._touch()
out = dxf.DxfDocument()
out.line((0, 0), (40, 0))
out.text((2, 2), 3.5, "LOGO")
dxf_path = os.path.join(WORK, "logo.dxf")
out.save(dxf_path)
before = (len(sk.entities), len(sk.texts))
win.import_sketch_dxf(dxf_path)
check("Import DXF adds its line and text",
      (len(sk.entities), len(sk.texts)) == (before[0] + 1, before[1] + 1))
win.finish_sketch()
pump()
block = drawing.title_blocks[name]
check("Finish Sketch: the block is the sketch, 310 wide with the circle",
      not win.editor.active and block.sketch is not None
      and abs(block.width - 310.0) < 1e-6, block.width)
w, h = sheet.extent()
frame = drawing.borders[sheet.border].frame(w, h)
rect = block_rect(drawing, sheet)
check("its bottom right on the border's", abs(rect[2] - frame[2]) < 1e-9
      and abs(rect[1] - frame[1]) < 1e-9)

print("Start Sketch on the sheet")
ui.start_sketch()
ui._placer.press((60.0, 60.0), None)
pump()
check("a click on empty sheet starts a sketch there",
      win.editor.active and ui.sheet_sketch_active)
win.editor.begin_change()
win.editor.sketch.add_line((50.0, 50.0), (90.0, 50.0))
win.editor._touch()
win.finish_sketch()
pump()
check("finished, it is the sheet's sketch",
      len(sheet.sketches) == 1 and sheet.sketches[0].view == 0
      and sheet.sketches[0].name == "Sketch1")

print("Start Sketch on a view")
ui.place_base_view()
pump()
session = ui._placer
session.dialog.scale.setEditText("1:1")
session.projections.wait()
session.dialog.place_requested.emit()
pump(40)
view = sheet.views[0]
ui.start_sketch()
ui._placer.press((view.x, view.y), None)
pump()
check("a click on a view sketches on it", ui.sheet_sketch_active)
surface = ui._sheet_sketch["surface"]
win.set_sketch_tool("project")
box = view.projection.box
edge_uv = (box[0], 0.0)
taken = surface.project_hook(edge_uv)
check("Project Geometry takes that view's line",
      taken and any(e.construction for e in win.editor.sketch.entities
                    .values()))
count = len(win.editor.sketch.entities)
surface.project_hook((box[2] + 200.0, 0.0))
check("and nothing off the view", len(win.editor.sketch.entities) == count)
win.set_sketch_tool("line")
win.editor.begin_change()
win.editor.sketch.add_line((0.0, 0.0), (10.0, 10.0))
win.editor._touch()
win.finish_sketch()
pump()
mine = sheet.sketches[-1]
check("finished, it is the view's", mine.view == view.id)
before = sheet.sketch_origin(mine)
view.x += 25.0
check("and it moves with the view",
      sheet.sketch_origin(mine) == (before[0] + 25.0, before[1]))
again = type(sheet).from_dict(sheet.to_dict())
check("saved in the drawing, and only there",
      len(again.sketches) == 2 and not hasattr(win.document, "sketches"))

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
