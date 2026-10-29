"""The Frame Generator's end treatments and Change Frame, without a window.

A rectangle of 40 x 40 x 3 square tubes on a 1000 x 600 skeleton, centred
on its lines.  Each treatment is held to what it has to come to by hand:
a miter keeps a member's volume at its section times its line (the cut
planes cross the line where it meets the next), a corner joint stops one
tube at the other's side and runs the other to the first's outside, and
so on.  Then the skeleton is edited and the treated corners follow.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import frames, kernel                             # noqa: E402
from datum.core.assembly import AssemblyDocument                  # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import SketchFeature                     # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                 # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_frame_ends_")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-3):
    return abs(a - b) < tol


skeleton = Document()
top = SketchFeature(name="Top")
top.sketch = Sketch(SketchPlane((0.0, 0.0, 750.0), (0.0, 0.0, 1.0)), "Top")
top.sketch.add_rectangle((0.0, 0.0), (1000.0, 600.0))
skeleton.add_feature(top)
skeleton.rebuild()
skeleton_path = skeleton.save(os.path.join(WORK, "Table skeleton"))
table = AssemblyDocument()
table.path = os.path.join(WORK, "Table.icasm")
table.save(table.path)
skeleton_occurrence = table.place(skeleton_path)
sketches = frames.skeleton_sketches(skeleton_path)
sid = next(iter(sketches))
lines = sketches[sid][2]
frame, frame_occurrence, problems = frames.insert(
    table, skeleton_occurrence, sid, list(lines),
    "din-en-10219-2-square", "40 x 40 x 3")
check("four tubes", len(frame.frame.members) == 4 and not problems, problems)
area = kernel.face_area(frames.square_tube(
    **frames.family("din-en-10219-2-square").row("40 x 40 x 3")))
folder = os.path.dirname(frame.path)


def member_by_line(predicate):
    """The member whose line the test picks, by its two ends."""
    for m in frame.frame.members:
        a, b = frames.run_of(lines, m.lines)
        if predicate(a, b):
            return m
    raise KeyError("no such member")


def part_of(member):
    doc = Document.load(os.path.join(folder, member.part))
    doc.rebuild()
    return doc


def volume(member):
    return kernel.volume(part_of(member).shape)


def length(member):
    return float(part_of(member).properties["Length"])


bottom = member_by_line(lambda a, b: near(a[1], 0) and near(b[1], 0))
right = member_by_line(lambda a, b: near(a[0], 1000) and near(b[0], 1000))
top_rail = member_by_line(lambda a, b: near(a[1], 600) and near(b[1], 600))
left = member_by_line(lambda a, b: near(a[0], 0) and near(b[0], 0))
check("the bare bottom rail is its line long", near(length(bottom), 1000))

# ==========================================================================
print("Miter")
_t, problems = frames.add_treatment(frame, "miter",
                                    [bottom.id, right.id, right.id,
                                     top_rail.id, top_rail.id, left.id,
                                     left.id, bottom.id])
check("all four corners mitered", not problems, problems)
check("each tube as long as its line plus a tube's width, outside",
      near(length(bottom), 1040, 0.01) and near(length(right), 640, 0.01),
      (length(bottom), length(right)))
check("and its volume its section times its line",
      near(volume(bottom), area * 1000, 1.0)
      and near(volume(right), area * 600, 1.0),
      (volume(bottom), area * 1000))
table.save(table.path)
table.rebuild()
box = kernel.bounding_box(table.shape)
check("the frame's outside where it was", near(box[0], -20, 0.05)
      and near(box[3], 1020, 0.05) and near(box[4], 620, 0.05), box)
frames.remove_treatments(frame, [bottom.id, right.id, top_rail.id, left.id])
check("Remove End Treatments puts them back as they were",
      near(length(bottom), 1000) and not frame.frame.treatments)

print("a miter with a gap, split between the two")
frames.add_treatment(frame, "miter", [bottom.id, right.id], gap=2.0)
check("each gives up half the gap at the corner, along the miter",
      near(volume(bottom), area * (1000 - 2 ** 0.5), 1.0),
      (volume(bottom), area * (1000 - 2 ** 0.5)))
frames.remove_treatments(frame, [bottom.id])

# ==========================================================================
print("Corner Joint")
frames.add_treatment(frame, "corner", [bottom.id], [right.id])
check("the bottom rail stops at the side of the right one: 980",
      near(length(bottom), 980, 0.01), length(bottom))
check("and the right one runs on to the bottom one's outside: 620",
      near(length(right), 620, 0.01), length(right))
check("butt ends are square: volumes are section times length",
      near(volume(bottom), area * 980, 1.0)
      and near(volume(right), area * 620, 1.0))
frames.remove_treatments(frame, [bottom.id])

# ==========================================================================
print("Trim - Extend To Face")
frames.add_treatment(frame, "trim_face", [bottom.id],
                     point=[900.0, 0.0, 0.0], normal=[1.0, 0.0, 0.0])
check("cut back to a face at 900", near(length(bottom), 900, 0.01),
      length(bottom))
frames.remove_treatments(frame, [bottom.id])
frames.add_treatment(frame, "trim_face", [bottom.id],
                     point=[1100.0, 0.0, 0.0], normal=[-1.0, 0.0, 0.0])
check("or run on out to one at 1100", near(length(bottom), 1100, 0.01),
      length(bottom))
frames.remove_treatments(frame, [bottom.id])

# ==========================================================================
print("Lengthen - Shorten")
frames.add_treatment(frame, "lengthen", [bottom.id], amount=50.0, side="b")
check("50 on at its end", near(length(bottom), 1050, 0.01), length(bottom))
frames.add_treatment(frame, "lengthen", [bottom.id], amount=-100.0,
                     side="both")
check("then 100 off, half at each end", near(length(bottom), 950, 0.01),
      length(bottom))
frames.remove_treatments(frame, [bottom.id])

# ==========================================================================
print("Notch")
# the right one run on past the corner, so its outline covers the end
frames.add_treatment(frame, "lengthen", [right.id], amount=40.0, side="both")
frames.add_treatment(frame, "notch", [bottom.id], [right.id])
# all but the slivers the other tube's rounded corners leave in the end
check("notched to the right one's outline: it stops at its side",
      980 < volume(bottom) / area < 983, volume(bottom) / area)
box = kernel.bounding_box(part_of(bottom).shape)
check("its corners reaching on round the other's, to its far side",
      near(box[5] - box[2], 1020, 0.01), box)
frames.remove_treatments(frame, [bottom.id, right.id])

# ==========================================================================
print("the skeleton edited: a mitered corner follows")
frames.add_treatment(frame, "miter", [bottom.id, right.id])
part = Document.load(skeleton_path)
for point in part.all_sketches()[sid].points.values():
    if near(point.x, 1000.0):
        point.x = 1200.0
part.rebuild()
part.save(skeleton_path)
table.rebuild()
frame = AssemblyDocument.load(frame.path)
bottom = frame.frame.member(bottom.id)
check("the bottom rail is 1200 plus the miter's 20 at that end",
      near(length(bottom), 1220, 0.01), length(bottom))

# ==========================================================================
print("Change Frame")
frame = AssemblyDocument.load(frame.path)
old_part = frame.frame.member(left.id).part
problems = frames.change_members(frame, [left.id, top_rail.id],
                                 size="60 x 60 x 4")
left_now = frame.frame.member(left.id)
check("two members changed to 60 x 60 x 4", not problems
      and left_now.size == "60 x 60 x 4"
      and frame.frame.member(top_rail.id).size == "60 x 60 x 4", problems)
check("the changed member's part is named for what it is now",
      left_now.part != old_part and "60 x 60 x 4" in left_now.part
      and not os.path.exists(os.path.join(folder, old_part)))
check("the others kept their size",
      frame.frame.member(bottom.id).size == "40 x 40 x 3")
problems = frames.change_members(frame, [bottom.id], anchor="bl",
                                 rotate=90.0)
check("and placement changes too", not problems
      and frame.frame.member(bottom.id).anchor == "bl", problems)
try:
    frames.change_members(frame, [bottom.id], colour="red")
    check("something a member does not have is refused", False)
except ValueError:
    check("something a member does not have is refused", True)

print("previews, nothing written")
solids = frames.member_world_solids(frame, [bottom.id],
                                    {"size": "80 x 80 x 5"})
box = kernel.bounding_box(solids[bottom.id])
check("a member as a change would make it",
      bottom.id in solids and near(box[5] - box[2], 80, 0.05), box)
check("and the member itself is as it was",
      frame.frame.member(bottom.id).size == "40 x 40 x 3")

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
