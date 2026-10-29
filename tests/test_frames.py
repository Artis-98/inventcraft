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
from datum.core.features import (                                 # noqa: E402
    ExtrudeFeature, FrameEndsFeature, FrameMemberFeature, HoleFeature,
    SketchFeature)
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
check("the frame lives where Inventor puts it: Table/Frame0001",
      os.path.normcase(folder) == os.path.normcase(
          os.path.join(WORK, "Table", "Frame0001")), folder)
member = Document.load(os.path.join(folder, sorted(parts)[-1]))
check("a member's part is made as Inventor makes one: the profile's "
      "sketch, extruded G_L long, then its end treatments",
      [type(f) for f in member.features]
      == [SketchFeature, ExtrudeFeature, FrameEndsFeature]
      and member.features[1].distance == "G_L"
      and member.features[2].size, [type(f) for f in member.features])
check("the profile's sizes are the part's parameters",
      {"G_B", "G_T", "G_L"} <= set(member.params.names()),
      member.params.names())
check("and the extrusion is a solid, there to cut from",
      member.last_report.ok and member.shape is not None
      and len(member.bodies) == 1)


def member_length(path):
    return float(next(f for f in Document.load(path).features
                      if isinstance(f, FrameEndsFeature)).length)

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
lengths = sorted(round(member_length(os.path.join(folder, m.part)), 3)
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
lengths = sorted(round(member_length(os.path.join(folder, m.part)), 3)
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

print("a member's part, made the way Inventor makes it")
part_path = os.path.join(WORK, "member.icpart")
tube = frames.family("din-en-10219-2-square")
member = frames.Member(id=7, family=tube.id, size="40 x 40 x 3")
frames.write_member_part(part_path, member, tube, 500.0,
                         {"extend_a": 10.0, "extend_b": 5.0})
part = Document.load(part_path)
want = kernel.volume(frames.member_solid("square_tube", tube.row(
    "40 x 40 x 3"), "", False, 500.0, 10.0, 5.0))
check("the sketch extruded is the tube, ends run on and all",
      near(kernel.volume(part.shape), want, 1e-3 * want)
      and near(kernel.bounding_box(part.shape)[2], -10.0, 1e-3)
      and near(part.params["G_L"].value, 515.0), kernel.volume(part.shape))
sketch = part.features[0].sketch
check("the profile's sketch has its dimensions, in the parameters",
      {c.expression for c in sketch.constraints.values() if c.expression}
      == {"G_B", "G_T", "G_RO"})
part.set_parameter("G_T", "2")
part.rebuild()
check("a new thickness in the part itself makes a thinner tube",
      part.last_report.ok and near(kernel.volume(part.shape), kernel.volume(
          frames.member_solid("square_tube", {"b": 40.0, "t": 2.0,
                                              "ro": 6.0}, "", False, 500.0,
                              10.0, 5.0)), 1.0))
part.save(part_path)
member.size = "50 x 50 x 4"
frames.write_member_part(part_path, member, tube, 500.0,
                         {"extend_a": 10.0, "extend_b": 5.0})
part = Document.load(part_path)
want = kernel.volume(frames.member_solid("square_tube", tube.row(
    "50 x 50 x 4"), "", False, 500.0, 10.0, 5.0))
check("a new size from the frame sets them again",
      near(kernel.volume(part.shape), want, 1e-3 * want))

angle = frames.family("din-en-10056-1-equal")
for mirror in (False, True):
    member = frames.Member(id=8, family=angle.id, size="L40x40x4",
                           mirror=mirror)
    path = os.path.join(WORK, "angle%d.icpart" % mirror)
    frames.write_member_part(path, member, angle, 300.0)
    part = Document.load(path)
    want = kernel.volume(frames.member_solid("angle", angle.row("L40x40x4"),
                                             "", mirror, 300.0))
    box = kernel.bounding_box(part.shape)
    check("an angle%s, from its sketch" % (" mirrored" if mirror else ""),
          near(kernel.volume(part.shape), want, 1e-3 * want)
          and (box[0] < -39 if mirror else box[3] > 39)
          and not all(p.fixed for p in part.features[0].sketch.points
                      .values()))

print("a member of a sketch profile of your own")
bar = Document()
bar.params.add("W", "30")
bf = SketchFeature(name="Profile")
bf.sketch = Sketch(SketchPlane(), "Profile")
sides = bf.sketch.add_rectangle((0.0, 0.0), (30.0, 10.0))
corner = bf.sketch.entities[sides[0]].points
bf.sketch.add_constraint("fix", points=[corner[0]])
bf.sketch.add_constraint("distance_x", points=corner, value=30.0,
                         expression="W")
bf.sketch.add_constraint("distance_y", points=[
    corner[0], bf.sketch.entities[sides[2]].points[1]], value=10.0)
bar.add_feature(bf)
bar.rebuild()
bar_path = bar.save(os.path.join(WORK, "Bar"))
bars = frames.ProfileFamily("bars", "Bars", "Workshop", "Flat Bars",
                            "sketch", ["W"], [["30", 30], ["50", 50]],
                            source=bar_path)
member = frames.Member(id=9, family="bars", size="30")
path = os.path.join(WORK, "bar.icpart")
frames.write_member_part(path, member, bars, 200.0)
part = Document.load(path)
check("its sketch is the member's, the width a parameter",
      near(kernel.volume(part.shape), 30 * 10 * 200.0, 1.0)
      and near(part.params["W"].value, 30.0), kernel.volume(part.shape))
member.size = "50"
frames.write_member_part(path, member, bars, 200.0)
part = Document.load(path)
check("and a new size widens it", near(kernel.volume(part.shape),
                                       50 * 10 * 200.0, 1.0),
      kernel.volume(part.shape))

print("a member's part from before members were sketches")
old = Document()
legacy = FrameMemberFeature()
for key, value in {"family": tube.id, "size": "40 x 40 x 3",
                   "kind": "square_tube", "dims": tube.row("40 x 40 x 3"),
                   "length": "%.6f" % 400.0}.items():
    setattr(legacy, key, value)
old.add_feature(legacy)
centres = SketchFeature()
centres.sketch = Sketch(STANDARD_PLANES["XZ"], "Hole")
centres.sketch.add_circle((0.0, 100.0), 5.0)
old.add_feature(centres)
hole = HoleFeature()
hole.sketch_id = centres.id
hole.diameter = "10"
hole.depth = "100"
hole.through = True
old.add_feature(hole)
old.rebuild()
drilled = kernel.volume(old.shape)
old_path = old.save(os.path.join(WORK, "old member"))
member = frames.Member(id=10, family=tube.id, size="40 x 40 x 3")
frames.write_member_part(old_path, member, tube, 400.0)
part = Document.load(old_path)
check("it is made over as a sketch and an extrusion, the hole kept",
      [type(f) for f in part.features] == [SketchFeature, ExtrudeFeature,
                                           FrameEndsFeature, SketchFeature,
                                           HoleFeature]
      and near(kernel.volume(part.shape), drilled, 1.0),
      [type(f).__name__ for f in part.features])

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
