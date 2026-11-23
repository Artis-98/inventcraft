"""Time a slow multibody rebuild: exact on one core, and the quick looks.

    .venv/Scripts/python.exe tools/bench_bodies.py [bodies]

A part of several plates, each drilled with a grid of holes whose edges
are filleted, is built once, then a parameter every plate reads is
changed and the part rebuilt three ways at once: exactly on one worker,
each plate on a worker of its own, and (one plate) without its fillets.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATUM_NO_RESULT_CACHE", "1")

from OCP.GeomAbs import GeomAbs_Circle          # noqa: E402
from OCP.BRepAdaptor import BRepAdaptor_Curve   # noqa: E402
from OCP.TopoDS import TopoDS                   # noqa: E402

from datum.core import kernel, workers           # noqa: E402
from datum.core import document as docmod        # noqa: E402
from datum.core.document import Document         # noqa: E402
from datum.core.features import (CUT, NEW_BODY, FilletFeature,  # noqa: E402
                                 PatternFeature, PrimitiveFeature)


def plate_part(count: int) -> Document:
    doc = Document()
    doc.params.add("d", "5")
    for i in range(count):
        x = i * 260.0
        doc.add_feature(PrimitiveFeature(
            name="Plate%d" % i, kind="box", a="220", b="160", c="10",
            origin=(str(x), "0", "0"),
            operation=NEW_BODY if i else "join"))
        hole = PrimitiveFeature(name="Hole%d" % i, kind="cylinder", a="d",
                                b="10", operation=CUT,
                                origin=(str(x + 15), "15", "0"))
        doc.add_feature(hole)
        doc.add_feature(PatternFeature(parents=[hole.id], count1="10",
                                       spacing1="20", dir1="X", count2="7",
                                       spacing2="20", dir2="Y"))
        doc.rebuild()
        body = doc.bodies[-1].shape
        rims = []
        for edge in kernel.edges(body):
            curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
            if curve.GetType() == GeomAbs_Circle:
                rims.append(edge)
        fillet = FilletFeature(name="Round%d" % i, radius="0.8")
        fillet.refs.capture_from(doc.shape, "edge", rims)
        doc.add_feature(fillet)
    doc.rebuild()
    return doc


def volume(shape) -> float:
    return kernel.volume(shape) if shape is not None else 0.0


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    t = time.perf_counter()
    doc = plate_part(count)
    print("built here: %.2f s, %d bodies, errors %s"
          % (time.perf_counter() - t, len(doc.bodies),
             doc.last_report.errors))
    found = docmod.body_groups(doc, 8)
    print("body groups:", None if found is None
          else [len(b) for b in found[0]], "shared",
          None if found is None else len(found[1]))

    pool = workers.pool()
    pool.start()
    pool.wait_ready()
    print("workers ready:", pool.ready)
    # every worker holds its copy built as it is now
    request = doc.remote_request(prime=True)
    pool.submit_to(doc.remote_key, "rebuild", **request).result()
    for r in doc.preview_requests(pool.ready - 1):
        r = dict(r, prime=True)
        taken = [doc.remote_key]
        pool.bind(r["key"], avoid=taken)
        pool.submit_to(r["key"], "rebuild", **r).result()

    doc.params.set_expression("d", "6")
    request = doc.remote_request()
    looks = doc.preview_requests(pool.ready - 1)
    t = time.perf_counter()
    exact = pool.submit_to(doc.remote_key, "rebuild", **request)
    taken = [doc.remote_key]
    quick = []
    for r in looks:
        pool.bind(r["key"], avoid=taken)
        taken.append(r["key"])
        quick.append(pool.submit_to(r["key"], "rebuild", **r))
    results = [q.result() for q in quick]
    t_quick = time.perf_counter() - t
    result = exact.result()
    t_exact = time.perf_counter() - t
    shape = doc.preview_shape(results, looks) if results else None
    report = doc.apply_remote(result, request)
    print("exact on one core: %.2f s, errors %s" % (t_exact, report.errors))
    if looks:
        print("quick look (%d cores): %.2f s, %s" % (
            len(looks), t_quick, looks[0]["key"].split("#")[1]))
        print("volumes: exact %.1f, quick %.1f" % (volume(doc.shape),
                                                    volume(shape)))
    pool.shutdown()


if __name__ == "__main__":
    main()
