"""Model states through the bridge: one part, several variations of it.

A state is what the core keeps in ``core/modelstates.py``: the part's own
state is Primary, and every other state remembers only how it differs from
Primary: parameter expressions (user parameters and the dimensions inside
sketches and features), which features are suppressed, the part's
properties and its material. The family of a part (a bolt at five lengths,
a bracket with and without its holes) is its states; ``place_component``'s
``model_state`` and ``bom`` read a state of a part placed in an assembly.

One tool, ``model_states``, with an action switch: unlike the rest of the
surface, every action here takes the same few arguments (a state's name
and the differences it should have), so one tool is clearer than five.

Every change is atomic (a state that does not build rolls everything back)
and is one undo step in either host. ``create`` and ``set`` leave the part
in the state it was in unless ``activate`` is asked for, so an agent can
describe a family without leaving the part in the last variant.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..core import modelparams, modelstates
from ..core.modelstates import PRIMARY
from ..core.params import ExpressionError
from . import ops
from .build import Build
from .errors import BridgeError
from .workspace import Entry, Workspace

op = ops.op

ACTIONS = ("list", "create", "activate", "set", "delete")


def _rebuild(d) -> Any:
    """Rebuild a part after a state change. The core's per-feature result
    cache is used as it is: P4b cleared it here because it put back a
    sketch solved for another state (found with a bolt family), which
    ``Document._rebuild_here`` now prevents (``tests/test_reuse_sketch.py``),
    so the app's own state switching and undo are safe as well."""
    return d.rebuild()


def _feature_names(d) -> Dict[int, str]:
    return {f.id: f.name for f in d.features}


def _primary_values(d) -> Dict[str, Any]:
    """What Primary holds, whichever state is active now."""
    ms = d.model_states
    if ms.active == PRIMARY:
        return modelstates.capture(d)
    return dict(ms.baseline)


def decode(d, changes: Dict[str, Any], primary: Dict[str, Any]
           ) -> Dict[str, Any]:
    """A state's differences as an agent reads them: parameter expressions,
    features suppressed or shown, properties, material."""
    names = _feature_names(d)
    out: Dict[str, Any] = {}
    params: Dict[str, str] = {}
    suppressed: List[str] = []
    shown: List[str] = []
    props: Dict[str, Any] = {}
    for key, value in changes.items():
        if key.startswith("p:"):
            params[key[2:]] = value
        elif key.startswith("s:"):
            try:
                name = names.get(int(key[2:]))
            except ValueError:
                name = None
            if name is None:
                continue
            (suppressed if value else shown).append(name)
        elif key.startswith("prop:"):
            props[key[5:]] = value
        elif key == "material":
            out["material"] = value
    if params:
        out["parameters"] = params
    if suppressed:
        out["suppressed"] = suppressed
    if shown:
        out["shown"] = shown
    if props:
        out["properties"] = props
    return out


def _listing(d, measure: Optional[Dict[str, Any]] = None
             ) -> List[Dict[str, Any]]:
    ms = d.model_states
    ms.sync(d)
    primary = _primary_values(d)
    out = [{"name": PRIMARY, "active": ms.active == PRIMARY,
            "differs": {}}]
    for name, changes in ms.states.items():
        item = {"name": name, "active": ms.active == name,
                "differs": decode(d, changes, primary)}
        out.append(item)
    if measure:
        for item in out:
            if item["name"] in measure:
                item.update(measure[item["name"]])
    return out


def _state_metrics(d) -> Dict[str, Any]:
    m = ops.metrics(d.shape)
    out = {"volume": m["volume"], "bbox": m["bbox"], "faces": m["faces"],
           "solids": m["solids"]}
    try:
        out["mass_g"] = round(d.mass_properties().get("mass_g", 0.0), 3)
    except Exception:                                   # noqa: BLE001
        pass
    return out


def summary_of(d) -> Dict[str, Any]:
    """What model_tree and the states resource show."""
    ms = d.model_states
    return {"active": ms.active, "names": ms.names()}


def _read(entry: Entry, measure: bool) -> Dict[str, Any]:
    d = ops._need_part(entry)
    found: Dict[str, Any] = {}
    if measure:
        before, modified = d.snapshot(), d.modified
        try:
            for name in d.model_states.names():
                if d.model_states.active != name:
                    d.model_states.activate(d, name)
                    _rebuild(d)
                found[name] = _state_metrics(d)
        finally:
            d.load_dict(json.loads(before))
            _rebuild(d)
            d.modified = modified
    return {"doc": entry.handle, "revision": entry.revision,
            "active": d.model_states.active,
            "states": _listing(d, found or None)}


def _need_state(d, name: str, what: str = "state") -> str:
    if not name:
        raise BridgeError("BAD_VALUE", "%s: give the state's name" % what)
    if name not in d.model_states:
        raise BridgeError(
            "NO_STATE", "no model state called %r" % name,
            ["States: %s" % ", ".join(d.model_states.names()),
             "model_states(action=\"create\", name=...) makes one."])
    return name


def _parameter_unit(d, name: str) -> str:
    if name in d.params:
        return {"deg": "angle", "ul": "count"}.get(
            getattr(d.params[name], "unit", "mm"), "length")
    found = modelparams.find(d, name)
    if found is None:
        known = list(d.params.names()) + [m.name
                                          for m in modelparams.collect(d)]
        raise BridgeError(
            "NOT_FOUND", "no parameter called %r" % name,
            ["Parameters: %s" % (", ".join(known[:30]) or "none"),
             "properties() lists them with their values."])
    return "angle" if found.kind == modelparams.ANGLE else "length"


def _change(entry: Entry, parameters: Optional[Dict[str, Any]],
            suppress: Optional[List[Any]], unsuppress: Optional[List[Any]],
            props: Optional[Dict[str, Any]], material: str,
            reset: Optional[List[Any]], primary: Dict[str, Any]) -> None:
    """Put the differences into the live part (the state being made)."""
    d = entry.document
    job = Build(entry)
    for name, expr in (parameters or {}).items():
        stored = job.stored(expr, _parameter_unit(d, name), name)
        try:
            modelparams.set_expression(d, name, stored)
        except ExpressionError as exc:
            raise BridgeError("BAD_EXPRESSION", "%s: %s" % (name, exc))
    for refs, flag in ((suppress, True), (unsuppress, False)):
        for ref in refs or []:
            fid = job.feature_id(ref, "feature")
            d.feature(fid).suppressed = flag
    for key, value in (props or {}).items():
        d.properties[str(key)] = str(value)
    if material:
        from ..core import materials
        if material not in materials.library().materials:
            raise BridgeError(
                "UNKNOWN_MATERIAL", "no material %r" % material,
                ops._material_hints(material, materials.library().materials))
        d.material = material
    for ref in reset or []:
        # back to what Primary has: a parameter by name, a feature by name
        if isinstance(ref, str) and ("p:" + ref) in primary:
            modelparams.set_expression(d, ref, str(primary["p:" + ref]))
            continue
        fid = job.feature_id(ref, "feature")
        d.feature(fid).suppressed = bool(primary.get("s:%d" % fid, False))
    d.params.evaluate_all()


def _evaluate(entry: Entry, before_errors: set) -> Dict[str, Any]:
    d = entry.document
    _rebuild(d)
    fresh = [(fid, msg) for fid, msg in d.last_report.errors
             if fid not in before_errors]
    if fresh:
        names = _feature_names(d)
        raise BridgeError(
            "FEATURE_FAILED", "the state does not build: %s" % "; ".join(
                "%s: %s" % (names.get(fid, fid), msg) for fid, msg in fresh),
            ["Nothing was changed. A value too small or a suppressed "
             "feature that others use usually does it; dry_run shows it "
             "without keeping it."])
    return _state_metrics(d)


@op
def model_states(ws: Workspace, doc: str = "", action: str = "list",
                 name: str = "", copy_from: str = "",
                 parameters: Optional[Dict[str, Any]] = None,
                 suppress: Optional[List[Any]] = None,
                 unsuppress: Optional[List[Any]] = None,
                 props: Optional[Dict[str, Any]] = None,
                 material: str = "", reset: Optional[List[Any]] = None,
                 rename: str = "", activate: bool = False,
                 measure: bool = False, dry_run: bool = False,
                 expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """list, create, activate, set or delete a part's model states."""
    entry = ws.get(doc)
    d = ops._need_part(entry)
    if action not in ACTIONS:
        raise BridgeError("BAD_VALUE", "action is one of %s"
                          % ", ".join(ACTIONS))
    if action == "list":
        return _read(entry, measure)
    ops._check_revision(entry, expected_revision)
    ms = d.model_states
    name = (name or "").strip()

    if action == "create":
        if not name:
            name = ms.next_name()
        if name in ms:
            raise BridgeError(
                "BAD_VALUE", "there is already a model state called %r" % name,
                ["Use action=\"set\" to change it."])
        if copy_from:
            _need_state(d, copy_from, "copy_from")
    elif action in ("activate", "set", "delete"):
        _need_state(d, name, action)
        if action == "delete" and name == PRIMARY:
            raise BridgeError("BAD_VALUE", "Primary cannot be deleted")
    if rename and action != "set":
        raise BridgeError("BAD_VALUE", "rename goes with action=\"set\"")
    if action == "set" and not any(
            (parameters, suppress, unsuppress, props, material, reset,
             rename)):
        raise BridgeError(
            "BAD_VALUE", "set changes nothing: give parameters, suppress, "
            "unsuppress, props, material, reset or rename")

    before = d.snapshot()
    modified = d.modified
    previous = ms.active
    known_errors = {fid for fid, _ in d.last_report.errors}
    result: Dict[str, Any] = {"doc": entry.handle, "action": action}
    failure: Optional[Exception] = None
    try:
        if action == "activate":
            ms.activate(d, name)
            result["state"] = name
            result["after"] = _evaluate(entry, known_errors)
        elif action == "delete":
            ms.delete(d, name)
            result["deleted"] = name
            result["after"] = _evaluate(entry, known_errors)
        else:
            if action == "create":
                start = copy_from or PRIMARY
                if ms.active != start:
                    ms.activate(d, start)
                ms.create(d, name)
                target = name
            else:
                target = name
                if ms.active != target:
                    ms.activate(d, target)
            primary = _primary_values(d)
            _change(entry, parameters, suppress, unsuppress, props, material,
                    reset, primary)
            result["after"] = _evaluate(entry, known_errors)
            ms.sync(d)
            if rename:
                ms.rename(d, target, rename)
                target = rename
            result["state"] = target
            if not activate and previous != target:
                # back where the part was; the new state is stored
                if previous in ms:
                    ms.activate(d, previous)
                    _evaluate(entry, known_errors)
            if activate:
                result["activated"] = True
    except Exception as exc:                            # noqa: BLE001
        failure = exc
    if failure is not None or dry_run:
        d.load_dict(json.loads(before))
        _rebuild(d)
        d.modified = modified
        if failure is not None:
            raise failure
        result["dry_run"] = True
        result["revision"] = entry.revision
        return result
    # one undo step: the state the part was in before this call
    d._undo.append(before)
    del d._undo[:-60]
    d._redo.clear()
    d.modified = True
    entry.touch()
    result["revision"] = entry.revision
    result["active"] = ms.active
    result["states"] = _listing(d)
    after = result.get("after") or {}
    result["summary"] = "model_states %s %s | active %s | %d state%s%s | " \
        "rev %d" % (
            action, result.get("state", result.get("deleted", "")),
            ms.active, len(ms), "" if len(ms) == 1 else "s",
            (" | V %s mm3" % ops._fmt(after["volume"])
             if "volume" in after else ""), entry.revision)
    return result

