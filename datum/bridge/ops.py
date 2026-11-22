"""What a host can be asked to do, as plain Python over ``datum.core``.

Every op takes the workspace and keyword arguments, and returns a dict
that is safe to send as JSON. A failure is raised as a :class:`BridgeError`
(or any exception, which the host classifies), never returned as a
half-answer.

Units: the API is millimetres and degrees, always. The core already
stores a bare number as millimetres whatever the part's own unit
(``core.units``: only text a *person* types into an inch part is given a
unit), so nothing an agent writes is ever read in the wrong unit, and an
inch part still shows it in inches.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from OCP.TopoDS import TopoDS_Iterator

from .. import APP_NAME, __version__
from ..core import edgequery, fileformat, fileio, kernel
from ..core import requirements as reqs
from ..core import rules as core_rules
from ..core.document import Document
from ..core.features import FEATURE_TYPES, SketchFeature
from . import PROTOCOL_VERSION, ir, refs, render, sketchir
from .build import Build, set_properties
from .errors import BridgeError, classify
from .workspace import Entry, Workspace, same_path

OPS: Dict[str, Callable[..., Dict[str, Any]]] = {}


def op(fn):
    OPS[fn.__name__] = fn
    return fn


# ---------------------------------------------------------------- helpers


def _assembly_shape(document) -> Any:
    shapes = [o.placed() for o in getattr(document, "occurrences", [])]
    shapes = [s for s in shapes if s is not None and not s.IsNull()]
    return kernel.compound(shapes) if shapes else None


def shape_of(entry: Entry):
    if entry.doc_type == "part":
        return entry.document.shape
    if entry.doc_type == "assembly":
        return _assembly_shape(entry.document)
    return None


def metrics(shape) -> Dict[str, Any]:
    """Size and topology of a shape, the numbers a change is judged by."""
    if shape is None or shape.IsNull():
        return {"volume": 0.0, "solids": 0, "faces": 0, "edges": 0,
                "bbox": None}
    props = kernel.geometry_properties(shape)
    return {"volume": round(props["volume_mm3"], 3),
            "solids": len(kernel.solids(shape)),
            "faces": len(kernel.faces(shape)),
            "edges": len(kernel.edges(shape)),
            "bbox": [round(v, 4) for v in props["bbox"]],
            "bbox_min": [round(v, 4) for v in props["bbox_min"]]}


def _fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-6:
        return "{:,}".format(int(round(v))).replace(",", " ")
    return ("%.3f" % v).rstrip("0").rstrip(".")


def _signed(v: float) -> str:
    return ("+" if v >= 0 else "-") + _fmt(abs(v))


def _units(entry: Entry) -> Dict[str, str]:
    return {"api": "mm", "document": getattr(entry.document, "units", "mm")}


def _need_part(entry: Entry) -> Document:
    if entry.doc_type != "part":
        raise BridgeError("WRONG_TYPE",
                          "%s is a %s; this works on parts"
                          % (entry.handle, entry.doc_type))
    return entry.document


def _check_revision(entry: Entry, expected: Optional[int]) -> None:
    if expected is not None and int(expected) != entry.revision:
        changes = _changes_since(entry, int(expected))
        said = (" (%s)" % changes["summary"]) if changes else ""
        extra: Dict[str, Any] = {"revision": entry.revision}
        if changes:
            extra["changes"] = changes
        raise BridgeError(
            "STALE_REVISION",
            "%s is at revision %d, not %d: it changed since it was read%s"
            % (entry.handle, entry.revision, int(expected), said),
            ["Read it again (model_tree) before changing it."
             + (" `changes` says what moved." if changes else "")],
            **extra)


def _changes_since(entry: Entry, expected: int) -> Optional[Dict[str, Any]]:
    """What moved in a document since revision ``expected``: the features
    added, removed or edited and the parameters changed, from the same
    comparison ``diff`` makes. None when that revision is no longer kept
    (or the document is not a part)."""
    if entry.doc_type != "part" or expected not in entry.history:
        return None
    try:
        got = _compare(entry, expected, "current")
    except Exception:
        return None
    if got["same"]:
        return {"summary": "nothing visible changed", "same": True}
    params = got["parameters"]
    return {
        "since_revision": expected,
        "added": [i["name"] for i in got["added"]],
        "removed": [i["name"] for i in got["removed"]],
        "edited": [{"name": c["name"], "fields": sorted(c["fields"])}
                   for c in got["changed"]],
        "moved": got["moved"],
        "parameters": params,
        "summary": got["summary"].split(" | ", 1)[-1]
        if " | " in got["summary"] else got["summary"]}


def _absolute(path: str, what: str) -> str:
    if not path or not os.path.isabs(path):
        raise BridgeError("BAD_PATH", "%s needs an absolute path, not %r"
                          % (what, path))
    return os.path.normpath(path)


# ---------------------------------------------------------------- session


@op
def ping(ws: Workspace) -> Dict[str, Any]:
    return {"ok": True}


@op
def status(ws: Workspace) -> Dict[str, Any]:
    return {"app": APP_NAME, "version": __version__,
            "protocol": PROTOCOL_VERSION, "host": "headless",
            "pid": os.getpid(),
            "units": "API lengths are mm, angles degrees",
            "documents": ws.listing()}


@op
def new_document(ws: Workspace, type: str = "part", units: str = "mm",
                 name: str = "") -> Dict[str, Any]:
    if type not in ("part", "assembly"):
        raise BridgeError("NOT_YET", "new %s documents come in a later "
                          "phase; parts and assemblies are supported now"
                          % type)
    from ..core import units as ucore
    if type == "assembly":
        from ..core.assembly import AssemblyDocument
        doc = AssemblyDocument()
    else:
        doc = Document()
    doc.units = ucore.known(units)
    if name:
        doc.properties["Title"] = name
    entry = ws.add(doc, type)
    return {"doc": entry.handle, "revision": entry.revision,
            "units": _units(entry)}


@op
def open_document(ws: Workspace, path: str) -> Dict[str, Any]:
    path = _absolute(path, "open_document")
    held = ws.by_path(path)
    if held is not None:
        ws.active = held.handle
        return {"doc": held.handle, "revision": held.revision,
                "already_open": True, "type": held.doc_type}
    if not os.path.exists(path):
        raise BridgeError("NOT_FOUND", "no such file: %s" % path)
    document = open_file(path)
    kind = fileformat.type_for_path(path) or "part"
    kind = {fileformat.PART: "part", fileformat.ASSEMBLY: "assembly",
            fileformat.DRAWING: "drawing"}.get(kind, kind)
    if kind == "assembly" and hasattr(document, "rebuild"):
        document.rebuild()
    entry = ws.add(document, kind)
    _foreign_code(entry)
    out = {"doc": entry.handle, "type": kind, "revision": entry.revision,
           "units": _units(entry)}
    waiting = _waiting(entry)
    if waiting:
        out["waiting_for_trust"] = waiting
        out["note"] = ("its code features do not run until the user allows "
                       "them in the app (icLogic panel); they are reported "
                       "as waiting for trust, not as broken")
    report = getattr(document, "last_report", None)
    if report is not None and getattr(report, "errors", None):
        out["rebuild_errors"] = [{"feature": fid, "error": msg}
                                 for fid, msg in report.errors]
    return out


def open_file(path: str):
    """Whichever document a file holds. ``open_any`` hands an .icdraw to
    the older drawing class that still lives in core/assembly.py (a test
    pins that), so a drawing is opened here with the real one."""
    from ..core.assembly import open_any
    if fileformat.peek(path).type == fileformat.DRAWING:
        from ..core.drawing import DrawingDocument as SheetDrawing
        return SheetDrawing.load(path)
    return open_any(path)


def _refuse_app_file(target: str, app_open: Any, what: str) -> None:
    """A headless host never writes over a file the app has open: the
    app's copy and this one would drift apart, and whichever saved last
    would win without anyone seeing it (plan section 3)."""
    for held in app_open or ():
        if isinstance(held, dict):
            where, handle = held.get("path", ""), held.get("doc", "")
        else:
            where, handle = str(held), ""
        if same_path(where, target):
            raise BridgeError(
                "FILE_OPEN_IN_APP",
                "%s is open in the app%s; %s from a headless host would "
                "leave two copies of one file" % (
                    target, " as %s" % handle if handle else "", what),
                ["Edit the app's copy%s and save it from there "
                 "(save_document with that handle)." % (
                     " (%s)" % handle if handle else ""),
                 "Or use a different path."])


@op
def save_document(ws: Workspace, doc: str = "", path: str = "",
                  overwrite: bool = False, app_open: Any = None
                  ) -> Dict[str, Any]:
    entry = ws.get(doc)
    target = _absolute(path, "save_document") if path else entry.path
    if not target:
        raise BridgeError("BAD_PATH", "this document has never been saved",
                          ["Give an absolute path ending in .icpart."])
    target = fileformat.ensure_extension(target, entry.document.doc_type)
    _refuse_app_file(target, app_open, "saving over it")
    is_own = bool(entry.path) and os.path.normcase(
        os.path.abspath(entry.path)) == os.path.normcase(target)
    if os.path.exists(target) and not is_own and not overwrite:
        raise BridgeError(
            "WOULD_OVERWRITE", "%s already exists" % target,
            ["Saving over another file cannot be undone. Pass "
             "overwrite: true only if the user asked for it."])
    written = entry.document.save(target)
    return {"doc": entry.handle, "path": written,
            "revision": entry.revision}


@op
def export(ws: Workspace, path: str, doc: str = "",
           overwrite: bool = False, app_open: Any = None) -> Dict[str, Any]:
    entry = ws.get(doc)
    if entry.doc_type == "drawing":
        raise BridgeError("WRONG_TYPE", "%s is a drawing" % entry.handle,
                          ["drawing_export() writes it as PDF, DXF, SVG "
                           "or PNG."])
    path = _absolute(path, "export")
    _refuse_app_file(path, app_open, "exporting onto it")
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".step", ".stp", ".stl", ".iges", ".igs", ".brep"):
        raise BridgeError("BAD_FORMAT", "cannot export %r" % ext,
                          ["Formats: .step .stl .iges .brep"])
    if os.path.exists(path) and not overwrite:
        raise BridgeError("WOULD_OVERWRITE", "%s already exists" % path,
                          ["Pass overwrite: true only if the user asked."])
    shape = shape_of(entry)
    if shape is None:
        raise BridgeError("NO_BODY", "there is nothing to export")
    fileio.write_shape(shape, path)
    return {"path": path, "bytes": os.path.getsize(path)}


@op
def close_document(ws: Workspace, doc: str = "") -> Dict[str, Any]:
    entry = ws.get(doc)
    ws.close(entry.handle)
    return {"closed": entry.handle,
            "unsaved_changes_dropped": bool(
                getattr(entry.document, "modified", False))}


# ---------------------------------------------------------------- reading


def _material_hints(asked: str, known) -> List[str]:
    """Close names first, then the whole list, each name quoted.

    Some names hold commas ("Steel, Mild"), so a comma-joined list read
    as more, shorter names: an agent asked for "Steel" and for
    "Aluminum 6061" before it found the real ones.
    """
    import difflib
    names = sorted(known)
    low = asked.lower()
    close = [n for n in names if n.lower().startswith(low)
             or low in n.lower().split(", ")[0]]
    close += [n for n in difflib.get_close_matches(asked, names, 3, 0.6)
              if n not in close]
    hints = []
    if close:
        hints.append("Did you mean %s?" % " or ".join('"%s"' % n
                                                     for n in close[:3]))
    hints.append("Known (ic://materials): %s" % "; ".join(
        '"%s"' % n for n in names))
    return hints


def _parameters(document: Document) -> List[Dict[str, Any]]:
    document.params.evaluate_all()
    out = []
    for name in document.params.names():
        p = document.params[name]
        item = {"name": name, "expression": p.expression,
                "value": round(p.value, 6)}
        if p.comment:
            item["comment"] = p.comment
        if p.error:
            item["error"] = p.error
        out.append(item)
    return out


@op
def model_tree(ws: Workspace, doc: str = "") -> Dict[str, Any]:
    entry = ws.get(doc)
    d = entry.document
    out: Dict[str, Any] = {"doc": entry.handle, "type": entry.doc_type,
                           "revision": entry.revision,
                           "units": _units(entry), "path": entry.path}
    if entry.doc_type == "part":
        errors = dict(getattr(d.last_report, "errors", []) or [])
        feats = []
        for f in d.features:
            item = {"id": f.id, "name": f.name, "type": f.type_name,
                    "summary": f.summary()}
            if f.suppressed:
                item["suppressed"] = True
            err = errors.get(f.id) or getattr(f, "error", "")
            if err and core_rules.WAITING_FOR_TRUST in err:
                item["waiting_for_trust"] = True
            elif err:
                item["error"] = err
            deps = f.depends_on()
            if deps:
                item["uses"] = deps
            feats.append(item)
        out["features"] = feats
        out["parameters"] = _parameters(d)
        out["bodies"] = [getattr(b, "name", str(i))
                         for i, b in enumerate(d.bodies)]
        if d.requirements:
            out["requirements"] = reqs.summary(
                d.last_report.requirements or reqs.check(d))
    elif entry.doc_type == "assembly":
        out.update(assembly_ops.tree(entry))
    elif entry.doc_type == "drawing":
        out.update(drawing_ops.tree(entry))
    if entry.doc_type == "part" and len(d.model_states) > 1:
        out["model_states"] = state_ops.summary_of(d)
    return out


@op
def properties(ws: Workspace, doc: str = "",
               parameters: Optional[Dict[str, Any]] = None,
               remove: Optional[List[str]] = None,
               props: Optional[Dict[str, str]] = None,
               material: str = "",
               expected_revision: Optional[int] = None,
               appearance: str = "") -> Dict[str, Any]:
    """Read, or change, parameters, iProperties, material and appearance."""
    entry = ws.get(doc)
    if entry.doc_type == "assembly":
        return assembly_ops.properties(ws, entry, parameters, remove, props,
                                       material, expected_revision,
                                       appearance)
    if entry.doc_type == "drawing":
        if appearance:
            raise BridgeError("WRONG_TYPE", "a drawing has no appearance")
        return drawing_ops.properties(ws, entry, parameters, remove, props,
                                      material, expected_revision)
    d = _need_part(entry)
    changed = bool(parameters or remove or props or material or appearance)
    if changed:
        _check_revision(entry, expected_revision)
        d.push_undo()
        before = d.snapshot()
        job = Build(entry)
        try:
            for name, spec in (parameters or {}).items():
                expr, comment = (spec.get("expression"), spec.get("comment")) \
                    if isinstance(spec, dict) else (spec, None)
                if expr is not None:
                    # the same storage rule as build: nothing an inch part
                    # keeps can be read in the wrong unit
                    unit = getattr(d.params[name], "unit", "mm") \
                        if name in d.params else "mm"
                    expr = job.stored(expr, {"deg": "angle", "ul": "count"}
                                      .get(unit, "length"), name)
                if name in d.params:
                    if expr is not None:
                        d.params.set_expression(name, str(expr))
                    if comment is not None:
                        d.params[name].comment = str(comment)
                elif expr is not None:
                    d.params.add(name, str(expr), comment=comment or "")
                else:
                    raise BridgeError("BAD_VALUE", "%s needs an expression"
                                      % name)
            for name in (remove or []):
                if name in d.params:
                    d.params.remove(name)
            set_properties(d, props, material, appearance)
            bad = [p for p in _parameters(d) if p.get("error")]
            if bad:
                raise BridgeError("BAD_EXPRESSION", "; ".join(
                    "%s: %s" % (p["name"], p["error"]) for p in bad))
            d.rebuild()
        except Exception:
            d.load_dict(json.loads(before))
            d._undo.pop() if d._undo else None
            d.rebuild()
            raise
        entry.touch()
    return {"doc": entry.handle, "revision": entry.revision,
            "parameters": _parameters(d), "properties": dict(d.properties),
            "material": d.material, "appearance": d.appearance,
            "colour": d.material_appearance.colour,
            "rebuild": _report(d),
            **({"reqs": _requirements(d)["summary"]}
               if d.requirements else {})}


def _requirements(d: Document) -> Dict[str, Any]:
    results = list(getattr(d.last_report, "requirements", []) or [])
    return {"results": results, "summary": reqs.summary(results)}


def _report(d: Document) -> Dict[str, Any]:
    r = d.last_report
    return {"ok": bool(r.ok), "errors": [{"feature": fid, "error": msg}
                                         for fid, msg in r.errors],
            "warnings": list(r.warnings)}


# tolerance relative to the value, for expectations
DEFAULT_TOL = 0.01
EXPECT_KEYS = {"bbox", "volume", "mass_g", "solids", "faces", "valid",
               "tolerance"}


@op
def inspect(ws: Workspace, doc: str = "",
            expected: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    entry = ws.get(doc)
    shape = shape_of(entry)
    m = metrics(shape)
    out: Dict[str, Any] = {"doc": entry.handle, "revision": entry.revision,
                           "units": _units(entry)}
    out.update(m)
    valid = shape is not None and not shape.IsNull()
    if valid:
        from OCP.BRepCheck import BRepCheck_Analyzer
        valid = bool(BRepCheck_Analyzer(shape).IsValid())
    out["valid"] = valid
    if entry.doc_type == "part" and shape is not None:
        mp = entry.document.mass_properties()
        out["mass_g"] = round(mp.get("mass_g", 0.0), 3)
        out["material"] = entry.document.material
        out["centre_of_mass"] = [round(c, 4) for c in mp.get("centre", ())]
        out["rebuild"] = _report(entry.document)
    if expected:
        out["verdict"] = _verdict(out, expected)
    return out


def _verdict(found: Dict[str, Any], expected: Dict[str, Any]
             ) -> Dict[str, Any]:
    unknown = set(expected) - EXPECT_KEYS
    if unknown:
        # an expectation that cannot be checked must not quietly pass
        raise BridgeError(
            "BAD_EXPECTATION", "cannot check: %s" % ", ".join(sorted(unknown)),
            ["Checkable: %s" % ", ".join(sorted(EXPECT_KEYS))])
    tol = float(expected.get("tolerance", DEFAULT_TOL))
    checks = []

    def near(a, b):
        return abs(a - b) <= max(tol * abs(b), 1e-6)

    for key, want in expected.items():
        if key == "tolerance":
            continue
        got = found.get(key)
        if key == "bbox":
            have = sorted(got or [0, 0, 0])
            ok = got is not None and all(near(a, b) for a, b in
                                         zip(have, sorted(want)))
            note = "compared sorted, so orientation does not matter"
        elif isinstance(want, bool):
            ok, note = got is want, ""
        elif isinstance(want, int) and key in ("solids", "faces"):
            ok, note = got == want, ""
        else:
            ok, note = got is not None and near(float(got), float(want)), ""
        item = {"check": key, "expected": want, "found": got, "pass": ok}
        if note:
            item["note"] = note
        checks.append(item)
    return {"pass": all(c["pass"] for c in checks), "checks": checks,
            "tolerance": tol}


@op
def render_view(ws: Workspace, doc: str = "", view: Any = "iso",
                width: int = 800, height: int = 600, hidden: bool = True,
                highlight_edges: Any = None, highlight: Any = None,
                style: str = "lines", section: Any = None, focus: Any = None
                ) -> Dict[str, Any]:
    entry = ws.get(doc)
    if entry.doc_type == "drawing":
        raise BridgeError("WRONG_TYPE", "%s is a drawing" % entry.handle,
                          ["drawing_render() shows a drawing's sheet."])
    if style not in ("lines", "shaded", "shaded_edges"):
        raise BridgeError("BAD_VALUE", "unknown style %r" % style,
                          ["Use lines, shaded or shaded_edges."])
    if style == "lines" and (section or focus):
        raise BridgeError("BAD_VALUE", "section and focus are for shaded "
                          "views", ['Add style="shaded".'])
    shape = shape_of(entry)
    if shape is None:
        raise BridgeError("NO_BODY", "there is nothing to draw yet")
    width = max(64, min(int(width), 2000))
    height = max(64, min(int(height), 2000))
    lit = list(edgequery.edges(shape, highlight_edges)) \
        if highlight_edges else []
    resolved = []
    if highlight:
        res = refs.resolver_for(entry)
        for ref in (highlight if isinstance(highlight, list)
                    else [highlight]):
            r = res.resolve(ref, "highlight", ("face", "edge", "vertex",
                                               "region", "body"))
            lit += r.shapes
            resolved.append(r.describe())
    lit = lit or None
    if style == "lines":
        png, info = render.render_shape(shape, view, (width, height), hidden,
                                        lit)
    else:
        from . import shade
        items = _drawn_items(entry)
        box = _focus_box(items, focus) if focus else None
        direction, up = render.view_direction(view)
        png, info = shade.render_items(
            items, direction, up, (width, height),
            edges=style == "shaded_edges", section=section, highlight=lit,
            focus=box)
        info["view"] = view if isinstance(view, str) else list(view)
    info["style"] = style
    info["png_base64"] = base64.b64encode(png).decode("ascii")
    info["doc"] = entry.handle
    info["revision"] = entry.revision
    if lit:
        info["highlighted"] = len(lit)
    if resolved:
        info["refs"] = resolved
    return info


def _drawn_items(entry: Entry) -> List[Dict[str, Any]]:
    """What a shaded view draws: shapes, each with the look the app would
    give it, down to the parts inside a sub-assembly."""
    d = entry.document
    if entry.doc_type != "assembly":
        return [{"name": entry.handle, "shape": shape_of(entry),
                 "look": d.material_appearance}]
    out: List[Dict[str, Any]] = []

    def add(name, shape, look, looks=None):
        if isinstance(looks, list):
            children = []
            it = TopoDS_Iterator(shape)
            while it.More():
                children.append(it.Value())
                it.Next()
            if len(children) == len(looks):
                for child, own in zip(children, looks):
                    if isinstance(own, list):
                        add(name, child, look, own)
                    else:
                        add(name, child, own or look)
                return
        out.append({"name": name, "shape": shape, "look": look})

    from ..core import materials
    for o in d.active():
        if o.shape is None or not o.visible:
            continue
        placed = o.placed()
        if placed is None or placed.IsNull():
            continue
        path = o.ref.resolve(d.base_dir) if d.base_dir else None
        look, looks = materials.library().appearance("Default"), None
        if path and os.path.exists(path):
            look = d.library.appearance(path)
            if fileformat.is_assembly(path):
                looks = d.library.looks(path)
        add(o.name, placed, look, looks)
    if not out:
        raise BridgeError("NO_BODY", "there is nothing to draw yet")
    return out


def _focus_box(items: List[Dict[str, Any]], focus: Any) -> List[float]:
    """A box to zoom to: given outright, or round named components."""
    if (isinstance(focus, (list, tuple)) and len(focus) == 6
            and all(isinstance(v, (int, float)) for v in focus)):
        return ([min(focus[i], focus[i + 3]) for i in range(3)]
                + [max(focus[i], focus[i + 3]) for i in range(3)])
    names = [focus] if isinstance(focus, str) else focus
    if not isinstance(names, (list, tuple)) or not all(
            isinstance(n, str) for n in names):
        raise BridgeError("BAD_VALUE", "focus is component name(s) or a box "
                          "[x0, y0, z0, x1, y1, z1]")
    found = [it for it in items if it["name"] in names]
    missing = set(names) - {it["name"] for it in found}
    if missing:
        raise BridgeError(
            "BAD_REF", "no component %s to focus on"
            % ", ".join(sorted(missing)),
            ["Here: %s" % ", ".join(sorted({it["name"] for it in items}))])
    boxes = [kernel.bounding_box(it["shape"]) for it in found]
    return ([min(b[i] for b in boxes) for i in range(3)]
            + [max(b[i] for b in boxes) for i in range(3, 6)])


# ---------------------------------------------------------------- build


@op
def build(ws: Workspace, ops: List[Dict[str, Any]], doc: str = "",
          dry_run: bool = False, keep_partial: bool = False,
          expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Apply a list of ops as one change."""
    entry = ws.get(doc)
    d = _need_part(entry)
    _check_revision(entry, expected_revision)
    if not isinstance(ops, list) or not ops:
        raise BridgeError("BAD_OP", "ops must be a non-empty list")
    before_state = d.snapshot()
    before = metrics(d.shape)
    known_errors = {fid for fid, _ in d.last_report.errors}
    known_warnings = set(d.last_report.warnings)
    job = Build(entry)
    waiting: Dict[int, str] = {}
    failure: Optional[Dict[str, Any]] = None
    done = 0
    for i, spec in enumerate(ops):
        try:
            if ws.should_cancel():
                raise BridgeError(
                    "CANCELLED", "stopped by the user before op %d" % i,
                    ["The user pressed Stop in the app. Nothing was kept "
                     "of this build; ask what they want before trying "
                     "again."])
            if not isinstance(spec, dict):
                raise BridgeError("BAD_OP", "op %d is not an object" % i)
            job.run(spec, i)
            if (not keep_partial and i + 1 < len(ops)
                    and _needs_no_body(d, spec)
                    and _needs_no_body(d, ops[i + 1])):
                # a run of parameters and sketch rewrites is rebuilt once:
                # six sections rewritten under a heavy body rebuilt it six
                # times over, which is what ran a script out of its 120 s
                done += 1
                continue
            d.rebuild()
            new_errors = [(fid, msg) for fid, msg in d.last_report.errors
                          if fid not in known_errors]
            for fid, msg in new_errors:
                if core_rules.WAITING_FOR_TRUST in msg:
                    waiting[fid] = msg
            new_errors = [(fid, msg) for fid, msg in new_errors
                          if fid not in waiting]
            if new_errors:
                raise BridgeError(
                    "FEATURE_FAILED", new_errors[0][1],
                    classify(RuntimeError(new_errors[0][1]))["hints"])
            done += 1
        except Exception as exc:
            failure = classify(exc)
            failure["at"] = {"index": i, "op": spec.get("op")
                             if isinstance(spec, dict) else None,
                             "id": spec.get("id")
                             if isinstance(spec, dict) else None}
            break

    after = metrics(d.shape)
    roll_back = dry_run or (failure is not None and not keep_partial)
    kept = done if not roll_back else 0
    result: Dict[str, Any] = {
        "ok": failure is None, "doc": entry.handle,
        "applied": kept, "of": len(ops), "dry_run": bool(dry_run),
        "created": job.created if not roll_back else [],
        "changed": job.changed if not roll_back else [],
        "removed": job.removed if not roll_back else [],
        "before": before, "after": after,
        "delta": _delta(before, after),
        "notes": job.notes, "units": _units(entry),
    }
    if job.vias:
        result["refs"] = job.vias
    # what the rebuild noticed: a pick found by where it was and not by the
    # feature that made it, an edge that could not be found
    fresh = [w for w in d.last_report.warnings if w not in known_warnings]
    if fresh and not roll_back:
        result["warnings"] = fresh
    still = {f.id: f.name for f in d.features}
    waiting_names = [still[fid] for fid in waiting if fid in still]
    if waiting_names and not roll_back:
        result["waiting_for_trust"] = waiting_names
    if dry_run:
        result["would_create"] = job.created
        result["would_change"] = job.changed
        result["would_remove"] = job.removed
    if failure is None:
        lint = job.lint()
        if lint:
            result["lint"] = lint
    else:
        result["error"] = failure
    if roll_back:
        d.load_dict(json.loads(before_state))
        d.rebuild()
        if failure is not None and not dry_run:
            result["rolled_back"] = True
    else:
        # one undo step for the whole build, as a person's edit would be
        d._undo.append(before_state)
        d._redo.clear()
        job.commit()
        entry.touch()
    result["revision"] = entry.revision
    got = _requirements(d)
    if got["results"]:
        result["requirements"] = got["results"]
        result["reqs"] = got["summary"]
    result["summary"] = _summary(result, d)
    return result


def _needs_no_body(d: Document, spec: Any) -> bool:
    """An op that reads nothing a rebuild makes."""
    if not isinstance(spec, dict):
        return False
    if spec.get("op") == "parameter":
        return True
    if spec.get("op") != "edit":
        return False
    fields = set(spec.get("set") or {}) | (
        set(spec) - {"op", "id", "feature", "set"})
    if not fields or fields - {"entities", "constraints", "dimensions",
                               "auto_constrain", "sketch", "comments"}:
        return False
    which = spec.get("feature")
    if isinstance(which, int):
        target = d.feature(which)
    else:
        target = next((f for f in d.features if f.name == which), None)
    return target is not None and target.type_name == "sketch"


def _delta(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    return {k: round(b[k] - a[k], 3) for k in ("volume", "solids", "faces",
                                                 "edges")}


def _summary(r: Dict[str, Any], d: Document) -> str:
    head = ("dry run" if r["dry_run"] else "build ok") if r["ok"] else \
        "build FAILED at op %d (%s): %s" % (
            r["error"]["at"]["index"], r["error"]["kind"],
            r["error"]["message"])
    made = " ".join(
        ["+%s" % c["name"] for c in r["created"] or r.get("would_create")
         or []]
        + ["~%s" % c["name"] for c in r["changed"] or r.get("would_change")
           or []]
        + ["-%s" % c["name"] for c in r["removed"] or r.get("would_remove")
           or []])
    a, dl = r["after"], r["delta"]
    geo = "V %s mm³ (%s) | F %d E %d | %d solid%s" % (
        _fmt(a["volume"]), _signed(dl["volume"]), a["faces"], a["edges"],
        a["solids"], "" if a["solids"] == 1 else "s")
    bits = [head]
    if made:
        bits.append(made)
    bits += [geo, "rev %d" % r["revision"]]
    if r.get("rolled_back"):
        bits.append("rolled back")
    if r.get("reqs"):
        bits.append(r["reqs"])
    if r.get("waiting_for_trust"):
        bits.append("waiting for trust: %s" % ", ".join(
            r["waiting_for_trust"]))
    if r.get("lint"):
        bits.append("lint: %d" % len(r["lint"]))
    if r.get("warnings"):
        bits.append("warnings: %d" % len(r["warnings"]))
    return " | ".join(bits)


# ---------------------------------------------------------------- the tree


def _find(entry: Entry, ref: Any):
    job = Build(entry)
    return entry.document.feature(job.feature_id(ref, "feature"))


@op
def edit_feature(ws: Workspace, feature: Any, doc: str = "",
                 params: Optional[Dict[str, Any]] = None,
                 suppress: Optional[bool] = None, move_to: Any = None,
                 delete: bool = False, delete_dependents: bool = False,
                 rename: str = "", dry_run: bool = False,
                 expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Change one feature: its fields, suppression, place or existence.

    With nothing to change it reports the feature, as the op ``build``
    takes, and what depends on it. A delete of a feature others use is
    refused, naming them, unless ``delete_dependents``."""
    entry = ws.get(doc)
    if entry.doc_type == "assembly":
        return assembly_ops.edit_item(
            ws, entry, feature, params, suppress, delete, delete_dependents,
            rename, dry_run, expected_revision)
    if entry.doc_type == "drawing":
        return drawing_ops.edit_item(
            ws, entry, feature, params, suppress, delete, delete_dependents,
            rename, dry_run, expected_revision)
    d = _need_part(entry)
    f = _find(entry, feature)
    job = Build(entry)
    deps = job.dependents(f.id)
    dep_list = [{"id": g.id, "name": g.name, "type": g.type_name}
                for g in deps]
    ops: List[Dict[str, Any]] = []
    if delete:
        if deps and not delete_dependents:
            raise BridgeError(
                "HAS_DEPENDENTS", "%s is used by %s" % (
                    f.name, ", ".join(g.name for g in deps)),
                ["Pass delete_dependents: true to delete them as well, or "
                 "change them to use something else first."],
                dependents=dep_list)
        ops.append({"op": "remove", "feature": f.id,
                    "dependents": "remove" if delete_dependents
                    else "refuse"})
    else:
        changes: Dict[str, Any] = dict(params or {})
        if suppress is not None:
            changes["suppressed"] = bool(suppress)
        if rename:
            changes["name"] = rename
        if changes:
            ops.append({"op": "edit", "feature": f.id, "set": changes})
        if move_to is not None:
            ops.append(_move_op(f.id, move_to))
    if not ops:
        read = ir.to_ir(d, [f.id], parameters=False)
        return {"doc": entry.handle, "revision": entry.revision,
                "feature": read[0] if read else None,
                "dependents": dep_list, "summary": f.summary()}
    result = build(ws, ops=ops, doc=entry.handle, dry_run=dry_run,
                   expected_revision=expected_revision)
    result["dependents"] = dep_list
    return result


def _move_op(fid: int, where: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"op": "move", "feature": fid}
    if isinstance(where, dict):
        out.update({k: v for k, v in where.items()
                    if k in ("before", "after", "to")})
    elif isinstance(where, int) or where in ("end", "start"):
        out["to"] = where
    elif isinstance(where, str) and ":" in where:
        side, _sep, target = where.partition(":")
        if side not in ("before", "after"):
            raise BridgeError("BAD_OP", "move_to: before:<feature>, "
                              "after:<feature>, an index, end or start")
        out[side] = target
    else:
        out["before"] = where
    return out


@op
def read_ir(ws: Workspace, doc: str = "",
            features: Optional[List[Any]] = None,
            parameters: Optional[bool] = None) -> Dict[str, Any]:
    """A part's tree as the ops build takes, so it can be built again."""
    entry = ws.get(doc)
    d = _need_part(entry)
    ids = None
    if features:
        ids = [_find(entry, ref).id for ref in features]
    if parameters is None:
        parameters = ids is None
    out = {"doc": entry.handle, "revision": entry.revision,
           "units": _units(entry), "material": d.material,
           "ops": ir.to_ir(d, ids, parameters=bool(parameters))}
    if d.sheet_metal is not None:
        out["note"] = ("the part's sheet metal rules (thickness, bend "
                       "radius, K-factor) are not ops: sheet_rules() "
                       "reads and sets them (+sheetmetal group)")
    return out


@op
def op_schema(ws: Workspace, type: str = "") -> Dict[str, Any]:
    """The JSON schema of one op, or the list of every op."""
    if not type:
        return {"ops": ir.index()}
    try:
        return ir.schema(type)
    except KeyError as exc:
        raise BridgeError("UNKNOWN_OP", "no op %r" % type,
                          ["Ops: %s" % ", ".join(FEATURE_TYPES)]) from exc


# ---------------------------------------------------------------- sketches


@op
def sketch_status(ws: Workspace, sketch: Any, doc: str = ""
                  ) -> Dict[str, Any]:
    """Degrees of freedom, what is loose, conflicts and regions."""
    entry = ws.get(doc)
    d = _need_part(entry)
    f = _find(entry, sketch)
    if not isinstance(f, SketchFeature):
        raise BridgeError("WRONG_TYPE", "%s is a %s, not a sketch"
                          % (f.name, f.type_name))
    names = dict(entry.sketch_names.get(f.id) or {})
    sk = d.all_sketches().get(f.id) or f.sketch
    sk.solve(d.parameter_scope())
    out = sketchir.describe(sk, names)
    job = Build(entry)
    try:
        regions = job.regions(f.id)
    except Exception:
        regions = []
    out["regions"] = [{"index": i, "area": round(r["area"], 4),
                       "centre": [round(c, 4) for c in r["centre"]]}
                      for i, r in enumerate(regions)]
    out.update({"doc": entry.handle, "revision": entry.revision,
                "sketch": f.name, "id": f.id,
                "plane": {"origin": list(sk.plane.origin),
                          "normal": list(sk.plane.normal),
                          "xdir": list(sk.plane.xdir)}})
    return out


# ---------------------------------------------------------------- history


@op
def snapshot(ws: Workspace, action: str = "list", name: str = "",
             doc: str = "", expected_revision: Optional[int] = None
             ) -> Dict[str, Any]:
    """Named copies of a document, in memory: save, restore, list, drop."""
    entry = ws.get(doc)
    d = _need_part(entry)
    if action == "save":
        name = name or "s%d" % (len(entry.snapshots) + 1)
        entry.snapshots[name] = {"state": d.snapshot(),
                                 "revision": entry.revision,
                                 "features": len(d.features)}
        return {"doc": entry.handle, "saved": name,
                "revision": entry.revision}
    if action == "list":
        return {"doc": entry.handle, "revision": entry.revision,
                "snapshots": [{"name": k, "revision": v["revision"],
                               "features": v["features"]}
                              for k, v in entry.snapshots.items()]}
    if action in ("restore", "drop"):
        held = entry.snapshots.get(name)
        if held is None:
            raise BridgeError("NOT_FOUND", "no snapshot %r" % name,
                              ["Snapshots: %s" % (", ".join(entry.snapshots)
                                                  or "none")])
        if action == "drop":
            del entry.snapshots[name]
            return {"doc": entry.handle, "dropped": name}
        _check_revision(entry, expected_revision)
        d.push_undo()
        d.load_dict(json.loads(held["state"]))
        d.rebuild()
        entry.touch()
        return {"doc": entry.handle, "restored": name,
                "revision": entry.revision, "from_revision": held["revision"],
                "rebuild": _report(d), "after": metrics(d.shape)}
    raise BridgeError("BAD_VALUE", "action is save, restore, list or drop")


def _state(entry: Entry, which: Any) -> Tuple[str, Dict[str, Any]]:
    if which in (None, "", "current"):
        return "current (rev %d)" % entry.revision, json.loads(
            entry.document.snapshot())
    if isinstance(which, int) or (isinstance(which, str) and
                                  which.lstrip("-").isdigit()):
        rev = int(which)
        if rev < 0:
            rev = entry.revision + rev
        if rev == entry.revision:
            return _state(entry, "current")
        held = entry.history.get(rev)
        if held is None:
            raise BridgeError(
                "NOT_FOUND", "revision %d is not kept" % rev,
                ["Kept revisions: %s" % ", ".join(
                    str(r) for r in sorted(entry.history))])
        return "rev %d" % rev, json.loads(held)
    name = str(which)
    if name.startswith(("branch:", "version:")):
        return branch_ops.state_of(entry, name)
    if name.startswith("snapshot:"):
        name = name[len("snapshot:"):]
    held = entry.snapshots.get(name)
    if held is None:
        raise BridgeError("NOT_FOUND", "no revision or snapshot %r" % which,
                          ["Give a revision number, a snapshot name or "
                           "\"current\"."])
    return "snapshot %s" % name, json.loads(held["state"])


def _short_value(v: Any) -> Any:
    text = json.dumps(v)
    return v if len(text) <= 120 else text[:117] + "..."


def _sketch_diff(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ("entities", "constraints", "points"):
        na, nb = len(a.get(key, [])), len(b.get(key, []))
        if na != nb:
            out[key] = [na, nb]
    dims_a = {c.get("name"): c for c in a.get("constraints", [])
              if c.get("name")}
    dims_b = {c.get("name"): c for c in b.get("constraints", [])
              if c.get("name")}
    changed = {}
    for n in sorted(set(dims_a) | set(dims_b)):
        ca, cb = dims_a.get(n), dims_b.get(n)
        va = (ca.get("expression") or ca.get("value")) if ca else None
        vb = (cb.get("expression") or cb.get("value")) if cb else None
        if va != vb:
            changed[n] = [va, vb]
    if changed:
        out["dimensions"] = changed
    if a.get("plane") != b.get("plane"):
        out["plane"] = "moved"
    if not out and a != b:
        out["geometry"] = "changed"
    return out


@op
def diff(ws: Workspace, doc: str = "", from_: Any = None, to: Any = None,
         **kw) -> Dict[str, Any]:
    """What changed between two revisions or snapshots of a part."""
    if "from" in kw:
        from_ = kw.pop("from")
    if kw:
        raise BridgeError("BAD_VALUE", "unknown argument(s) %s"
                          % ", ".join(kw))
    entry = ws.get(doc)
    _need_part(entry)
    if from_ is None:
        from_ = entry.revision - 1 if entry.revision > 1 else entry.revision
    return _compare(entry, from_, to)


def _compare(entry: Entry, from_: Any, to: Any) -> Dict[str, Any]:
    la, a = _state(entry, from_)
    lb, b = _state(entry, to)
    fa = {f["id"]: f for f in a.get("features", [])}
    fb = {f["id"]: f for f in b.get("features", [])}
    order_a = [f["id"] for f in a.get("features", [])]
    order_b = [f["id"] for f in b.get("features", [])]
    added = [{"id": i, "name": fb[i]["name"], "type": fb[i]["type"]}
             for i in order_b if i not in fa]
    removed = [{"id": i, "name": fa[i]["name"], "type": fa[i]["type"]}
               for i in order_a if i not in fb]
    changed = []
    for i in order_b:
        if i not in fa or fa[i] == fb[i]:
            continue
        x, y = fa[i], fb[i]
        fields: Dict[str, Any] = {}
        for k in sorted(set(x) | set(y)):
            if x.get(k) == y.get(k) or k in ("param_names",):
                continue
            if k == "sketch":
                fields[k] = _sketch_diff(x.get(k) or {}, y.get(k) or {})
            else:
                fields[k] = [_short_value(x.get(k)), _short_value(y.get(k))]
        changed.append({"id": i, "name": y["name"], "type": y["type"],
                        "fields": fields})
    common_a = [i for i in order_a if i in fb]
    common_b = [i for i in order_b if i in fa]
    moved = [fb[i]["name"] for n, i in enumerate(common_b)
             if common_a[n] != i]
    pa = {p["name"]: p for p in a.get("parameters", [])}
    pb = {p["name"]: p for p in b.get("parameters", [])}
    params = {"added": {n: pb[n]["expression"] for n in pb if n not in pa},
              "removed": sorted(n for n in pa if n not in pb),
              "changed": {n: [pa[n]["expression"], pb[n]["expression"]]
                          for n in pb if n in pa
                          and pa[n].get("expression") != pb[n].get("expression")
                          }}
    other = sorted(k for k in set(a) | set(b)
                   if k not in ("features", "parameters", "next_id", "view")
                   and a.get(k) != b.get(k))
    same = not (added or removed or changed or moved or params["added"]
                or params["removed"] or params["changed"] or other)
    bits = ["%s -> %s" % (la, lb)]
    if same:
        bits.append("no change")
    for label, items in (("+", added), ("-", removed), ("~", changed)):
        if items:
            bits.append(" ".join(label + it["name"] for it in items))
    if moved:
        bits.append("moved " + ", ".join(moved))
    pchanges = (len(params["added"]) + len(params["removed"])
                + len(params["changed"]))
    if pchanges:
        bits.append("%d parameter change(s)" % pchanges)
    return {"doc": entry.handle, "from": la, "to": lb, "same": same,
            "added": added, "removed": removed, "changed": changed,
            "moved": moved, "parameters": params, "document": other,
            "summary": " | ".join(bits)}


# ---------------------------------------------------------------- code trust


def _foreign_code(entry: Entry) -> None:
    """Remember the code an opened file brought, so that writing the same
    source in a build is not a way round the user's trust."""
    from ..core.features import CodeFeature
    for f in getattr(entry.document, "features", []) or []:
        if isinstance(f, CodeFeature) and not core_rules.code_trusted(
                f.source):
            entry.foreign_code.add(core_rules.code_hash(f.source))


def _waiting(entry: Entry) -> List[str]:
    if entry.doc_type != "part":
        return []
    return [f.name for f in core_rules.code_waiting(entry.document)]


# ---------------------------------------------------------------- geometry


@op
def find_geometry(ws: Workspace, doc: str = "", what: str = "face",
                  where: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Faces, edges or vertices by rule, each with an @ handle."""
    entry = ws.get(doc)
    _need_part(entry)
    out = refs.find(entry, what, where or {})
    out["summary"] = "%d %s(s) matched%s" % (
        out["matched"], out["kind"],
        "" if out["found"] == out["matched"]
        else ", %d kept" % out["found"])
    return out


@op
def measure(ws: Workspace, a: Any, b: Any = None, doc: str = ""
            ) -> Dict[str, Any]:
    """Sizes of one reference, or how two relate."""
    from . import measure as measure_mod
    entry = ws.get(doc)
    if entry.doc_type != "assembly":
        _need_part(entry)
    return measure_mod.measure(entry, a, b)


@op
def ref_schema(ws: Workspace) -> Dict[str, Any]:
    return dict(refs.GRAMMAR)


@op
def guide_facts(ws: Workspace) -> Dict[str, Any]:
    """The tables the guides (ic://guide/...) are written from, read from
    the code itself, so a guide cannot say what the code no longer does:
    op types, sketch vocabulary, the ref grammar, query keys, requirement
    metrics, code-feature helpers, units, profile families and the error
    kinds with their hints."""
    import inspect as pyinspect
    from ..core import constraints3d as c3
    from ..core import frames, geometry, units
    from ..core.params import CONSTANTS, FUNCTIONS
    from . import errors as errors_mod
    from .build import FACE_KEYS

    def signature(fn):
        try:
            parts = []
            for p in pyinspect.signature(fn).parameters.values():
                text = ("*" if p.kind == p.VAR_POSITIONAL else "") + p.name
                if p.default is not p.empty:
                    text += "=%r" % (p.default,)
                parts.append(text)
            return "%s(%s)" % (fn.__name__, ", ".join(parts))
        except (TypeError, ValueError, AttributeError):
            return getattr(fn, "__name__", "?")

    helpers = {name: signature(fn) for name, fn in geometry.namespace().items()
               if callable(fn) and not isinstance(fn, type)
               and name not in ("math",)}
    def methods(cls):
        return [signature(getattr(cls, n)).replace("(self, ", "(")
                .replace("(self)", "()") for n in sorted(vars(cls))
                if not n.startswith("_") and callable(getattr(cls, n))]

    solid_methods = methods(geometry.Solid)
    profile_methods = methods(geometry.Profile)
    sheet = [name for name in FEATURE_TYPES
             if "Thickness" in str(ir.defaults(name).get("thickness", ""))]
    return {
        "ops": ir.index(),
        "sheet_metal_ops": sheet,
        "sketch": {"entities": list(sketchir.ENTITY_SHAPES),
                   "constraints": sorted(set(sketchir.KINDS)
                                         - set(sketchir.DIMENSIONS)),
                   "dimensions": list(sketchir.DIMENSIONS),
                   "signatures": {k: list(v) for k, v in
                                  sketchir.SIGNATURES.items()},
                   "usage": dict(sketchir.USAGE)},
        "refs": dict(refs.GRAMMAR),
        "find_keys": list(refs.FIND_KEYS),
        "face_types": list(refs.FACE_TYPES),
        "edge_types": list(refs.EDGE_TYPES),
        "face_query_keys": list(FACE_KEYS),
        "edge_query_keys": list(edgequery.KNOWN),
        "requirements": {"metrics": list(reqs.METRICS),
                         "keys": list(reqs.KEYS),
                         "default_tolerance": reqs.DEFAULT_TOLERANCE},
        "code_helpers": helpers,
        "solid_methods": solid_methods,
        "solid_operators": {"+": "union", "-": "difference",
                            "&": "intersection"},
        "profile_methods": profile_methods,
        "units": {"api": "mm", "angles": "deg",
                  "documents": dict(units.LABELS)},
        "expressions": {"constants": sorted(CONSTANTS),
                        "functions": sorted(FUNCTIONS)},
        "profile_families": [
            {"family": f.id, "kind": f.kind, "columns": list(f.columns),
             "sizes": f.sizes()[:4] + (["..."] if len(f.sizes()) > 4
                                       else [])}
            for f in frames.families()],
        "assembly": {"kinds": dict(c3.KIND_HINTS)},
        "drawing": drawing_ops.facts(),
        "errors": {k: {"means": v[0], "fix": v[1]}
                   for k, v in errors_mod.KINDS.items()},
        "materials": sorted(_materials_lib().materials),
    }


def _materials_lib():
    from ..core import materials
    return materials.library()


@op
def materials(ws: Workspace) -> Dict[str, Any]:
    from ..core import materials as mat
    lib = mat.library().materials
    return {"materials": [{"name": n, "density_g_cm3": round(m.density, 4)}
                          for n, m in sorted(lib.items())]}


# ---------------------------------------------------------------- requirements


@op
def requirements(ws: Workspace, doc: str = "",
                 set: Optional[List[Dict[str, Any]]] = None,
                 remove: Optional[List[str]] = None, check: bool = False,
                 expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Read, set or remove a part's requirements; they are checked on
    every rebuild. Setting one of an existing name replaces it."""
    from . import measure as measure_mod
    entry = ws.get(doc)
    d = _need_part(entry)
    changing = bool(set or remove)
    if changing:
        _check_revision(entry, expected_revision)
        parsed = []
        for spec in set or []:
            if not isinstance(spec, dict):
                raise BridgeError("BAD_REQUIREMENT", "a requirement is an "
                                  "object")
            spec = dict(spec)
            if spec.get("metric") == "clearance":
                for end in ("a", "b"):
                    if end in spec:
                        spec[end] = measure_mod.capture_end(entry, spec[end])
            try:
                parsed.append(reqs.Requirement.from_dict(spec))
            except reqs.RequirementError as exc:
                raise BridgeError(exc.kind, str(exc), exc.hints) from exc
        missing = [n for n in (remove or []) if d.requirements.get(n) is None]
        if missing:
            raise BridgeError("NOT_FOUND", "no requirement %s" % ", ".join(
                missing), ["Requirements: %s" % (", ".join(
                    r.name for r in d.requirements) or "none")])
        before = d.snapshot()
        for r in parsed:
            d.requirements.put(r)
        for name in remove or []:
            d.requirements.remove(name)
        d.rebuild()
        d._undo.append(before)
        d._redo.clear()
        d.modified = True
        entry.touch()
    elif check:
        d.rebuild()
    results = reqs.check(d) if (check or not changing) else \
        list(d.last_report.requirements or [])
    return {"doc": entry.handle, "revision": entry.revision,
            "requirements": d.requirements.to_list(), "results": results,
            "summary": reqs.summary(results) or "no requirements"}


# ---------------------------------------------------------------- scripts

SCRIPT_TIMEOUT = 60.0
SCRIPT_TIMEOUT_MAX = 240.0


@op
def script_exec(ws: Workspace, data: Dict[str, Any], code: str,
                path: str = "", safe_mode: bool = False,
                trusted: bool = False, trusted_code: Any = (),
                sketch_names: Any = None) -> Dict[str, Any]:
    """Run a script on a copy (in the child host run_script starts)."""
    from . import script
    return script.execute(ws, data, code, path=path, safe_mode=safe_mode,
                          trusted=trusted, trusted_code=trusted_code,
                          sketch_names=sketch_names)


def _script_child(data: Dict[str, Any], path: str, code: str,
                  timeout: float, safe_mode: bool, trusted: bool,
                  trusted_code: Any, sketch_names: Any) -> Dict[str, Any]:
    """Run ``code`` in a child host on ``data``; its answer, or a
    BridgeError. The one place a script is ever run."""
    from . import safemode
    from .client import HostClient, HostLost, RemoteError
    if not isinstance(code, str) or not code.strip():
        raise BridgeError("BAD_VALUE", "code is empty")
    if safe_mode:
        try:
            safemode.check(code)
        except safemode.SafeModeViolation as exc:
            raise BridgeError("SAFE_MODE", "line %d: %s" % (exc.line, exc),
                              ["safe_mode refuses this; use the helpers, "
                               "or run without safe_mode if the user "
                               "agrees."], line=exc.line) from exc
    else:
        try:
            compile(code, "<script>", "exec")
        except SyntaxError as exc:
            raise BridgeError("SCRIPT_FAILED", "line %d: %s" % (
                exc.lineno or 0, exc.msg), line=exc.lineno or 0) from exc
    timeout = max(1.0, min(float(timeout or SCRIPT_TIMEOUT),
                           SCRIPT_TIMEOUT_MAX))
    child = HostClient(timeout=timeout)
    try:
        answer = child.call("script_exec", {
            "data": data, "code": code, "path": path or "",
            "safe_mode": bool(safe_mode), "trusted": bool(trusted),
            "trusted_code": list(trusted_code or ()),
            "sketch_names": sketch_names or {}})
    except HostLost as exc:
        if "did not answer" in str(exc):
            raise BridgeError(
                "TIMEOUT", "the script ran past %g s and was stopped"
                % timeout, ["Nothing was changed. Give a longer timeout "
                            "(up to %g s) or do less per call."
                            % SCRIPT_TIMEOUT_MAX]) from exc
        raise BridgeError("SCRIPT_CRASHED", "the script's host died: %s"
                          % exc, ["Nothing was changed; the document is "
                                  "as it was."]) from exc
    except RemoteError as exc:
        raise BridgeError(exc.data.get("kind", "SCRIPT_FAILED"),
                          exc.data.get("message", "failed"),
                          exc.data.get("hints", [])) from exc
    finally:
        child.stop()
    if not answer.get("ok"):
        err = answer.get("error") or {}
        raise BridgeError(err.get("kind", "SCRIPT_FAILED"),
                          err.get("message", "the script failed"),
                          err.get("hints", []), line=err.get("line", 0),
                          output=answer.get("output", ""))
    return answer


def _script_plan(before: Document, answer: Dict[str, Any]) -> Dict[str, Any]:
    """What a script left, as the build ops that make it so: plain data,
    which any host may apply (the app applies it, never the script)."""
    from . import script
    ops_list, origin, notes = script.tree_ops(before, answer["data"])
    plan: Dict[str, Any] = {
        "ops": ops_list, "origin": origin, "notes": notes,
        "output": answer.get("output", ""),
        "sketch_names": answer.get("sketch_names") or {}}
    if answer.get("result") is not None:
        plan["result"] = answer["result"]
    return plan


def _script_apply(ws: Workspace, entry: Entry, plan: Dict[str, Any],
                  dry_run: bool) -> Dict[str, Any]:
    """Apply a plan as one build, the way run_script always did."""
    ops_list = plan.get("ops") or []
    notes = list(plan.get("notes") or [])
    base = {"output": plan.get("output", ""), "script_ops": len(ops_list)}
    if plan.get("result") is not None:
        base["result"] = plan["result"]
    if not ops_list:
        m = metrics(entry.document.shape)
        out = {"ok": True, "doc": entry.handle, "applied": 0, "of": 0,
               "dry_run": bool(dry_run), "created": [], "changed": [],
               "removed": [], "before": m, "after": m,
               "delta": _delta(m, m), "notes": notes, "units": _units(entry),
               "revision": entry.revision}
        out.update(base)
        out["summary"] = "run_script ok | no change to the model | rev %d" \
            % entry.revision
        return out
    result = build(ws, ops=ops_list, doc=entry.handle, dry_run=dry_run)
    result.update(base)
    result["notes"] = list(result.get("notes") or []) + notes
    if result["ok"] and not dry_run:
        names = plan.get("sketch_names") or {}
        origin = plan.get("origin") or {}
        for made in result.get("created", []):
            old = origin.get(made.get("op_id") or "")
            if old is not None and str(old) in names:
                entry.sketch_names[made["id"]] = {
                    n: tuple(v) for n, v in names[str(old)].items()}
    if dry_run:
        result["ops"] = ops_list
    result["summary"] = "run_script: " + result["summary"]
    return result


@op
def run_script(ws: Workspace, code: str, doc: str = "",
               timeout: float = SCRIPT_TIMEOUT, safe_mode: bool = False,
               dry_run: bool = False,
               expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Python against datum.core, in a separate host on a copy; what it
    changed comes back as build ops and is applied as one build."""
    entry = ws.get(doc)
    d = _need_part(entry)
    _check_revision(entry, expected_revision)
    answer = _script_child(
        d.to_dict(), d.path or "", code, timeout, safe_mode,
        core_rules.document_trusted(d), core_rules.trusted_code_in(d),
        {str(k): {n: list(v) for n, v in m.items()}
         for k, m in entry.sketch_names.items()})
    return _script_apply(ws, entry, _script_plan(d, answer), dry_run)


@op
def script_prepare(ws: Workspace, doc: str = "") -> Dict[str, Any]:
    """Everything a script needs to run on a copy of this document,
    elsewhere: the app's run_script is done by the server in a headless
    host, with this, and applied back with script_apply."""
    entry = ws.get(doc)
    d = _need_part(entry)
    return {"doc": entry.handle, "revision": entry.revision,
            "data": d.to_dict(), "path": d.path or "",
            "trusted": core_rules.document_trusted(d),
            "trusted_code": core_rules.trusted_code_in(d),
            "sketch_names": {str(k): {n: list(v) for n, v in m.items()}
                             for k, m in entry.sketch_names.items()}}


@op
def script_plan(ws: Workspace, data: Dict[str, Any], code: str,
                path: str = "", timeout: float = SCRIPT_TIMEOUT,
                safe_mode: bool = False, trusted: bool = False,
                trusted_code: Any = (), sketch_names: Any = None
                ) -> Dict[str, Any]:
    """Run a script on ``data`` and say what it changed, as build ops.
    Headless hosts only: it is what keeps the app from running code."""
    answer = _script_child(data, path, code, timeout, safe_mode, trusted,
                           trusted_code, sketch_names)
    before = Document()
    before.path = path or ""
    before.load_dict(data)
    return _script_plan(before, answer)


@op
def script_apply(ws: Workspace, plan: Dict[str, Any], doc: str = "",
                 dry_run: bool = False,
                 expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Apply a script's plan (ops, as data) to a document as one build."""
    entry = ws.get(doc)
    _need_part(entry)
    _check_revision(entry, expected_revision)
    return _script_apply(ws, entry, plan, dry_run)


# ---------------------------------------------------------------- dispatch


def call(ws: Workspace, method: str, params: Dict[str, Any]
         ) -> Dict[str, Any]:
    fn = OPS.get(method)
    if fn is None:
        raise BridgeError("UNKNOWN_METHOD", "no method %r" % method,
                          ["Methods: %s" % ", ".join(sorted(OPS))])
    return fn(ws, **(params or {}))


# assemblies: place_component, constrain, assembly_check, bom, and the
# assembly branches of model_tree, properties, edit_feature, measure
from . import assembly_ops  # noqa: E402,F401
# drawings (the +drawing group), model states, branches
from . import drawing_ops, state_ops  # noqa: E402,F401
from . import branch_ops  # noqa: E402,F401
from . import design_ops  # noqa: E402,F401
# evaluate and optimise: variants on the worker pool
from . import explore_ops  # noqa: E402,F401
# build_project: many parts and their assembly in one call
from . import project_ops  # noqa: E402,F401
from . import import_ops  # noqa: E402,F401
