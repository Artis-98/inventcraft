"""A work plane placed by numbers, and fillets and chamfers by an edge rule.

* "placed": a work plane through an origin, square to a normal, its X
  along a direction, every one of them an expression that follows the
  parameters (and a parameter renamed is renamed in them);
* an edge query ("the edges along Z", "the edges round the top") picks
  edges by what they are, so a fillet stays on the corners however a
  parameter moves them, where a stored pick can lose them.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import edgequery, kernel, modelparams  # noqa: E402
from datum.core.document import Document  # noqa: E402
from datum.core.features import (  # noqa: E402
    ChamferFeature, FilletFeature, PrimitiveFeature, WorkPlaneFeature,
)

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def near(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def unit(v):
    n = sum(c * c for c in v) ** 0.5
    return tuple(c / n for c in v)


def block():
    doc = Document()
    doc.params.add("w", "60")
    doc.params.add("h", "20")
    box = PrimitiveFeature()
    box.kind = "box"
    box.a, box.b, box.c = "w", "40", "h"
    box.operation = "new"
    doc.add_feature(box)
    return doc


print("a work plane placed by numbers")
doc = block()
plane = WorkPlaneFeature(name="Side")
plane.mode = "placed"
plane.origin = ("w/2", "0", "h")
plane.normal = ("1", "0", "1")
plane.xdir = ("0", "1", "0")
doc.add_feature(plane)
report = doc.rebuild()
check("it builds", not report.errors, report.errors)
made = doc.planes.get("Side")
check("through its origin", made is not None
      and near(made.origin, (30, 0, 20)), made and made.origin)
check("square to its normal", made is not None
      and near(unit(made.normal), unit((1, 0, 1))), made and made.normal)
check("its X along the direction given", made is not None
      and near(unit(made.xdir), (0, 1, 0)), made and made.xdir)
check("it says what it was made from", plane.made_from ==
      "a point and a normal", plane.made_from)

doc.params.set_expression("w", "80")
doc.rebuild()
check("its origin follows the parameter", near(doc.planes["Side"].origin,
                                               (40, 0, 20)),
      doc.planes["Side"].origin)
check("the parameter knows the plane uses it",
      "Side" in modelparams.consumers(doc, "w"),
      modelparams.consumers(doc, "w"))
modelparams.rename(doc, "w", "width")
check("renaming the parameter renames it in the origin",
      plane.origin[0] == "width/2", plane.origin)
doc.rebuild()
check("and it still builds there", near(doc.planes["Side"].origin,
                                        (40, 0, 20)),
      doc.planes["Side"].origin)

again = Document()
again.load_dict(json.loads(json.dumps(doc.to_dict())))
again.rebuild()
check("saved and loaded, it is the same plane",
      near(again.planes["Side"].origin, (40, 0, 20))
      and near(unit(again.planes["Side"].normal), unit((1, 0, 1))),
      again.planes.get("Side"))

flipped = WorkPlaneFeature(name="Back")
flipped.mode = "placed"
flipped.normal = ("0", "0", "1")
flipped.flip = True
doc.add_feature(flipped)
doc.rebuild()
check("flip turns its normal round", near(unit(doc.planes["Back"].normal),
                                          (0, 0, -1)),
      doc.planes["Back"].normal)

bad = WorkPlaneFeature(name="Nowhere")
bad.mode = "placed"
bad.normal = ("0", "0", "0")
doc.add_feature(bad)
report = doc.rebuild()
check("a normal with no length is an error that says so",
      any("no length" in m for _f, m in report.errors), report.errors)

print("fillets and chamfers by an edge rule")
doc = block()
round_ = FilletFeature(name="Corners")
round_.radius = "5"
round_.query = {"along": "z"}
doc.add_feature(round_)
report = doc.rebuild()
check("a fillet on the edges along Z builds", not report.errors,
      report.errors)
check("it rounds the four upright corners: 6 faces become 10",
      len(kernel.faces(doc.shape)) == 10, len(kernel.faces(doc.shape)))
doc.params.set_expression("w", "120")
doc.rebuild()
check("the plate twice as wide still has its four corners rounded",
      len(kernel.faces(doc.shape)) == 10, len(kernel.faces(doc.shape)))
check("the summary says what the rule is",
      round_.summary() == "Corners: R5 on edges where along z",
      round_.summary())

top = ChamferFeature(name="Top")
top.distance = "1"
top.query = {"at": "+z", "kind": "line"}
doc.add_feature(top)
report = doc.rebuild()
check("a chamfer on the straight edges round the top builds",
      not report.errors, report.errors)
check("it adds a face for each of them",
      len(kernel.faces(doc.shape)) > 10, len(kernel.faces(doc.shape)))

data = json.loads(json.dumps(doc.to_dict()))
kept = [f for f in data["features"] if f.get("query")]
check("the rule is what is saved", [f["query"] for f in kept] ==
      [{"along": "z"}, {"at": "+z", "kind": "line"}], kept)
again = Document()
again.load_dict(data)
again.rebuild()
check("and loaded, it gives the same part",
      len(kernel.faces(again.shape)) == len(kernel.faces(doc.shape))
      and abs(kernel.volume(again.shape) - kernel.volume(doc.shape)) < 1e-6)

nothing = FilletFeature(name="Nothing")
nothing.radius = "1"
nothing.query = {"along": "z", "min_length": 1000}
doc.add_feature(nothing)
report = doc.rebuild()
check("a rule that finds no edge is an error naming the feature",
      any(m.startswith("Nothing:") for _f, m in report.errors),
      report.errors)

try:
    edgequery.edges(doc.shape, {"sideways": 1})
    check("an unknown condition is refused", False)
except edgequery.QueryError:
    check("an unknown condition is refused", True)

print()
if FAILS:
    print("%d FAILURE(S): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
