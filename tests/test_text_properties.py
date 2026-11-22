"""A part's sketch text can show its properties, and keeps up (#414).

A steel plate with its mass written in a sketch on it, <Model.Mass:0>:
the text reads the plate's mass, and when a parameter makes the plate
bigger, the text, and the letters it makes, change with it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATUM_NO_WORKERS"] = "1"

from datum.core import kernel                                      # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.core.features import PrimitiveFeature, SketchFeature    # noqa: E402
from datum.core.sketch import SketchPlane                          # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


doc = Document()
doc.params.add("w", "100")
doc.add_feature(PrimitiveFeature(kind="box", a="w", b="50", c="10"))
sketch_feature = SketchFeature(name="Weight")
sketch_feature.sketch.plane = SketchPlane((0, 0, 10), (0, 0, 1), (1, 0, 0),
                                          "Top")
tid = sketch_feature.sketch.add_text(5, 5, "<Model.Mass:0>", size=6.0)
doc.add_feature(sketch_feature)
doc.rebuild()

mass = doc.mass_properties().get("mass_g")
written = kernel.filled_text("<Model.Mass:0>")
check("the text reads the plate's mass", mass is not None
      and written.startswith("%d" % round(mass)), (written, mass))
before = kernel.text_box(sketch_feature.sketch, tid) \
    if hasattr(kernel, "text_box") else None

doc.params.set_expression("w", "300") if hasattr(
    doc.params, "set_expression") else doc.params.add("w", "300")
doc.rebuild()
mass_after = doc.mass_properties().get("mass_g")
again = kernel.filled_text("<Model.Mass:0>")
check("a bigger plate, a bigger number",
      again.startswith("%d" % round(mass_after)) and again != written,
      (again, written))
after = kernel.text_box(sketch_feature.sketch, tid) \
    if hasattr(kernel, "text_box") else None
check("and the letters change with it", before != after, (before, after))

print()
print("all passed" if not FAILS else "FAILED: %s" % FAILS)
sys.exit(1 if FAILS else 0)
