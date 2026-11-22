"""Rebuild every example part and write down what it came to.

    python tests\provenance_numbers.py --record out.json [--root DIR]

``--root`` puts another copy of the ``datum`` package first on the path,
which is how the "before" numbers of Phase 2 were taken: from the commit
before provenance, extracted with ``git archive``. Per part: volume, face
count, solids, the seconds a cold rebuild took (best of ``--repeat``), and,
where the code in use keeps provenance, how many bytes its index map is
beside the body (``prov_bytes``) and how many tagged faces it holds.

tests/test_provenance.py compares a fresh run of this with
tests/data/example_parts.json, written from the commit before provenance, so
that "files without provenance open and rebuild exactly as before" is a
checked fact and not a claim.
"""
import argparse
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EXAMPLES = os.path.join(REPO, "examples")


def example_parts():
    found = []
    for ext in ("*.icpart", "*.pdat"):
        found += glob.glob(os.path.join(EXAMPLES, "**", ext), recursive=True)
    return sorted(found)


def measure(path, repeat=1):
    from datum.core import kernel
    from datum.core.document import Document
    best, doc = None, None
    for _ in range(max(1, repeat)):
        started = time.perf_counter()
        doc = Document.load(path)
        took = time.perf_counter() - started
        best = took if best is None else min(best, took)
    shape = doc.shape
    out = {"seconds": round(best, 4), "ok": bool(doc.last_report.ok)}
    if shape is None or shape.IsNull():
        out.update({"volume": 0.0, "faces": 0, "solids": 0})
        return out
    # By plain integration, as the recorded numbers were: this is to show
    # that the geometry is as it was.  kernel.volume() has since been made
    # more accurate (the slew pedestal tube is 0.0014% bigger by it), and
    # tests/test_freeform_measure.py is what checks that.
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    out.update({"volume": round(props.Mass(), 4),
                "faces": kernel.face_count(shape),
                "solids": len(kernel.solids(shape))})
    try:
        from datum.core import provenance
        data = provenance.dump(shape)
        if data:
            out["prov_bytes"] = len(json.dumps(data, separators=(",", ":")))
            out["tagged_faces"] = len({i for ix in data["roles"].values()
                                       for i in ix})
    except ImportError:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", required=True)
    ap.add_argument("--root", default=REPO)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    sys.path.insert(0, args.root)
    parts = example_parts()
    if args.limit:
        parts = parts[:args.limit]
    out = {}
    for path in parts:
        rel = os.path.relpath(path, EXAMPLES).replace("\\", "/")
        try:
            out[rel] = measure(path, args.repeat)
        except Exception as exc:  # noqa: BLE001
            out[rel] = {"error": "%s: %s" % (type(exc).__name__, exc)}
        print(rel, out[rel], flush=True)
    with open(args.record, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
