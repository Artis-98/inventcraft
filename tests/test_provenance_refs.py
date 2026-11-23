"""Provenance through the MCP bridge: references an agent writes.

tests/test_provenance.py checks the kernel's history, how roles travel and
that the example parts are unchanged, on core features alone. This checks
the same roles the way an agent meets them, through build ops and written
references ("Plate.end", "Holes.wall[0]", "Plate.end.edge(side(r.top))"):

* roles hold through +-50 % parameter changes and features inserted
  upstream, on a plate and on parts from recorded sessions (a bracket, a
  DIN 934 nut, a plate with a hole pattern); for each change the same
  faces are also followed the old way, by fingerprint alone, and the count
  of those that would have failed is printed;
* every kind of written reference resolves by role, and keeps resolving
  to the same face;
* a sketch written again with entities added first keeps its names;
* a stored pick whose roles name nothing is followed by position, and the
  build says so.
"""
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import harness  # noqa: E402,F401

from datum.bridge.host import InProcessHost  # noqa: E402
from datum.bridge.refs import Resolver, facts  # noqa: E402
from datum.core import kernel, provenance  # noqa: E402
from datum.core.naming import ShapeRef  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_prov_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


# ------------------------------------------------------------------ parts

PLATE = [
    {"op": "parameter", "name": "w", "value": 100},
    {"op": "parameter", "name": "h", "value": 60},
    {"op": "parameter", "name": "t", "value": 8},
    {"op": "sketch", "id": "s1", "plane": "XY", "name": "Outline", "entities": [
        {"rect": {"center": [0, 0], "size": ["w", "h"]}, "id": "r"}]},
    {"op": "extrude", "id": "e1", "sketch": "$s1", "distance": "t",
     "name": "Plate"},
    {"op": "sketch", "id": "s2", "plane": "XY", "name": "Hole sketch",
     "entities": [
         {"circle": {"center": ["w/6", "h/6"], "d": 8}},
         {"circle": {"center": ["-w/6", "h/6"], "d": 6}}]},
    {"op": "hole", "id": "h1", "sketch": "$s2", "diameter": 8, "name": "Holes"},
    {"op": "sketch", "id": "s3", "plane": "XY", "name": "Cbore sketch",
     "entities": [{"point": [0, "-h/4"], "id": "c"}]},
    {"op": "hole", "id": "h2", "sketch": "$s3", "diameter": 6,
     "hole_type": "counterbore", "cb_diameter": 12, "cb_depth": 3,
     "points": ["c"], "name": "Cbore"},
    {"op": "fillet", "radius": 4, "edges": {"along": "z"}, "name": "Corners"},
]

# a pocket and a boss, inserted between the plate and its holes
PLATE_INSERT = [
    {"op": "sketch", "id": "s9", "plane": "XY", "name": "Pocket sketch",
     "entities": [{"rect": {"center": ["w/4", "-h/4"], "size": [10, 8]}}]},
    {"op": "extrude", "id": "e9", "sketch": "$s9", "operation": "cut",
     "extent": "through_all", "name": "Pocket"},
    {"op": "move", "feature": "$s9", "before": "Hole sketch"},
    {"op": "move", "feature": "$e9", "before": "Hole sketch"},
]


def replay_ops(name):
    """The ops of the first build in a recorded session."""
    with open(os.path.join(HERE, "mcp_replays", name + ".json"),
              encoding="utf-8") as handle:
        for call in json.load(handle)["calls"]:
            if call["tool"] == "build":
                return call["args"]["ops"]
    raise AssertionError(name)


# ------------------------------------------------------------ descriptors


def signature(shape):
    """Each face of a shape as (surface, direction, where): what kind it is,
    which way it faces or runs, and where it stands in the part. A plane is
    at the low end, the high end or in the middle of the part along its own
    normal; a cylinder is on which side of the middle of the part, across
    its axis. None of it depends on size, so it is what a reference must
    still be after a resize."""
    box = kernel.exact_bounding_box(shape)
    lo, hi = box[:3], box[3:]
    span = max(h - l for l, h in zip(lo, hi))
    out = {}
    for face in kernel.faces(shape):
        f = facts(face, "face")
        c = f["centre"]
        if f["type"] == "plane":
            n = f.get("normal") or [0, 0, 0]
            axis = max(range(3), key=lambda i: abs(n[i]))
            pos = c[axis]
            where = ("lo" if pos <= lo[axis] + 1e-6 * span else
                     "hi" if pos >= hi[axis] - 1e-6 * span else "mid")
            out[hash(face)] = ("plane", tuple(round(v, 3) for v in n), where)
        else:
            a = [abs(v) for v in (f.get("axis") or [])]
            axis = max(range(3), key=lambda i: a[i]) if a else 2
            side = tuple(0 if (i == axis or abs(c[i] - (lo[i] + hi[i]) / 2)
                               < 0.05 * (hi[i] - lo[i]))
                         else (1 if c[i] > (lo[i] + hi[i]) / 2 else -1)
                         for i in range(3))
            out[hash(face)] = (f["type"], tuple(round(v, 3) for v in a),
                               f.get("hole"), side)
    return out


def role_table(doc):
    """role -> sorted signatures of the faces carrying it."""
    shape = doc.shape
    sig = signature(shape)
    table = {}
    for tags in provenance.lookup(shape):
        for role, indices in tags.all_roles().items():
            table[role] = sorted(sig[hash(tags.face(i))] for i in indices)
    return table


def fingerprint_refs(doc, table_roles):
    """For every face that holds a role: the reference the old way would have
    kept (where it is, how big, what surface), with its signature."""
    shape = doc.shape
    sig = signature(shape)
    pool = kernel.faces(shape)
    out = []
    for tags in provenance.lookup(shape):
        for role, indices in tags.all_roles().items():
            for i in indices:
                face = tags.face(i)
                index = next(j for j, f in enumerate(pool) if f.IsSame(face))
                out.append((role, ShapeRef.capture(face, "face", index),
                            sig[hash(face)]))
    return out


class Case:
    def __init__(self, name, ops, name_of_part=None):
        self.name = name
        self.host = InProcessHost()
        self.d = self.host.call("new_document")["doc"]
        r = self.host.call("build", {"ops": ops})
        assert r["ok"], (name, r.get("error"))
        self.entry = self.host.workspace.get(self.d)
        self.doc = self.entry.document
        self.base_roles = role_table(self.doc)
        self.base_prints = fingerprint_refs(self.doc, self.base_roles)
        self.checked = 0
        self.role_failed = 0
        self.finger_failed = 0
        self.lost = []

    def params(self, **kw):
        # in millimetres, whatever the part's own unit is
        r = self.host.call("properties", {"parameters": {
            k: "%s mm" % v for k, v in kw.items()}})
        assert r["rebuild"]["ok"], (self.name, r["rebuild"])

    def build(self, ops):
        r = self.host.call("build", {"ops": ops})
        assert r["ok"], (self.name, r.get("error"))

    def verify(self, label, allow_lost=()):
        """Every role the part had still names the same faces; and the old
        way's score on the same faces."""
        now = role_table(self.doc)
        bad = []
        for role, sigs in self.base_roles.items():
            if any(role.startswith(a) or a in role for a in allow_lost):
                continue
            self.checked += 1
            if now.get(role) != sigs:
                self.role_failed += 1
                bad.append((role, sigs, now.get(role)))
        shape = self.doc.shape
        sig = signature(shape)
        pool = kernel.faces(shape)
        for role, ref, want in self.base_prints:
            if any(a in role for a in allow_lost):
                continue
            ref.roles, ref.adjacent = [], []
            found = ref._resolve_by_fingerprint(shape)
            ok = (found is not None and ref.resolved
                  and sig.get(hash(found)) == want)
            if not ok:
                self.finger_failed += 1
        check("%s: %s: every role names the same face" % (self.name, label),
              not bad, bad[:3])
        return not bad

    def report(self):
        return (self.name, self.checked, self.role_failed, self.finger_failed)


def resolve_text(case, text):
    r = Resolver(case.entry).resolve(text, "ref")
    return r


# ----------------------------------------------------------- 3. robustness

print("references hold through changes")
cases = []

c = Case("plate", PLATE)
cases.append(c)
for label, change in (
        ("w +50%", dict(w=150)), ("w -50%", dict(w=50)),
        ("h +50%", dict(h=90)), ("h -50%", dict(h=30)),
        ("t +50%", dict(t=12)), ("t -50%", dict(t=4)),
        ("all up", dict(w=150, h=90, t=12)),
        ("all down", dict(w=50, h=30, t=4)),
        ("back", dict(w=100, h=60, t=8))):
    c.params(**change)
    c.verify(label)
c.build(PLATE_INSERT)
c.verify("a pocket inserted before the holes")
c.params(w=150, h=90)
c.verify("and then +50 % on top of it")
c.params(w=50, h=30)
c.verify("and -50 %")

# named references are the same story told in text: every kind of ref an
# agent writes, and which way each was found
c = Case("plate refs", PLATE)
refs = ["Plate.end", "Plate.start", "Plate.side(r.top)", "Plate.side(r.right)",
        "Holes.wall[0]", "Holes.wall[1]", "Cbore.wall[0]", "Cbore.cbore[0]",
        "Cbore.shoulder[0]", "Corners.face[0]", "Corners.face[3]",
        "Plate.end.edge(Holes.wall[0])", "Plate.end.edge(side(r.top))",
        "Plate.side(r.top).edge(end)"]
def resolved(case):
    out = {}
    sig = signature(case.doc.shape)
    for text in refs:
        try:
            r = resolve_text(case, text)
        except Exception as exc:  # noqa: BLE001
            out[text] = ("ERR", str(exc)[:60])
            continue
        kinds = []
        for s in r.shapes:
            if r.kind == "face":
                kinds.append(sig[hash(s)])
            else:
                f = facts(s, "edge")
                kinds.append((f["type"], tuple(f.get("direction") or ())))
        out[text] = (r.kind, r.via, sorted(kinds))
    return out
base = resolved(c)
check("every written reference resolves, by role",
      all(v[0] != "ERR" for v in base.values()) and all(
          v[1] == "role" for v in base.values()),
      {k: v for k, v in base.items() if v[0] == "ERR" or v[1] != "role"})
for label, change in (("w 150, h 90", dict(w=150, h=90)),
                      ("w 50, h 30", dict(w=50, h=30)), ("t 4", dict(t=4))):
    c.params(**change)
    now = resolved(c)
    same = {k for k in base if now[k][2:] == base[k][2:]
            and now[k][1] == "role"}
    check("written refs after %s: same faces, still by role" % label,
          same == set(base), {k: now[k] for k in base if k not in same})

# the bracket and the nut, from the recorded sessions
bracket = Case("bracket", replay_ops("bracket"))
cases.append(bracket)
for label, change in (
        ("w +50%, pitch with it", dict(w=180, pitch=45)),
        ("w -50%, pitch with it", dict(w=60, pitch=15)),
        ("h +50%", dict(h=60)), ("h -50%", dict(h=20)),
        ("d +50%", dict(d=90)), ("d -50%", dict(d=30)),
        ("wall +25%", dict(wall=5)), ("wall -25%", dict(wall=3))):
    bracket.params(**change)
    bracket.verify(label)
    bracket.params(w=120, pitch=30, h=40, d=60, wall=4)

nut = Case("nut", replay_ops("din934_nut"))
cases.append(nut)
for label, change in (("s +50%", dict(s=25, dh=11)), ("s -50%", dict(s=17 / 2 + 1, dh=4)),
                      ("m +50%", dict(m=12)), ("m -50%", dict(m=4))):
    nut.params(**change)
    nut.verify(label, allow_lost=("thread",))
    nut.params(s=17, dh=8.5, m=8)

# the agent-built plate of the Tier 2 run: holes sized and placed by parameters
tier2 = Case("tier2 plate", replay_ops("tier2_plate_hole_pattern"))
cases.append(tier2)
base_values = {"L": 160, "W": 100, "T": 10}
# (W -50 % would put the 40 mm bore outside the plate: not a part)
for label, change in (("L +50%", dict(L=240)), ("L -50%", dict(L=80)),
                      ("W +50%", dict(W=150)), ("W -25%", dict(W=75)),
                      ("T +50%", dict(T=15)), ("T -50%", dict(T=5))):
    try:
        tier2.params(**change)
    except AssertionError as exc:
        print("  (skipped %s: the part itself does not build: %s)" % (
            label, str(exc)[:80]))
        tier2.params(**base_values)
        continue
    tier2.verify(label)
    tier2.params(**base_values)

# a feature inserted upstream: a boss in the bracket, before the fillet
bracket.build([
    {"op": "sketch", "id": "ins", "plane": "XY", "name": "Insert sketch",
     "entities": [{"circle": {"center": ["w/3", 0], "d": 12}}]},
    {"op": "extrude", "id": "insx", "sketch": "$ins", "operation": "cut",
     "extent": "through_all", "name": "Insert window"},
    {"op": "move", "feature": "$ins", "before": "Hollow"},
    {"op": "move", "feature": "$insx", "before": "Hollow"}])
bracket.verify("a window cut inserted before the shell",
               allow_lost=("Hollow", "Corners"))
bracket.params(w=180, pitch=45)
bracket.verify("and then w +50%", allow_lost=("Hollow", "Corners"))

# a sketch redrawn with an entity added first (the agent's way of adding one:
# it writes the whole sketch again, and every entity used to get a new id)
print("a sketch entity added before the referenced one")
REDRAW = PLATE + [
    # picked by reference, so stored as roles: the top edge of the plate (the
    # chamfer runs on round the whole rim, being tangent all the way)
    {"op": "chamfer", "distance": 1, "edges": ["Plate.end.edge(side(r.top))"],
     "name": "Top chamfer"},
]
c = Case("redrawn sketch", REDRAW)
cases.append(c)
text_refs = ["Plate.side(r.top)", "Plate.side(r.right)", "Plate.side(r.left)",
             "Plate.end", "Holes.wall[0]", "Holes.wall[1]", "Cbore.wall[0]",
             "Top chamfer.face[0]"]
def faces_by_text(case, texts):
    sig = signature(case.doc.shape)
    out = {}
    for t in texts:
        r = resolve_text(case, t)
        out[t] = (r.via, sorted(sig[hash(s)] for s in r.shapes))
    return out
want = faces_by_text(c, text_refs)
edit_ok = c.host.call("build", {"ops": [{"op": "edit", "feature": "Outline",
    "set": {"entities": [
        {"circle": {"center": ["w/3", "h/3"], "d": 7}, "id": "extra"},
        {"line": [[-60, -40], [-50, -40]], "construction": True, "id": "guide"},
        {"rect": {"center": [0, 0], "size": ["w", "h"]}, "id": "r"}]}}]})
check("the sketch is written again with new entities first", edit_ok["ok"],
      edit_ok.get("error"))
got = faces_by_text(c, text_refs)
check("every name still means the face it meant (the redraw keeps the ids "
      "of what keeps its name)", {k: v[1] for k, v in got.items()} == {
          k: v[1] for k, v in want.items()}, {
          k: (want[k][1], got[k][1]) for k in want if got[k][1] != want[k][1]})
check("found by role", all(v[0] == "role" for v in got.values()),
      {k: v[0] for k, v in got.items()})
c.verify("after the redraw")
stored = [f for f in c.doc.features if f.name == "Top chamfer"][0]
check("the chamfer, stored as roles, still has them and rebuilt by role",
      stored.refs.refs and all(r.has_roles for r in stored.refs)
      and c.doc.last_report.ok and not [
          w for w in c.doc.last_report.warnings if "position" in w],
      c.doc.last_report.warnings)

# a stored pick whose roles no longer name anything is followed by where it
# was, and build() says so in its envelope
print("a fallback is reported")
stored = [f for f in c.doc.features if f.name == "Top chamfer"][0]
for r in stored.refs:
    r.roles, r.adjacent = ["999:nothing"], []
warn = c.host.call("build", {"ops": [{"op": "edit", "feature": "Top chamfer",
                                      "set": {"distance": 1.2}}]})
check("the fallback comes back as a warning",
      warn["ok"] and any("position" in w or "where" in w
                         for w in warn.get("warnings", [])),
      warn.get("warnings"))

# ------------------------------------------------------------- the numbers

print()
print("   case                 roles   role path   fingerprint path")
print("                       checked    failed        failed")
tot = [0, 0, 0]
for c in cases:
    name, n, rf, ff = c.report()
    print("   %-20s %6d %10d %14d" % (name, n, rf, ff))
    tot = [tot[0] + n, tot[1] + rf, tot[2] + ff]
print("   %-20s %6d %10d %14d" % ("all", *tot))
check("no role changed face anywhere", tot[1] == 0)
check("and the old way would have failed some of them", tot[2] > 0, tot)

print()
if FAILS:
    print("FAILED: %d" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("all provenance tests passed")
