"""The Frame Generator, without a window.

Profiles held to Inventor's own: every DIN EN 10056-1 equal angle and
DIN EN 10219-2 square hollow section's area against its Content Center
table (inventor-explore/explore-frames.ps1), which rounds to 0.01 cm2.
Then a table: a skeleton of a top and four legs, members inserted on its
lines, the skeleton edited and moved, the members following.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import frames, kernel                             # noqa: E402
from datum.core.assembly import AssemblyDocument                  # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import FrameMemberFeature, SketchFeature  # noqa: E402
from datum.core.sketch import STANDARD_PLANES, Sketch, SketchPlane  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_frames_")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


# ==========================================================================
print("profiles, as Inventor's Content Center has them")

# a few rows of Inventor's own tables: designation, area in cm2
INVENTOR_ANGLES = {"L20x20x3": 1.12, "L40x40x4": 3.08, "L100x100x10": 19.2,
                   "L250x250x35": 163.0}
INVENTOR_TUBES = {"20 x 20 x 2": 1.34, "40 x 40 x 3": 4.21,
                  "100 x 100 x 5": 18.4, "400 x 400 x 16": 235.0}
angles = frames.family("din-en-10056-1-equal")
tubes = frames.family("din-en-10219-2-square")
check("44 equal angles and 142 square tubes",
      len(angles.rows) == 44 and len(tubes.rows) == 142)
for size, area in INVENTOR_ANGLES.items():
    d = angles.row(size)
    got = kernel.face_area(frames.equal_angle(**d)) / 100.0
    check("%s: %.3g cm2, Inventor's %.3g" % (size, got, area),
          abs(got - area) / area < 0.006, got)
for size, area in INVENTOR_TUBES.items():
    d = tubes.row(size)
    got = kernel.face_area(frames.square_tube(d["b"], d["t"], d["ro"])) / 100
    check("%s: %.3g cm2, Inventor's %.3g" % (size, got, area),
          abs(got - area) / area < 0.006, got)
every = all(kernel.face_area(frames.square_tube(**tubes.row(s))) > 0
            for s in tubes.sizes()) and all(
    kernel.face_area(frames.equal_angle(**angles.row(s))) > 0
    for s in angles.sizes())
check("every size in both families builds", every)

print("your own family, kept in the library")
mine = frames.ProfileFamily("my-tubes", "My Tubes", "Workshop",
                            "Square Tubes", "square_tube",
                            frames.COLUMNS["square_tube"],
                            [["30x30x2", 30, 2, 3]])
frames.save_family(mine)
check("it is in the library after the built in ones",
      [f.id for f in frames.families()][-1] == "my-tubes")
check("and gives its sizes", frames.family("my-tubes").row("30x30x2")
      == {"b": 30.0, "t": 2.0, "ro": 3.0})
try:
    frames.save_family(angles)
    check("a built in family cannot be overwritten", False)
except ValueError:
    check("a built in family cannot be overwritten", True)

print("a sketch profile of your own")
profile_part = Document()
pf = SketchFeature(name="Profile")
pf.sketch = Sketch(SketchPlane(), "Profile")
pf.sketch.add_rectangle((0.0, 0.0), (30.0, 10.0))
profile_part.add_feature(pf)
profile_part.rebuild()
profile_path = profile_part.save(os.path.join(WORK, "Flat bar"))
face = frames.profile_face("sketch", {}, profile_path)
check("a closed sketch is a profile", near(kernel.face_area(face), 300.0,
                                           1e-6), kernel.face_area(face))

# ==========================================================================
print("a table: a skeleton, members on its lines")

skeleton = Document()
top = SketchFeature(name="Top")
top.sketch = Sketch(SketchPlane((0.0, 0.0, 750.0), (0.0, 0.0, 1.0)), "Top")
top.sketch.add_rectangle((0.0, 0.0), (1000.0, 600.0))
skeleton.add_feature(top)
legs = SketchFeature(name="Legs")
legs.sketch = Sketch(STANDARD_PLANES["XZ"], "Legs")
legs.sketch.add_line((0.0, 0.0), (0.0, 750.0))
legs.sketch.add_line((1000.0, 0.0), (1000.0, 750.0))
skeleton.add_feature(legs)
skeleton.rebuild()
skeleton_path = skeleton.save(os.path.join(WORK, "Table skeleton"))

table = AssemblyDocument()
table.path = os.path.join(WORK, "Table.icasm")
table.save(table.path)
skeleton_occurrence = table.place(skeleton_path)
sketches = frames.skeleton_sketches(skeleton_path)
top_id = next(i for i, s in sketches.items() if s[1] == "Top")
legs_id = next(i for i, s in sketches.items() if s[1] == "Legs")
frame, frame_occurrence, problems = frames.insert(
    table, skeleton_occurrence, top_id, list(sketches[top_id][2]),
    "din-en-10219-2-square", "40 x 40 x 3")
check("four rails, no problems", len(frame.frame.members) == 4
      and not problems, problems)
frame, frame_occurrence, problems = frames.insert(
    table, skeleton_occurrence, legs_id, list(sketches[legs_id][2]),
    "din-en-10056-1-equal", "L40x40x4", anchor="bl",
    frame_occurrence=frame_occurrence)
check("two legs added to the same frame", len(frame.frame.members) == 6
      and not problems, problems)
folder = os.path.dirname(frame.path)
parts = [n for n in os.listdir(folder) if n.endswith(".icpart")]
check("each member a part of its own, beside the frame", len(parts) == 6,
      parts)
check("the frame lives in a folder of its own, Frames/Frame0001",
      folder.replace("\\", "/").endswith("Frames/Frame0001"))
member = Document.load(os.path.join(folder, sorted(parts)[-1]))
feature = member.features[0]
check("a member's part is one Frame Member feature",
      isinstance(feature, FrameMemberFeature) and feature.size)
table.save(table.path)
report = table.rebuild()
box = kernel.bounding_box(table.shape)
# the legs' heels on their lines (anchor bl), their legs running out
check("the frame stands as the skeleton does, tubes centred on its lines",
      near(box[0], -40, 0.05) and near(box[3], 1020, 0.05)
      and near(box[2], 0, 0.05) and near(box[5], 770, 0.05),
      [round(c, 2) for c in box])
rail = next(m for m in frame.frame.members if m.sketch == top_id)
rail_part = Document.load(os.path.join(folder, rail.part))
rail_part.rebuild()
lengths = sorted(round(float(Document.load(os.path.join(folder, m.part))
                             .features[0].length), 3)
                 for m in frame.frame.members if m.sketch == top_id)
check("the rails are the lines' lengths", lengths == [600, 600, 1000, 1000],
      lengths)

print("the skeleton edited: the members follow")
skeleton = Document.load(skeleton_path)
sketch = skeleton.all_sketches()[top_id]
for point in sketch.points.values():
    if near(point.x, 1000.0):
        point.x = 1200.0
skeleton.rebuild()
skeleton.save(skeleton_path)
table.rebuild()
box = kernel.bounding_box(table.shape)
check("the top is 1200 wide now", near(box[3], 1220, 0.05), box)
frame = AssemblyDocument.load(frame.path)
lengths = sorted(round(float(Document.load(os.path.join(folder, m.part))
                             .features[0].length), 3)
                 for m in frame.frame.members if m.sketch == top_id)
check("and the long rails 1200 long", lengths == [600, 600, 1200, 1200],
      lengths)

print("the skeleton moved: the frame goes with it")
skeleton_occurrence.placement.position = [0.0, 0.0, 100.0]
table.rebuild()
box = kernel.bounding_box(table.shape)
check("the frame is 100 higher", near(box[2], 100, 0.05)
      and near(box[5], 870, 0.05), box)

print("merged members")
lines = {1: ((0, 0, 0), (100, 0, 0)), 2: ((100, 0, 0), (250, 0, 0)),
         3: ((250, 0, 0), (250, 80, 0))}
check("two lines in a straight run merge, a corner does not",
      frames.mergeable_runs(lines, [1, 2, 3]) == [[1, 2], [3]],
      frames.mergeable_runs(lines, [1, 2, 3]))
check("a merged run is one member end to end",
      frames.run_of(lines, [1, 2]) == ((0, 0, 0), (250, 0, 0)))

print("placing a member on its line")
import numpy as np                                                 # noqa: E402
m = frames.member_frame((0, 0, 0), (100, 0, 0), (0, 0, 1))
check("its Z runs along the line, its Y up out of the sketch",
      np.allclose(m[:, 2], [1, 0, 0]) and np.allclose(m[:, 1], [0, 0, 1]))
check("a right handed frame", near(np.linalg.det(m), 1.0, 1e-9))
m = frames.member_frame((0, 0, 0), (0, 0, 750), (0, 1, 0), rotate_deg=90)
check("turned about its line, still right handed",
      near(np.linalg.det(m), 1.0, 1e-9) and np.allclose(m[:, 2], [0, 0, 1]))

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
