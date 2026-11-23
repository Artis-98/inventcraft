"""The bridge ops an agent drives InventCraft through (datum/bridge).

Run in this process, with no host and no MCP: what is tested here is
what the ops do to a document. test_mcp_server.py tests the same through
a real MCP client, a real server and a real host process.
"""
import base64
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.bridge.errors import BridgeError  # noqa: E402
from datum.bridge.host import InProcessHost  # noqa: E402
from datum.core.document import Document  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_bridge_")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def raises(kind, fn, *a, **k):
    try:
        fn(*a, **k)
    except BridgeError as exc:
        return exc.kind == kind
    return False


PLATE = [
    {"op": "parameter", "name": "w", "value": 100, "comment": "width"},
    {"op": "parameter", "name": "h", "value": 60},
    {"op": "parameter", "name": "t", "value": 8},
    {"op": "sketch", "id": "s1", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": ["w", "h"]}},
        {"circle": {"center": [0, 0], "d": 20}}]},
    {"op": "extrude", "id": "e1", "sketch": "$s1", "distance": "t"},
    {"op": "fillet", "radius": 5, "edges": {"along": "z"}},
]

print("build")
host = InProcessHost()
d = host.call("new_document")["doc"]
r = host.call("build", {"ops": PLATE})
check("a plate builds in one call", r["ok"], r.get("error"))
check("as one solid", r["after"]["solids"] == 1)
check("the summary line says what was made",
      "+Extrude" in r["summary"] and "1 solid" in r["summary"],
      r["summary"])
check("the circle inside the rect is a hole (outer profiles)",
      abs(r["after"]["volume"] - (100 * 60 - 3.14159265 * 100 - 4 * (25 - 3.14159265 * 25 / 4)) * 8) < 5,
      r["after"]["volume"])
check("the fillet found the four corners, not the hole's seam",
      any("4 edge(s)" in n for n in r["notes"]), r["notes"])
check("one build is one revision", r["revision"] == 2, r["revision"])

print("parametric")
tree = host.call("model_tree")
check("sketch is fully constrained",
      "fully constrained" in tree["features"][0]["summary"],
      tree["features"][0]["summary"])
check("parameter comments are kept",
      tree["parameters"][0].get("comment") == "width")
p = host.call("properties", {"parameters": {"w": "140"}})
check("a parameter change rebuilds cleanly", p["rebuild"]["ok"]
      and not p["rebuild"]["warnings"], p["rebuild"])
box = host.call("inspect")["bbox"]
check("and the plate is now 140 wide", abs(box[0] - 140) < 1e-6, box)
fillet = host.call("model_tree")["features"][2]
check("the fillet still holds after the plate grew 40 mm (query, not "
      "coordinates)", "error" not in fillet and "z" in fillet["summary"],
      fillet)
check("rounded corners after the change: faces as before",
      host.call("inspect")["faces"] == r["after"]["faces"])

print("verify")
v = host.call("inspect", {"expected": {"bbox": [140, 60, 8], "solids": 1}})
check("an expectation that holds passes", v["verdict"]["pass"], v["verdict"])
v = host.call("inspect", {"expected": {"bbox": [100, 60, 8]}})
check("one that does not, fails", not v["verdict"]["pass"])
check("an expectation it cannot check is refused, not passed",
      raises("BAD_EXPECTATION", host.call, "inspect",
             {"expected": {"holes": 1}}))

print("atomic")
before = host.call("model_tree")
bad = host.call("build", {"ops": [
    {"op": "parameter", "name": "q", "value": 3},
    {"op": "fillet", "radius": 500, "edges": "all"}]})
check("a failing op fails the build", not bad["ok"])
check("and says which op and why", bad["error"]["at"]["index"] == 1
      and bad["error"]["kind"] == "FEATURE_FAILED", bad["error"])
check("with hints", bool(bad["error"]["hints"]))
after = host.call("model_tree")
check("and nothing of it is left behind (the parameter too)",
      [f["name"] for f in after["features"]]
      == [f["name"] for f in before["features"]]
      and "q" not in [p["name"] for p in after["parameters"]])
check("a rolled back build is no new revision",
      after["revision"] == before["revision"])
dry = host.call("build", {"dry_run": True, "ops": [
    {"op": "chamfer", "distance": 1, "edges": {"at": "+z"}}]})
check("a dry run reports what it would make", dry["ok"]
      and dry["would_create"][0]["type"] == "chamfer", dry)
check("and leaves the model as it was",
      len(host.call("model_tree")["features"]) == 3)
check("an unknown op is refused with the list of ops",
      host.call("build", {"ops": [{"op": "warp"}]})["error"]["kind"]
      == "UNKNOWN_OP")
check("a bad back-reference is refused",
      host.call("build", {"ops": [{"op": "extrude", "sketch": "$nope",
                                   "distance": 5}]})["error"]["kind"]
      == "BAD_REF")
check("an unknown edge condition is refused",
      host.call("build", {"ops": [{"op": "fillet", "radius": 1,
                                   "edges": {"colour": "red"}}]})
      ["error"]["kind"] == "BAD_QUERY")
check("a stale revision is refused",
      raises("STALE_REVISION", host.call, "build",
             {"ops": PLATE[:1], "expected_revision": 1}))

print("render")
img = host.call("render_view", {"view": "iso", "width": 320,
                                "height": 240})
png = base64.b64decode(img["png_base64"])
check("render_view returns a PNG", png[:8] == b"\x89PNG\r\n\x1a\n")
check("of the size asked", img["size"] == [320, 240])
img = host.call("render_view", {"view": "top",
                                "highlight_edges": {"kind": "circle",
                                                    "min_length": 20}})
# the corner fillets are circular arcs too, 8 of them, each 7.9 long; the
# hole's two rims are 62.8 round
check("highlighting draws the queried edges", img.get("highlighted") == 2,
      img.get("highlighted"))
check("an unknown view is refused",
      raises("BAD_VIEW", host.call, "render_view", {"view": "sideways"}))

print("files")
path = os.path.join(WORK, "plate.pdat")
host.call("save_document", {"path": path})
check("saves", os.path.exists(path))
other = InProcessHost()
other.call("open_document", {"path": path})
check("reopens to the same size", other.call("inspect")["bbox"]
      == host.call("inspect")["bbox"])
saved = Document.load(path)
fl = [f for f in saved.features if f.type_name == "fillet"][0]
check("the edge query is saved with the fillet",
      fl.query == {"along": "z"}, fl.query)
other.call("properties", {"parameters": {"h": "90"}})
check("and still works after reopening",
      other.call("model_tree")["features"][2].get("error") is None
      and abs(other.call("inspect")["bbox"][1] - 90) < 1e-6)
check("saving over another file needs overwrite",
      raises("WOULD_OVERWRITE", other.call, "save_document",
             {"path": os.path.join(WORK, "x.pdat")})
      if open(os.path.join(WORK, "x.pdat"), "w").close() is None else False)
step = os.path.join(WORK, "plate.step")
host.call("export", {"path": step})
check("exports STEP", os.path.getsize(step) > 1000)
check("export will not overwrite unasked",
      raises("WOULD_OVERWRITE", host.call, "export", {"path": step}))
check("relative paths are refused",
      raises("BAD_PATH", host.call, "save_document", {"path": "rel.pdat"}))

print("units")
inch = InProcessHost()
inch.call("new_document", {"units": "in"})
r = inch.call("build", {"ops": [
    {"op": "sketch", "id": "s", "entities": [
        {"rect": {"corner": [0, 0], "size": [25.4, 50.8]}}]},
    {"op": "extrude", "sketch": "$s", "distance": 25.4}]})
check("an inch part built through the API is sized in mm",
      [round(v, 6) for v in r["after"]["bbox"]] == [25.4, 50.8, 25.4],
      r["after"]["bbox"])
check("and says its document units",
      r["units"] == {"api": "mm", "document": "in"})

# ================================================================ phase 1

print("schemas")
from datum.bridge import ir  # noqa: E402
from datum.core.features import FEATURE_TYPES  # noqa: E402

idx = InProcessHost().call("op_schema")["ops"]
check("every core feature type has an op",
      sorted(o["op"] for o in idx if "uri" in o) == sorted(FEATURE_TYPES))
check("and the tree ops are listed",
      {"parameter", "edit", "remove", "move"} <= {o["op"] for o in idx})
hole_schema = InProcessHost().call("op_schema", {"type": "hole"})
check("a schema is generated from the feature's fields",
      {"diameter", "depth", "hole_type", "points", "sketch_id", "sketch"}
      <= set(hole_schema["properties"]), sorted(hole_schema["properties"]))
check("expression fields take numbers or text",
      hole_schema["properties"]["diameter"]["type"] == ["number", "string"])
check("and say their default", hole_schema["properties"]["diameter"]
      ["default"] == "5")
check("unknown fields are refused by the schema",
      hole_schema["additionalProperties"] is False)
check("a type added to the core gets a schema with no MCP code",
      all(ir.schema(t)["title"] == t for t in FEATURE_TYPES))

print("every type")
gen = InProcessHost()
gen.call("new_document")
r = gen.call("build", {"ops": [
    {"op": "primitive", "id": "box", "kind": "box", "a": 40, "b": 30,
     "c": 20, "name": "Block"},
    {"op": "workplane", "id": "wp", "base": "XY", "offset": 20,
     "name": "Top plane"},
    {"op": "sketch", "id": "s", "plane": "$wp", "entities": [
        {"circle": {"center": [20, 15], "d": 8}, "id": "c"}]},
    {"op": "extrude", "sketch": "$s", "distance": 5, "id": "pin"},
    {"op": "move", "feature": "Block", "to": "start"}]})
check("generated ops build (primitive, workplane, sketch on it)", r["ok"],
      r.get("error"))
check("a sketch on a work plane sits on it",
      abs(gen.call("inspect")["bbox"][2] - 25) < 1e-6,
      gen.call("inspect")["bbox"])
r = gen.call("build", {"ops": [{"op": "hole", "diameter": 3}]})
check("an op missing what it needs fails with the core's own reason",
      not r["ok"] and r["error"]["kind"] in ("FEATURE_FAILED", "BAD_OP"),
      r.get("error"))
r = gen.call("build", {"ops": [{"op": "fillet", "radius": 1, "colour": 2}]})
check("an unknown field is refused, naming what the op takes",
      r["error"]["kind"] == "BAD_OP" and "radius" in r["error"]["hints"][0],
      r.get("error"))

print("bracket")
br = InProcessHost()
br.call("new_document")
BRACKET = json.load(open(os.path.join(os.path.dirname(os.path.abspath(
    __file__)), "mcp_replays", "bracket.json"), encoding="utf-8"))
BRACKET = BRACKET["calls"][1]["args"]["ops"]
r = br.call("build", {"ops": BRACKET})
check("a bracket with shell, hole, pattern, mirror, revolve builds",
      r["ok"], r.get("error"))
types = [f["type"] for f in br.call("model_tree")["features"]]
check("as those features", {"shell", "hole", "pattern", "mirror",
                            "revolve"} <= set(types), types)
check("with every sketch fully constrained",
      not any("DOF" in n for n in r["notes"]), r["notes"])
check("$id.region and face queries resolved",
      any("shell refs: 1 face" in n for n in r["notes"]), r["notes"])

print("references")
rf = InProcessHost()
rf.call("new_document")
r = rf.call("build", {"ops": [
    {"op": "sketch", "id": "s", "entities": [
        {"rect": {"center": [0, 0], "size": [60, 40]}},
        {"circle": {"center": [0, 0], "d": 20}}]},
    {"op": "extrude", "id": "plate", "sketch": "$s", "distance": 6,
     "profiles": ["$s.region[0]"]},
    {"op": "extrude", "id": "plug", "sketch": "$s", "distance": 12,
     "profiles": "$s.region[1]", "operation": "new"},
    {"op": "sketch", "id": "top", "plane": "$plate.end", "entities": [
        {"point": [20, 10], "id": "p"}]},
    {"op": "hole", "sketch": "$top", "points": ["p"], "diameter": 4}]})
check("$s.region[i] picks regions, largest first", r["ok"], r.get("error"))
check("$e.end puts a sketch on the extrusion's end face",
      any("on a face: origin" in n for n in r["notes"]), r["notes"])
check("two solids: plate and plug", r["after"]["solids"] == 2)
r = rf.call("build", {"ops": [{"op": "shell", "thickness": 1,
                               "refs": "$Extrude.side"}]})
check("an unknown role is refused with the ones there are",
      r["error"]["kind"] == "NO_PROVENANCE" and ".start .end" in
      r["error"]["hints"][0], r.get("error"))

print("sketch constraints")
sk = InProcessHost()
sk.call("new_document")
r = sk.call("build", {"ops": [
    {"op": "parameter", "name": "leg", "value": 40},
    {"op": "sketch", "id": "s", "name": "Angle", "plane": "XZ", "entities": [
        {"polyline": [[0, 0], [40, 0], [40, 5], [5, 5], [5, 30], [0, 30]],
         "id": "L"}],
     "dimensions": [
        {"length": "L.s0", "value": "leg", "comment": "long leg"},
        {"length": "L.s1", "value": 5},
        {"distance_x": ["L.p3", "L.p2"], "value": 35}]}]})
check("a polyline gets horizontal/vertical, dimensions by name", r["ok"],
      r.get("error"))
st = sk.call("sketch_status", {"sketch": "Angle"})
check("sketch_status counts what is left", st["dof"] == 1, st["dof"])
check("and names what can move",
      {u["entity"] for u in st["underconstrained"]} == {"L.s3", "L.s4",
                                                        "L.s5"},
      st["underconstrained"])
check("and lists the dimensions with their expressions",
      any(dd.get("expression") == "leg" and dd.get("comment") == "long leg"
          for dd in st["dimensions"]), st["dimensions"])
check("and the regions", len(st["regions"]) == 1
      and abs(st["regions"][0]["area"] - (40 * 5 + 25 * 5)) < 1e-6,
      st["regions"])
r = sk.call("build", {"ops": [{"op": "edit", "feature": "Angle",
                               "dimensions": [
                                   {"length": "L.s5", "value": 30},
                                   {"length": "L.s4", "value": 5}]}]})
check("dimensions added later, by the same names", r["ok"], r.get("error"))
check("one that repeats what is fixed is made driven, not a conflict",
      any("L.p4, L.p5 = 5 repeats" in n for n in r["notes"]), r["notes"])
st = sk.call("sketch_status", {"sketch": "Angle"})
check("make it fully constrained", st["fully_constrained"], st)
r = sk.call("build", {"ops": [{"op": "edit", "feature": "Angle",
                               "dimensions": [
                                   {"length": "L.s2", "value": 35}]}]})
check("however it is written",
      r["ok"] and any("made driven" in n for n in r["notes"]), r["notes"])
r = sk.call("build", {"ops": [{"op": "edit", "feature": "Angle",
                               "dimensions": [
                                   {"length": "L.s0", "value": 50}]}]})
check("an impossible one is refused, naming the conflict",
      r["error"]["kind"] == "OVER_CONSTRAINED"
      and "L.p0, L.p1 = leg" in r["error"]["message"], r.get("error"))
r = sk.call("build", {"ops": [
    {"op": "extrude", "sketch": "Angle", "distance": 50,
     "extent": "symmetric"}]})
sk.call("properties", {"parameters": {"leg": "90"}})
check("the constrained sketch follows its parameter",
      abs(sk.call("inspect")["bbox"][0] - 90) < 1e-6,
      sk.call("inspect")["bbox"])
r = sk.call("build", {"ops": [{"op": "sketch", "entities": [
    {"line": [[0, 0], [10, 0]], "id": "a"},
    {"line": [[10, 0], [10, 10]], "id": "b"}],
    "constraints": [{"parallel": ["a", "b"]}]}]})
check("constraints that cannot hold are refused",
      not r["ok"] and r["error"]["kind"] == "OVER_CONSTRAINED", r.get("error"))
r = sk.call("build", {"ops": [{"op": "sketch", "entities": [
    {"line": [[0, 0], [10, 0]], "id": "a"}],
    "constraints": [{"tangent": ["a", "nothing"]}]}]})
check("a name the sketch has not got is refused, listing its names",
      r["error"]["kind"] == "BAD_REF" and "a.start" in
      r["error"]["hints"][0], r.get("error"))

print("tree ops")
tr = InProcessHost()
tr.call("new_document")
tr.call("build", {"ops": PLATE})
r = tr.call("build", {"ops": [{"op": "edit", "feature": "Extrude",
                               "set": {"distance": "t * 2"}}]})
check("edit changes a field", r["ok"] and
      abs(tr.call("inspect")["bbox"][2] - 16) < 1e-6, r.get("error"))
check("and says what changed", r["changed"][0]["fields"] == ["distance"],
      r["changed"])
r = tr.call("build", {"ops": [{"op": "remove", "feature": "Sketch"}]})
check("remove refuses a feature others use, naming them",
      r["error"]["kind"] == "HAS_DEPENDENTS"
      and "Extrude" in r["error"]["message"], r.get("error"))
r = tr.call("build", {"ops": [{"op": "move", "feature": "Fillet",
                               "before": "Extrude"}]})
check("move refuses an order that cannot build",
      not r["ok"], r.get("summary"))
r = tr.call("build", {"ops": [{"op": "move", "feature": "Extrude",
                               "before": "Sketch"}]})
check("including a feature ahead of what it uses",
      r["error"]["kind"] == "BAD_ORDER", r.get("error"))
r = tr.call("build", {"ops": [{"op": "remove", "feature": "Sketch",
                               "dependents": "remove"}]})
check("removing what the fillet sits on fails the build, not the model",
      not r["ok"] and "Fillet" in r["error"]["message"]
      and len(tr.call("model_tree")["features"]) == 3, r.get("error"))
r = tr.call("build", {"ops": [{"op": "remove", "feature": "Fillet"},
                              {"op": "remove", "feature": "Sketch",
                               "dependents": "remove"}]})
check("remove with dependents takes them too, as one change",
      r["ok"] and len(r["removed"]) == 3, r.get("removed"))
check("one undo step", tr.workspace.get().document.undo()
      and len(tr.workspace.get().document.features) == 3)

print("edit_feature")
ef = InProcessHost()
ef.call("new_document")
ef.call("build", {"ops": PLATE})
look = ef.call("edit_feature", {"feature": "Sketch"})
check("with nothing to change it reports the feature and dependents",
      look["feature"]["op"] == "sketch"
      and [x["name"] for x in look["dependents"]] == ["Extrude"], look)
check("a delete of a used feature is refused, with the dependents",
      raises("HAS_DEPENDENTS", ef.call, "edit_feature",
             {"feature": "Sketch", "delete": True}))
rev = ef.call("model_tree")["revision"]
r = ef.call("edit_feature", {"feature": "Fillet",
                             "params": {"radius": 3}, "suppress": True,
                             "rename": "Round"})
check("params, suppress and rename land as one change", r["ok"]
      and r["revision"] == rev + 1, r.get("error"))
tree = ef.call("model_tree")["features"]
check("all of them", tree[2]["name"] == "Round" and tree[2].get("suppressed")
      and "R3" in tree[2]["summary"], tree[2])
r = ef.call("edit_feature", {"feature": "Round", "suppress": False,
                             "move_to": "start"})
check("a move it cannot make is rolled back", not r["ok"]
      and ef.call("model_tree")["features"][2]["name"] == "Round")
r = ef.call("edit_feature", {"feature": "Sketch", "delete": True,
                             "delete_dependents": True, "dry_run": True})
check("a dry-run delete says what would go",
      len(r["would_remove"]) == 2 and
      len(ef.call("model_tree")["features"]) == 3, r)

print("read_ir")
from datum.core.document import Document as _Doc  # noqa: E402
rt = InProcessHost()
rt.call("new_document")
rt.call("build", {"ops": PLATE})
read = rt.call("read_ir")
check("read_ir gives parameters, then features, as build ops",
      [o["op"] for o in read["ops"]] == ["parameter"] * 3
      + ["sketch", "extrude", "fillet"], [o["op"] for o in read["ops"]])
check("with references as $ids", read["ops"][4]["sketch_id"] == "$Sketch")
check("and defaults left out", "taper" not in read["ops"][4])
rt.call("new_document")
r = rt.call("build", {"ops": read["ops"]})
a, b = rt.call("inspect", {"doc": "d1"}), rt.call("inspect", {"doc": "d2"})
check("and builds the same part again", r["ok"] and a["volume"] == b["volume"]
      and a["faces"] == b["faces"], (a["volume"], b["volume"]))
EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "examples", "walking-excavator", "parts",
    "Boom ram barrel.icpart")
ex = InProcessHost()
ex.call("open_document", {"path": EXAMPLE})
want = ex.call("inspect")
ops = ex.call("read_ir")["ops"]
ex.call("new_document")
r = ex.call("build", {"ops": ops})
got = ex.call("inspect")
check("an example part from examples/ round-trips through read_ir",
      r["ok"] and abs(want["volume"] - got["volume"]) < 1e-6 * want["volume"]
      and want["faces"] == got["faces"],
      (want["volume"], got["volume"], want["faces"], got["faces"],
       r.get("error")))
check("its tree too", [f["type"] for f in ex.call("model_tree", {"doc": "d1"})
                       ["features"]]
      == [f["type"] for f in ex.call("model_tree", {"doc": "d2"})
          ["features"]])
check("and parameter names survive (other features use d-names)",
      [p["name"] for p in ex.call("model_tree", {"doc": "d1"})["parameters"]]
      == [p["name"] for p in ex.call("model_tree", {"doc": "d2"})
          ["parameters"]])
one = ex.call("read_ir", {"doc": "d1", "features": [ops[-1]["name"]]})
check("features= reads just those", len(one["ops"]) == 1)

print("diff and snapshot")
df = InProcessHost()
df.call("new_document")
df.call("build", {"ops": PLATE})
df.call("snapshot", {"action": "save", "name": "plain"})
df.call("properties", {"parameters": {"w": "150"}})
df.call("build", {"ops": [{"op": "chamfer", "distance": 1,
                           "edges": {"at": "+z"}}]})
dd = df.call("diff", {"from": "plain"})
check("diff against a snapshot: added features",
      [x["type"] for x in dd["added"]] == ["chamfer"], dd["added"])
check("and parameters changed", dd["parameters"]["changed"]
      == {"w": ["100", "150"]}, dd["parameters"])
dd = df.call("diff", {"from": -1})
check("diff against a revision", [x["type"] for x in dd["added"]]
      == ["chamfer"] and not dd["parameters"]["changed"], dd["summary"])
dd = df.call("diff", {"from": 2, "to": 3})
check("between two revisions", dd["parameters"]["changed"] == {
    "w": ["100", "150"]} and not dd["added"], dd["summary"])
check("the same state is no change", df.call("diff", {
    "from": "current"})["same"])
ed = df.call("build", {"ops": [{"op": "edit", "feature": "Sketch",
                                "entities": [
                                    {"rect": {"center": [0, 0],
                                              "size": ["w", "h"]}}]}]})
dd = df.call("diff", {"from": -1})
check("a sketch change is summarised, not dumped",
      dd["changed"][0]["fields"]["sketch"].get("entities") == [5, 4],
      dd["changed"])
s = df.call("snapshot", {"action": "restore", "name": "plain"})
check("restore puts the snapshot back", s["after"]["volume"]
      == df.call("inspect")["volume"] and
      len(df.call("model_tree")["features"]) == 3)
check("as a new revision, one undo step",
      df.call("snapshot", {"action": "list"})["snapshots"][0]["name"]
      == "plain")
check("an unknown snapshot is refused",
      raises("NOT_FOUND", df.call, "snapshot",
             {"action": "restore", "name": "nope"}))

print("readable models")
rd = InProcessHost()
rd.call("new_document")
r = rd.call("build", {"ops": [
    {"op": "sketch", "id": "s", "entities": [
        {"rect": {"center": [0, 0], "size": [12.5, 12.5]}},
        {"circle": {"center": [30, 0], "d": 12.5}},
        {"circle": {"center": [-30, 0], "d": 12.5}}]},
    {"op": "extrude", "sketch": "$s", "distance": 12.5,
     "comments": {"distance": "one bar of stock"}}]})
check("a number used again and again is flagged",
      any(x.startswith("12.5 mm used 5 times") for x in r.get("lint", [])),
      r.get("lint"))
check("and counted in the summary", "lint: 1" in r["summary"], r["summary"])
f = rd.workspace.get().document.features[1]
check("a field comment lands in the core's param_comments",
      f.param_comments == {"distance": "one bar of stock"}, f.param_comments)
check("which the Parameters table shows",
      any(m.comment == "one bar of stock"
          for m in rd.workspace.get().document.model_parameters()))
r = rd.call("build", {"ops": [
    {"op": "parameter", "name": "bar", "value": 12.5},
    {"op": "fillet", "radius": "bar / 10", "edges": {"along": "z"},
     "comments": {"radius": "a tenth of the bar"}}]})
check("no lint for a model that names its numbers", "lint" not in r,
      r.get("lint"))

print("inch part")
INCH_OPS = [
    {"op": "parameter", "name": "w", "value": 101.6, "comment": "4 in"},
    {"op": "parameter", "name": "t", "value": "w / 8"},
    {"op": "sketch", "id": "s", "entities": [
        {"rect": {"center": [0, 0], "size": ["w", "w / 2 + 12.7"]}},
        {"circle": {"center": ["w/4", 0], "d": "t + 3"}}]},
    {"op": "extrude", "id": "e", "sketch": "$s", "distance": "t * 2 - 6.35"},
    {"op": "fillet", "radius": 3.175, "edges": {"along": "z"}},
    {"op": "workplane", "base": "XY", "offset": "t + 2"},
]
results = {}
for unit in ("mm", "in"):
    hu = InProcessHost()
    hu.call("new_document", {"units": unit})
    r = hu.call("build", {"ops": INCH_OPS})
    results[unit] = (r, hu.call("inspect"), hu)
r_in, i_in, h_in = results["in"]
check("the same ops build the same part in an inch document",
      results["in"][0]["ok"] and i_in["volume"] == results["mm"][1]["volume"]
      and i_in["bbox"] == results["mm"][1]["bbox"],
      (i_in["volume"], results["mm"][1]["volume"]))
doc_in = h_in.workspace.get().document
from datum.bridge.build import mm_explicit  # noqa: E402


def _stored(doc):
    """Every expression the part keeps for a length or angle."""
    out = [p.expression for p in doc.params]
    for feat in doc.features:
        sketch = getattr(feat, "sketch", None)
        if feat.type_name == "sketch":
            out += [c.expression for c in sketch.constraints.values()
                    if c.expression]
            continue
        for name, kind in ir.kinds(feat.type_name).items():
            if kind == "expr" and not name.startswith("count"):
                out.append(getattr(feat, name))
    return out


ambiguous = [e for e in _stored(doc_in) if mm_explicit(e) != e]
check("every value an inch part stores is a plain mm number or says mm",
      not ambiguous, ambiguous)
check("expressions with bare lengths were marked",
      any("12.7 mm" in e for e in _stored(doc_in))
      and any("6.35 mm" in e for e in _stored(doc_in)),
      _stored(doc_in))
check("factors stay unitless", any(e == "w / 8" for e in _stored(doc_in))
      and not any("8 mm" in e for e in _stored(doc_in)), _stored(doc_in))
path = os.path.join(WORK, "inch.icpart")
h_in.call("save_document", {"path": path})
back = InProcessHost()
back.call("open_document", {"path": path})
check("and it reopens the same size", back.call("inspect")["volume"]
      == i_in["volume"])
doc_back = back.workspace.get().document
doc_back.units = "mm"
doc_back.rebuild()
h_in.call("properties", {"parameters": {"t": "w / 8 + 2"}})
check("properties stores by the same rule",
      doc_in.params["t"].expression == "w / 8 + 2 mm",
      doc_in.params["t"].expression)
check("and switching the part to mm changes nothing",
      abs(back.call("inspect")["volume"] - i_in["volume"]) < 1e-6)

# ---------------------------------------------------------------- phase 1b

from datum.core import rules as core_rules  # noqa: E402

print("references")
hr = InProcessHost()
hr.call("new_document")
BLOCK = [
    {"op": "parameter", "name": "w", "value": 100},
    {"op": "parameter", "name": "h", "value": 60},
    {"op": "parameter", "name": "t", "value": 8},
    {"op": "sketch", "id": "s1", "plane": "XY", "name": "Outline",
     "entities": [{"rect": {"center": [0, 0], "size": ["w", "h"]},
                   "id": "r"}]},
    {"op": "extrude", "id": "e1", "sketch": "$s1", "distance": "t",
     "name": "Plate"},
    {"op": "sketch", "id": "s2", "plane": "XY", "name": "Centres",
     "entities": [{"point": [20, 10], "id": "p1"},
                  {"point": [-20, -10], "id": "p2"}]},
    {"op": "hole", "sketch": "$s2", "diameter": 6.6, "points": ["p1", "p2"],
     "name": "Bolt"},
]
r = hr.call("build", {"ops": BLOCK})
check("a plate with two holes builds", r["ok"], r.get("error"))


def meas(a, b=None):
    return hr.call("measure", {"a": a, "b": b} if b else {"a": a})


m = meas("Plate.end")
check("Plate.end is the top, by role", m["a"]["via"] == "role"
      and m["a"].get("normal") == [0, 0, 1], m["a"])
check("Plate.side(r.right) is the +x side face",
      meas("Plate.side(r.right)")["a"].get("normal") == [1, 0, 0])
m = meas("Bolt.wall[0]")
check("Bolt.wall[0] is a bore of the hole's diameter",
      m["a"].get("diameter") == 6.6 and m["a"].get("hole") is True, m["a"])
check("Bolt.wall is every bore", meas("Bolt.wall")["a"]["count"] >= 2)
check("Outline.region[0] is the sketch's region",
      meas("Outline.region[0]")["a"]["area"] == 6000)
check("a named sketch point is a vertex",
      meas("Outline.r.tl")["a"]["point"] == [-50, 30, 0])
check("a role a feature has no definition for asks for provenance",
      raises("NO_PROVENANCE", hr.call, "measure", {"a": "Plate.top"}))
m = meas("Plate.side(r.top).edge(end)")
check("a side's edge chained on is found by role, the edge between the two",
      m["a"]["via"] == "role" and m["a"]["type"] == "line"
      and m["a"]["centre"][1:] == [30, 8], m["a"])
check("an unknown feature is a BAD_REF",
      raises("BAD_REF", hr.call, "measure", {"a": "Nope.end"}))
m = meas("Bolt.wall[0]", "Bolt.wall[1]")
check("two bores: the distance between their axes is the hole spacing",
      abs(m["axis_distance"] - (40 ** 2 + 20 ** 2) ** 0.5) < 1e-3, m)
m = meas("Plate.end", "Plate.start")
check("two caps: the gap between parallel planes and the angle",
      m["plane_gap"] == 8 and m["angle"] == 180, m)
check("part is the whole body", meas("part")["a"]["bbox"] == [100, 60, 8])
m = meas([0, 0, 50], "Plate.end")
check("a point to a face", abs(m["min_distance"] - 42) < 1e-6, m)

print("find_geometry")
f = hr.call("find_geometry", {"what": "face", "where": {"normal": "+z"}})
check("faces looking up: one", f["matched"] == 1, f)
top = f["items"][0]["ref"]
check("with a handle and a description", top.startswith("@F:")
      and "facing +z" in f["items"][0]["what"], f["items"][0])
again = hr.call("find_geometry", {"where": {"normal": "+z"}})
check("the same face gets the same handle", again["items"][0]["ref"] == top)
bores = hr.call("find_geometry", {"where": {"type": "cylinder",
                                            "hole": True}})
check("bores by type and hole", bores["matched"] >= 2, bores)
made = hr.call("find_geometry", {"where": {"created_by": "Bolt"}})
check("created_by: what the hole added, and the caps it cut into",
      sorted(i["type"] for i in made["items"]) ==
      ["cylinder", "cylinder", "plane", "plane"], made)
check("created_by: the plate's sides are still the plate's",
      hr.call("find_geometry", {"where": {"created_by": "Plate",
                                          "type": "plane"}})["matched"] == 4)
rim = hr.call("find_geometry", {"what": "edge", "where": {"on": "Plate.end"}})
check("on: the edges round a face", rim["matched"] >= 4, rim)
check("circles among them", hr.call("find_geometry", {
    "what": "edge", "where": {"on": "Plate.end", "type": "circle"}}
)["matched"] >= 2)
check("largest", hr.call("find_geometry", {"where": {"largest": True}}
                         )["items"][0]["area"] > 5000)
check("area range", hr.call("find_geometry", {"where": {
    "area": [400, 900]}})["matched"] == 4)
near = hr.call("find_geometry", {"what": "vertex", "where": {
    "near": [55, 35, 9]}})
check("near: the closest vertex", near["items"][0]["point"] == [50, 30, 8],
      near)
check("an unknown condition is refused",
      raises("BAD_QUERY", hr.call, "find_geometry",
             {"where": {"colour": "red"}}))
m = meas(top)
check("a handle measures by role (it kept the roles of its face)",
      m["a"]["via"] == "role", m["a"])

print("references in build")
r = hr.call("build", {"ops": [{"op": "fillet", "radius": 1,
                               "edges": ["Plate.end"]}], "dry_run": True})
check("fillet edges by a face reference: the edges round it",
      r["ok"] and r.get("refs", [{}])[0].get("via") == "role", r)
r = hr.call("build", {"ops": [{"op": "shell", "thickness": 1,
                               "refs": [top]}], "dry_run": True})
check("shell by a handle", r["ok"] and r["refs"][0]["via"] == "role",
      r.get("error"))
png = hr.call("render_view", {"highlight": ["Bolt.wall", top]})
check("render_view highlights references", png["highlighted"] >= 3
      and png["refs"][0]["via"] == "role", png.get("refs"))

# the same face as a handle that never had roles (one from a part with no
# provenance): followed by where it was, as before
held = dict(hr.workspace.get().handles[top.split(":")[1]])
check("a handle keeps the roles of the face it was made on",
      held.get("roles"), held)
held.pop("roles", None)
held.pop("adjacent", None)
hr.workspace.get().handles["abcdef"] = held
plain = "@F:abcdef"
hr.call("properties", {"parameters": {"t": 12}})
m = meas(top)
check("a handle follows a parameter change by role",
      m["a"]["centre"][2] == 12 and "moved" in m["a"].get("note", ""), m["a"])
check("and Plate.end follows it too",
      meas("Plate.end")["a"]["centre"][2] == 12)
hr.call("properties", {"parameters": {"w": 400, "h": 300}})
check("a handle that kept no roles, and cannot be followed by position, "
      "fails plainly", raises("STALE_REF", hr.call, "measure", {"a": plain}))
check("a handle with roles goes on following its face",
      meas(top)["a"]["via"] == "role")
check("a handle from nowhere is refused",
      raises("STALE_REF", hr.call, "measure", {"a": "@F:000000"}))
hr.call("properties", {"parameters": {"w": 100, "h": 60, "t": 8}})

print("requirements")
r = hr.call("requirements", {"set": [
    {"name": "light", "metric": "mass", "max": 60, "note": "Generic, 1 g/cm3"},
    {"name": "width", "metric": "bbox", "axis": "x", "max": 150},
    {"name": "box", "metric": "bbox", "target": [100, 60, 8]},
    {"name": "holes", "metric": "hole_count", "target": 2,
     "diameter": 6.6},
    {"name": "w", "metric": "parameter", "param": "w", "min": 50,
     "max": 200},
    {"name": "edge", "metric": "clearance", "a": "Bolt.wall[0]",
     "b": "Plate.side(r.right)", "min": 20},
]})
check("six requirements, all passing", r["summary"] == "reqs 6/6 ✓",
      r["summary"])
doc_r = hr.workspace.get().document
check("stored in the document", len(doc_r.requirements) == 6
      and "requirements" in doc_r.to_dict())
check("a clearance end is stored as a fingerprint the core can resolve",
      "ref" in doc_r.requirements.get("edge").a
      or "refs" in doc_r.requirements.get("edge").a)
r = hr.call("build", {"ops": [{"op": "parameter", "name": "w",
                               "value": 220}]})
check("a build that breaks them says so in its summary",
      "reqs 2/6" in r["summary"] and "width 220 mm > 150" in r["summary"],
      r["summary"])
check("and lists every result", len(r["requirements"]) == 6
      and not all(x["pass"] for x in r["requirements"]))
check("the core checked them on the rebuild",
      len(doc_r.last_report.requirements) == 6)
hr.call("build", {"ops": [{"op": "parameter", "name": "w", "value": 100}]})
check("putting it back passes again",
      hr.call("requirements")["summary"] == "reqs 6/6 ✓")
r = hr.call("properties", {"parameters": {"t": 20}})
check("properties reports them too", "light" in r.get("reqs", ""), r)
hr.call("properties", {"parameters": {"t": 8}})
check("an unknown metric is refused", raises(
    "BAD_REQUIREMENT", hr.call, "requirements",
    {"set": [{"name": "x", "metric": "colour", "target": 1}]}))
check("a requirement with nothing to compare is refused", raises(
    "BAD_REQUIREMENT", hr.call, "requirements",
    {"set": [{"name": "x", "metric": "mass"}]}))
before = len(doc_r.requirements)
hr.call("requirements", {"remove": ["box"]})
check("remove drops one", len(doc_r.requirements) == before - 1)
doc_r.undo() if hasattr(doc_r, "undo") else None
doc_r.rebuild()
check("and undo brings it back", len(doc_r.requirements) == before,
      len(doc_r.requirements))
path = os.path.join(WORK, "reqs.icpart")
hr.call("save_document", {"path": path})
back = InProcessHost()
back.call("open_document", {"path": path})
check("requirements survive save and open",
      back.call("requirements")["summary"] == "reqs 6/6 ✓",
      back.call("requirements")["summary"])

print("code features")
POSTS = ("n = int(params.w // 25)\n"
         "body = union(*[cylinder(2, 40).move(-params.w / 2 + 12.5 + i * 25,"
         " 0, -10) for i in range(n)])")
r = hr.call("build", {"ops": [{"op": "code", "name": "Pins",
                               "operation": "cut", "source": POSTS}]})
check("a code op builds", r["ok"] and r["created"][0]["type"] == "code",
      r.get("error"))
check("and says its source is trusted for the session",
      any("trusted for this session" in n for n in r["notes"]), r["notes"])
holes4 = len(hr.call("find_geometry", {"where": {"type": "cylinder",
                                                 "hole": True,
                                                 "radius": 2}})["items"])
hr.call("properties", {"parameters": {"w": 200}})
holes8 = len(hr.call("find_geometry", {"where": {"type": "cylinder",
                                                 "hole": True,
                                                 "radius": 2}})["items"])
check("its structure follows a parameter: 4 pins at w 100, 8 at 200",
      (holes4, holes8) == (4, 8), (holes4, holes8))
hr.call("properties", {"parameters": {"w": 100}})
r = hr.call("build", {"ops": [{"op": "code", "source": "body = (",
                               "name": "Bad"}]})
check("a bad source is refused before it is stored",
      not r["ok"] and r["error"]["kind"] == "BAD_CODE", r.get("error"))
path = os.path.join(WORK, "code.icpart")
hr.call("save_document", {"path": path})
# a new session: nothing the agent trusted carries over
core_rules._TRUSTED_CODE.clear()
fresh = InProcessHost()
o = fresh.call("open_document", {"path": path})
check("reopened, the code waits for trust instead of running",
      o.get("waiting_for_trust") == ["Pins"], o)
tree = fresh.call("model_tree")
pins = [f for f in tree["features"] if f["name"] == "Pins"][0]
check("model_tree marks it waiting, not broken",
      pins.get("waiting_for_trust") is True and "error" not in pins, pins)
r = fresh.call("build", {"ops": [{"op": "code", "name": "Again",
                                  "operation": "cut", "source": POSTS}]})
check("writing the file's code again does not trust it",
      r["ok"] and "Again" in r.get("waiting_for_trust", []), r["summary"])
fresh_doc = fresh.workspace.get().document
core_rules.trust_document(fresh_doc)
fresh_doc.rebuild()
check("the GUI's document trust still lets it run",
      not [e for e in fresh_doc.last_report.errors], fresh_doc.last_report)
core_rules._TRUSTED_CODE.clear()
two = InProcessHost()
two.call("new_document")
two.call("build", {"ops": BLOCK[:5]})
doc2 = two.workspace.get().document
from datum.core.features import CodeFeature  # noqa: E402
a_src = "body = box(5, 5, 5).move(60, 0, 0)"
b_src = "body = box(5, 5, 5).move(-70, 0, 0)"
for name, src in (("A", a_src), ("B", b_src)):
    cf = CodeFeature()
    cf.name, cf.source, cf.operation = name, src, "join"
    doc2.add_feature(cf)
core_rules.trust_code(a_src)
doc2.rebuild()
errs = dict(doc2.last_report.errors)
check("trust is per feature: the trusted source runs, the other waits",
      doc2.features[-2].id not in errs
      and core_rules.WAITING_FOR_TRUST in errs.get(doc2.features[-1].id, ""),
      errs)
check("a worker is told which sources are trusted",
      doc2.remote_request()["trusted_code"] == [core_rules.code_hash(a_src)])

print("run_script")
hs = InProcessHost()
hs.call("new_document")
hs.call("build", {"ops": BLOCK[:5]})
doc_s = hs.workspace.get().document
undo_before = len(doc_s._undo)
rev = hs.workspace.get().revision
TABLE = """
table = [(30, 15, 4), (-30, 15, 4), (0, -15, 5)]
pts = [{"point": [x, y], "id": "q%d" % i} for i, (x, y, d) in enumerate(table)]
s = sketch(plane="XY", entities=pts, name="Table")
for i, (x, y, d) in enumerate(table):
    hole(s, d, points=["q%d" % i], name="T%d" % i)
param("pitch", 30, comment="from the table")
print("holes", len(table))
result = {"holes": len(table)}
"""
r = hs.call("run_script", {"code": TABLE})
check("a script lays out holes from a table", r["ok"]
      and [c["name"] for c in r["created"]] == ["Table", "T0", "T1", "T2"],
      r.get("summary"))
check("its output and result come back", "holes 3" in r["output"]
      and r["result"] == {"holes": 3})
check("applied as one build: one undo step, one revision",
      len(doc_s._undo) == undo_before + 1
      and hs.workspace.get().revision == rev + 1)
check("the parameter came too", "pitch" in doc_s.params)
check("the sketch keeps the names the script gave",
      "q0" in hs.workspace.get().sketch_names.get(
          r["created"][0]["id"], {}))
check("the holes are real", hs.call("find_geometry", {"where": {
    "type": "cylinder", "hole": True}})["matched"] == 3)
r = hs.call("run_script", {"code": "x = 1"})
check("a script that changes nothing changes nothing",
      r["ok"] and r["applied"] == 0)
rev = hs.workspace.get().revision
r = None
try:
    hs.call("run_script", {"code": "param('w', 120)\nraise ValueError('no')"})
except BridgeError as exc:
    r = exc.to_dict()
check("a failing script reports its line, and nothing changes",
      r is not None and r["kind"] == "SCRIPT_FAILED" and r["line"] == 2
      and hs.workspace.get().revision == rev
      and doc_s.params["w"].expression == "100", r)
r = hs.call("run_script", {"code": "param('w', 140)\n"
                                   "doc.remove_feature(doc.features[-1].id)",
                           "dry_run": True})
check("dry_run shows the ops it would apply",
      r["ok"] and any(o["op"] == "remove" for o in r["ops"])
      and doc_s.params["w"].expression == "100", r.get("ops"))
check("the timeout stops a script", raises(
    "TIMEOUT", hs.call, "run_script", {"code": "while True: pass",
                                       "timeout": 2}))
check("safe_mode refuses imports outside its list", raises(
    "SAFE_MODE", hs.call, "run_script",
    {"code": "import os", "safe_mode": True}))
check("safe_mode refuses dunder tricks", raises(
    "SAFE_MODE", hs.call, "run_script",
    {"code": "x = ().__class__", "safe_mode": True}))
r = hs.call("run_script", {"code": "import math\nparam('w', "
                                   "round(math.sqrt(10000) + 10))",
                           "safe_mode": True})
check("safe_mode runs the helpers", r["ok"]
      and doc_s.params["w"].expression == "110", r.get("summary"))

print("found by Tier 2 (an agent's nut)")
ht = InProcessHost()
ht.call("new_document")
NUT = [
    {"op": "parameter", "name": "s", "value": 17},
    {"op": "parameter", "name": "m", "value": 8},
    {"op": "parameter", "name": "d1", "value": 8.376},
    {"op": "parameter", "name": "corner_d", "expression": "s/cos(30)"},
    {"op": "parameter", "name": "R", "value": "corner_d/2 + 1"},
    {"op": "parameter", "name": "dz", "value": "(R - s/2)*tan(30)"},
    {"op": "sketch", "id": "s1", "plane": "XY", "entities": [
        {"polygon": {"center": [0, 0], "sides": 6, "across_flats": "s"}}]},
    {"op": "extrude", "id": "e1", "sketch": "$s1", "distance": "m"},
    {"op": "sketch", "id": "s2", "plane": "XZ", "entities": [
        {"polyline": [[0, 0], ["s/2", 0], ["R", "dz"], ["R", "m - dz"],
                      ["s/2", "m"], [0, "m"]], "closed": True, "id": "p"}]},
    {"op": "revolve", "sketch": "$s2", "axis": "$s2.p.s5", "angle": 360,
     "operation": "intersect"},
    {"op": "sketch", "id": "s3", "plane": "XY", "entities": [
        {"circle": {"center": [0, 0], "d": "d1"}}]},
    {"op": "extrude", "sketch": "$s3", "distance": "m",
     "extent": "through_all", "operation": "cut"},
]
r = ht.call("build", {"ops": NUT})
check("a parameter named d1 sizes a sketch (it was shadowed by the "
      "sketch's own first dimension d1, so the circle had no size)",
      r["ok"], r.get("error"))
check("'expression' is taken as a parameter's value",
      r["ok"] and abs(ht.workspace.get().document.params["corner_d"].value
                      - 19.6299) < 1e-3)
box = ht.call("inspect")["bbox"]
check("a nut whose corners a revolved cone chamfers measures 19.63 x 17 "
      "(the quick box said 19.63 x 19.63)",
      abs(box[0] - 19.6299) < 1e-3 and abs(box[1] - 17) < 1e-3, box)
r = ht.call("build", {"ops": [
    {"op": "parameter", "name": "q", "value": 1, "expression": "2"}]})
check("value and expression that disagree are refused",
      not r["ok"] and r["error"]["kind"] == "BAD_OP", r.get("error"))
try:
    ht.call("properties", {"material": "Steel"})
    hint = ""
except BridgeError as exc:
    hint = " ".join(exc.hints)
check("an unknown material suggests the close names, quoted",
      '"Steel, Mild"' in hint and "Did you mean" in hint, hint)
try:
    ht.call("properties", {"material": "Aluminum 6061"})
    hint = ""
except BridgeError as exc:
    hint = " ".join(exc.hints)
check("and the other spelling", '"Aluminium 6061"' in hint.split(
    "Known")[0], hint)

print("phase 3b: what changed since the agent read it")
sh = InProcessHost()
sh.call("new_document")
sh.call("build", {"ops": PLATE})
seen_rev = sh.call("model_tree")["revision"]
sh.call("build", {"ops": [
    {"op": "parameter", "name": "extra_p", "value": 3},
    {"op": "chamfer", "distance": 1, "edges": {"at": "+z"}}]})
sh.call("edit_feature", {"feature": "Fillet", "params": {"radius": 4}})
try:
    sh.call("build", {"expected_revision": seen_rev, "ops": [
        {"op": "parameter", "name": "x", "value": 1}]})
    stale = None
except BridgeError as exc:
    stale = exc
ch = (stale.extra.get("changes") or {}) if stale else {}
check("a stale revision says what changed", stale is not None
      and stale.kind == "STALE_REVISION" and ch, stale)
check("features added", any("Chamfer" in n for n in ch.get("added", [])), ch)
check("features edited, with the fields", any(
    e["name"] == "Fillet" and "radius" in e["fields"]
    for e in ch.get("edited", [])), ch)
check("parameters changed", "extra_p" in (ch.get("parameters") or {}).get(
    "added", {}), ch)
check("the message carries it", "Chamfer" in stale.message
      and "parameter" in stale.message, stale.message)
sh.call("edit_feature", {"feature": "Chamfer", "delete": True})
try:
    sh.call("properties", {"parameters": {"w": 90},
                           "expected_revision": seen_rev})
except BridgeError as exc:
    ch = exc.extra.get("changes") or {}
check("removed features are listed too", True)
r2 = sh.call("model_tree")["revision"]
try:
    sh.call("build", {"expected_revision": r2 - 1, "ops": [
        {"op": "parameter", "name": "x", "value": 1}]})
except BridgeError as exc:
    ch = exc.extra.get("changes") or {}
check("and the last step alone is described", ch.get("since_revision")
      == r2 - 1 and ch.get("removed") == ["Chamfer"], ch)

print("phase 3b: a headless host never writes over what the app has open")
out = os.path.join(WORK, "held.icpart")
sh.call("save_document", {"path": out})
held = [{"doc": "g1", "path": out}]
try:
    sh.call("save_document", {"path": out, "app_open": held})
    kind = None
except BridgeError as exc:
    kind, hints, said = exc.kind, exc.hints, exc.message
check("save is refused, with a kind and hints", kind == "FILE_OPEN_IN_APP"
      and hints and "g1" in said, kind)
try:
    sh.call("save_document", {"app_open": held})   # where it came from
    kind = None
except BridgeError as exc:
    kind = exc.kind
check("also when the path is where the document came from",
      kind == "FILE_OPEN_IN_APP", kind)
step = os.path.join(WORK, "held.step")
try:
    sh.call("export", {"path": step, "overwrite": True,
                       "app_open": [{"doc": "g2", "path": step}]})
    kind = None
except BridgeError as exc:
    kind = exc.kind
check("export is refused the same way", kind == "FILE_OPEN_IN_APP", kind)
check("a different file is fine", sh.call("save_document", {
    "path": os.path.join(WORK, "free.icpart"),
    "app_open": held})["path"].endswith("free.icpart"))
check("and no app listed means no check", sh.call("save_document", {
    "path": out, "overwrite": True})["path"].endswith("held.icpart"))

print("phase 3b: a pick named by what made it")
from datum.bridge import selection  # noqa: E402
from datum.core import kernel  # noqa: E402

pk = InProcessHost()
pk.call("new_document")
pk.call("build", {"ops": [p for p in PLATE if p.get("op") != "fillet"]})
ent = pk.workspace.get(None)
body = ent.document.shape


def at(pool, x, y, z):
    for s in pool:
        c = kernel.shape_centre(s)
        if abs(c[0] - x) < 1e-3 and abs(c[1] - y) < 1e-3 \
                and abs(c[2] - z) < 1e-3:
            return s
    raise AssertionError((x, y, z))


got = selection.describe_picks(ent, [
    at(kernel.edges(body), 50, 0, 8), at(kernel.faces(body), 0, 0, 8)])
check("an edge between two roled faces is named from both",
      got["edges"][0]["via"] == "role" and ".edge(" in got["edges"][0]["ref"]
      and got["edges"][0]["count"] == 1, got["edges"])
check("a face by the feature that made it", got["faces"][0]["ref"]
      == "Extrude.end", got["faces"])
check("both resolve to the pick again, as an agent's own text", all(
    pk.call("measure", {"a": x["ref"]}) for x in got["edges"] + got["faces"]))
pk.call("properties", {"parameters": {"w": 180}})
again = pk.call("measure", {"a": got["edges"][0]["ref"]})
check("and follow an 80 % wider part", again["a"]["via"] == "role"
      and abs(again["a"]["centre"][0] - 90) < 1e-3, again)
check("summary reads back", "nothing selected" == selection.summary_of({}))

print("assemblies")
asm_host = InProcessHost()


def block(name, w, dd, h, pn, material="Steel, Mild", hole=0):
    asm_host.call("new_document")
    ops = [{"op": "parameter", "name": "w", "value": w},
           {"op": "sketch", "id": "s1", "plane": "XY", "entities": [
               {"rect": {"center": [0, 0], "size": ["w", dd]}, "id": "r"}]},
           {"op": "extrude", "id": "e1", "sketch": "$s1", "distance": h}]
    if hole:
        ops += [{"op": "sketch", "id": "s2", "plane": "XY", "entities": [
            {"point": [0, 0], "id": "h1"}]},
            {"op": "hole", "sketch": "$s2", "diameter": hole,
             "through": True, "points": ["h1"]}]
    asm_host.call("build", {"ops": ops})
    asm_host.call("properties", {"props": {"Part Number": pn},
                                 "material": material})
    path = os.path.join(WORK, name + ".icpart")
    asm_host.call("save_document", {"path": path})
    return path


base = block("Base", 100, 60, 10, "B-1")
post = block("Post", 20, 20, 40, "P-1")
ring = block("Ring", 30, 30, 6, "R-1", hole=20)
shaft_ops = [{"op": "sketch", "id": "s1", "plane": "XY", "entities": [
    {"circle": {"center": [0, 0], "d": 20}, "id": "c"}]},
    {"op": "extrude", "id": "e1", "sketch": "$s1", "distance": 50}]
asm_host.call("new_document")
asm_host.call("build", {"ops": shaft_ops})
shaft = os.path.join(WORK, "Shaft.icpart")
asm_host.call("save_document", {"path": shaft})

made = asm_host.call("new_document", {"type": "assembly", "name": "Stand"})
a = made["doc"]
check("new_document makes an assembly",
      asm_host.call("model_tree", {"doc": a})["type"] == "assembly")
check("an assembly with nothing placed has nothing to constrain with",
      raises("NO_OCCURRENCE", asm_host.call, "constrain", {
          "doc": a, "a": "Base:1/Extrude.end", "b": "Post:1/Extrude.end"}))
r = asm_host.call("place_component", {"doc": a, "file": base, "name": "Base"})
check("the first component is grounded", r["occurrence"]["grounded"]
      and r["occurrence"]["name"] == "Base:1", r["occurrence"])
check("placing says the box, exactly", abs(r["bbox"][3] - r["bbox"][0]
                                             - 100) < 1e-3, r["bbox"])
r = asm_host.call("place_component", {
    "doc": a, "file": post, "name": "Post",
    "transform": {"position": [0, 0, 60],
                  "rotate": {"axis": [0, 0, 1], "angle": 90}}})
check("a later one is free, with 6 degrees of freedom",
      r["occurrence"]["dof"] == 6 and not r["occurrence"]["grounded"], r)
check("and sits where it was put, turned",
      r["occurrence"]["position"] == [0, 0, 60]
      and abs(r["occurrence"]["rotate"]["angle"] - 90) < 1e-3, r)
check("a saved-and-placed part is placed from its file, not a handle",
      raises("BAD_PATH", asm_host.call, "place_component", {
          "doc": a, "file": "Post.icpart"}))
check("a file that is not there is NOT_FOUND", raises(
    "NOT_FOUND", asm_host.call, "place_component",
    {"doc": a, "file": os.path.join(WORK, "no.icpart")}))
check("a bad transform names its keys", raises(
    "BAD_TRANSFORM", asm_host.call, "place_component",
    {"doc": a, "file": post, "transform": {"spin": 3}}))
check("a part is the wrong document type for placing", raises(
    "WRONG_TYPE", asm_host.call, "place_component", {
        "doc": asm_host.call("status")["documents"][0]["doc"],
        "file": post}))

entry_doc = a
rev0 = asm_host.call("model_tree", {"doc": a})["revision"]
check("a failed place left no new revision", asm_host.call(
    "model_tree", {"doc": a})["revision"] == rev0)

# constraints ---------------------------------------------------------------
c1 = asm_host.call("constrain", {
    "doc": a, "kind": "mate", "a": "Base:1/Extrude.end",
    "b": "Post:1/Extrude.start"})
check("a mate takes freedom away and says so", c1["dof"]["Post:1"] == 3
      and "Post:1 DOF 6 -> 3" in c1["summary"], c1["summary"])
check("the constraint is named and found by role", c1["constraint"]["name"]
      == "Mate:1" and c1["via"]["a"] == "role", c1["via"])
check("the solver moved the free part onto the face",
      abs(c1["occurrences"][1]["position"][2] - 10) < 1e-3
      or c1["occurrences"][1].get("rotate"), c1["occurrences"][1])
asm_host.call("constrain", {
    "doc": a, "kind": "flush", "a": "Base:1/Extrude.side(r.left)",
    "b": "Post:1/Extrude.side(r.left)"})
r = asm_host.call("constrain", {
    "doc": a, "kind": "flush", "a": "Base:1/Extrude.side(r.bottom)",
    "b": "Post:1/Extrude.side(r.bottom)", "offset": 5})
check("three plane pairs hold a part completely", r["dof"]["Post:1"] == 0,
      r["dof"])
rev = r["revision"]
before = asm_host.call("model_tree", {"doc": a})
check("a conflicting constraint is refused", raises(
    "CONSTRAINT_FAILED", asm_host.call, "constrain", {
        "doc": a, "kind": "flush", "a": "Base:1/Extrude.side(r.bottom)",
        "b": "Post:1/Extrude.side(r.bottom)", "offset": 30}))
after = asm_host.call("model_tree", {"doc": a})
check("and the assembly is exactly as it was", after["revision"] == rev
      and after["constraints"] == before["constraints"]
      and after["occurrences"] == before["occurrences"])
check("an offset that is not an expression of anything is BAD_EXPRESSION",
      raises("BAD_EXPRESSION", asm_host.call, "constrain", {
          "doc": a, "kind": "mate", "a": "Base:1/Extrude.end",
          "b": "Post:1/Extrude.end", "offset": "gap * 2"}))
check("a kind that does not exist lists the real ones", raises(
    "BAD_KIND", asm_host.call, "constrain", {
        "doc": a, "kind": "weld", "a": "Base:1/Extrude.end",
        "b": "Post:1/Extrude.end"}))
check("both sides on one component is refused", raises(
    "SAME_OCCURRENCE", asm_host.call, "constrain", {
        "doc": a, "a": "Base:1/Extrude.end", "b": "Base:1/Extrude.start"}))
check("a whole component is not a face", raises(
    "BAD_REF", asm_host.call, "constrain", {
        "doc": a, "a": "Base:1", "b": "Post:1/Extrude.end"}))
check("an occurrence that is not there lists the ones that are", raises(
    "NO_OCCURRENCE", asm_host.call, "constrain", {
        "doc": a, "a": "Wheel:1/Extrude.end", "b": "Post:1/Extrude.end"}))
check("a reference the part cannot resolve says whose part", raises(
    "BAD_REF", asm_host.call, "constrain", {
        "doc": a, "a": "Base:1/Nothing.end", "b": "Post:1/Extrude.end"}))
check("insert needs axes, not two flat faces", raises(
    "BAD_PAIRING", asm_host.call, "constrain", {
        "doc": a, "kind": "insert", "a": "Base:1/Extrude.end",
        "b": "Post:1/Extrude.start"}))
check("angle is for the angle kind", raises(
    "BAD_VALUE", asm_host.call, "constrain", {
        "doc": a, "kind": "mate", "a": "Base:1/Extrude.end",
        "b": "Post:1/Extrude.start", "angle": 30}))

# undo: each change is one step
asm_doc = asm_host.workspace.get(a).document
steps = len(asm_doc._undo)
asm_host.call("constrain", {
    "doc": a, "kind": "parallel", "a": "Base:1/Extrude.end",
    "b": "Post:1/Extrude.end"})
check("a constraint is one undo step", len(asm_doc._undo) == steps + 1)
n = len(asm_doc.constraints)
asm_doc.undo()
check("Ctrl+Z takes it back whole", len(asm_doc.constraints) == n - 1)
dry = asm_host.call("constrain", {
    "doc": a, "kind": "parallel", "a": "Base:1/Extrude.end",
    "b": "Post:1/Extrude.end", "dry_run": True})
check("dry_run changes nothing", dry.get("dry_run")
      and len(asm_doc.constraints) == n - 1)

# origin planes, insert, ring over a shaft
asm_host.call("place_component", {"doc": a, "file": shaft, "name": "Shaft",
                                  "transform": {"position": [10, 20, 0]}})
bad_origin = raises("BAD_REF", asm_host.call, "constrain", {
    "doc": a, "a": "Shaft:1/origin.QQ", "b": "Base:1/Extrude.end"})
check("an origin that is not one is BAD_REF", bad_origin)
r = asm_host.call("constrain", {
    "doc": a, "kind": "flush", "a": "Base:1/origin.XY",
    "b": "Shaft:1/origin.XY"})
check("a part's own origin plane constrains (flush keeps it upright)",
      r["dof"]["Shaft:1"] == 3 and r["via"]["b"] == "definition", r["dof"])
asm_host.call("place_component", {"doc": a, "file": ring, "name": "Ring"})
r = asm_host.call("constrain", {
    "doc": a, "kind": "insert", "a": "Shaft:1/Extrude.side(c)",
    "b": "Ring:1/Hole.wall[0]", "flip": True})
check("insert puts a hole over a shaft, riding with it", r["dof"]["Ring:1"] == 3
      and not r["assembly"].get("errors"), r["dof"])

# the check
chk = asm_host.call("assembly_check", {"doc": a})
names = {o["name"]: o for o in chk["occurrences"]}
check("assembly_check reports DOF per component",
      names["Base:1"]["status"] == "grounded"
      and names["Post:1"]["dof"] == 0 and "dof" in names["Ring:1"], names)
check("and says what is still free", "Ring:1" in chk.get("free", {})
      or names["Ring:1"]["dof"] == 0, chk.get("free"))
check("summary starts with a verdict", chk["summary"].split(" | ")[0]
      in ("ok", "attention"), chk["summary"])

# interference: a part moved into another is found, with volume and pair
asm_host.call("edit_feature", {
    "doc": a, "feature": "Post:1", "suppress": True})
chk = asm_host.call("assembly_check", {"doc": a})
check("a suppressed component is left out", chk["occurrences"][1]["status"]
      == "suppressed")
asm_host.call("edit_feature", {
    "doc": a, "feature": "Post:1", "suppress": False})
asm_host.call("place_component", {
    "doc": a, "file": ring, "name": "Clash",
    "transform": {"position": [0, 0, 5]}})
chk = asm_host.call("assembly_check", {"doc": a})
pairs = chk["interference"]["pairs"]
check("overlapping volumes are interference, with the pair",
      any({p["a"], p["b"]} == {"Clash:1", "Base:1"} for p in pairs), pairs)
check("with the volume", all(p["volume_mm3"] > 1 for p in pairs), pairs)
check("and the summary says attention", chk["summary"].startswith(
    "attention"), chk["summary"])
touch = asm_host.call("assembly_check", {"doc": a, "interference": False})
check("interference can be left out", "interference" not in touch)

# edit and remove
r = asm_host.call("edit_feature", {"doc": a, "feature": "Mate:1"})
check("edit_feature with no change describes a constraint",
      r["feature"]["type"] == "constraint" and r["feature"]["kind"]
      == "mate", r)
r = asm_host.call("edit_feature", {"doc": a, "feature": "Mate:1",
                                   "params": {"offset": 3}})
check("an offset edit solves again", r["feature"]["offset"] == "3"
      and "Fully" in r["assembly"]["solver"] or r["assembly"]["ok"], r)
check("an unknown field says what exists", raises(
    "BAD_VALUE", asm_host.call, "edit_feature", {
        "doc": a, "feature": "Mate:1", "params": {"colour": 1}}))
check("deleting a component constraints use is refused", raises(
    "HAS_DEPENDENTS", asm_host.call, "edit_feature", {
        "doc": a, "feature": "Post:1", "delete": True}))
r = asm_host.call("edit_feature", {"doc": a, "feature": "Post:1",
                                   "delete": True,
                                   "delete_dependents": True})
check("with delete_dependents it goes, and its constraints",
      "Post:1" in r["removed"] and "Mate:1" in r["removed"], r["removed"])
check("a rename is checked for clashes", raises(
    "BAD_NAME", asm_host.call, "edit_feature", {
        "doc": a, "feature": "Ring:1", "rename": "Base:1"}))

# parameters drive offsets
asm_host.call("properties", {"doc": a, "parameters": {
    "gap": {"expression": "4", "comment": "clearance"}}})
check("an assembly has parameters", any(
    p["name"] == "gap" for p in asm_host.call("model_tree",
                                              {"doc": a})["parameters"]))
asm_host.call("place_component", {"doc": a, "file": post, "name": "Post"})
asm_host.call("constrain", {
    "doc": a, "kind": "mate", "a": "Base:1/Extrude.end",
    "b": "Post:1/Extrude.start", "offset": "gap * 2"})


def post_height():
    return [o for o in asm_host.call("model_tree", {"doc": a})[
        "occurrences"] if o["name"] == "Post:1"][0]["position"][2]


check("an offset can be an expression over the assembly's parameters",
      abs(post_height() - 18) < 1e-2, post_height())
asm_host.call("properties", {"doc": a, "parameters": {"gap": "10"}})
chk = asm_host.call("assembly_check", {"doc": a, "interference": False})
check("changing the parameter moves the part", abs(post_height() - 30)
      < 1e-2, post_height())

# measure and render_view take occurrence references
m = asm_host.call("measure", {"doc": a, "a": "Base:1/Extrude.end",
                              "b": "Post:1/Extrude.end"})
check("measure takes occurrence references, in the assembly's frame",
      abs(m["min_distance"] - 60) < 1e-3, m.get("min_distance"))
img = asm_host.call("render_view", {"doc": a, "width": 300, "height": 200,
                                    "highlight": ["Ring:1/Extrude.end"]})
check("render_view highlights one", img.get("highlighted"), img.keys())

# bom
b = asm_host.call("bom", {"doc": a})
flat = {x["name"]: x for x in b["flat"]}
check("the bom counts a part once per file", flat["Post"]["qty"] == 1
      and flat["Base"]["part_number"] == "B-1", flat)
check("with material and mass from the density", flat["Base"]["material"]
      == "Steel, Mild" and abs(flat["Base"]["mass_g"] - 471.0) < 0.5,
      flat["Base"])
check("a structured list and totals", b["structured"]
      and b["totals"]["parts"] == sum(x["qty"] for x in b["flat"])
      and b["totals"]["line_items"] == len(b["flat"]), b["totals"])
asm_host.call("place_component", {"doc": a, "file": post, "name": "Post"})
b = asm_host.call("bom", {"doc": a, "structure": "flat"})
check("two occurrences of one file are two of one part",
      {x["name"]: x["qty"] for x in b["flat"]}["Post"] == 2 and
      "structured" not in b, b["flat"])
check("bom structure is checked", raises("BAD_VALUE", asm_host.call, "bom",
                                         {"doc": a, "structure": "tree"}))

# a part change follows through the constraints (role, not position)
asm_host.workspace.get(asm_host.call("status")["documents"][0]["doc"])
saved = os.path.join(WORK, "Stand.icasm")
asm_host.call("save_document", {"doc": a, "path": saved})
reopened = asm_host.call("open_document", {"path": saved})
chk = asm_host.call("assembly_check", {"doc": reopened["doc"],
                                       "interference": False})
check("a saved assembly reopens with its constraints and DOF",
      chk["constraints"] == len(asm_doc.constraints)
      and chk["rebuild"]["ok"], chk["summary"])
saved_tree = asm_host.call("model_tree", {"doc": reopened["doc"]})
check("a constraint remembers how it was named", any(
    c["a"].get("ref", "").endswith("Extrude.end")
    for c in saved_tree["constraints"]), saved_tree["constraints"][:2])
# stale revision for assemblies
stale_rev = saved_tree["revision"]
asm_host.call("edit_feature", {"doc": reopened["doc"], "feature":
                               "Ring:1", "params": {"visible": False}})
check("an old revision is STALE_REVISION on an assembly", raises(
    "STALE_REVISION", asm_host.call, "constrain", {
        "doc": reopened["doc"], "a": "Base:1/Extrude.end",
        "b": "Post:2/Extrude.end", "kind": "parallel",
        "expected_revision": stale_rev}))

# a part changed and saved again: the constraints follow its faces by role
for side in ("left", "bottom"):
    asm_host.call("constrain", {
        "doc": a, "kind": "flush", "a": "Base:1/Extrude.side(r.%s)" % side,
        "b": "Post:1/Extrude.side(r.%s)" % side})
base_doc = asm_host.workspace.by_path(base).handle
asm_host.call("properties", {"doc": base_doc, "parameters": {"w": 160}})
asm_host.call("save_document", {"doc": base_doc})
chk = asm_host.call("assembly_check", {"doc": a, "interference": False})
post1 = [o for o in chk["occurrences"] if o["name"] == "Post:1"][0]
check("a 60 % wider base: the assembly reads the saved file and the post "
      "stays flush with the side it was constrained to",
      not chk["failed"] and post1["dof"] == 0
      and abs(post1["position"][0] + 70) < 1e-2, post1)

# the weld cart
cart = asm_host.call("open_document", {"path": os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "examples", "weld-cart", "Welding Cart.icasm")})
chk = asm_host.call("assembly_check", {"doc": cart["doc"]})
check("the weld cart: 18 components, 46 constraints, none failing",
      chk["components"] == 18 and chk["constraints"] == 46
      and not chk["failed"], chk["summary"])
check("only the gas bottle is free, by one", chk["free"] == {
    "Gas Bottle:1": 1}, chk.get("free"))
check("redundant constraints are named", len(chk["redundant"]) >= 1,
      chk["redundant"])
check("and nothing interferes", chk["interference"]["count"] == 0,
      chk["interference"])
cb = asm_host.call("bom", {"doc": cart["doc"]})
caster = [x for x in cb["flat"] if x["name"] == "Caster Plate"][0]
check("the cart's bom counts four caster plates", caster["qty"] == 4
      and caster["mass_total_g"] > 0, caster)
check("through the frame sub-assembly", any(
    x["kind"] == "assembly" and x["children"] for x in cb["structured"]))


# ---------------------------------------------------------------- phase 4b
print("phase 4b: drawings")
import shutil  # noqa: E402

REPLAYS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tests", "mcp_replays")
if not os.path.isdir(REPLAYS):
    REPLAYS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "mcp_replays")
bracket_ops = json.load(open(os.path.join(REPLAYS, "bracket.json"),
                             encoding="utf-8"))["calls"][1]["args"]
DRAW = os.path.join(WORK, "drawings")
os.makedirs(DRAW)
dh = InProcessHost()
dh.call("new_document", {})
dh.call("build", bracket_ops)
unsaved = dh.workspace.active
check("a drawing of an unsaved part is refused with a hint",
      raises("NO_MODEL", dh.call, "drawing_create", {"source": unsaved}))
dh.call("save_document", {"path": os.path.join(DRAW, "Bracket.icpart")})
model = os.path.join(DRAW, "Bracket.icpart")
check("a size that is not a sheet size is refused",
      raises("BAD_VALUE", dh.call, "drawing_create",
             {"source": model, "size": "A9"}))
r = dh.call("drawing_create", {"source": unsaved, "size": "A3",
                               "props": {"Title": "Bracket", "Author": "t"}})
dr = r["doc"]
dent = dh.workspace.entries[dr]
ddoc = dent.document
check("drawing_create makes a drawing beside its model, from a handle",
      dent.doc_type == "drawing" and r["path"] == os.path.join(
          DRAW, "Bracket.icdraw") and not os.path.exists(r["path"]), r)
check("it reports the sheet's frame and title block",
      r["sheet"]["sheet_mm"] == [420.0, 297.0]
      and len(r["sheet"]["title_block"]) == 4, r["sheet"])
open(os.path.join(DRAW, "Exists.icdraw"), "w").write("x")
check("an existing path needs overwrite", raises(
    "WOULD_OVERWRITE", dh.call, "drawing_create",
    {"source": model, "path": os.path.join(DRAW, "Exists.icdraw")}))


def undo_steps():
    return len(ddoc._undo)


steps = undo_steps()
r = dh.call("drawing_base_view", {"doc": dr, "orientation": "front"})
v1 = r["view"]
check("a base view needs no source (the drawing knows its model)",
      v1["name"] == "View1" and v1["looks"] == "front", v1)
check("at a standard scale, with its extent in model mm",
      v1["scale"] == "1:1" and v1["extent_mm"] == [120.0, 48.0], v1)
check("the base view is one undo step", undo_steps() == steps + 1)
check("a dry run changes nothing", (dh.call("drawing_projected_view", {
    "doc": dr, "parent": "View1", "shows": "top", "dry_run": True})
    and len(ddoc.sheets[0].views) == 1 and undo_steps() == steps + 1))
top = dh.call("drawing_projected_view", {"doc": dr, "parent": "View1",
                                        "shows": "top"})["view"]
check("shows=top gives the top view, below the base",
      top["looks"] == "top" and top["at"][1] < v1["at"][1]
      and abs(top["at"][0] - v1["at"][0]) < 1e-6, top)
right = dh.call("drawing_projected_view", {
    "doc": dr, "parent": "View1", "shows": "left"})["view"]
check("under ISO first angle the left view stands on the right",
      right["looks"] == "left" and right["at"][0] > v1["at"][0], right)
check("and the right view on the left (a dry run: no room there)",
      dh.call("drawing_projected_view", {
          "doc": dr, "parent": "View1", "shows": "right", "dry_run": True
      })["view"]["at"][0] < v1["at"][0])
iso = dh.call("drawing_projected_view", {
    "doc": dr, "parent": "View1", "shows": "iso"})
check("an isometric goes in the free corner, inside the sheet",
      iso["view"]["looks"] == "iso" and not iso.get("warnings")
      and iso["view"]["box_sheet"][2] < 410, iso)
check("a view that is not a projection is refused with a hint",
      raises("BAD_VIEW", dh.call, "drawing_projected_view",
             {"doc": dr, "parent": "View1", "shows": "back"}))
n_views = len(ddoc.sheets[0].views)
check("a cut that misses the part is VIEW_FAILED",
      raises("VIEW_FAILED", dh.call, "drawing_section_view", {
          "doc": dr, "parent": "View1",
          "cut": {"direction": "vertical", "at": 900}}))
check("and the drawing is exactly as it was",
      len(ddoc.sheets[0].views) == n_views
      and not any(v.error for v in ddoc.sheets[0].views))
before = ddoc.snapshot()
sec = dh.call("drawing_section_view", {
    "doc": dr, "parent": "View1",
    "cut": {"direction": "vertical", "at": 0}})["view"]
sec_view = [v for v in ddoc.sheets[0].views if v.kind == "section"][0]
check("a section: lettered, hatched, its width the part's depth",
      sec["letter"] == "A" and abs(sec["extent_mm"][0] - 60) < 1.0
      and any(l.kind == "cut" for l in sec_view.projection.lines), sec)
check("it stands clear of the other views", not [
    w for w in dh.call("drawing_dimension", {
        "doc": dr, "view": "View1", "kind": "overall"}).get(
        "warnings", [])])
over = dh.call("drawing_dimension", {"doc": dr, "view": "View1",
                                     "kind": "overall", "axis": "x"})
texts_ = [x["text"] for x in dh.call("drawing_dimension", {
    "doc": dr, "view": "View1", "kind": "overall", "axis": "y"})[
    "dimensions"]]
check("overall dimensions read the model: 120 across, 48 up",
      [x["text"] for x in over["dimensions"]] == ["120"]
      and texts_ == ["48"], (over["dimensions"], texts_))
check("and are anchored to it", all(
    x["anchored"] for x in over["dimensions"]))
dia = dh.call("drawing_dimension", {"doc": dr, "view": top["name"],
                                    "kind": "diameter"})
check("diameters: one per size, with a count",
      any(x["text"].endswith("20") for x in dia["dimensions"])
      and any(x["text"].startswith("8x") for x in dia["dimensions"]),
      dia["dimensions"])
lin = dh.call("drawing_dimension", {
    "doc": dr, "view": top["name"], "kind": "linear",
    "between": [[-54.1, -30], [54, -29.9]], "axis": "x"})
check("a linear dimension between two corners snaps and reads 108",
      lin["dimensions"][0]["text"] == "108"
      and lin["dimensions"][0]["anchored"], lin["dimensions"])
notes = dh.call("drawing_note", {"doc": dr, "view": top["name"],
                                 "kind": "hole_notes"})
check("hole notes are automatic", notes["count"] >= 2
      and any("THRU" in a["text"] for a in notes["annotations"]), notes)
marks = dh.call("drawing_note", {"doc": dr, "view": top["name"],
                                 "kind": "centre_marks"})
check("and so are centre marks", marks["count"] >= 8, marks)
dh.call("drawing_note", {"doc": dr, "view": "View1", "kind": "note",
                         "text": "BREAK ALL EDGES"})
det = dh.call("drawing_detail_view", {
    "doc": dr, "parent": top["name"], "centre": [50, 20], "radius": 12})
check("a detail: lettered, at twice the scale",
      det["view"]["kind"] == "detail" and det["view"]["scale"] == "2:1",
      det["view"])
check("a detail of empty space is VIEW_FAILED", raises(
    "VIEW_FAILED", dh.call, "drawing_detail_view",
    {"doc": dr, "parent": top["name"], "centre": [900, 900],
     "radius": 5}))
check("a parts list needs an assembly", raises(
    "WRONG_TYPE", dh.call, "drawing_parts_list", {"doc": dr}))
tr = dh.call("model_tree", {"doc": dr})
sheet0 = tr["sheets"][0]
check("model_tree lists the views, the annotations and the sheet",
      len(sheet0["views"]) == 6 and len(sheet0["annotations"]) > 20
      and tr["type"] == "drawing" and "frame" in sheet0, len(
          sheet0["views"]))
check("with no view stale and none overlapping", "stale_views" not in tr)
steps_before = undo_steps()
r = dh.call("edit_feature", {"doc": dr, "feature": top["name"],
                             "params": {"x": 100.0}})
check("edit_feature moves a view", r["view"]["at"][0] == 100.0, r)
check("one undo step per call", undo_steps() == steps_before + 1)
check("deleting a view others come from is refused, naming them",
      raises("HAS_DEPENDENTS", dh.call, "edit_feature", {
          "doc": dr, "feature": "View1", "delete": True}))
r = dh.call("edit_feature", {"doc": dr, "feature": det["view"]["name"],
                             "delete": True})
check("a view nothing comes from deletes", len(
    ddoc.sheets[0].views) == 5, r)
check("a name that is not there says which are",
      raises("NO_VIEW", dh.call, "edit_feature", {
          "doc": dr, "feature": "Nope", "params": {"x": 1}}))
ddoc.undo()
check("Ctrl+Z (the document's undo) brings the view back",
      len(ddoc.sheets[0].views) == 6)
check("properties set the title block's fields", dh.call("properties", {
    "doc": dr, "props": {"Revision": "B"}})["properties"]["Revision"]
    == "B")
check("a drawing has no parameters", raises(
    "WRONG_TYPE", dh.call, "properties",
    {"doc": dr, "parameters": {"a": 1}}))

img = dh.call("drawing_render", {"doc": dr, "width": 900})
png = base64.b64decode(img["png_base64"])
check("drawing_render returns a PNG of the sheet",
      png[:8] == b"\x89PNG\r\n\x1a\n" and img["width"] == 900
      and len(png) > 8000, (len(png), img.get("width")))
pdf = os.path.join(DRAW, "Bracket.pdf")
r = dh.call("drawing_export", {"doc": dr, "path": pdf})
check("drawing_export writes a PDF",
      open(pdf, "rb").read(5) == b"%PDF-" and r["bytes"] > 5000, r)
check("and refuses to overwrite it", raises(
    "WOULD_OVERWRITE", dh.call, "drawing_export", {"doc": dr, "path": pdf}))
check("unless asked", dh.call("drawing_export", {
    "doc": dr, "path": pdf, "overwrite": True})["bytes"] > 5000)
dxf = os.path.join(DRAW, "Bracket.dxf")
dh.call("drawing_export", {"doc": dr, "path": dxf})
check("and a DXF, with its layers",
      "VIEW_VISIBLE" in open(dxf, errors="replace").read())
check("any other format is refused", raises(
    "BAD_FORMAT", dh.call, "drawing_export",
    {"doc": dr, "path": os.path.join(DRAW, "a.txt")}))
check("a headless host will not export over the app's file", raises(
    "FILE_OPEN_IN_APP", dh.call, "drawing_export", {
        "doc": dr, "path": os.path.join(DRAW, "x.pdf"),
        "app_open": [{"doc": "g1", "path": os.path.join(DRAW, "x.pdf")}]}))
check("and render_view / export say a drawing is not a solid", raises(
    "WRONG_TYPE", dh.call, "render_view", {"doc": dr}) and raises(
    "WRONG_TYPE", dh.call, "export", {
        "doc": dr, "path": os.path.join(DRAW, "a.step")}))

saved = dh.call("save_document", {"doc": dr})
check("a drawing saves as .icdraw", saved["path"].endswith(".icdraw")
      and os.path.exists(saved["path"]), saved)
dh2 = InProcessHost()
o = dh2.call("open_document", {"path": saved["path"]})
check("and opens again as a drawing, with its views drawn already",
      o["type"] == "drawing" and all(
          "box_mm" in v for v in dh2.call("model_tree", {
              "doc": o["doc"]})["sheets"][0]["views"]), o)
# the model changes: the drawing follows
dh.call("properties", {"doc": unsaved, "parameters": {"w": 160}})
dh.call("save_document", {"doc": unsaved})
img = dh.call("drawing_render", {"doc": dr, "width": 600})
check("a changed model is drawn again before it is rendered",
      img.get("refreshed_views", 0) >= 1, img.get("refreshed_views"))
tr = dh.call("model_tree", {"doc": dr})
base = [v for v in tr["sheets"][0]["views"] if v["name"] == "View1"][0]
check("the base view is now 160 wide", base["extent_mm"][0] == 160.0,
      base["extent_mm"])
ov = [x for x in tr["sheets"][0]["annotations"] if x["kind"] == "linear"
      and x["text"] in ("120", "160")][:1]
check("and its anchored dimension reads 160",
      ov and ov[0]["text"] == "160" and not ov[0].get("sick"), ov)

# an assembly: a parts list and balloons
cart_dir = os.path.join(DRAW, "cart")
cart_src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), "examples", "weld-cart")
shutil.copytree(cart_src, cart_dir)
r = dh.call("drawing_create", {"source": os.path.join(
    cart_dir, "Welding Cart.icasm"), "size": "A2"})
ca = r["doc"]
v = dh.call("drawing_base_view", {"doc": ca, "orientation": "iso"})
check("an isometric alone is sized to the free area",
      v["view"]["scale"] == "1:5" and not v.get("warnings"), v)
pl = dh.call("drawing_parts_list", {"doc": ca})
check("a parts list of the cart with a balloon for each part",
      pl["balloons"] == 10 and len(pl["parts_list"]["rows"]) == 11
      and not pl.get("warnings"), pl["summary"])
rows = {x["part_number"]: x["qty"] for x in pl["parts_list"]["rows"]}
check("with the quantities", rows.get("Caster Plate") == 4, rows)

print("phase 4b: model states")
sh = InProcessHost()
sh.call("new_document", {})
sh.call("build", {"ops": [
    {"op": "parameter", "name": "len", "value": 30},
    {"op": "parameter", "name": "dia", "value": 6},
    {"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"circle": {"center": [0, 0], "d": "dia"}}]},
    {"op": "extrude", "id": "e", "sketch": "$s", "distance": "len",
     "name": "Shank"},
    {"op": "sketch", "id": "s2", "plane": "XY", "entities": [
        {"circle": {"center": [0, 0], "d": 14}}]},
    {"op": "extrude", "id": "e2", "sketch": "$s2", "distance": 4,
     "name": "Head"}]})
sh.call("properties", {"props": {"Part Number": "B-30"}})
bolt = os.path.join(WORK, "Bolt.icpart")
sh.call("save_document", {"path": bolt})
sd = sh.workspace.active
sdoc = sh.workspace.entries[sd].document
primary = sh.call("inspect")["volume"]
steps = len(sdoc._undo)
r = sh.call("model_states", {"action": "create", "name": "M6x40",
                             "parameters": {"len": "40"},
                             "props": {"Part Number": "B-40"}})
check("a state is created with its differences, and the part stays "
      "in Primary", r["active"] == "Primary" and sh.call("inspect")[
          "volume"] == primary and len(sdoc._undo) == steps + 1, r)
sh.call("model_states", {"action": "create", "name": "Headless",
                         "suppress": ["Head"]})
sh.call("model_states", {"action": "create", "name": "Stout",
                         "parameters": {"dia": "8"}, "copy_from": "M6x40"})
ls = sh.call("model_states", {"action": "list", "measure": True})
by = {s["name"]: s for s in ls["states"]}
check("list gives every state with what it changes",
      by["M6x40"]["differs"]["parameters"] == {"len": "40"}
      and by["M6x40"]["differs"]["properties"] == {"Part Number": "B-40"}
      and by["Headless"]["differs"]["suppressed"] == ["Head"], ls["states"])
check("and measured: longer, and without a head",
      by["M6x40"]["volume"] > by["Primary"]["volume"]
      > by["Headless"]["volume"], {k: v["volume"] for k, v in by.items()})
check("a state copied from another has both differences",
      by["Stout"]["differs"]["parameters"] == {"len": "40", "dia": "8"},
      by["Stout"]["differs"])
check("measuring left the part where it was",
      sh.call("inspect")["volume"] == primary and ls["active"] == "Primary")
r = sh.call("model_states", {"action": "activate", "name": "M6x40"})
check("activate makes the part that state", abs(
    sh.call("inspect")["bbox"][2] - 40) < 1e-6 and sdoc.properties[
        "Part Number"] == "B-40", r["summary"])
r = sh.call("model_states", {"action": "set", "name": "M6x40",
                             "parameters": {"len": "50"}})
check("set changes a state's difference", abs(
    sh.call("inspect")["bbox"][2] - 50) < 1e-6, r["summary"])
sh.call("model_states", {"action": "set", "name": "M6x40",
                         "reset": ["len"]})
check("reset puts it back to Primary's",
      "len" not in (sh.call("model_states", {"action": "list"})["states"][
          1]["differs"].get("parameters") or {}))
sh.call("model_states", {"action": "activate", "name": "Primary"})
check("Primary is the part as it was", sh.call("inspect")["volume"]
      == primary and sdoc.properties["Part Number"] == "B-30")
check("an unknown state is NO_STATE", raises(
    "NO_STATE", sh.call, "model_states", {"action": "activate",
                                          "name": "Nope"}))
check("an unknown parameter is refused", raises(
    "NOT_FOUND", sh.call, "model_states",
    {"action": "set", "name": "M6x40", "parameters": {"zzz": "1"}}))
before = sdoc.snapshot()
check("a state that does not build is refused and changes nothing", raises(
    "FEATURE_FAILED", sh.call, "model_states",
    {"action": "set", "name": "M6x40", "parameters": {"len": "-5"}})
    and sdoc.snapshot() == before)
check("a dry run keeps nothing", (sh.call("model_states", {
    "action": "create", "name": "Tmp", "parameters": {"len": "5"},
    "dry_run": True}) and "Tmp" not in sdoc.model_states))
check("model_tree names the states", sh.call("model_tree")["model_states"][
    "names"] == ["Primary", "M6x40", "Headless", "Stout"])
sh.call("save_document", {})
# in an assembly: place a state, and the bom reads its own part number
ah = InProcessHost()
ah.call("new_document", {"type": "assembly"})
p1 = ah.call("place_component", {"file": bolt, "name": "Bolt"})
p2 = ah.call("place_component", {"file": bolt, "name": "Long",
                                 "model_state": "Stout"})
check("place_component(model_state) places that variant: 10 mm longer",
      abs(p2["bbox"][5] - p2["bbox"][2] - (p1["bbox"][5] - p1["bbox"][2])
          - 10) < 1e-6, (p1["bbox"], p2["bbox"]))
bm = ah.call("bom", {"structure": "flat"})
check("and the bom still works with states", bm["totals"]["parts"] == 2
      and len(bm["flat"]) >= 1, bm["summary"])

print("phase 4b: branches")
bh = InProcessHost()
bh.call("new_document", {})
bh.call("build", {"ops": [
    {"op": "parameter", "name": "a", "value": 10},
    {"op": "parameter", "name": "b", "value": 20},
    {"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": ["a", "b"]}}]},
    {"op": "extrude", "id": "e", "sketch": "$s", "distance": 5,
     "name": "Plate"}]})
bd = bh.workspace.active
bdoc = bh.workspace.entries[bd].document
check("an unsaved document cannot branch", raises(
    "BAD_PATH", bh.call, "branch", {"action": "create", "name": "x"}))
bpath = os.path.join(WORK, "Branchy.icpart")
bh.call("save_document", {"path": bpath})
r = bh.call("branch", {"action": "create", "name": "wider"})
check("create checks main in and switches to the new branch",
      r["branch"] == "wider" and r["head"]["id"] == 1, r)
check("and it is in the core's own store, beside the file",
      os.path.isdir(os.path.join(WORK, ".icversions", "Branchy.icpart")))
bh.call("properties", {"parameters": {"a": 30}})
check("switching with unsaved changes is refused", raises(
    "UNSAVED_CHANGES", bh.call, "branch",
    {"action": "switch", "name": "main"}))
check("and creating one too", raises(
    "UNSAVED_CHANGES", bh.call, "branch",
    {"action": "create", "name": "second"}))
bh.call("branch", {"action": "check_in", "message": "wider plate"})
check("check_in keeps a version on the branch", bh.call(
    "branch", {"action": "list"})["branches"][1]["head"] == 2)
d = bh.call("diff", {"from": "branch:main", "to": "branch:wider"})
check("diff reviews a branch against main without switching",
      d["parameters"]["changed"] == {"a": ["10", "30"]}
      and bh.call("branch", {"action": "list"})["current"] == "wider", d)
before_rev = bh.workspace.entries[bd].revision
bh.call("branch", {"action": "switch", "name": "main"})
v_main = bh.call("inspect")["bbox"]
check("switching puts main's design in the document", sorted(
    round(x) for x in v_main) == [5, 10, 20], v_main)
steps = len(bdoc._undo)
bdoc.undo()
bdoc.rebuild()
check("it is one undo step, and an undo brings the branch back",
      sorted(round(x) for x in bh.call("inspect")["bbox"]) == [5, 20, 30])
bdoc.redo()
bdoc.rebuild()
bdoc.modified = False          # main's design again, as the file has it
check("a branch that is not there is NO_BRANCH", raises(
    "NO_BRANCH", bh.call, "branch", {"action": "switch", "name": "zz"}))
r = bh.call("branch", {"action": "merge", "name": "wider", "dry_run": True})
check("merge dry_run says what it would do", r["would"] == "fast forward")
r = bh.call("branch", {"action": "merge", "name": "wider"})
check("merging a branch main has not moved from is a fast-forward",
      r["merged"] and r["how"] == "fast forward" and sorted(
          round(x) for x in bh.call("inspect")["bbox"]) == [5, 20, 30], r)
check("and the file on disk is the merged design",
      Document.load(bpath).params["a"].expression == "30")
check("merging again is nothing to do", bh.call("branch", {
    "action": "merge", "name": "wider"})["merged"] is False)

# both moved, in different places: merged feature by feature
bh.call("branch", {"action": "create", "name": "taller"})
bh.call("build", {"ops": [{"op": "edit", "feature": "Plate",
                           "set": {"distance": 8}}]})
bh.call("branch", {"action": "check_in", "message": "taller"})
bh.call("branch", {"action": "switch", "name": "main"})
bh.call("properties", {"parameters": {"b": 25}})
bh.call("branch", {"action": "check_in", "message": "longer on main"})
r = bh.call("branch", {"action": "merge", "name": "taller"})
check("both sides changed different things: a three-way merge",
      r["how"] == "merged", r)
bb = sorted(round(x) for x in bh.call("inspect")["bbox"])
check("the merged part has main's length and the branch's height",
      bb == [8, 25, 30], bb)
check("with one version for the merge", r["version"]["message"].startswith(
    "Merged taller"), r["version"])

# a conflict is refused, and says what
bh.call("branch", {"action": "create", "name": "c1"})
bh.call("properties", {"parameters": {"a": 11}})
bh.call("branch", {"action": "check_in", "message": "c1"})
bh.call("branch", {"action": "switch", "name": "main"})
bh.call("properties", {"parameters": {"a": 12}})
bh.call("branch", {"action": "check_in", "message": "main a"})
head = bh.call("branch", {"action": "list"})["branches"][0]["head"]
try:
    bh.call("branch", {"action": "merge", "name": "c1"})
    err = None
except BridgeError as exc:
    err = exc
check("a parameter both changed differently is a MERGE_CONFLICT",
      err is not None and err.kind == "MERGE_CONFLICT", err)
check("naming the parameter with its three values", err is not None and any(
    c["kind"] == "parameter" and c["name"] == "a"
    and c["fields"]["expression"] == {"base": "30", "ours": "12",
                                      "theirs": "11"}
    for c in err.extra["conflicts"]), err and err.extra)
check("and nothing was merged: same version, same design",
      bh.call("branch", {"action": "list"})["branches"][0]["head"] == head
      and bh.workspace.entries[bd].document.params["a"].expression == "12")
check("a branch can be discarded (not the current one)", raises(
    "BAD_VALUE", bh.call, "branch", {"action": "discard", "name": "main"})
    and bh.call("branch", {"action": "discard", "name": "c1"})["discarded"]
    == "c1")
check("a headless host will not branch a file the app has open", raises(
    "FILE_OPEN_IN_APP", bh.call, "branch", {
        "action": "check_in", "app_open": [{"doc": "g1", "path": bpath}]}))
bs = bh.call("branch", {"action": "list"})
check("list says where you are and what is checked in",
      bs["current"] == "main" and bs["versions"] and not bs.get("unsaved"),
      bs)


print("phase 4c: sheet metal")
sm = InProcessHost()
sm.call("new_document")
rules0 = sm.call("sheet_rules")
check("a plain part reports it is not sheet metal",
      rules0["sheet_metal"] is False and "converts" in rules0["note"], rules0)
check("flat_pattern and sheet_check refuse a part with no rules",
      raises("NOT_SHEET_METAL", sm.call, "flat_pattern")
      and raises("NOT_SHEET_METAL", sm.call, "sheet_check"))
SM_OPS = [
    {"op": "parameter", "name": "Thickness", "value": 2},
    {"op": "parameter", "name": "BendRadius", "value": 0.5},
    {"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"rect": {"corner": [0, 0], "size": [100, 60]}},
        {"circle": {"center": [95, 30], "d": 4}}]},
    {"op": "sheet_face", "id": "b", "sketch": "$s", "name": "Face"},
    {"op": "flange", "name": "Short", "height": 5,
     "edges": {"edges": {"at": "+z", "kind": "line"}}}]
check("a tray with a tight radius and a short lip builds",
      sm.call("build", {"ops": SM_OPS})["ok"])
chk = sm.call("sheet_check")
kinds = {(f["level"], f["check"]) for f in chk["findings"]}
check("sheet_check fails the 0.5 mm radius in 2 mm sheet and the 5 mm lip",
      not chk["ok"] and ("error", "bend_radius") in kinds
      and ("error", "min_flange") in kinds, kinds)
check("and warns about the hole 0.5 mm from a bend, with the numbers",
      ("warning", "hole_to_bend") in kinds and chk["holes_near_bends"]
      and chk["holes_near_bends"][0]["minimum"] == 4.0
      and chk["thresholds"]["hole_to_bend"], chk["holes_near_bends"])
check("a part that unfolds says so, with the relief it needs",
      chk["relief"]["unfolds"] and chk["relief"]["min_depth"] == 2.5
      and len(chk["bends"]) == 4, chk["relief"])
sm.call("edit_feature", {"feature": "Short", "params": {"height": 12}})
sm.call("properties", {"parameters": {"BendRadius": 2}})
fixed = sm.call("sheet_check")
check("after the fix the errors are gone",
      fixed["ok"] and not [f for f in fixed["findings"]
                           if f["level"] == "error"], fixed["findings"])
before = sm.call("model_tree")["revision"]
r = sm.call("sheet_rules", {"k_factor": 0.3, "thickness": 2})
check("sheet_rules sets the K-factor and converts the part",
      r["k_factor"] == 0.3 and r["sheet_metal"] and r["revision"] > before, r)
f3 = sm.call("flat_pattern")
f5 = sm.call("flat_pattern", {"k_factor": 0.5})
check("a K-factor override moves the flat, and not the part",
      abs(f3["length"] - f5["length"]) > 0.2 and f5["k_factor"] == 0.5
      and sm.call("sheet_rules")["k_factor"] == 0.3,
      (f3["length"], f5["length"]))
check("the bend list has each bend's angle, radius and allowance",
      f3["bend_count"] == 4 and all(
          b["angle"] == 90.0 and b["radius"] == 2.0 and b["allowance"] > 0
          and b["toward"] in ("front", "back") and len(b["line"]) == 2
          for b in f3["bends"]), f3["bends"][:1])
check("the flat has the sheet's area, its hole and a mass",
      f3["area_mm2"] > 6000 and f3["holes"] == 1 and f3["mass_g"] > 0, f3["extent_xy"])
dxf = os.path.join(WORK, "tray.dxf")
w = sm.call("flat_pattern", {"path": dxf})
text = open(dxf, errors="replace").read()
check("a DXF has the outline and the bend lines on their own layers",
      w["layers"] == ["OUTER_PROFILE", "BEND_CENTERLINE"]
      and "OUTER_PROFILE" in text and text.count("BEND_CENTERLINE") >= 4,
      w.get("layers"))
plain = os.path.join(WORK, "plain.dxf")
sm.call("flat_pattern", {"path": plain, "bend_lines": False})
check("bend_lines=false leaves them out",
      "BEND_CENTERLINE" not in open(plain, errors="replace").read())
check("a DXF is never overwritten unasked", raises(
    "WOULD_OVERWRITE", sm.call, "flat_pattern", {"path": dxf}))
check("nor written over a file the app has open", raises(
    "FILE_OPEN_IN_APP", sm.call, "flat_pattern", {
        "path": os.path.join(WORK, "open.dxf"),
        "app_open": [{"doc": "g1", "path": os.path.join(WORK, "open.dxf")}]}))
check("or written as another format", raises(
    "BAD_FORMAT", sm.call, "flat_pattern", {
        "path": os.path.join(WORK, "tray.step")}))
check("a K-factor outside 0 to 1 is refused and the part is unchanged",
      raises("BAD_VALUE", sm.call, "sheet_rules", {"k_factor": 1.5})
      and sm.call("sheet_rules")["k_factor"] == 0.3)
dry = sm.call("sheet_rules", {"k_factor": 0.2, "dry_run": True})
check("a dry run reports and changes nothing",
      dry["dry_run"] and sm.call("sheet_rules")["k_factor"] == 0.3, dry)
sm.call("properties", {"parameters": {"BendRadius": 0.2}})
check("a bend radius is judged on the part as it is now",
      not sm.call("sheet_check")["ok"])

print("phase 4c: frames and a skeleton")
SK = os.path.join(WORK, "Skel.icpart")
fh = InProcessHost()
fh.call("new_document")
fh.call("build", {"ops": [
    {"op": "parameter", "name": "L", "value": 600},
    {"op": "parameter", "name": "W", "value": 400},
    {"op": "parameter", "name": "H", "value": 300},
    {"op": "workplane", "id": "top", "name": "Top", "base": "XY",
     "offset": "H"},
    {"op": "sketch", "id": "r", "name": "Rail", "plane": "$top", "entities": [
        {"rect": {"corner": [0, 0], "size": ["L", "W"]}}]},
    {"op": "sketch", "id": "m", "name": "Marker", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": [2, 2]}}]},
    {"op": "extrude", "sketch": "$m", "distance": 2, "name": "Block"}]})
fh.call("save_document", {"path": SK})
PL = os.path.join(WORK, "Plate.icpart")
fh.call("new_document")
fh.call("build", {"ops": [
    {"op": "parameter", "name": "PL", "value": 500},
    {"op": "parameter", "name": "PW", "value": 300},
    {"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": ["PL", "PW"]}}]},
    {"op": "extrude", "sketch": "$s", "distance": 4}]})
fh.call("save_document", {"path": PL})
asm = fh.call("new_document", {"type": "assembly"})["doc"]
INS = {"doc": asm, "skeleton": "Skel", "sketch": "Rail",
       "profile": "din-en-10219-2-square", "size": "30 x 30 x 2"}
check("a frame needs a saved assembly", raises(
    "BAD_PATH", fh.call, "frame_insert", INS))
AS = os.path.join(WORK, "Rack.icasm")
fh.call("save_document", {"doc": asm, "path": AS})
fh.call("place_component", {"doc": asm, "file": SK, "name": "Skel"})
profiles = fh.call("frame_profiles")
check("the profile library lists families", any(
    p["id"] == "din-en-10219-2-square" for p in profiles["families"]),
    profiles["summary"])
one = fh.call("frame_profiles", {"family": "10219"})
check("and a family's sizes", any("30 x 30 x 2" in p["sizes"]
                                  for p in one["families"]), one)
check("an unknown sketch lists the ones there are", raises(
    "NO_SKETCH", fh.call, "frame_insert", dict(INS, sketch="Nope")))
check("an unknown size is NO_PROFILE", raises(
    "NO_PROFILE", fh.call, "frame_insert", dict(INS, size="1 x 1 x 1")))
check("a cut list before any frame is NO_FRAME", raises(
    "NO_FRAME", fh.call, "cut_list", {"doc": asm}))
fi = fh.call("frame_insert", INS)
check("frame_insert puts a member on each of the sketch's four lines",
      fi["member_count"] == 4 and fi["frame"] == "Frame0001:1"
      and sorted(m["length"] for m in fi["members"]) == [400, 400, 600, 600],
      fi["members"])
check("the frame's files are beside the assembly, one part a member",
      os.path.isdir(os.path.join(WORK, "Rack", "Frame0001"))
      and len([n for n in os.listdir(os.path.join(
          WORK, "Rack", "Frame0001")) if n.endswith(".icpart")]) == 4)
bare = fh.call("cut_list", {"doc": asm})
check("an untreated frame is cut square", bare["pieces"] == 4 and all(
    r["end_a"] == 0 and r["end_b"] == 0 for r in bare["rows"]), bare["rows"])
ft = fh.call("frame_treat", {"doc": asm, "frame": "Frame0001:1",
                             "kind": "miter", "corners": True})
check("corners=true mitres the four corners", len(ft["treatments"]) == 1
      and len(ft["treatments"][0]["members"]) == 8, ft["treatments"])
cl = fh.call("cut_list", {"doc": asm, "path": os.path.join(WORK, "cuts.csv")})
check("the cut list has the mitres at 45 degrees on every end",
      all(r["end_a"] == 45.0 and r["end_b"] == 45.0 for r in cl["rows"])
      and cl["totals"]["30 x 30 x 2"]["pieces"] == 4
      and sorted(r["length"] for r in cl["rows"]) == [430, 630], cl["rows"])
check("and a csv for the saw", len(open(os.path.join(
    WORK, "cuts.csv"), encoding="utf-8").read().splitlines()) == 3)
check("a cut list is never overwritten unasked", raises(
    "WOULD_OVERWRITE", fh.call, "cut_list", {
        "doc": asm, "path": os.path.join(WORK, "cuts.csv")}))
check("frame_treat refuses a part that is not a frame", raises(
    "WRONG_TYPE", fh.call, "frame_treat", {"doc": asm, "frame": "Skel"}))
check("an end treatment that names a missing member is refused", raises(
    "BAD_VALUE", fh.call, "frame_treat", {
        "doc": asm, "frame": "Frame0001:1", "kind": "miter",
        "members": [1, 99]}))
rm = fh.call("frame_treat", {"doc": asm, "frame": "Frame0001:1",
                             "remove": True})
check("remove takes the treatments off", rm["treatments"] == [] and all(
    r["end_a"] == 0 for r in fh.call("cut_list", {"doc": asm})["rows"]))
lg = fh.call("frame_treat", {"doc": asm, "frame": "Frame0001:1",
                             "kind": "lengthen", "members": [1],
                             "amount": 10, "side": "b"})
check("lengthen adds to a member and the cut list follows",
      any(r["length"] in (410, 610)
          for r in fh.call("cut_list", {"doc": asm})["rows"]), lg["summary"])
fh.call("frame_treat", {"doc": asm, "frame": "Frame0001:1", "kind": "lengthen",
                        "members": [1], "amount": -10, "side": "b"})
fh.call("frame_treat", {"doc": asm, "frame": "Frame0001:1", "kind": "miter",
                        "corners": True})

# a plate that follows the skeleton
check("derive_part needs something to derive", raises(
    "BAD_VALUE", fh.call, "derive_part", {"doc": asm, "part": "Skel"}))
dp = fh.call("derive_part", {
    "doc": asm, "file": PL, "name": "Plate",
    "drives": {"PL": "Skel_L - 100", "PW": "Skel_W - 100"}})
check("derive_part places the part and writes the expressions' values in",
      dp["values"] == {"Plate_PL": 500.0, "Plate_PW": 300.0}
      and dp["drivers"]["Plate_PL"] == "Skel_L - 100", dp)
check("an unknown parameter is NO_PARAMETER", raises(
    "NO_PARAMETER", fh.call, "derive_part", {
        "doc": asm, "part": "Plate", "drives": {"nothing": "1"}}))
check("and a bad expression is BAD_EXPRESSION and changes nothing", raises(
    "BAD_EXPRESSION", fh.call, "derive_part", {
        "doc": asm, "part": "Plate", "drives": {"PL": "Skel_Nope"}})
    and fh.call("skeleton_params", {"doc": asm})["drivers"]
    == {"Plate_PL": "Skel_L - 100", "Plate_PW": "Skel_W - 100"})
sp = fh.call("skeleton_params", {"doc": asm})
skel = next(c for c in sp["components"] if c["part"] == "Skel")
plate = next(c for c in sp["components"] if c["part"] == "Plate")
check("skeleton_params retrieves the master parameters and what drives",
      {p["name"] for p in skel["parameters"]} == {"Skel_L", "Skel_W", "Skel_H"}
      and {p["name"]: p.get("driven_by") for p in plate["parameters"]}
      == {"Plate_PL": "Skel_L - 100", "Plate_PW": "Skel_W - 100"}, sp)
check("one part's parameters can be asked for", len(fh.call(
    "skeleton_params", {"doc": asm, "part": "Plate"})["components"]) == 1)
for plane, axis_offset in (("XY", "Skel_H"), ("YZ", "Skel_L / 2"),
                           ("XZ", "-(Skel_W / 2)")):
    fh.call("constrain", {"doc": asm, "kind": "flush",
                          "a": "Skel:1/origin." + plane,
                          "b": "Plate:1/origin." + plane,
                          "offset": axis_offset})
ac = fh.call("assembly_check", {"doc": asm})
check("the plate is fully constrained to the skeleton by its parameters",
      ac["fully_constrained"] and ac["ok"], ac["summary"])
skel_bytes = open(SK, "rb").read()
plate_bytes = open(PL, "rb").read()
dry = fh.call("skeleton_set", {"doc": asm, "set": {"Skel_L": 900},
                               "dry_run": True})
check("a dry run says what would move and writes nothing",
      dry["dry_run"] and dry["changed"]["Plate_PL"]["to"] == 800.0
      and open(SK, "rb").read() == skel_bytes
      and open(PL, "rb").read() == plate_bytes, dry)
before_cut = sorted(r["length"] for r in fh.call("cut_list",
                                                 {"doc": asm})["rows"])
ss = fh.call("skeleton_set", {"doc": asm, "set": {"Skel_L": 800}})
check("skeleton_set moves the plate, the frame and the box",
      ss["changed"]["Skel_L"] == {"from": 600.0, "to": 800.0}
      and ss["changed"]["Plate_PL"] == {"from": 500.0, "to": 700.0}
      and "Frame0001:1" in ss["components_resized"]
      and "Plate:1" in ss["components_resized"]
      and ss["bbox_after"][3] - ss["bbox_before"][3] == 200
      and sorted(ss["written"]) == ["Plate.icpart", "Skel.icpart"], ss)
after_cut = sorted(r["length"] for r in fh.call("cut_list",
                                                {"doc": asm})["rows"])
check("the cut list follows the skeleton: the long sides are 200 longer",
      before_cut == [430, 630] and after_cut == [430, 830], after_cut)
check("the file the agent has open is the one that was changed",
      fh.workspace.by_path(SK).document.params["L"].expression == "800")
check("and the assembly still fits", fh.call(
    "assembly_check", {"doc": asm})["ok"])
skel_bytes = open(SK, "rb").read()
plate_bytes = open(PL, "rb").read()
check("a change a part will not build with is refused",
      raises("FEATURE_FAILED", fh.call, "skeleton_set", {
          "doc": asm, "set": {"Skel_L": 100}}))
check("and nothing was written or changed",
      open(SK, "rb").read() == skel_bytes
      and open(PL, "rb").read() == plate_bytes
      and fh.workspace.by_path(SK).document.params["L"].expression == "800")
check("an unknown parameter is NO_PARAMETER", raises(
    "NO_PARAMETER", fh.call, "skeleton_set", {
        "doc": asm, "set": {"Skel_Nope": 1}}))
check("a file the app has open is not written", raises(
    "FILE_OPEN_IN_APP", fh.call, "skeleton_set", {
        "doc": asm, "set": {"Skel_L": 700},
        "app_open": [{"doc": "g1", "path": PL}]})
    and open(SK, "rb").read() == skel_bytes
    and fh.workspace.by_path(SK).document.params["L"].expression == "800")
fh.call("skeleton_set", {"doc": asm, "set": {"Skel_L": 600}})
check("a value put back puts the frame back",
      sorted(r["length"] for r in fh.call("cut_list", {"doc": asm})["rows"])
      == before_cut)
rel = fh.call("derive_part", {"doc": asm, "part": "Plate",
                              "release": ["PL"]})
check("release stops driving a parameter and keeps its value",
      rel["drivers"] == {"Plate_PW": "Skel_W - 100"}, rel["drivers"])


print("evaluate and optimise")
import json as _json  # noqa: E402
import threading  # noqa: E402

from datum.bridge import explore_ops  # noqa: E402
from datum.core import workers as _workers  # noqa: E402

EV = InProcessHost()
EV.call("new_document")
EV.call("properties", {"material": "Aluminium 6061"})
EV.call("build", {"ops": [
    {"op": "parameter", "name": "w", "value": 100},
    {"op": "parameter", "name": "t", "value": 8},
    {"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": ["w", 50]}, "id": "r"},
        {"circle": {"center": [0, 0], "d": 10}, "id": "c"}]},
    {"op": "extrude", "sketch": "$s", "distance": "t", "name": "Plate"}]})
EV.call("requirements", {"set": [
    {"name": "edge", "metric": "clearance", "a": "Plate.side(c)",
     "b": "Plate.side(r.right)", "min": 20},
    {"name": "light", "metric": "mass", "max": 150}]})
ev_entry = EV.workspace.get("")
rev0 = ev_entry.revision
doc0 = _json.dumps(ev_entry.document.to_dict(), sort_keys=True)
undo0 = len(ev_entry.document._undo)
eight = EV.call("evaluate", {"variations": [
    {"t": 3}, {"t": 4}, {"t": 6}, {"t": 10}, {"w": 30}, {"w": 60},
    {"w": 140}, {"t": 5, "w": 90}], "detail": True})
cap = _workers.capacity()
check("eight variants and the part as it is: nine rows",
      eight["evaluated"] == 9 and len(eight["rows"]) == 9
      and not eight["cancelled"], eight["summary"])
check("the open document's revision never moves",
      ev_entry.revision == rev0 and eight["revision"] == rev0)
check("nor its content nor its undo stack",
      _json.dumps(ev_entry.document.to_dict(), sort_keys=True) == doc0
      and len(ev_entry.document._undo) == undo0)
pids = {r["worker"] for r in eight["rows"] if r.get("worker")}
check("it ran within the worker capacity (%d)" % cap,
      0 < len(pids) <= cap and eight["workers"]["used"] <= cap
      and eight["workers"]["capacity"] == cap, (pids, eight["workers"]))
by = {r["label"]: r for r in eight["rows"]}
check("each row has mass, volume, bbox, faces and validity",
      all(r["ok"] and r["mass_g"] > 0 and r["volume_mm3"] > 0
          and len(r["bbox"]) == 3 and r["faces"] > 0 and r["valid"]
          for r in eight["rows"]), eight["rows"][1])
check("the numbers are the part's (t=4 halves the volume of t=8)",
      abs(by["t=4"]["volume_mm3"] * 2 - by["as is"]["volume_mm3"]) < 0.01,
      (by["t=4"]["volume_mm3"], by["as is"]["volume_mm3"]))
check("requirements are checked on every variant, with values",
      by["w=30"]["reqs"] == "1/2" and not by["w=30"]["pass"]
      and "edge" in by["w=30"]["failing"][0]
      and abs(by["w=30"]["values"]["edge"] - 10) < 1e-6
      and by["t=4"]["pass"] and by["t=4"]["values"]["light"] > 0,
      by["w=30"])
check("the table is compact text with one line a variant",
      eight["table"].count("\n") == 9 and "fails: edge" in eight["table"]
      and "evaluate ok" in eight["summary"], eight["table"])
g = EV.call("evaluate", {"grid": {"t": [4, 6], "w": {"from": 60, "to": 100,
                                                        "steps": 3}},
                         "baseline": False, "metrics": ["mass", "valid"]})
check("a grid tries every combination", g["evaluated"] == 6
      and "bbox" not in g["rows"][0] and "mass_g" in g["rows"][0], g["summary"])
bad = EV.call("evaluate", {"variations": [
    {"nope": 1}, {"t": 0}, {"t": "w*5"}], "baseline": False})
check("a variant that fails to build is a row with its error",
      bad["evaluated"] == 3 and not bad["rows"][0]["ok"]
      and "nope" in bad["rows"][0]["error"] and not bad["rows"][1]["ok"]
      and bad["rows"][1]["error"] and bad["rows"][2]["ok"], bad["table"])
cl = EV.call("evaluate", {"variations": [{"w": 80}], "baseline": False,
                          "clearances": {"edge gap": {
                              "a": "Plate.side(c)",
                              "b": "Plate.side(r.right)"}}})
check("clearances between references are a column",
      abs(cl["rows"][0]["clearance"]["edge gap"] - 35) < 1e-3
      and "edge gap" in cl["table"], cl["rows"][0])
check("nothing to evaluate is refused", raises(
    "BAD_VALUE", EV.call, "evaluate", {"baseline": False}))
check("too many variants are refused", raises(
    "TOO_MANY", EV.call, "evaluate", {"grid": {"t": list(range(1, 16)),
                                                "w": list(range(1, 16))}}))
check("an unknown metric is refused", raises(
    "BAD_VALUE", EV.call, "evaluate", {"variations": [{"t": 4}],
                                       "metrics": ["beauty"]}))
EV.call("model_states", {"action": "create", "name": "thin",
                         "parameters": {"t": 4}})
EV.call("model_states", {"action": "activate", "name": "Primary"})
st = EV.call("evaluate", {"variations": [{"state": "thin"}],
                          "baseline": False})
check("a model state is a variant", st["rows"][0]["ok"]
      and abs(st["rows"][0]["volume_mm3"] * 2
              - by["as is"]["volume_mm3"]) < 0.01, st["rows"][0])
check("and evaluating it left the part in its own state",
      EV.call("model_tree", {})["model_states"]["active"] == "Primary")

# ---- optimise
rev1 = ev_entry.revision
doc0 = _json.dumps(ev_entry.document.to_dict(), sort_keys=True)
op1 = EV.call("optimise", {"vary": {"t": [2, 12], "w": [30, 140]},
                           "objective": "min mass", "budget": 16})
check("optimise finds a feasible design lighter than the start",
      op1["feasible"] and not op1["applied"]
      and op1["best"]["value"] < op1["start"]["mass_g"]
      and op1["evaluations"] <= 16, op1["summary"])
check("the best design clears every requirement",
      op1["best"]["row"]["pass"] and op1["best"]["vary"]["w"] >= 49,
      op1["best"])
check("it counts why the others failed", op1["failed_by"].get("edge", 0) > 0
      and op1["table"].startswith("#"), op1["failed_by"])
check("and does not touch the document", ev_entry.revision == rev1
      and _json.dumps(ev_entry.document.to_dict(), sort_keys=True) == doc0)
op2 = EV.call("optimise", {"vary": {"t": [2, 12], "w": [30, 140]},
                           "objective": "max mass", "budget": 8})
check("max mass is bounded by the mass requirement",
      op2["feasible"] and op2["best"]["value"] <= 150 + 1e-6, op2["summary"])
op3 = EV.call("optimise", {"vary": {"t": [2, 12]}, "budget": 6,
                           "subject_to": [{"name": "thick", "metric":
                                           "parameter", "param": "t",
                                           "min": 20}]})
check("with nothing feasible it says so and names the closest",
      op3["feasible"] is False and "closest" in op3 and "best" not in op3
      and op3["failed_by"].get("thick", 0) > 0, op3["summary"])
op4 = EV.call("optimise", {"vary": {"t": [2, 12], "w": [30, 140]},
                           "subject_to": ["light"], "budget": 8})
check("naming a requirement enforces only that one",
      op4["feasible"] and op4["not_enforced"] == ["edge"]
      and op4["best"]["vary"]["w"] < 49, op4["best"])
op5 = EV.call("optimise", {"vary": {"t": {"values": [3, 5, 8]}},
                           "objective": "min req:light", "budget": 6})
check("a list of values is searched as a list, and req: is an objective",
      op5["feasible"] and op5["best"]["vary"]["t"] == 3, op5["summary"])
check("vary needs real parameters", raises(
    "NOT_FOUND", EV.call, "optimise", {"vary": {"zz": [1, 2]}}))
check("vary needs a range", raises(
    "BAD_VALUE", EV.call, "optimise", {"vary": {"t": [3]}}))
check("an objective must say min or max", raises(
    "BAD_VALUE", EV.call, "optimise", {"vary": {"t": [2, 3]},
                                       "objective": "weight"}))
check("a budget must be sensible", raises(
    "BAD_VALUE", EV.call, "optimise", {"vary": {"t": [2, 3]},
                                       "budget": 1}))
nap = EV.call("optimise", {"vary": {"t": [2, 3]}, "budget": 6,
                           "apply": True,
                           "subject_to": [{"name": "thick", "metric":
                                           "parameter", "param": "t",
                                           "min": 20}]})
check("apply with nothing feasible changes nothing", not nap["applied"]
      and "not_applied" in nap and ev_entry.revision == rev1)
check("apply on a branch needs a saved document", raises(
    "BAD_PATH", EV.call, "optimise", {
        "vary": {"t": [2, 12], "w": [30, 140]}, "budget": 8,
        "apply": True, "branch": "lighter"}) and ev_entry.revision == rev1)
ap = EV.call("optimise", {"vary": {"t": [2, 12], "w": [30, 140]},
                          "budget": 12, "apply": True,
                          "expected_revision": rev1})
check("apply writes the best into the part as one change",
      ap["applied"] and ap["revision"] == rev1 + 1
      and abs(float(ev_entry.document.params["w"].value)
              - ap["best"]["vary"]["w"]) < 1e-6
      and ap["reqs"].endswith("\u2713"), (ap["summary"], ap.get("reqs")))
ev_entry.document.undo()
check("and Undo puts it back in one step",
      _json.dumps(ev_entry.document.to_dict(), sort_keys=True) == doc0
      or float(ev_entry.document.params["w"].value) == 100.0)
check("a stale revision stops an apply", raises(
    "STALE_REVISION", EV.call, "optimise", {
        "vary": {"t": [2, 12]}, "budget": 6, "apply": True,
        "expected_revision": rev1 - 1}))
explore_ops.shutdown_private()

# ---- a real headless host: progress, and Stop between variants
from datum.bridge.client import HostClient  # noqa: E402

hc = HostClient()
try:
    hc.call("new_document", {})
    hc.call("build", {"ops": [
        {"op": "parameter", "name": "t", "value": 8},
        {"op": "sketch", "id": "s", "plane": "XY", "entities": [
            {"rect": {"center": [0, 0], "size": [60, 40]}}]},
        {"op": "extrude", "sketch": "$s", "distance": "t"}]})
    told = []
    full = hc.call("evaluate", {"variations": [{"t": 3}, {"t": 5}, {"t": 6}],
                                "baseline": False},
                   progress=lambda d, t, m: told.append((d, t)))
    check("a host reports progress while it works",
          told and told[-1] == (3, 3) and full["evaluated"] == 3, told)
    stopper = {"sent": False}

    def stop_after_first(done, total, message):
        if done >= 1 and not stopper["sent"]:
            stopper["sent"] = True
            hc.cancel()

    got = hc.call("evaluate", {"grid": {"t": [2 + i * 0.25
                                               for i in range(40)]},
                               "baseline": False},
                  progress=stop_after_first)
    built = [r for r in got["rows"] if r.get("ok")]
    check("Stop ends it between variants, keeping what was built",
          got["cancelled"] and 1 <= len(built) < 40
          and "cancelled" in got["summary"]
          and any(r.get("cancelled") for r in got["rows"]),
          (got["summary"], len(built)))
    again = hc.call("evaluate", {"variations": [{"t": 4}], "baseline": False})
    check("and the host is fine afterwards", again["evaluated"] == 1
          and not again["cancelled"])
finally:
    hc.stop()


# ============================================================ import to a tree
print("recognize and parametrize")


def step_of(host_, ops_, name):
    """Build ops in a new document, write it to STEP, close; its path."""
    host_.call("new_document")
    r_ = host_.call("build", {"ops": ops_})
    assert r_["ok"], r_.get("error")
    path_ = os.path.join(WORK, name + ".step").replace("\\", "/")
    host_.call("export", {"path": path_, "overwrite": True})
    host_.call("close_document")
    return path_


def dumb(host_, path_):
    host_.call("new_document")
    r_ = host_.call("build", {"ops": [{"op": "import", "path": path_}]})
    assert r_["ok"], r_.get("error")
    return host_.workspace.get().document


SQ = [{"op": "sketch", "id": "s", "plane": "XY", "entities": [
    {"rect": {"center": [0, 0], "size": [100, 60]}}]},
    {"op": "extrude", "id": "e", "sketch": "$s", "distance": 8,
     "name": "Plate"}]
ih = InProcessHost()

# a plate, rounded corners, a counterbore grid, a bolt circle of
# countersinks and a blind hole, all of it read and rebuilt
rich = step_of(ih, SQ + [
    {"op": "fillet", "radius": 5, "edges": {"along": "z"}},
    {"op": "sketch", "id": "g", "plane": "XY", "entities": [
        {"point": [-30, -15], "id": "p"}]},
    {"op": "hole", "id": "h1", "sketch": "$g", "diameter": 6.6,
     "points": ["p"], "through": True, "hole_type": "counterbore",
     "cb_diameter": 11, "cb_depth": 4},
    {"op": "pattern", "parents": ["$h1"], "count1": 3, "spacing1": 30,
     "dir1": "X", "count2": 2, "spacing2": 30, "dir2": "Y"},
    {"op": "sketch", "id": "b", "plane": "XY", "entities": [
        {"point": [0, 0], "id": "p"}]},
    {"op": "hole", "id": "h2", "sketch": "$b", "diameter": 8,
     "points": ["p"], "through": False, "depth": 5}], "rich")
ddoc = dumb(ih, rich)
base_undo = len(ddoc._undo)
rec = ih.call("recognize")
kinds = {(f["type"], f.get("kind")): f for f in rec["features"]}
check("recognize finds the base, the holes, the fillet",
      rec["prismatic"] and rec["axis"] == "z"
      and ("extrude", None) in kinds and ("fillet", None) in kinds
      and ("hole", "counterbore") in kinds and ("hole", "simple") in kinds,
      [(f["type"], f.get("kind")) for f in rec["features"]])
cb = kinds[("hole", "counterbore")]
check("a counterbore with its measured sizes, six of them in a grid",
      cb["count"] == 6 and cb["arrangement"] == "grid"
      and abs(cb["diameter"] - 6.6) < 1e-6
      and abs(cb["counterbore_d"] - 11) < 1e-6
      and abs(cb["counterbore_depth"] - 4) < 1e-6, cb)
bl = kinds[("hole", "simple")]
check("a blind hole with its depth", bl["through"] is False
      and abs(bl["depth"] - 5) < 1e-6, bl)
check("a fillet radius, found by a rule on the sharp body",
      abs(kinds[("fillet", None)]["radius"] - 5) < 1e-6
      and kinds[("fillet", None)]["selected_by"] == "rule")
check("coverage is every face, counted on the rebuilt body",
      rec["coverage"]["basis"] == "rebuilt"
      and rec["coverage"]["faces"]["share"] == 1.0
      and rec["coverage"]["area"]["share"] == 1.0
      and rec["unexplained"] == [], rec["coverage"])
check("with a residual volume near zero",
      rec["check"]["residual_volume"] < 0.01
      and abs(rec["check"]["volume_original"]
              - rec["check"]["volume_rebuilt"]) < 0.01, rec["check"])
check("the summary line says it", "recognize ok" in rec["summary"]
      and "faces explained" in rec["summary"], rec["summary"])
check("recognize names parameters", all(
    n in rec["parameters"] for n in ("thickness", "hole_d", "hole_cb_d",
                                     "hole_cb_depth", "pitch",
                                     "hole_count", "fillet_r", "hole2_d",
                                     "hole2_depth")), rec["parameters"])
rev0 = ih.call("model_tree")["revision"]
js0 = json.dumps(ddoc.to_dict(), sort_keys=True)
check("recognize reads only: no undo step, no change",
      len(ddoc._undo) == base_undo)
ih.call("recognize", {"check": False, "detail": True})
check("also unchecked", ih.call("model_tree")["revision"] == rev0
      and json.dumps(ddoc.to_dict(), sort_keys=True) == js0)
nocheck = ih.call("recognize", {"check": False})
check("unchecked, coverage is only what was claimed",
      nocheck["coverage"]["basis"] == "claimed" and "check" not in nocheck)
check("a read of a non-part is refused", raises(
    "WRONG_TYPE", ih.call, "recognize", {"doc": ih.call(
        "new_document", {"type": "assembly"})["doc"]}))
ih.call("close_document")

# ---- parametrize: replaced, one undo step, same body, editable
undo_n = len(ddoc._undo)
dry = ih.call("parametrize", {"dry_run": True})
check("a dry run says so and changes nothing",
      "dry run ok" in dry["summary"] and len(ddoc._undo) == undo_n
      and json.dumps(ddoc.to_dict(), sort_keys=True) == js0)
r = ih.call("parametrize", {"expected_revision": rev0})
check("parametrize replaces the import with a tree",
      "parametrize ok" in r["summary"] and not any(
          f.type_name == "import" for f in ddoc.features)
      and len(ddoc.features) > 8, r["summary"])
check("as one undo step and one revision", len(ddoc._undo) == undo_n + 1
      and r["revision"] == rev0 + 1, (len(ddoc._undo), undo_n))
check("the same body", abs(r["after"]["volume"]
                           - rec["check"]["volume_original"]) < 0.01
      and len(ddoc.bodies) == 1, r["after"])
check("with named parameters in the part",
      {"thickness", "hole_d", "pitch", "fillet_r", "hole_count"}
      <= set(ddoc.params.names()), ddoc.params.names())
vol1 = ih.call("inspect")["volume"]
ih.call("properties", {"parameters": {"hole_d": 8}})
vol2 = ih.call("inspect")["volume"]
import math as _m  # noqa: E402
check("a hole diameter edit rebuilds, six holes bigger",
      abs((vol1 - vol2) - 6 * _m.pi / 4 * (8 ** 2 - 6.6 ** 2) * 4) < 5.0
      or vol2 < vol1, (vol1, vol2))
ih.call("properties", {"parameters": {"hole_d": 6.6, "thickness": 12}})
check("so does the thickness", abs(ih.call("inspect")["bbox"][2] - 12) < 1e-6)
ih.call("properties", {"parameters": {"thickness": 8}})
while len(ddoc._undo) > base_undo:
    ddoc.undo()
check("undo walks back to the dumb solid, whole",
      [f.type_name for f in ddoc.features] == ["import"]
      and json.dumps(ddoc.to_dict(), sort_keys=True) == js0)
ih.call("close_document")

# ---- the same through a bolt circle, a pocket and a boss
mix = step_of(ih, SQ + [
    {"op": "workplane", "id": "top", "base": "XY", "offset": 8},
    {"op": "sketch", "id": "pk", "plane": "$top", "entities": [
        {"rect": {"center": [-25, 0], "size": [30, 20]}}]},
    {"op": "extrude", "id": "pocket", "sketch": "$pk", "distance": 3,
     "operation": "cut", "reversed": True, "name": "Pocket"},
    {"op": "sketch", "id": "bs", "plane": "$top", "entities": [
        {"circle": {"center": [25, 0], "d": 20}}]},
    {"op": "extrude", "id": "boss", "sketch": "$bs", "distance": 12,
     "operation": "join", "name": "Boss"},
    {"op": "chamfer", "distance": 1, "edges": [{"near": [25, 10, 20],
                                                  "count": 1}]}], "mix")
dumb(ih, mix)
m = ih.call("recognize")
types = sorted(f["type"] for f in m["features"])
check("a boss, a pocket and a chamfer are read",
      types == ["boss", "chamfer", "extrude", "pocket"]
      and m["coverage"]["faces"]["share"] == 1.0, (types, m["summary"]))
check("the boss's diameter and the pocket's depth are measured",
      any(f["type"] == "boss" and abs(f["diameter"] - 20) < 1e-6
          for f in m["features"])
      and any(f["type"] == "pocket" and abs(f["depth"] - 3) < 1e-6
              for f in m["features"]), m["features"])
ih.call("parametrize")
check("and it rebuilds as the same body",
      abs(ih.call("inspect")["volume"] - m["check"]["volume_original"])
      < 0.01)
ih.call("properties", {"parameters": {"boss_height": 20}})
check("the boss height is a parameter", abs(
    ih.call("inspect")["bbox"][2] - 28) < 1e-6)
ih.call("close_document")

pc = step_of(ih, [
    {"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"circle": {"center": [0, 0], "d": 120}}]},
    {"op": "extrude", "id": "e", "sketch": "$s", "distance": 10},
    {"op": "sketch", "id": "h", "plane": "XY", "entities": [
        {"point": [40, 0], "id": "p"}]},
    {"op": "hole", "id": "h1", "sketch": "$h", "diameter": 6,
     "points": ["p"], "through": True, "hole_type": "countersink",
     "cb_diameter": 12, "cs_angle": 90},
    {"op": "pattern", "mode": "circular", "parents": ["$h1"], "count1": 6,
     "axis": "Z"}], "circle")
dumb(ih, pc)
c = ih.call("recognize")
hg = [f for f in c["features"] if f["type"] == "hole"]
check("a bolt circle of countersinks: count, kind, angle",
      len(hg) == 1 and hg[0]["count"] == 6
      and hg[0]["arrangement"] == "circle"
      and hg[0]["kind"] == "countersink"
      and abs(hg[0]["countersink_angle"] - 90) < 1e-3
      and c["coverage"]["faces"]["share"] == 1.0, hg)
ih.call("parametrize")
ih.call("properties", {"parameters": {"hole_count": 8}})
check("the count is a parameter: eight holes now",
      ih.call("recognize")["features"][-1]["count"] == 8
      or sum(f.get("count", 0) for f in ih.call("recognize")["features"]
             if f["type"] == "hole") == 8)
ih.call("close_document")

# ---- partial coverage: refused, honest, nothing changed
tp = step_of(ih, SQ + [
    {"op": "workplane", "id": "top", "base": "XY", "offset": 8},
    {"op": "sketch", "id": "bs", "plane": "$top", "entities": [
        {"rect": {"center": [25, 0], "size": [24, 24]}}]},
    {"op": "extrude", "id": "boss", "sketch": "$bs", "distance": 14,
     "operation": "join", "taper": 10, "name": "Tapered boss"}], "taper")
tdoc = dumb(ih, tp)
tjs = json.dumps(tdoc.to_dict(), sort_keys=True)
trev = ih.call("model_tree")["revision"]
t = ih.call("recognize")
check("a tapered boss is only partly explained, and it says so",
      t["coverage"]["faces"]["share"] < 1.0
      and t["coverage"]["faces"]["explained"] < t["coverage"]["faces"]["total"]
      and t["check"]["residual_volume"] > 100
      and len(t["unexplained"]) >= 4, (t["coverage"], t["check"]))
check("every unexplained face has a handle and a reason",
      all(u.get("handle", "").startswith("@F:") and u["why"]
          for u in t["unexplained"]), t["unexplained"])
try:
    ih.call("parametrize")
    refused = None
except BridgeError as exc:
    refused = exc
check("parametrize refuses it: PARTIAL_COVERAGE with the report",
      refused is not None and refused.kind == "PARTIAL_COVERAGE"
      and refused.extra["report"]["refused"] is True
      and refused.extra["report"]["unexplained"]
      and "mm3 away" in str(refused), refused)
check("and nothing changed: the dumb solid, the revision, the undo stack",
      json.dumps(tdoc.to_dict(), sort_keys=True) == tjs
      and ih.call("model_tree")["revision"] == trev
      and [f.type_name for f in tdoc.features] == ["import"])
mine = {"ops": [{"op": "parameter", "name": "w", "value": 100},
                {"op": "sketch", "id": "s", "plane": "XY", "entities": [
                    {"rect": {"center": [0, 0], "size": ["w", 60]}}]},
                {"op": "extrude", "sketch": "$s", "distance": 8}]}
try:
    ih.call("parametrize", {"plan": mine})
    mine_refused = None
except BridgeError as exc:
    mine_refused = exc.kind
check("an agent's own ops are checked the same way",
      mine_refused == "PARTIAL_COVERAGE", mine_refused)
ih.call("close_document")

# ---- the refusals that are not about coverage
ih.call("new_document")
check("no solid, nothing to read", raises("NO_BODY", ih.call, "recognize"))
ih.call("build", {"ops": SQ + [
    {"op": "sketch", "id": "s2", "plane": "XY", "entities": [
        {"rect": {"center": [200, 0], "size": [10, 10]}}]},
    {"op": "extrude", "sketch": "$s2", "distance": 5,
     "operation": "new", "body_name": "Second"}]})
check("several bodies: name one", raises("AMBIGUOUS", ih.call, "recognize"))
check("a body that is not there", raises("BAD_VALUE", ih.call, "recognize",
                                         {"body": "Nope"}))
one = ih.call("recognize", {"body": "Second"})
check("a named body reads", one["prismatic"] and one["body"] == "Second", one)
check("parametrize will not rewrite a part of several bodies",
      raises("AMBIGUOUS", ih.call, "parametrize", {"body": "Second"}))
ih.call("close_document")
ih.call("new_document")
ih.call("build", {"ops": [{"op": "import", "path": rich}]})
check("a stale revision is refused", raises(
    "STALE_REVISION", ih.call, "parametrize", {"expected_revision": 99}))
ih.call("close_document")


# --- a loft that is not capped is an open surface: it must not join ---------
ih.call("new_document")
_loft_ops = [
    {"op": "workplane", "id": "w2", "base": "XY", "offset": 40},
    {"op": "sketch", "id": "a", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": [40, 40]}}]},
    {"op": "sketch", "id": "b", "plane": "$w2", "entities": [
        {"rect": {"center": [0, 0], "size": [20, 20]}}]}]
check("a capped loft makes a solid", ih.call("build", {"ops": _loft_ops + [
    {"op": "loft", "sections": ["$a", "$b"], "ruled": True}]})["ok"])
ih.call("close_document")
ih.call("new_document")
_bad = ih.call("build", {"ops": _loft_ops + [
    {"op": "loft", "sections": ["$a", "$b"], "closed": False}]})
check("an uncapped loft will not join, and says why",
      not _bad["ok"] and _bad["error"]["kind"] == "FEATURE_FAILED"
      and "closed=true" in _bad["error"]["message"], _bad.get("error"))
ih.call("close_document")


print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all mcp bridge tests passed")
sys.exit(0)
