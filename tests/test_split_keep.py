"""Split Solid keeps both halves, or only the one asked for.

A 40 mm cube from z = -20 to 20, split on the XY plane: both halves as
two solids, or only the upper one (the side the plane faces), or only
the lower, the other thrown away. The choice is kept in the file.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATUM_NO_WORKERS"] = "1"

from datum.core import kernel                                      # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature, SplitFeature     # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def split(keep):
    doc = Document()
    doc.add_feature(PrimitiveFeature(kind="box", a="40", b="40", c="40",
                                     origin=("-20", "-20", "-20")))
    doc.add_feature(SplitFeature(mode="solid", plane="XY", keep=keep))
    report = doc.rebuild()
    return doc, report


for keep, solids, low, high in (("both", 2, -20.0, 20.0),
                                ("front", 1, 0.0, 20.0),
                                ("back", 1, -20.0, 0.0)):
    doc, report = split(keep)
    box = kernel.bounding_box(doc.shape)
    count = len(kernel.explore(doc.shape, __import__(
        "OCP.TopAbs", fromlist=["TopAbs_SOLID"]).TopAbs_SOLID))
    print("keep %s" % keep)
    check("it builds", report.ok, report.message)
    check("%d solid(s) left" % solids, count == solids, count)
    check("from z %g to %g" % (low, high),
          abs(box[2] - low) < 1e-6 and abs(box[5] - high) < 1e-6, box)
    check("about half the volume, or all of it",
          abs(kernel.volume(doc.shape) - (64000.0 if keep == "both"
                                          else 32000.0)) < 1.0,
          kernel.volume(doc.shape))

print("kept in the file")
feature = SplitFeature(keep="back")
again = SplitFeature()
again.load_fields(feature.field_dict())
check("the side comes back", again.keep == "back")
old = SplitFeature()
old.load_fields({"mode": "solid", "plane": "XY"})
check("a split from before keeps both", old.keep == "both")

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
