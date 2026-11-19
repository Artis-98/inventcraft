"""Frames and pipes along a part's own edges, not only a sketch's lines.

A block placed in an assembly offers its straight edges to Insert Frame:
three tubes go along three of its edges, corner to corner, lying flat on
a face beside each.  The block made longer, its members follow.  A pipe
runs along two edges meeting at a corner, bent round it.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtWidgets                              # noqa: E402

from datum.core import frames, kernel                              # noqa: E402
from datum.core.assembly import AssemblyDocument                   # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature                   # noqa: E402
from datum.ui.main_window import MainWindow                        # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_frame_edges_")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def settle(ms=300):
    loop = QtCore.QEventLoop()
    QtCore.QTimer.singleShot(ms, loop.quit)
    loop.exec()


def near(a, b, tol=0.05):
    return abs(a - b) < tol


block = Document()
feature = PrimitiveFeature(kind="box", a="500", b="300", c="200")
block.add_feature(feature)
block.rebuild()
BLOCK = block.save(os.path.join(WORK, "Block"))

print("a part's edges as lines")
edges = frames.model_edges(block)
check("a block offers its twelve edges", len(edges) == 12, len(edges))
check("each a sketch of one line, under a negative id",
      all(sid < 0 and len(found[2]) == 1 for sid, found in edges.items()))
check("each lying on a face beside it", all(
    abs(sum(c * c for c in found[0].normal) - 1.0) < 1e-6
    and abs(sum(found[0].normal[i] * (found[2][1][1][i] - found[2][1][0][i])
                for i in range(3))) < 1e-6 for found in edges.values()))

asm = AssemblyDocument()
asm.path = os.path.join(WORK, "Rig.icasm")
asm.place(BLOCK)
asm.save(asm.path)
win.open_path(asm.path)
settle(800)
lines = win.assembly_ui.component_sketch_lines()
check("the assembly offers the block's edges to pick", len(lines) == 12,
      len(lines))


def along(axis, at):
    """The edge running along ``axis`` through the corner ``at``."""
    for key, (a, b) in lines.items():
        d = [b[i] - a[i] for i in range(3)]
        if all(abs(d[i]) < 1e-6 for i in range(3) if i != axis) and all(
                near(min(a[i], b[i]), at[i]) for i in range(3)):
            return key
    return None


corner = (0.0, 0.0, 200.0)
picked = [along(0, corner), along(1, corner), along(2, (0.0, 0.0, 0.0))]
check("three edges from one top corner found", all(picked), picked)

print("Insert Frame along them")
dialog = win.insert_frame()
settle(200)
check("the edges are candidates", len(dialog.candidates()) == 12,
      len(dialog.candidates()))
dialog.add_lines([k for k in picked if k])
check("a square tube chosen",
      dialog.choose("din-en-10219-2-square", "40 x 40 x 3"))
check("it applies", dialog.apply(), dialog.message.text())
settle(300)
frame = [o for o in win.assembly.occurrences if o.follows]
check("a frame follows the block", len(frame) == 1)
fd = frames.read_frame(win.assembly.component_path(frame[0]))
check("with three members", fd is not None and len(fd.members) == 3,
      fd and len(fd.members))
check("each on an edge", fd is not None
      and all(m.sketch < 0 for m in fd.members))
box = kernel.bounding_box(win.assembly.shape)
check("the tubes run the block's length and width",
      box[3] >= 500 - 0.1 and box[4] >= 300 - 0.1, [round(c) for c in box])
dialog.close()
settle(200)

print("the block made longer: the members follow")
live = win._in_place_document(BLOCK)
live.features[0].a = "800"
live.rebuild()
live.save(BLOCK)
win.assembly_ui.rebuild()
settle(300)
box = kernel.bounding_box(win.assembly.shape)
check("the frame is 800 long now", box[3] >= 800 - 0.1 and box[3] < 830,
      [round(c) for c in box])

print("a pipe round a corner of the block")
dialog = win.insert_frame()
settle(200)
lines = win.assembly_ui.component_sketch_lines()
corner = (0.0, 300.0, 200.0)
legs = [along(0, corner), along(2, (0.0, 300.0, 0.0))]
pipe_family = next((f.id for f in frames.families() if f.kind == "pipe"),
                   None)
check("a pipe family exists", pipe_family is not None)
if pipe_family and all(legs):
    fam = frames.family(pipe_family)
    dialog.choose(pipe_family, fam.sizes()[len(fam.sizes()) // 2]
                  if hasattr(fam, "sizes") else fam.rows[0]["size"])
    dialog.add_lines(legs)
    ok = dialog.apply()
    check("the pipe applies", ok, dialog.message.text())
    fd = frames.read_frame(win.assembly.component_path(
        [o for o in win.assembly.occurrences if o.follows][0]))
    pipes = [m for m in fd.members if frames.family(m.family).kind == "pipe"]
    check("one pipe, along both edges", len(pipes) == 1
          and len(pipes[0].lines or pipes[0].segments) >= 1,
          [(m.lines, m.segments) for m in pipes])
dialog.close()

print()
print("FAILED: %s" % FAILS if FAILS else "ALL PASSED")
sys.exit(1 if FAILS else 0)
