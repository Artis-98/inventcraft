"""Beam analysis checked against the textbook (#275).

A frame solver is only worth anything if it gives the answers every
engineer knows by heart, so these are the classic cases:

* a cantilever with a load on its end deflects P L3 / 3 E I;
* a simply supported beam under its own weight sags 5 w L4 / 384 E I
  in the middle, and is stressed w L2 / 8 there;
* a cantilever's first natural frequency is 1.875^2 / 2 pi
  times the root of E I / (m L4);
* a square tube's section from its face matches the handbook;
* wind on a column pushes it the way the wind blows, as much as
  q Cd d L would at its middle.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import beams  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("" if cond else "  " + str(extra)))
    if not cond:
        FAILS.append(name)


def near(a, b, rel=0.01):
    return abs(a - b) <= rel * max(abs(b), 1e-12)


STEEL = beams.Material(e=210000.0, nu=0.3, density=7.85,
                       yield_strength=235.0)
# a solid 20 x 40 bar, 40 tall: I about y (the tall way) = b h3 / 12
B, H = 20.0, 40.0
BAR = beams.Section(area=B * H, iy=B * H ** 3 / 12.0, iz=H * B ** 3 / 12.0,
                    j=0.229 * H * B ** 3, cy=B / 2, cz=H / 2, width=H)
L = 1000.0

print("a cantilever with an end load")
model = beams.Model(nodes=[(0, 0, 0), (L, 0, 0)],
                    members=[beams.Member(0, 1, BAR, STEEL,
                                          y_axis=(0, 1, 0))],
                    supports={0: beams.FIXED},
                    loads=[beams.Load(1, (0, 0, -1000.0))],
                    self_weight=False)
r = beams.solve(model, modes=0)
expect = 1000.0 * L ** 3 / (3 * STEEL.e * BAR.iy)
check("tip deflection P L3 / 3 E I = %.4f mm" % expect,
      near(r.max_deflection, expect), r.max_deflection)
check("it goes down", r.displacements[1, 2] < 0)
moment = 1000.0 * L
check("root stress M c / I = %.2f MPa" % (moment * 20 / BAR.iy),
      near(r.max_stress, moment * 20 / BAR.iy), r.max_stress)
check("the support holds 1000 N up", near(r.reactions[0][2], 1000.0),
      r.reactions[0])

print("a simply supported beam under its own weight")
model = beams.Model(nodes=[(0, 0, 0), (L, 0, 0)],
                    members=[beams.Member(0, 1, BAR, STEEL,
                                          y_axis=(0, 1, 0))],
                    supports={0: beams.PINNED, 1: beams.PINNED},
                    self_weight=True)
# pinned both ends leaves it free to spin about its own axis: hold that
model.supports = {0: beams.FIXED, 1: beams.PINNED}
r = beams.solve(model, modes=0)
check("solved", not r.error, r.error)
# against a true simply supported beam, the fixed end changes it; check
# instead with both ends pinned and a torsion stop added by a tiny member
w = STEEL.rho * BAR.area * beams.G
model = beams.Model(nodes=[(0, 0, 0), (L, 0, 0), (0, 0, 1)],
                    members=[beams.Member(0, 1, BAR, STEEL,
                                          y_axis=(0, 1, 0))],
                    supports={0: beams.PINNED, 1: beams.PINNED},
                    self_weight=True)
model.supports[0] = beams.PINNED
# hold the spin with a spring: a short stiff stub fixed at its far end
stub = beams.Section(area=1.0, iy=1e-3, iz=1e-3, j=1e-3, cy=1, cz=1)
model.members.append(beams.Member(0, 2, stub, STEEL, y_axis=(1, 0, 0)))
model.supports[2] = beams.FIXED
model.self_weight = False
model.loads = []
# the beam's own weight as the solver would put it, but on the beam only
model.members[0].material = STEEL
model.self_weight = True
model.members[1].material = beams.Material(e=210000.0, density=0.0)
r = beams.solve(model, modes=0)
mid = r.displacements[:, 2].min()
expect = 5 * w * L ** 4 / (384 * STEEL.e * BAR.iy)
check("mid span sags 5 w L4 / 384 E I = %.5f mm" % expect,
      near(-mid, expect, 0.03), -mid)
expect_stress = w * L ** 2 / 8 * 20 / BAR.iy
check("and is stressed w L2 / 8 there: %.4f MPa" % expect_stress,
      near(r.members[0].stress, expect_stress, 0.03), r.members[0].stress)

print("a cantilever rings")
model = beams.Model(nodes=[(0, 0, 0), (L, 0, 0)],
                    members=[beams.Member(0, 1, BAR, STEEL,
                                          y_axis=(0, 1, 0))],
                    supports={0: beams.FIXED}, self_weight=False)
r = beams.solve(model, modes=3)
m = STEEL.rho * BAR.area
f1 = 1.875 ** 2 / (2 * math.pi) * math.sqrt(STEEL.e * BAR.iz / (m * L ** 4))
check("first frequency, the weak way: %.2f Hz" % f1,
      bool(r.frequencies) and near(r.frequencies[0], f1, 0.01),
      r.frequencies)
f2 = 1.875 ** 2 / (2 * math.pi) * math.sqrt(STEEL.e * BAR.iy / (m * L ** 4))
check("the second, the stiff way: %.2f Hz" % f2,
      len(r.frequencies) > 1 and near(r.frequencies[1], f2, 0.01),
      r.frequencies)

print("a square tube's section from its face")
from datum.core import frames  # noqa: E402
face = frames.square_tube(40.0, 4.0, 0.0)
s = beams.section_of_face(face, kind="square_tube",
                          dims={"b": 40.0, "t": 4.0})
area = 40 * 40 - 32 * 32
inertia = (40 ** 4 - 32 ** 4) / 12.0
check("area %.0f mm2" % area, near(s.area, area, 1e-6), s.area)
check("I %.0f mm4 both ways" % inertia, near(s.iy, inertia, 1e-6)
      and near(s.iz, inertia, 1e-6), (s.iy, s.iz))
check("outer fibres 20 mm out", near(s.cy, 20.0, 1e-6)
      and near(s.cz, 20.0, 1e-6), (s.cy, s.cz))
check("Bredt torsion constant", near(s.j, 4 * 36 ** 4 * 4 / (4 * 36), 1e-9),
      s.j)

print("an equal angle: principal axes")
face = frames.equal_angle(50.0, 5.0, 0.0, 0.0)
s = beams.section_of_face(face, kind="angle", dims={"b": 50.0, "t": 5.0})
check("turned 45 degrees", near(abs(s.angle), 45.0, 1e-3), s.angle)
check("the stiff way stiffer than the weak way", s.iy > s.iz * 3,
      (s.iy, s.iz))

print("wind on a column")
model = beams.Model(nodes=[(0, 0, 0), (0, 0, L)],
                    members=[beams.Member(0, 1, BAR, STEEL,
                                          y_axis=(0, 1, 0))],
                    supports={0: beams.FIXED}, self_weight=False,
                    wind_speed=30.0, wind_direction=(1, 0, 0), drag=2.0)
r = beams.solve(model, modes=0)
q = 0.5 * beams.AIR * 30.0 ** 2 * 1e-6 * 2.0 * BAR.width     # N/mm
# the wind blows along the bar's 40 deep side: it bends the stiff way
tip = q * L ** 4 / (8 * STEEL.e * BAR.iy)
check("it leans downwind", r.displacements[1, 0] > 0)
check("by q L4 / 8 E I = %.4f mm" % tip, near(r.displacements[1, 0], tip,
                                             0.01), r.displacements[1, 0])

print("a frame standing on nothing")
model = beams.Model(nodes=[(0, 0, 0), (L, 0, 0)],
                    members=[beams.Member(0, 1, BAR, STEEL)])
r = beams.solve(model, modes=0)
check("says so", "support" in r.error, r.error)

print()
if FAILS:
    print("%d FAILED" % len(FAILS))
    sys.exit(1)
print("all passed")
