"""``run_script``: Python against ``datum.core``, applied as IR ops.

Plan §4, the script route. The script runs in a *separate* headless host,
started for it and stopped after, on a *copy* of the document. What it
leaves behind is compared with the document it started from, by feature
id (open decision 3), and the difference becomes ordinary build ops:
parameter ops, ``remove``, ``edit``, new feature ops, ``move``. Those are
applied to the real document as one build: atomically, as one undo step,
with the usual envelope. So a script cannot do anything to a document
that a build could not, and the document never sees the script run.

This is **not a sandbox**. The script runs with the user's own
privileges and can do anything Python can. The protection is the second
process, the copy and the timeout; ``safe_mode`` adds an AST allowlist
(``safemode``) for when what the agent writes may have been steered by
something it read.

What a script sees:

    build(ops)                    a build on the copy, as the tool takes it
    op(type, **fields)            one op; returns the feature's name
    param(name, value, comment=)  a parameter
    sketch(**fields)              op("sketch", ...)
    extrude(sketch, distance, **fields)
    hole(sketch, diameter, **fields)
    fillet(radius, edges, **fields)
    ref(text)                     what a reference resolves to, and how
    find(what="face", **where)    find_geometry's items
    measure(a, b=None)            measure's answer
    inspect(expected=None)        inspect's answer
    params                        parameter values by name: params["w"]
    doc, core                     the copy itself and datum.core (not in
                                  safe mode)
    print / log                   output, returned with the result
    math                          the module
    result                        leave a value here to have it returned
"""

from __future__ import annotations

import json
import traceback
from typing import Any, Dict, List, Tuple

from ..core.document import Document
from . import ir
from .errors import BridgeError

OUTPUT_LIMIT = 20000


class ScriptFailed(Exception):
    pass


def _namespace(ws, entry, lines: List[str], safe: bool) -> Dict[str, Any]:
    import math
    from . import measure as measure_mod
    from . import ops as ops_mod
    from . import refs as refs_mod

    def log(*parts: Any) -> None:
        lines.append(" ".join(str(p) for p in parts))

    def build(ops_list, **kw):
        r = ops_mod.build(ws, ops=ops_list, doc=entry.handle, **kw)
        if not r["ok"]:
            raise ScriptFailed(r["summary"])
        return r

    def op(type_name, **fields):
        r = build([dict(fields, op=type_name)])
        made = r["created"] or r["changed"]
        # a sketch on a plane by numbers makes that plane first: the name
        # wanted is the sketch's
        mine = [m for m in made if m.get("type") == type_name] or made
        return mine[0]["name"] if mine else None

    def param(name, value, comment=None):
        spec = {"name": name, "value": value}
        if comment is not None:
            spec["comment"] = comment
        build([dict(spec, op="parameter")])
        return entry.document.params[name].value

    class Params:
        def __getitem__(self, name):
            entry.document.params.evaluate_all()
            return entry.document.params[name].value

        def __contains__(self, name):
            return name in entry.document.params

        def get(self, name, default=None):
            return self[name] if name in self else default

        def names(self):
            return list(entry.document.params.names())

    names: Dict[str, Any] = {
        "build": build, "op": op, "param": param,
        "sketch": lambda **f: op("sketch", **f),
        "extrude": lambda sketch, distance, **f: op(
            "extrude", sketch=sketch, distance=distance, **f),
        "hole": lambda sketch, diameter, **f: op(
            "hole", sketch=sketch, diameter=diameter, **f),
        "fillet": lambda radius, edges, **f: op(
            "fillet", radius=radius, edges=edges, **f),
        "ref": lambda text: refs_mod.Resolver(entry).resolve(
            text, "ref", ("face", "edge", "vertex", "region", "body",
                          "point")).describe(),
        "find": lambda what="face", **where: refs_mod.find(
            entry, what, where)["items"],
        "measure": lambda a, b=None: measure_mod.measure(entry, a, b),
        "inspect": lambda expected=None: ops_mod.inspect(
            ws, doc=entry.handle, expected=expected),
        "params": Params(), "math": math, "log": log, "print": log,
        "result": None,
    }
    if not safe:
        from .. import core
        names["doc"] = entry.document
        names["core"] = core
    return names


def execute(ws, data: Dict[str, Any], code: str, path: str = "",
            safe_mode: bool = False, trusted: bool = False,
            trusted_code=(), sketch_names=None) -> Dict[str, Any]:
    """Run ``code`` on a document made from ``data``; in the child host."""
    from ..core import rules
    from . import safemode
    doc = Document()
    doc.path = path or ""
    doc.load_dict(data)
    doc.rules.trusted = bool(trusted)
    rules.trust_code_hashes(trusted_code)
    doc.rebuild()
    entry = ws.add(doc, "part")
    entry.sketch_names = {int(k): {n: tuple(v) for n, v in names.items()}
                          for k, names in (sketch_names or {}).items()}
    lines: List[str] = []
    names = _namespace(ws, entry, lines, safe_mode)
    if safe_mode:
        names["__builtins__"] = safemode.builtins()
        names["print"] = names["log"]
    out: Dict[str, Any] = {"ok": True}
    try:
        if safe_mode:
            safemode.check(code)
        exec(compile(code, "<script>", "exec"), names)     # noqa: S102
    except safemode.SafeModeViolation as exc:
        out = {"ok": False, "error": {
            "kind": "SAFE_MODE", "message": "line %d: %s" % (exc.line, exc),
            "line": exc.line,
            "hints": ["safe_mode refuses this; rewrite it with the "
                      "helpers, or run without safe_mode if the user "
                      "agrees."]}}
    except BaseException as exc:                            # noqa: BLE001
        line = 0
        for frame in traceback.extract_tb(exc.__traceback__):
            if frame.filename == "<script>":
                line = frame.lineno or 0
        if isinstance(exc, SyntaxError) and exc.filename == "<script>":
            line = exc.lineno or 0
        hints = ["Nothing was changed: the document is as it was."]
        data_err = None
        if isinstance(exc, BridgeError):
            data_err = exc.to_dict()
            hints = data_err.get("hints", []) + hints
        out = {"ok": False, "error": {
            "kind": data_err["kind"] if data_err else "SCRIPT_FAILED",
            "message": "line %d: %s: %s" % (line, type(exc).__name__, exc),
            "line": line, "hints": hints}}
    text = "\n".join(lines)
    if len(text) > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT] + "\n... (%d more characters)" % (
            len(text) - OUTPUT_LIMIT)
    out["output"] = text
    if out["ok"]:
        out["data"] = entry.document.to_dict()
        out["sketch_names"] = {str(k): {n: list(v) for n, v in m.items()}
                               for k, m in entry.sketch_names.items()}
        value = names.get("result")
        try:
            json.dumps(value)
            out["result"] = value
        except (TypeError, ValueError):
            out["result"] = repr(value)
    return out


# ---------------------------------------------------------------- the diff


def tree_ops(before: Document, after_data: Dict[str, Any]
             ) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[str]]:
    """The build ops that turn ``before`` into what the script left.

    Returns (ops, {op id: the script's feature id} for added features,
    notes). Features are matched by id; those the script added get fresh
    ids when the build adds them."""
    after = Document()
    after.load_dict(after_data)
    notes: List[str] = []
    ops: List[Dict[str, Any]] = []
    old = {f.id: f for f in before.features}
    new = {f.id: f for f in after.features}

    pb = {n: before.params[n] for n in before.params.names()}
    pa = {n: after.params[n] for n in after.params.names()}
    for name, p in pa.items():
        q = pb.get(name)
        if q is None or q.expression != p.expression or \
                (q.comment or "") != (p.comment or ""):
            item: Dict[str, Any] = {"op": "parameter", "name": name,
                                    "value": p.expression}
            if p.comment:
                item["comment"] = p.comment
            if getattr(p, "unit", "mm") not in ("mm", ""):
                item["unit"] = p.unit
            ops.append(item)

    for f in reversed(before.features):
        if f.id not in new:
            ops.append({"op": "remove", "feature": f.id,
                        "dependents": "remove"})

    taken: set = set()
    tokens = {f.id: ir.token_for(f.name, taken) for f in after.features}
    for f in after.features:
        if f.id not in old:
            continue
        a, b = old[f.id].to_dict(), f.to_dict()
        if a == b:
            continue
        if a.get("type") != b.get("type"):
            raise BridgeError("SCRIPT_UNSUPPORTED", "the script turned %s "
                              "into another type of feature" % f.name,
                              ["Remove it and add a new one instead."])
        item = ir.to_ir(after, [f.id], parameters=False)[0]
        dflt = ir.defaults(f.type_name)
        allowed = set(ir.allowed_keys(f.type_name))
        changes: Dict[str, Any] = {}
        for key in sorted(set(a) | set(b)):
            if a.get(key) == b.get(key) or key in ("id", "type"):
                continue
            if key == "param_comments":
                changes["comments"] = item.get("comments", {})
                continue
            if key not in allowed:
                continue
            changes[key] = item.get(key, dflt.get(key, b.get(key)))
        if changes:
            ops.append({"op": "edit", "feature": f.id, "set": changes})

    added = [f for f in after.features if f.id not in old]
    origin: Dict[str, int] = {}
    if added:
        for item in ir.to_ir(after, [f.id for f in added], parameters=False):
            ops.append(item)
        for f in added:
            origin[tokens[f.id]] = f.id
    order = [f.id for f in after.features]
    for i, fid in enumerate(order):
        if fid in old or not any(o in old for o in order[i + 1:]):
            continue
        prev = order[i - 1] if i else None
        move: Dict[str, Any] = {"op": "move", "feature": "$" + tokens[fid]}
        if prev is None:
            move["to"] = "start"
        else:
            move["after"] = ("$" + tokens[prev]) if prev not in old else prev
        ops.append(move)
    kept_old = [fid for fid in order if fid in old]
    if kept_old != [f.id for f in before.features if f.id in new]:
        notes.append("the script reordered existing features; that order "
                     "was not applied (move them with edit_feature)")

    for name in pb:
        if name not in pa:
            ops.append({"op": "parameter", "name": name, "remove": True})
    was, now = before.to_dict(), after.to_dict()
    item = {}
    if (was.get("appearance") or "") != (now.get("appearance") or ""):
        item["appearance"] = now.get("appearance") or "material"
    if was.get("material") != now.get("material") and now.get("material"):
        item["material"] = now["material"]
    old_props = was.get("properties") or {}
    new_props = now.get("properties") or {}
    changed = {k: v for k, v in new_props.items() if old_props.get(k) != v}
    if changed:
        item["props"] = changed
    if item:
        ops.append(dict(item, op="properties"))
    for key in ("requirements", "units"):
        if was.get(key) != now.get(key):
            notes.append("the script changed the part's %s; only the tree, "
                         "parameters, appearance, material and iProperties "
                         "are applied (use requirements or new_document)"
                         % key)
    return ops, origin, notes


__all__: List[str] = ["execute", "tree_ops", "OUTPUT_LIMIT"]
