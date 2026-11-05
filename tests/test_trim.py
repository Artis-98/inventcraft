"""Trim as Inventor's: the piece clicked goes, up to the nearest geometry.

From GitHub #16: a line held on a box's side and tangent to a circle
inside it, drawn too long. Trimming the overhang took the whole line.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datum.core import trim                                     # noqa: E402
from datum.core.sketch import Sketch, SketchPlane               # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def ends(s, eid):
    e = s.entities[eid]
    pts = e.points if e.kind == "line" else e.points[1:]
    return [(round(s.points[p].x, 4), round(s.points[p].y, 4)) for p in pts]


print("a line tangent to a circle stops at the tangent point (#16)")
s = Sketch(SketchPlane(), "s")
box = s.add_rectangle((0.0, 0.0), (100.0, 60.0))
circle = s.add_circle((50.0, 30.0), 10.0)
# along y = 40, touching the circle's top at (50, 40), from the right side
# of the box out past the circle to x = 20
line = s.add_line((100.0, 40.0), (20.0, 40.0))
right = next(e for e in s.entities.values() if e.kind == "line"
             and e.id != line and abs(s.points[e.points[0]].x - 100) < 1e-9
             and abs(s.points[e.points[1]].x - 100) < 1e-9)
s.add_constraint("point_on", points=[s.entities[line].points[0]],
                 entities=[right.id])
s.add_constraint("tangent", entities=[line, circle])
s.solve()
check("it is cut at the tangent point",
      [round(t, 4) for t, _o in trim.cuts(s, line)] == [0.625],
      trim.cuts(s, line))
check("the overhang is what lights up",
      [tuple(round(c, 4) for c in p) for p in trim.piece(s, line, (30.0, 40.0))]
      == [(50.0, 40.0), (20.0, 40.0)], trim.piece(s, line, (30.0, 40.0)))
trim.trim(s, line, (30.0, 40.0))
check("only the overhang goes", line in s.entities
      and ends(s, line) == [(100.0, 40.0), (50.0, 40.0)], ends(s, line)
      if line in s.entities else "line gone")
check("it keeps its tangent and its hold on the box",
      any(c.kind == "tangent" and set(c.entities) == {line, circle}
          for c in s.constraints.values())
      and any(c.kind == "point_on" and c.entities == [right.id]
              for c in s.constraints.values()))
ok = s.solve()
check("and still solves, nothing over-constrained",
      ends(s, line)[1] == (50.0, 40.0) and not s.conflicting,
      (ends(s, line), s.conflicting))

print("a line crossing two lines loses its middle")
s = Sketch(SketchPlane(), "s")
h = s.add_line((0.0, 0.0), (100.0, 0.0))
s.add_line((30.0, -10.0), (30.0, 10.0))
s.add_line((70.0, -10.0), (70.0, 10.0))
s.add_constraint("horizontal", entities=[h])
trim.trim(s, h, (50.0, 1.0))
lines = sorted(ends(s, e) for e, ent in s.entities.items()
               if ent.kind == "line" and all(
                   abs(s.points[p].y) < 1e-9 for p in ent.points))
check("two pieces are left, either side",
      lines == [[(0.0, 0.0), (30.0, 0.0)], [(70.0, 0.0), (100.0, 0.0)]], lines)
check("both still horizontal", sum(
    1 for c in s.constraints.values() if c.kind == "horizontal") == 2)

print("a circle cut by a line becomes the arc that is left")
s = Sketch(SketchPlane(), "s")
c = s.add_circle((0.0, 0.0), 10.0)
s.add_line((-20.0, 5.0), (20.0, 5.0))
trim.trim(s, c, (0.0, 10.0))
arc = s.entities[c]
check("it is an arc now", arc.kind == "arc")
a0, a1 = s.arc_angles(c)
sweep = (a1 - a0) % (2 * math.pi)
check("the lower part of it, without the cap",
      abs(sweep - (2 * math.pi - 2 * math.acos(0.5))) < 1e-6
      and all(abs(s.points[p].y - 5.0) < 1e-6 for p in arc.points[1:]),
      (sweep, ends(s, c)))

print("an arc trimmed at a line")
s = Sketch(SketchPlane(), "s")
a = s.add_arc((0.0, 0.0), 10.0, 0.0, math.pi)
s.add_line((0.0, -5.0), (0.0, 20.0))
trim.trim(s, a, (-8.0, 6.0))
check("the left half goes", ends(s, a) == [(10.0, 0.0), (0.0, 10.0)],
      ends(s, a))

print("nothing crossing: the whole of it goes")
s = Sketch(SketchPlane(), "s")
lone = s.add_line((0.0, 0.0), (10.0, 0.0))
trim.trim(s, lone, (5.0, 0.0))
check("as Inventor does", lone not in s.entities)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all trim checks passed")
