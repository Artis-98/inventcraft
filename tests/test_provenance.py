"""Provenance: which feature made which face (datum/core/provenance.py).

Four things are checked, in this order:

1. The kernel's history (``kernel.*_h``) is folded through the booleans,
   the repair and the merge of faces, so a plate with holes knows each
   hole's wall, its caps, its sides and its rounds.
2. What is known survives the ways a body travels: the body cache, and a
   worker's rebuild applied to another document.
3. The roles hold through +-50 % parameter changes and a feature switched
   on upstream: every role still names the same face (same surface, same
   direction, same place in the part). For each change the same faces are
   also followed the old way, by fingerprint alone, and the count of those
   that would have been lost is printed.
4. Existing parts stay the same: every example part rebuilds to the volume,
   area, bounding box and solid, face, edge and vertex counts measured on
   the code before provenance (tests/data/example_parts.json, written by
   ``tools/compare_models.py measure`` on InventCraft 0.4.8).

Run on its own:  python tests\\test_provenance.py [--fast]
``--fast`` leaves out the example parts.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import harness  # noqa: E402,F401

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface  # noqa
from OCP.GeomAbs import GeomAbs_CurveType, GeomAbs_SurfaceType  # noqa: E402
from OCP.TopoDS import TopoDS  # noqa: E402

from datum.core import kernel, provenance  # noqa: E402
from datum.core.document import Document  # noqa: E402
from datum.core.features import FilletFeature  # noqa: E402
from datum.core.naming import RefSet, ShapeRef  # noqa: E402

FAST = "--fast" in sys.argv
FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_prov_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


# ------------------------------------------------------------------ the part

# A plate w x h x t (parameters), two plain holes and a counterbored one,
# and a pocket cut through it before the holes (suppressed to start with),
# as document data. The four upright corners are rounded below, picked as
# a person picks them, so the fillet stores references.
with open(os.path.join(HERE, "data", "provenance_plate.json"),
          encoding="utf-8") as handle:
    PLATE = json.load(handle)


def upright_edges(shape):
    out = []
    for edge in kernel.edges(shape):
        curve = BRepAdaptor_Curve(TopoDS.Edge_s(edge))
        if curve.GetType() != GeomAbs_CurveType.GeomAbs_Line:
            continue
        d = curve.Line().Direction()
        if abs(abs(d.Z()) - 1) < 1e-9:
            box = kernel.bounding_box(edge)
            whole = kernel.bounding_box(shape)
            # the plate's corners, not the edges of the pocket
            if (min(abs(box[0] - whole[0]), abs(box[3] - whole[3])) < 1e-6
                    and min(abs(box[1] - whole[1]),
                            abs(box[4] - whole[4])) < 1e-6):
                out.append(edge)
    return out


def plate(pocket=False):
    doc = Document()
    doc.load_dict(json.loads(json.dumps(PLATE)))
    for f in doc.features:
        if f.name in ("Pocket sketch", "Pocket"):
            f.suppressed = not pocket
    doc.rebuild()
    corners = FilletFeature(name="Corners")
    corners.radius = "4"
    refs = RefSet()
    refs.capture_from(doc.shape, "edge", upright_edges(doc.shape))
    corners.refs = refs
    doc.add_feature(corners)
    report = doc.rebuild()
    assert not report.errors, report.errors
    return doc


def set_params(doc, **values):
    for name, value in values.items():
        doc.params.set_expression(name, str(value))
    report = doc.rebuild()
    assert not report.errors, report.errors


# ------------------------------------------------------------ descriptors


def tight_box(shape):
    """The box the faces themselves span: OpenCASCADE's quick box is
    padded, and by more on a body that has been meshed."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    return box.Get()


def signature(shape):
    """Each face of a shape as (surface, direction, where): what kind it is,
    which way it faces or runs, and where it stands in the part. None of it
    depends on size, so it is what a role must still name after a resize."""
    box = tight_box(shape)
    lo, hi = box[:3], box[3:]
    span = max(h - l for l, h in zip(lo, hi))
    out = {}
    for face in kernel.faces(shape):
        surface = BRepAdaptor_Surface(TopoDS.Face_s(face))
        kind = surface.GetType()
        c = kernel.shape_centre(face)
        if kind == GeomAbs_SurfaceType.GeomAbs_Plane:
            d = surface.Plane().Axis().Direction()
            n = [d.X(), d.Y(), d.Z()]
            axis = max(range(3), key=lambda i: abs(n[i]))
            pos = c[axis]
            where = ("lo" if pos <= lo[axis] + 1e-6 * span else
                     "hi" if pos >= hi[axis] - 1e-6 * span else "mid")
            out[hash(face)] = ("plane", tuple(round(abs(v), 3) for v in n),
                               where)
            continue
        if kind == GeomAbs_SurfaceType.GeomAbs_Cylinder:
            d = surface.Cylinder().Axis().Direction()
            a = [abs(d.X()), abs(d.Y()), abs(d.Z())]
            name = "cylinder"
        else:
            a, name = [0, 0, 1], str(kind)
        axis = max(range(3), key=lambda i: a[i])
        side = tuple(0 if (i == axis or abs(c[i] - (lo[i] + hi[i]) / 2)
                           < 0.05 * (hi[i] - lo[i]))
                     else (1 if c[i] > (lo[i] + hi[i]) / 2 else -1)
                     for i in range(3))
        out[hash(face)] = (name, tuple(round(v, 3) for v in a), side)
    return out


def role_table(doc):
    """role -> sorted signatures of the faces carrying it."""
    sig = signature(doc.shape)
    table = {}
    for tags in provenance.lookup(doc.shape):
        for role, indices in tags.all_roles().items():
            table[role] = sorted(sig[hash(tags.face(i))] for i in indices)
    return table


def fingerprint_refs(doc):
    """For every face that holds a role: the reference the old way would
    have kept (where it is, how big, what surface), with its signature."""
    sig = signature(doc.shape)
    pool = kernel.faces(doc.shape)
    out = []
    for tags in provenance.lookup(doc.shape):
        for role, indices in tags.all_roles().items():
            for i in indices:
                face = tags.face(i)
                index = next(j for j, f in enumerate(pool) if f.IsSame(face))
                out.append((role, ShapeRef.capture(face, "face", index),
                            sig[hash(face)]))
    return out


# -------------------------------------------------------------- 1. history

print("kernel history through a plate with holes")
doc = plate()
body = doc.bodies[0]
check("the body carries tags for the shape it has",
      body.tags is not None and body.tags.is_for(body.shape))
roles = body.tags.all_roles()
ids = {f.name: f.id for f in doc.features}
slab, holes, cb, corners = (ids["Plate"], ids["Holes"], ids["Cbore"],
                            ids["Corners"])
check("the plate's two caps", "%d:start" % slab in roles
      and "%d:end" % slab in roles, sorted(roles))
check("the plate's four sides (one per sketch entity)",
      sum(1 for r in roles if r.startswith("%d:side:" % slab)) == 4,
      sorted(roles))
check("each hole's wall by its sketch point",
      sum(1 for r in roles if r.startswith("%d:wall:" % holes)) == 2,
      sorted(roles))
check("the counterbore, its shoulder and its bore",
      all("%d:%s:" % (cb, k) in " ".join(roles)
          for k in ("wall", "cbore", "shoulder")), sorted(roles))
check("four rounds, each also named for the faces it lies between",
      sum(1 for r in roles if r.startswith("%d:face:" % corners)) == 4
      and sum(1 for r in roles if r.startswith("%d:edge:" % corners)) == 4,
      sorted(roles))
sig = signature(doc.shape)
wall = [r for r in roles if r.startswith("%d:wall:" % holes)][0]
check("a hole's wall is its cylinder",
      [sig[hash(f)][0] for f in body.tags.faces_for(wall)] == ["cylinder"])
top = body.tags.faces_for("%d:end" % slab)
check("Plate.end is one plane, facing +z, at the top",
      len(top) == 1 and sig[hash(top[0])] == ("plane", (0, 0, 1), "hi"),
      [sig[hash(f)] for f in top])
check("the tags are for exactly the shape the part has",
      body.tags.is_for(doc.shape)
      and body.tags.count == len(kernel.faces(doc.shape)))
check("the stored corner picks carry the roles of their faces",
      all(r.has_roles for r in doc.features[-1].refs))

print("the history objects themselves")
box = kernel.box(40, 20, 10)
tool = kernel.cylinder(3, 30, (20, 10, -5))
made, hist = kernel.boolean_h(box, tool, "cut")
check("boolean_h tells what became of a cut face",
      hist.known and all(hist.image(f) is not None for f in kernel.faces(box)))
check("each face the tool did not cut came through as one face",
      len([f for f in kernel.faces(box) if len(hist.image(f)) == 1]) >= 4)
square = kernel.faces(kernel.box(5, 5, 0.001))[0]
prism, ph = kernel.extrude_h(square, (0, 0, 1), 7)
check("extrude_h names the caps",
      len(ph.first_faces()) == 1 and len(ph.last_faces()) == 1)
check("and the side swept from each edge of the profile",
      all(ph.generated(e) for e in kernel.edges(square)))
check("the shape is the one extrude makes",
      abs(kernel.volume(prism) - kernel.volume(kernel.extrude(
          square, (0, 0, 1), 7))) < 1e-9)

# --------------------------------------------------------- 2. travelling

print("a body travels")
before = role_table(doc)
from datum.core import bodycache, prefs  # noqa: E402
bodycache.FOLDER = os.path.join(WORK, "bodies")
prefs.config_path = lambda *p: os.path.join(WORK, *p)
shape = doc.shape
check("the body is stored", bodycache.store("ab" * 32, shape))
side = bodycache._roles_file(bodycache._file_for("ab" * 32))
check("with its index map beside it, small",
      os.path.exists(side) and os.path.getsize(side) < 4000,
      os.path.getsize(side) if os.path.exists(side) else -1)
provenance.forget()
loaded = bodycache.load("ab" * 32)
check("read back it is a different object", loaded is not None
      and not loaded.IsSame(shape))
back = provenance.lookup(loaded)
check("and still knows its roles, by index",
      bool(back) and back[0].all_roles().keys() == body.tags.all_roles(
      ).keys())
check("naming the same kinds of face",
      sorted(signature(loaded).values()) == sorted(signature(shape).values()))

from datum.core import worker  # noqa: E402
request = {"key": "k1", "path": "", "data": doc.to_dict(),
           "trusted": False, "rollback": None, "have": [], "prime": False}
result = worker._rebuild("k1", "", request["data"], False)
check("a worker's answer carries the index map",
      all("prov" in b for b in result["bodies"]), result["bodies"])
provenance.forget()
again = Document()
again.load_dict(request["data"])
again.apply_remote(result, request)
tags = again.bodies[0].tags
check("a document that took a worker's rebuild has the roles",
      tags is not None and tags.is_for(again.bodies[0].shape))
check("the same roles as the document that built it",
      role_table(again) == before, (sorted(role_table(again)), sorted(before)))

# ----------------------------------------------------------- 3. robustness

print("roles hold through changes")
lost_by_fingerprint = [0]


def verify(doc, base_roles, base_prints, label):
    now = role_table(doc)
    bad = [(role, sigs, now.get(role)) for role, sigs in base_roles.items()
           if now.get(role) != sigs]
    sig = signature(doc.shape)
    for _role, ref, want in base_prints:
        ref.roles, ref.adjacent = [], []
        found = ref._resolve_by_fingerprint(doc.shape)
        if not (found is not None and ref.resolved
                and sig.get(hash(found)) == want):
            lost_by_fingerprint[0] += 1
    check("%s: every role names the same face" % label, not bad, bad[:3])
    check("%s: the corner fillet found its edges" % label,
          not doc.last_report.errors, doc.last_report.errors)


doc = plate()
base_roles, base_prints = role_table(doc), fingerprint_refs(doc)
for label, change in (
        ("w +50%", dict(w=150)), ("w -50%", dict(w=50)),
        ("h +50%", dict(h=90)), ("h -50%", dict(h=30)),
        ("t +50%", dict(t=12)), ("t -50%", dict(t=4)),
        ("all up", dict(w=150, h=90, t=12)),
        ("all down", dict(w=50, h=30, t=4)),
        ("back", dict(w=100, h=60, t=8))):
    set_params(doc, **change)
    verify(doc, base_roles, base_prints, label)

doc = plate()
base_roles, base_prints = role_table(doc), fingerprint_refs(doc)
for f in doc.features:
    if f.name in ("Pocket sketch", "Pocket"):
        f.suppressed = False
doc.rebuild()
pocket = {f.name: f.id for f in doc.features}["Pocket"]
kept = {r: s for r, s in base_roles.items()}
verify(doc, kept, base_prints, "a pocket switched on before the holes")
set_params(doc, w=150, h=90)
verify(doc, kept, base_prints, "and then +50 % on top of it")
print("  faces the old way, by fingerprint alone, would have lost: %d"
      % lost_by_fingerprint[0])
check("and the old way would have lost some of them",
      lost_by_fingerprint[0] > 0)

# ----------------------------------------------------------- 4. old files

if not FAST:
    print("every example part, as before")
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import compare_models  # noqa: E402
    with open(os.path.join(HERE, "data", "example_parts.json"),
              encoding="utf-8") as handle:
        want = json.load(handle)
    os.environ["DATUM_NO_BODY_CACHE"] = "1"
    bad = []
    for rel, w in sorted(want.items()):
        got = compare_models._measure_one(os.path.join(REPO, rel))
        for key in sorted(set(w) | set(got)):
            if key not in w or key not in got or compare_models._differs(
                    w[key], got[key], key):
                bad.append("%s: %s %s -> %s" % (rel, key, w.get(key),
                                                 got.get(key)))
    check("%d example parts are the same as on 0.4.8 (volume, area, box, "
          "solids, faces, edges, vertices, errors)" % len(want), not bad,
          bad[:3])

print()
if FAILS:
    print("FAILED: %d" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("all provenance tests passed")
