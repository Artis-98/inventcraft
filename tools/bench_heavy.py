"""A heavy part, timed feature by feature: what multicore work is for.

    .venv/Scripts/python.exe tools/bench_heavy.py [--save path]

A 600 x 400 plate with 24 x 16 holes patterned through it, every hole's
top edge filleted, and a second plate as a body of its own with its own
pattern and fillets. Prints the rebuild time and each feature's share.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATUM_FULL_REBUILD"] = "1"
os.environ.setdefault("DATUM_NO_WORKERS", "1")

from datum.core import kernel                                     # noqa
from datum.core.document import Document                          # noqa
from datum.core.features import (CUT, NEW_BODY, FilletFeature,    # noqa
                                 PatternFeature, PrimitiveFeature)
from datum.core.naming import RefSet                              # noqa


def heavy() -> Document:
    doc = Document()
    doc.add_feature(PrimitiveFeature(kind="box", a="600", b="400", c="20"))
    hole = PrimitiveFeature(kind="cylinder", a="6", b="20", operation=CUT,
                            origin=("15", "15", "0"))
    doc.add_feature(hole)
    doc.add_feature(PatternFeature(parents=[hole.id], count1="24",
                                   spacing1="24", dir1="X", count2="16",
                                   spacing2="24", dir2="Y"))
    doc.add_feature(PrimitiveFeature(kind="box", a="300", b="200", c="15",
                                     operation=NEW_BODY,
                                     origin=("700", "0", "0")))
    slot = PrimitiveFeature(kind="cylinder", a="5", b="15", operation=CUT,
                            origin=("715", "15", "0"))
    doc.add_feature(slot)
    doc.add_feature(PatternFeature(parents=[slot.id], count1="12",
                                   spacing1="24", dir1="X", count2="8",
                                   spacing2="24", dir2="Y"))
    doc.rebuild()
    # every hole's top rim rounded: the circles on the top faces
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_CurveType
    rims = [e for e in kernel.edges(doc.shape)
            if BRepAdaptor_Curve(e).GetType() == GeomAbs_CurveType.GeomAbs_Circle
            and kernel.shape_centre(e)[2] > 14.0]
    fillet = FilletFeature(radius="1")
    fillet.refs = RefSet()
    fillet.refs.capture_from(doc.shape, "edge", rims)
    doc.add_feature(fillet)
    return doc


if __name__ == "__main__":
    doc = heavy()
    timings = {}
    real = {}
    for feature in doc.features:
        build = feature.build

        def timed(ctx, _build=build, _f=feature):
            t = time.perf_counter()
            try:
                return _build(ctx)
            finally:
                timings[_f.name + " #%d" % _f.id] = time.perf_counter() - t
        feature.build = timed
    t = time.perf_counter()
    report = doc.rebuild()
    total = time.perf_counter() - t
    print("rebuild %.2f s  ok=%s  %s" % (total, report.ok,
                                        "" if report.ok else report.message))
    for name, took in sorted(timings.items(), key=lambda kv: -kv[1]):
        print("  %6.2f s  %s" % (took, name))
    if "--save" in sys.argv:
        path = sys.argv[sys.argv.index("--save") + 1]
        for feature in doc.features:
            feature.__dict__.pop("build", None)
        print("saved", doc.save(path))
