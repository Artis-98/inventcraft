"""Shell on the small, simple shapes it used to give up on.

OCCT's thick-solid builder said Done and handed back the solid untouched
on a fused L, a fully filleted box and a ribbed plate, and with no face
open failed on nearly everything. Each case here is checked by the volume
the shell should have, not by whether something came back.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse   # noqa: E402
from OCP.BRepPrimAPI import (                                  # noqa: E402
    BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder)
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt                      # noqa: E402

from datum.core import kernel                                  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def box(x, y, z, dx, dy, dz):
    return BRepPrimAPI_MakeBox(gp_Pnt(x, y, z), dx, dy, dz).Shape()


def cylinder(x, y, z, r, h):
    return BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(x, y, z), gp_Dir(0, 0, 1)), r, h).Shape()


def top(shape):
    return max(kernel.faces(shape), key=lambda f: kernel.bounding_box(f)[2])


def shelled(shape, open_top):
    try:
        return kernel.volume(kernel.shell(
            shape, [top(shape)] if open_top else [], 2.0))
    except kernel.KernelError:
        return None


def near(got, want, rel=0.01):
    return got is not None and abs(got - want) <= abs(want) * rel


plain = box(0, 0, 0, 50, 30, 20)
check("a box, top open", near(shelled(plain, True), 30000 - 46 * 26 * 18))
check("a box, closed: a hollow", near(shelled(plain, False),
                                      30000 - 46 * 26 * 16))

ell = BRepAlgoAPI_Fuse(box(0, 0, 0, 50, 30, 20),
                       box(50, 0, 0, 30, 30, 20)).Shape()
check("two fused boxes, the seam between them merged first",
      near(shelled(ell, True), 48000 - 76 * 26 * 18), shelled(ell, True))
check("  and closed", near(shelled(ell, False), 48000 - 76 * 26 * 16))

can = cylinder(0, 0, 0, 15, 20)
check("a cylinder, top open",
      near(shelled(can, True), kernel.volume(can) - 3.14159265 * 13 ** 2 * 18))

holed = BRepAlgoAPI_Cut(plain, cylinder(25, 15, -1, 5, 30)).Shape()
check("a box with a hole through it, closed",
      shelled(holed, False) is not None
      and shelled(holed, False) < kernel.volume(holed) * 0.6)

rounded = kernel.fillet(plain, kernel.edges(plain), 1.0)
got = shelled(rounded, True)
check("every edge rounded smaller than the wall: shelled, not handed back",
      got is not None and got < kernel.volume(rounded) * 0.5, got)

ribbed = BRepAlgoAPI_Fuse(box(0, 0, 0, 50, 30, 10),
                          box(20, 0, 10, 3, 30, 10)).Shape()
got = shelled(ribbed, False)
check("a plate with a rib thinner than two walls: shells as it can",
      got is not None and got < kernel.volume(ribbed) * 0.7, got)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all shell checks passed")
