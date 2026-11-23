"""Several parts and the assembly of them, in one call.

An aircraft of forty parts took some 175 calls a document at a time: new,
build, colour, save, place. ``build_project`` is those calls in a row, in
the headless host. Each part is all or nothing by itself: one that fails
is not written and is reported, and the rest go on, so a second call need
only carry what failed.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ..core import fileformat
from ..core.assembly import AssemblyDocument
from . import ops
from .assembly_ops import parse_transform
from .errors import BridgeError, classify
from .workspace import Workspace, same_path

PART_KEYS = {"file", "ops", "code", "appearance", "material", "props",
             "units", "timeout", "place"}
PLACE_KEYS = {"name", "transform", "grounded"}


def _placings(value: Any, label: str) -> List[Dict[str, Any]]:
    """What ``place`` asks for: one at the part's own origin unless said."""
    if value is False:
        return []
    if value is None or value is True:
        value = [{}]
    elif isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or not all(
            isinstance(v, dict) and not set(v) - PLACE_KEYS for v in value):
        raise BridgeError(
            "BAD_VALUE", "%s: place is true, false, or a list of {name, "
            "transform, grounded}" % label)
    out = []
    for v in value:
        name = str(v.get("name") or "").strip()
        if "/" in name or chr(92) in name:
            raise BridgeError("BAD_NAME", "%s: name %r cannot hold a slash"
                              % (label, name))
        out.append({"name": name, "given": v.get("transform"),
                    "placement": parse_transform(v.get("transform")),
                    "grounded": bool(v.get("grounded", True))})
    return out


def _free_to_write(ws: Workspace, path: str, overwrite: bool,
                   app_open: Any) -> None:
    ops._refuse_app_file(path, app_open, "writing it")
    held = ws.by_path(path)
    if held is not None and getattr(held.document, "modified", False):
        raise BridgeError(
            "FILE_IN_USE", "%s is open as %s with unsaved changes"
            % (path, held.handle), ["Save or close %s first." % held.handle])
    if os.path.exists(path) and not overwrite:
        raise BridgeError(
            "WOULD_OVERWRITE", "%s already exists" % path,
            ["Pass overwrite: true to write it again (the last version is "
             "kept in OldVersions), or use another folder."])


def _make_part(ws: Workspace, part: Dict[str, Any], path: str, shared: str,
               timeout: float, overwrite: bool,
               safe_mode: bool) -> Dict[str, Any]:
    made = ops.new_document(ws, type="part", units=part.get("units", "mm"))
    handle = made["doc"]
    try:
        steps = list(part.get("ops") or [])
        setting = {k: part[k] for k in ("appearance", "material", "props")
                   if part.get(k)}
        if setting:
            steps.insert(0, dict(setting, op="properties"))
        if steps:
            got = ops.build(ws, ops=steps, doc=handle)
            if not got["ok"]:
                raise BridgeError("BUILD_FAILED", got["summary"])
        output = ""
        if part.get("code"):
            code = (shared.rstrip() + "\n" if shared else "") + part["code"]
            got = ops.run_script(
                ws, code=code, doc=handle, safe_mode=safe_mode,
                timeout=min(240.0, float(part.get("timeout") or timeout)))
            if not got["ok"]:
                raise BridgeError("BUILD_FAILED", got["summary"])
            output = str(got.get("output") or "").strip()
        entry = ws.get(handle)
        size = ops.metrics(ops.shape_of(entry))
        if not size["solids"]:
            raise BridgeError(
                "NO_BODY", "it has no solid, so it was not written",
                ["Build it alone (new_document, build) to see each step."])
        held = ws.by_path(path)
        if held is not None:
            ws.close(held.handle)       # unchanged, and about to be stale
        saved = ops.save_document(ws, doc=handle, path=path,
                                  overwrite=overwrite)
        out = {"file": saved["path"], "ok": True, "volume": size["volume"],
               "solids": size["solids"], "bbox": size["bbox"]}
        if entry.document.appearance:
            out["appearance"] = entry.document.appearance
        if output:
            out["output"] = output[-800:]
        return out
    finally:
        ws.close(handle)


def _assemble(ws: Workspace, path: str,
              wanted: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The assembly, with each part placed as asked. One that is there is
    added to: a part it already places is not placed a second time."""
    held = ws.by_path(path)
    existed = os.path.exists(path)
    if existed:
        # read afresh: the parts under it have just been written
        d = AssemblyDocument.load(path)
    else:
        d = AssemblyDocument()
        d.path = path               # so the files it places resolve by it
    d.rebuild()
    there = [(o, d.component_path(o)) for o in d.occurrences]
    known = set(d.last_report.errors) | set(d.last_report.missing)
    added = kept = moved = 0
    for part in wanted:
        mine = [o for o, where in there
                if where and same_path(where, part["file"])]
        for i, spot in enumerate(part["place"]):
            if i < len(mine):
                kept += 1
                if spot["given"]:
                    mine[i].placement = spot["placement"]
                    moved += 1
                continue
            o = d.place(part["file"], label=spot["name"])
            if spot["given"]:
                o.placement = spot["placement"]
            o.grounded = spot["grounded"]
            added += 1
    report = d.rebuild()
    bad = [e for e in list(report.errors) + list(report.missing)
           if e not in known]
    if bad:
        raise BridgeError("ASSEMBLY_FAILED", "; ".join(map(str, bad[:5])),
                          ["The parts are saved; the assembly was not."])
    if held is not None:
        ws.close(held.handle)
    written = d.save(path)
    entry = ws.add(d, "assembly")
    return {"file": written, "doc": entry.handle, "revision": entry.revision,
            "components": len(d.occurrences), "placed": added,
            "already_there": kept, "moved": moved}


@ops.op
def build_project(ws: Workspace, parts: List[Dict[str, Any]],
                  assembly: str = "", shared: str = "",
                  overwrite: bool = False, timeout: float = 60.0,
                  app_open: Any = None, safe_mode: bool = False,
                  code_allowed: bool = False) -> Dict[str, Any]:
    """Build and save many parts, and place them in an assembly.
    ``code_allowed``: the user read and allowed the project's code, so
    the code features it makes run without asking again."""
    from . import codepolicy
    with codepolicy.allowing(code_allowed):
        return _build_project(ws, parts, assembly, shared, overwrite,
                              timeout, app_open, safe_mode)


def _build_project(ws: Workspace, parts: List[Dict[str, Any]],
                   assembly: str = "", shared: str = "",
                   overwrite: bool = False, timeout: float = 60.0,
                   app_open: Any = None,
                   safe_mode: bool = False) -> Dict[str, Any]:
    if not isinstance(parts, list) or not parts:
        raise BridgeError("BAD_VALUE", "parts must be a non-empty list")
    plan = []
    seen: Dict[str, int] = {}
    for n, part in enumerate(parts):
        label = "part %d" % n
        if not isinstance(part, dict) or set(part) - PART_KEYS:
            raise BridgeError(
                "BAD_VALUE", "%s: the keys are %s"
                % (label, ", ".join(sorted(PART_KEYS))))
        if not part.get("file"):
            raise BridgeError("BAD_PATH", "%s needs file, an absolute "
                              ".icpart path" % label)
        if (not part.get("ops") and not part.get("code")
                and not os.path.isfile(str(part["file"]))):
            raise BridgeError("BAD_VALUE", "%s needs ops, code or both "
                              "(or a file that is there, to place it)"
                              % label)
        path = fileformat.ensure_extension(
            ops._absolute(part["file"], "build_project"), "part")
        key = os.path.normcase(path)
        if key in seen:
            raise BridgeError("BAD_PATH", "parts %d and %d are the same file"
                              % (seen[key], n))
        seen[key] = n
        plan.append((part, path, _placings(part.get("place"), label)))
    target = ""
    if assembly:
        target = fileformat.ensure_extension(
            ops._absolute(assembly, "build_project"), "assembly")
        # an assembly is added to, so that it is there is no objection
        _free_to_write(ws, target, True, app_open)

    results: List[Dict[str, Any]] = []
    wanted: List[Dict[str, Any]] = []
    total = len(plan) + (1 if target else 0)
    stopped = False
    for n, (part, path, spots) in enumerate(plan):
        if ws.should_cancel():
            stopped = True
            break
        ws.progress(n, total, os.path.basename(path))
        try:
            if not part.get("ops") and not part.get("code"):
                # one that is there already, only to be placed
                results.append({"file": path, "ok": True, "existing": True})
                if target and spots:
                    wanted.append({"file": path, "place": spots})
                continue
            _free_to_write(ws, path, overwrite, app_open)
            done = _make_part(ws, part, path, shared, timeout, overwrite,
                              safe_mode)
            if target and spots:
                wanted.append({"file": done["file"], "place": spots})
        except Exception as exc:                            # noqa: BLE001
            err = classify(exc)
            done = {"file": path, "ok": False, "error": err}
        results.append(done)
    built = sum(1 for r in results if r["ok"])
    out: Dict[str, Any] = {"parts": results, "built": built,
                           "failed": len(results) - built, "of": len(plan)}
    if stopped:
        out["cancelled"] = len(plan) - len(results)
    made: Optional[Dict[str, Any]] = None
    if target and wanted and not stopped:
        ws.progress(len(plan), total, os.path.basename(target))
        try:
            made = _assemble(ws, target, wanted)
            out["assembly"] = made
        except Exception as exc:                            # noqa: BLE001
            err = classify(exc)
            out["assembly"] = {"file": target, "error": err}
    out["ok"] = (built == len(plan)
                 and (not target or not wanted or made is not None))
    bits = ["%d of %d parts" % (built, len(plan))]
    if out["failed"]:
        bits.append("%d failed, not written" % out["failed"])
    if made:
        bits.append("%d components in %s, open as %s" % (
            made["components"], os.path.basename(made["file"]), made["doc"]))
    if stopped:
        bits.append("stopped by the user")
    out["summary"] = "build_project %s | %s" % (
        "ok" if out["ok"] else "attention", " | ".join(bits))
    return out
