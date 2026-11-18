"""Miter every corner at once: the six sides of a hexagon picked, all six
corners mitered, each member cut on the half angle at both its ends."""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import frames, kernel                             # noqa: E402
from datum.core.assembly import AssemblyDocument                  # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import FrameEndsFeature, SketchFeature   # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                 # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_miter_all_")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


skeleton = Document()
hexagon = SketchFeature(name="Hex")
hexagon.sketch = Sketch(SketchPlane(), "Hex")
corners = [(500 * math.cos(math.radians(60 * i)),
            500 * math.sin(math.radians(60 * i))) for i in range(6)]
for i in range(6):
    hexagon.sketch.add_line(corners[i], corners[(i + 1) % 6])
# and a line off on its own, picked too, meeting nothing
hexagon.sketch.add_line((2000.0, 0.0), (2000.0, 400.0))
skeleton.add_feature(hexagon)
skeleton.rebuild()
skeleton_path = skeleton.save(os.path.join(WORK, "Hex skeleton"))
asm = AssemblyDocument()
asm.path = os.path.join(WORK, "Hex.icasm")
asm.save(asm.path)
occ = asm.place(skeleton_path)
sketches = frames.skeleton_sketches(skeleton_path)
sid = next(iter(sketches))
frame, _o, problems = frames.insert(asm, occ, sid, sorted(sketches[sid][2]),
                                    "din-en-10219-2-square", "40 x 40 x 3")
ids = [m.id for m in frame.frame.members]
check("seven members", len(ids) == 7 and not problems, problems)

# picked in any order
picked = [ids[3], ids[0], ids[5], ids[6], ids[1], ids[4], ids[2]]
pairs = frames.meeting_pairs(frame, picked)
check("the six corners found, two by two, the lone one in none",
      len(pairs) == 12 and ids[6] not in pairs, pairs)
corner_sets = {frozenset(pairs[i:i + 2]) for i in range(0, len(pairs), 2)}
check("each corner is two sides next to each other",
      corner_sets == {frozenset((ids[i], ids[(i + 1) % 6]))
                      for i in range(6)}, corner_sets)
_t, problems = frames.add_treatment(frame, "miter", pairs, gap=0.0,
                                    split=True)
check("one miter does them all", not problems, problems)
folder = os.path.dirname(frame.path)
cut_twice = 0
for mid in ids[:6]:
    m = frame.frame.member(mid)
    part = Document.load(os.path.join(folder, m.part))
    ends = next(f for f in part.features if isinstance(f, FrameEndsFeature))
    cut_twice += len(ends.cuts) == 2
check("every side is cut at both its ends", cut_twice == 6, cut_twice)
asm.save(asm.path)
asm.rebuild()
check("and the hexagon builds", asm.shape is not None
      and kernel.volume(asm.shape) > 0)

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
