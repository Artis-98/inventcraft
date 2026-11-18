"""Piping, without a window.

Copper tube sizes from EN 12735-1 and ASTM B280; a run of skeleton
lines meeting end to end made one pipe, bent at its corners to the bend
radius; its developed length worked out and written on the part; its
insulation a part of its own that follows the bends; the cut list's
totals per size; and the pipe following the skeleton when it is edited.
"""
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import frames, kernel, piping                    # noqa: E402
from datum.core.assembly import AssemblyDocument                  # noqa: E402
from datum.core.document import Document                          # noqa: E402
from datum.core.features import PipeRunFeature, SketchFeature     # noqa: E402
from datum.core.sketch import Sketch, SketchPlane                 # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_piping_")
os.environ["DATUM_PROFILE_LIBRARY"] = os.path.join(WORK, "profiles")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


print("the tube sizes")
copper = frames.family("en-12735-1-copper")
check("EN 12735-1 copper is a pipe family under Piping",
      copper.kind == "pipe" and copper.category.startswith("Piping"))
check("22 x 1 is 22 outside, 1 wall",
      copper.row("22x1")["d"] == 22 and copper.row("22x1")["t"] == 1)
acr = frames.family("astm-b280-drawn")
check("ACR 7/8 in is 22.22 mm outside, 1.14 wall",
      near(acr.row("7/8 in")["d"], 22.22, 0.01)
      and near(acr.row("7/8 in")["t"], 1.14, 0.01))
check("coils come in too", "1/4 in" in frames.family("astm-b280-coil").sizes())

print("bends")
r = piping.route([(0, 0, 0), (0, 0, 1000), (500, 0, 1000)], 66.0)
check("a right angle bend sets back its radius from the corner",
      len(r.bends) == 1 and near(r.bends[0].setback, 66.0)
      and near(r.bends[0].angle, 90.0))
check("and the developed length is the straights and the arc",
      near(r.length, 1000 + 500 - 2 * 66 + 66 * math.pi / 2))
r45 = piping.route([(0, 0, 0), (0, 0, 500), (300, 0, 800)], 66.0)
check("a 45 degree bend sets back r tan 22.5",
      near(r45.bends[0].setback, 66 * math.tan(math.radians(22.5))))
try:
    piping.route([(0, 0, 0), (0, 0, 100), (100, 0, 100), (100, 0, 0)],
                 66.0)
    check("a leg too short for its two bends is refused", False)
except kernel.KernelError as exc:
    check("a leg too short for its two bends is refused",
          "too short" in str(exc), exc)
solid = piping.tube_solid(r.points, 22.0, 1.0, 66.0)
ring = math.pi / 4 * (22 ** 2 - 20 ** 2)
check("the bent tube's volume is its ring times its developed length",
      abs(kernel.volume(solid) - ring * r.length) < 0.002 * ring * r.length,
      (kernel.volume(solid), ring * r.length))

print("runs")
lines = {1: ((0, 0, 0), (1000, 0, 0)), 2: ((1000, 0, 0), (1000, 500, 0)),
         3: ((1500, 500, 0), (1000, 500, 0)), 4: ((0, 900, 0), (400, 900, 0))}
check("lines meeting end to end are one run, a line apart another",
      sorted(map(sorted, piping.runs(lines, [3, 1, 4, 2])))
      == [[1, 2, 3], [4]], piping.runs(lines, [3, 1, 4, 2]))
tee = {1: ((0, 0, 0), (500, 0, 0)), 2: ((500, 0, 0), (1000, 0, 0)),
       3: ((500, 0, 0), (500, 400, 0))}
check("where three meet, the runs end: a tee goes there",
      len(piping.runs(tee, [1, 2, 3])) == 3)
check("a straight run of two lines is one leg",
      len(piping.run_points({1: ((0, 0, 0), (1, 0, 0)),
                             2: ((1, 0, 0), (3, 0, 0))}, [1, 2])) == 2)

print("a pipe in an assembly")
skeleton = Document()
route_sketch = SketchFeature(name="Route")
route_sketch.sketch = Sketch(SketchPlane((0.0, 0.0, 300.0), (0.0, 0.0, 1.0)),
                             "Route")
s = route_sketch.sketch
s.add_line((0.0, 0.0), (1000.0, 0.0))
s.add_line((1000.0, 0.0), (1000.0, 500.0))
s.add_line((1000.0, 500.0), (1500.0, 500.0))
s.add_line((0.0, 900.0), (400.0, 900.0))
skeleton.add_feature(route_sketch)
skeleton.rebuild()
skeleton_path = skeleton.save(os.path.join(WORK, "Pipe skeleton"))
plant = AssemblyDocument()
plant.path = os.path.join(WORK, "Plant.icasm")
plant.save(plant.path)
skeleton_occurrence = plant.place(skeleton_path)
sketches = frames.skeleton_sketches(skeleton_path)
sid = next(iter(sketches))
ids = sorted(sketches[sid][2])
frame, frame_occurrence, problems = frames.insert(
    plant, skeleton_occurrence, sid, ids, "en-12735-1-copper", "22x1",
    insulation=13.0, merge=True)
check("four lines, two pipes", len(frame.frame.members) == 2
      and not problems, problems)
folder = os.path.dirname(frame.path)
bent = max(frame.frame.members, key=lambda m: len(m.lines))
part = Document.load(os.path.join(folder, bent.part))
part.rebuild()
check("a pipe's part is one Pipe Run feature, copper",
      [type(f) for f in part.features] == [PipeRunFeature]
      and part.material == "Copper" and part.last_report.ok)
radius = copper.row("22x1")["r"]
want = 1000 + 500 + 500 - 4 * radius + 2 * radius * math.pi / 2
check("its Length is the developed length, %.1f" % want,
      near(float(part.properties["Length"]), want, 0.01),
      part.properties["Length"])
check("with its two bends and their radius",
      part.properties["Bends"] == "2"
      and float(part.properties["Bend Radius"]) == radius)
check("its volume is the tube's ring that long",
      abs(kernel.volume(part.shape) - ring * want) < 0.002 * ring * want)
check("the insulation is a part beside it",
      bent.insulation_part and bent.insulation_occurrence
      and os.path.exists(os.path.join(folder, bent.insulation_part)))
lag = Document.load(os.path.join(folder, bent.insulation_part))
lag.rebuild()
lag_ring = math.pi / 4 * (48 ** 2 - 22 ** 2)
check("of elastomeric foam, 13 mm round the tube, the bends and all",
      lag.material == piping.INSULATION_MATERIAL
      and abs(kernel.volume(lag.shape) - lag_ring * want)
      < 0.003 * lag_ring * want, kernel.volume(lag.shape))

plant.save(plant.path)
plant.rebuild()
box = kernel.bounding_box(plant.shape)
check("the pipe lies on its lines in the assembly",
      near(box[0], 0, 0.1) and near(box[1], -24, 0.1)
      and near(box[3], 1500, 0.1) and near(box[4], 924, 0.1)
      and near(box[2], 300 - 24, 0.1) and near(box[5], 300 + 24, 0.1),
      [round(c, 2) for c in box])

rows, wrong = piping.cut_list(frame)
t = piping.totals(rows)
check("the cut list has both pipes, nothing wrong",
      len(rows) == 2 and not wrong, wrong)
check("and totals the 22 x 1: two pieces, %.0f mm" % (want + 400),
      t["tube"]["22x1"][0] == 2
      and near(t["tube"]["22x1"][1], want + 400, 0.01))
check("and its insulation by thickness",
      near(t["insulation"][("22x1", 13.0, piping.INSULATION_MATERIAL)],
           want + 400, 0.01))
text = piping.cut_list_csv(rows)
check("as a spreadsheet would take it",
      "Cut length mm" in text and "Total tube m" in text)

print("changed after")
problems = frames.change_members(frame, [bent.id], insulation=0.0,
                                 bend_radius=50.0)
part = Document.load(os.path.join(folder, bent.part))
check("no insulation takes its part away", not problems
      and not bent.insulation_part and not bent.insulation_occurrence
      and len([n for n in os.listdir(folder) if "Insulation" in n]) == 1,
      problems)
check("and a radius of its own bends it at that",
      float(part.properties["Bend Radius"]) == 50.0)
problems = frames.change_members(frame, [bent.id], size="28x1")
check("a new size renames the part for it",
      not problems and "28x1" in bent.part
      and os.path.exists(os.path.join(folder, bent.part)), problems)

# the skeleton edited: the second leg longer, the pipe follows
skeleton = Document.load(skeleton_path)
sk = skeleton.all_sketches()[sid]
for p in sk.points.values():
    if near(p.y, 500.0):
        p.y = 700.0
skeleton.save(skeleton_path)
frames.refresh(frame.path)
frame = AssemblyDocument.load(frame.path)
bent = frame.frame.member(bent.id)
part = Document.load(os.path.join(folder, bent.part))
want = 1000 + 700 + 500 - 4 * 50 + 2 * 50 * math.pi / 2
check("an edited skeleton lengthens the pipe to %.1f" % want,
      near(float(part.properties["Length"]), want, 0.01),
      part.properties["Length"])
check("a pipe's part is known as the Frame Generator's",
      frames.is_member_part(os.path.join(folder, bent.part)))

print("a run from one sketch into another")
from datum.core.sketch import STANDARD_PLANES                     # noqa: E402
riser = Document()
floor = SketchFeature(name="Floor")
floor.sketch = Sketch(SketchPlane((0.0, 0.0, 300.0), (0.0, 0.0, 1.0)),
                      "Floor")
floor.sketch.add_line((0.0, 0.0), (1000.0, 0.0))
riser.add_feature(floor)
wall = SketchFeature(name="Wall")
wall.sketch = Sketch(STANDARD_PLANES["XZ"], "Wall")
wall.sketch.add_line((1000.0, 300.0), (1000.0, 800.0))
wall.sketch.add_line((1000.0, 800.0), (400.0, 800.0))
riser.add_feature(wall)
riser.rebuild()
riser_path = riser.save(os.path.join(WORK, "Riser skeleton"))
room = AssemblyDocument()
room.path = os.path.join(WORK, "Room.icasm")
room.save(room.path)
riser_occurrence = room.place(riser_path)
sk = frames.skeleton_sketches(riser_path)
fid = next(i for i, v in sk.items() if v[1] == "Floor")
wid = next(i for i, v in sk.items() if v[1] == "Wall")
check("the wall's line stands up from the floor's end",
      near(sk[wid][2][min(sk[wid][2])][0][2], 300.0, 1e-6)
      and near(sk[wid][2][min(sk[wid][2])][0][0], 1000.0, 1e-6))
keys = [(fid, i) for i in sk[fid][2]] + [(wid, i) for i in sk[wid][2]]
frame2, _occ2, problems = frames.insert(
    room, riser_occurrence, fid, [], "en-12735-1-copper", "15x1",
    merge=True, segments=keys)
check("three lines in two sketches, merged: one pipe", not problems
      and len(frame2.frame.members) == 1, problems)
riser_pipe = frame2.frame.members[0]
folder2 = os.path.dirname(frame2.path)
part2 = Document.load(os.path.join(folder2, riser_pipe.part))
r15 = frames.family("en-12735-1-copper").row("15x1")["r"]
want2 = 1000 + 500 + 600 - 4 * r15 + 2 * r15 * math.pi / 2
check("bent up the wall and along it, %.1f long" % want2,
      part2.properties["Bends"] == "2"
      and near(float(part2.properties["Length"]), want2, 0.01),
      dict(part2.properties))
check("its route is kept by sketch and line",
      sorted(map(tuple, riser_pipe.segments)) == sorted(keys))
room.save(room.path)
room.rebuild()
box = kernel.bounding_box(room.shape)
check("and stands where the skeleton has it, up to 800",
      near(box[5], 800 + 7.5, 0.1) and near(box[3], 1000 + 7.5, 0.1),
      [round(c, 1) for c in box])
# the wall sketch edited: the riser taller, the pipe follows
riser = Document.load(riser_path)
for p in riser.all_sketches()[wid].points.values():
    if near(p.y, 800.0):
        p.y = 900.0
riser.save(riser_path)
frames.refresh(frame2.path)
frame2 = AssemblyDocument.load(frame2.path)
part2 = Document.load(os.path.join(folder2, frame2.frame.members[0].part))
check("a sketch it runs through edited, it follows",
      near(float(part2.properties["Length"]), want2 + 100, 0.01),
      part2.properties["Length"])
frame3, _occ3, problems = frames.insert(
    room, riser_occurrence, fid, [], "en-12735-1-copper", "15x1",
    merge=False, segments=keys)
check("not merged, each line is a straight pipe of its own",
      not problems and len(frame3.frame.members) == 3
      and all(not m.segments for m in frame3.frame.members), problems)
folder3 = os.path.dirname(frame3.path)
check("and an elbow goes in at each corner between them",
      sorted(f["part"] for f in frame3.frame.fittings)
      == ["Elbow 90 15.icpart"] * 2, frame3.frame.fittings)
from datum.core import piping_fittings                            # noqa: E402
sock = piping_fittings.socket(15.0)
floor_pipe = next(m for m in frame3.frame.members if m.sketch == fid)
fp = Document.load(os.path.join(folder3, floor_pipe.part))
check("each pipe cut back to the elbow's socket bottom, %g short"
      % sock["R"],
      near(float(fp.properties["Length"]), 1000 - sock["R"], 0.01),
      fp.properties["Length"])
elbow = Document.load(os.path.join(folder3, "Elbow 90 15.icpart"))
elbow.rebuild()
check("the elbow is a part that builds, of copper",
      elbow.last_report.ok and elbow.shape is not None
      and elbow.material == "Copper")
rows, _w = piping.cut_list(frame3)
check("the cut list counts the two elbows",
      piping.fittings_of(frame3) == {"Elbow 90 15": 2}
      and "Elbow 90 15,2" in piping.cut_list_csv(
          rows, piping.fittings_of(frame3)), piping.fittings_of(frame3))

print("tees, couplings and reducers")
tee_sk = Document()
t = SketchFeature(name="Tee")
t.sketch = Sketch(SketchPlane(), "Tee")
t.sketch.add_line((0.0, 0.0), (500.0, 0.0))
t.sketch.add_line((500.0, 0.0), (1000.0, 0.0))
t.sketch.add_line((500.0, 0.0), (500.0, 400.0))
t.sketch.add_line((1000.0, 0.0), (1600.0, 0.0))
tee_sk.add_feature(t)
tee_sk.rebuild()
tee_path = tee_sk.save(os.path.join(WORK, "Tee skeleton"))
shop = AssemblyDocument()
shop.path = os.path.join(WORK, "Shop.icasm")
shop.save(shop.path)
tee_occ = shop.place(tee_path)
tk = frames.skeleton_sketches(tee_path)
tsid = next(iter(tk))
tl = tk[tsid][2]
by_start = {(round(a[0]), round(b[0]), round(b[1])): i
            for i, (a, b) in tl.items()}
main = [by_start[(0, 500, 0)], by_start[(500, 1000, 0)],
        by_start[(500, 500, 400)]]
tail = [by_start[(1000, 1600, 0)]]
frame4, occ4, problems = frames.insert(shop, tee_occ, tsid, main,
                                       "en-12735-1-copper", "22x1")
frame4, occ4, problems = frames.insert(shop, tee_occ, tsid, tail,
                                       "en-12735-1-copper", "15x1",
                                       frame_occurrence=occ4)
labels = sorted(f["part"] for f in frame4.frame.fittings)
check("three meeting square: a tee; a 22 into a 15 in line: a reducer",
      not problems and labels == ["Reducer 22x15.icpart", "Tee 22.icpart"],
      (labels, problems))
folder4 = os.path.dirname(frame4.path)
built = []
for name in labels:
    fit = Document.load(os.path.join(folder4, name))
    fit.rebuild()
    built.append(fit.last_report.ok and fit.shape is not None
                 and kernel.volume(fit.shape) > 0)
check("each fitting's part builds a solid", all(built), built)


def sockets_round_their_pipes(frame_doc):
    """For every fitting, a point in each socket's wall, half its depth
    along the pipe that goes in it: inside the fitting where it is
    placed, or the fitting is turned the wrong way."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt
    fd = frame_doc.frame
    geos = frames.member_geometries(fd, frames.skeleton_sketches(
        frames.skeleton_path(frame_doc)), [])
    ends = {(m, e): u for m, e, _p, u, _d in piping_fittings.pipe_ends(geos)}
    wrong = []
    for f in fd.planned_fittings:
        solid = piping_fittings.solid(f.kind, f.sockets).Moved(
            f.placement().location())
        backs = piping_fittings.setback(f.kind, f.sockets)
        socks = f.sockets if f.kind != "tee" else \
            [f.sockets[0], f.sockets[0], f.sockets[1]]
        for (mid, end), back, sock in zip(f.ends, backs, socks):
            u = ends[(mid, end)]
            into = tuple(-c for c in u)
            side = (1.0, 0.0, 0.0) if abs(into[0]) < 0.9 else (0.0, 1.0, 0.0)
            dot = sum(side[i] * into[i] for i in range(3))
            side = [side[i] - dot * into[i] for i in range(3)]
            n = math.sqrt(sum(c * c for c in side))
            side = [c / n for c in side]
            r = sock["d"] / 2.0 + sock["s"] / 2.0
            along = back + sock["L"] / 2.0
            p = [f.point[i] + into[i] * along + side[i] * r for i in range(3)]
            probe = BRepClass3d_SolidClassifier(solid, gp_Pnt(*p), 1e-6)
            if probe.State() != TopAbs_IN:
                wrong.append((f.label, mid, end))
    return wrong


check("the tee's and the reducer's sockets sit round their pipes",
      not sockets_round_their_pipes(frame4),
      sockets_round_their_pipes(frame4))
check("and each elbow's", not sockets_round_their_pipes(frame3),
      sockets_round_their_pipes(frame3))
shop.save(shop.path)
shop.rebuild()
check("and the whole lot builds in the assembly", shop.shape is not None)

print("each corner a bend or an elbow, switched one by one")
from datum.core import pipe_corners                               # noqa: E402
# the riser run from before, merged: one pipe, two bends
c = pipe_corners.corners(frame2)
check("a merged run's two corners are bends, either can be an elbow",
      [k.kind for k in c] == ["bend", "bend"]
      and all(k.choices == ["bend", "elbow"] for k in c), c)
first_bend = min(c, key=lambda k: k.point[2])
problems = pipe_corners.set_corner(frame2, first_bend.point, "elbow")
c = pipe_corners.corners(frame2)
check("the lower one made an elbow: two pipes and an elbow between them",
      not problems and len(frame2.frame.members) == 2
      and sorted(k.kind for k in c) == ["bend", "elbow90"]
      and [f["part"] for f in frame2.frame.fittings] == ["Elbow 90 15.icpart"],
      (problems, c))
lower = next(m for m in frame2.frame.members if m.sketch == fid)
lp = Document.load(os.path.join(folder2, lower.part))
check("the floor pipe now ends in the elbow's socket",
      near(float(lp.properties["Length"]),
           1000 - piping_fittings.socket(15.0)["R"], 0.01),
      lp.properties["Length"])
elbow_at = next(k for k in c if k.kind == "elbow90")
problems = pipe_corners.set_corner(frame2, elbow_at.point, "bend")
c = pipe_corners.corners(frame2)
check("and back to a bend: one pipe again, no fittings",
      not problems and len(frame2.frame.members) == 1
      and [k.kind for k in c] == ["bend", "bend"]
      and not frame2.frame.fittings, (problems, c))
part2 = Document.load(os.path.join(folder2, frame2.frame.members[0].part))
check("its length as before", near(float(part2.properties["Length"]),
                                   want2 + 100, 0.01),
      part2.properties["Length"])

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
