"""Sheet metal, frames and skeletons through the bridge.

Three groups of tools, each a thin layer over the core's own pieces
(``core/sheetmetal.py``, ``core/frames.py``, ``core/assembly_params.py``):

``+sheetmetal``  ``sheet_rules`` (the part's sheet metal style: thickness,
                 bend radius, K-factor), ``flat_pattern`` (size, bend
                 list, DXF), ``sheet_check`` (manufacturing rules).
``+frames``      ``frame_profiles`` (the profile library), ``frame_insert``
                 (members along skeleton lines), ``frame_treat`` (miter,
                 corner, trim, notch, lengthen), ``cut_list``.
``+skeleton``    ``skeleton_params`` (retrieve a skeleton's parameters),
                 ``derive_part`` (a part's parameters follow the skeleton's
                 by expression), ``skeleton_set`` (change a master
                 parameter; every derived part and the frame follow).

A skeleton is a part of layout sketches and master parameters. Nothing new
is stored for "derive": the assembly's *drivers* (``assembly_params``) are
the core's own way for an expression across parts to drive a part, so a
derived part is an ordinary part, opens and builds on its own, and the
relationship lives in the assembly where the app's Parameters table shows it.
"""

from __future__ import annotations

import csv
import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core import bom as core_bom
from ..core import fileformat, frames, kernel, sheetmetal
from ..core.assembly import AssemblyDocument
from ..core.assembly_params import AssemblyParameters
from ..core.document import Document
from ..core.kernel import KernelError
from ..core.params import ExpressionError, evaluate
from . import assembly_ops, ops
from .assembly_ops import (_apply, _num, _stamped, component_file,
                           find_occurrence, need_assembly, report_info)
from .build import Build
from .errors import BridgeError
from .workspace import Entry, Workspace, same_path

op = ops.op

# the rules sheet_check judges by, stated so an answer can quote them;
# thickness t, inside bend radius r
RULES = {
    "min_bend_radius": "0.5 t (error below; a note below 1 t)",
    "k_factor": "0.25 to 0.5 for steel and aluminium (error outside 0 to 1)",
    "min_flange_height": "4 t outside (the leg after the bend 2 t at least)",
    "hole_to_bend": "2 t from a hole's edge to the bend's tangent line",
}


def _need_part(entry: Entry) -> Document:
    return ops._need_part(entry)


def _scope(d: Document) -> Dict[str, float]:
    return d.parameter_scope()


def _value(d: Document, text: str) -> float:
    return float(evaluate(str(text), _scope(d)))


# ---------------------------------------------------------------- sheet rules


def _rules(d: Document) -> Dict[str, Any]:
    sm = d.sheet_metal
    out: Dict[str, Any] = {"sheet_metal": sm is not None}
    names = set(d.params.names())
    if sm is None:
        out["note"] = ("not converted: flat_pattern and sheet_check read "
                       "the Thickness and BendRadius parameters if the "
                       "part has them; sheet_rules() converts it")
    thickness = sm.thickness if sm else "Thickness"
    radius = sm.bend_radius if sm else "BendRadius"
    k = sm.k_factor if sm else sheetmetal.DEFAULT_K
    gap = sm.gap if sm else "Thickness"
    for key, expr in (("thickness", thickness), ("bend_radius", radius),
                      ("k_factor", k), ("gap", gap)):
        try:
            out[key] = _num(_value(d, expr), 5)
        except (ExpressionError, Exception):                  # noqa: BLE001
            out[key] = None
        out[key + "_expression"] = expr
    out["has_parameters"] = {"Thickness": "Thickness" in names,
                             "BendRadius": "BendRadius" in names}
    return out


@op
def sheet_rules(ws: Workspace, doc: str = "", thickness: Any = None,
                bend_radius: Any = None, k_factor: Any = None,
                gap: Any = None, dry_run: bool = False,
                expected_revision: Optional[int] = None) -> Dict[str, Any]:
    """Read, or set, a part's sheet metal rules."""
    entry = ws.get(doc)
    d = _need_part(entry)
    changing = any(v is not None for v in (thickness, bend_radius,
                                           k_factor, gap))
    if changing:
        ops._check_revision(entry, expected_revision)
        before = d.snapshot()
        d.push_undo()
        job = Build(entry)
        try:
            sm = d.sheet_metal or sheetmetal.SheetMetalDefaults(
                "Thickness", "BendRadius", sheetmetal.DEFAULT_K)
            names = set(d.params.names())
            if "Thickness" not in names:
                if thickness is None:
                    try:
                        thickness = sheetmetal.measure(d)
                    except (KernelError, ValueError):
                        thickness = None
                if thickness is None:
                    raise BridgeError(
                        "BAD_VALUE", "the part has no Thickness parameter "
                        "and no body to measure one from",
                        ["Pass thickness (mm or an expression)."])
                d.params.add("Thickness", job.stored(thickness, "length",
                                                     "thickness"), d.units,
                             "Sheet metal thickness")
            elif thickness is not None:
                d.params.set_expression("Thickness", job.stored(
                    thickness, "length", "thickness"))
            if "BendRadius" not in names:
                d.params.add("BendRadius", job.stored(
                    bend_radius if bend_radius is not None else "Thickness",
                    "length", "bend_radius"), d.units,
                    "Sheet metal bend radius")
            elif bend_radius is not None:
                d.params.set_expression("BendRadius", job.stored(
                    bend_radius, "length", "bend_radius"))
            sm.thickness, sm.bend_radius = "Thickness", "BendRadius"
            if k_factor is not None:
                kk = float(job.number(k_factor, "k_factor"))
                if not 0.0 <= kk <= 1.0:
                    raise BridgeError("BAD_VALUE", "k_factor is between 0 "
                                      "and 1, not %s" % k_factor)
                sm.k_factor = ("%.6g" % kk)
            if gap is not None:
                sm.gap = job.stored(gap, "length", "gap")
            d.sheet_metal = sm
            d.modified = True
            bad = [p for p in ops._parameters(d) if p.get("error")]
            if bad:
                raise BridgeError("BAD_EXPRESSION", "; ".join(
                    "%s: %s" % (p["name"], p["error"]) for p in bad))
            d.rebuild()
            out_rules = _rules(d)
        except Exception:
            d.load_dict(json.loads(before))
            if d._undo:
                d._undo.pop()
            d.rebuild()
            raise
        if dry_run:
            d.load_dict(json.loads(before))
            if d._undo:
                d._undo.pop()
            d.rebuild()
            out_rules["dry_run"] = True
        else:
            entry.touch()
    else:
        out_rules = _rules(d)
    out_rules.update({"doc": entry.handle, "revision": entry.revision,
                      "rebuild": ops._report(d)})
    out_rules["summary"] = "sheet rules | t %s mm | r %s mm | K %s | rev %d" % (
        out_rules.get("thickness"), out_rules.get("bend_radius"),
        out_rules.get("k_factor"), entry.revision)
    return out_rules


# ---------------------------------------------------------------- flat pattern


class _Temp:
    """Sheet metal rules a part is read with when it was never converted:
    its Thickness and BendRadius parameters, and a K-factor. Put back."""

    def __init__(self, d: Document, k_factor: Any) -> None:
        self.d, self.k = d, k_factor
        self.was = d.sheet_metal
        self.was_k = self.was.k_factor if self.was else None

    def __enter__(self):
        d = self.d
        if d.sheet_metal is None:
            if "Thickness" not in d.params.names():
                raise BridgeError(
                    "NOT_SHEET_METAL", "this part has no sheet metal "
                    "rules and no Thickness parameter",
                    ["sheet_rules(thickness=1.5, bend_radius=1.5, "
                     "k_factor=0.44) converts it; build sheet_face and "
                     "flange features first."])
            d.sheet_metal = sheetmetal.SheetMetalDefaults(
                "Thickness", "BendRadius" if "BendRadius" in d.params.names()
                else "Thickness", sheetmetal.DEFAULT_K)
        if self.k is not None:
            d.sheet_metal.k_factor = "%.6g" % float(self.k)
        return d.sheet_metal

    def __exit__(self, *exc):
        d = self.d
        if self.was is None:
            d.sheet_metal = None
        elif self.was_k is not None:
            d.sheet_metal.k_factor = self.was_k
        return False


def _flat(d: Document, k_factor: Any):
    with _Temp(d, k_factor):
        try:
            return sheetmetal.flat_pattern(d)
        except KernelError as exc:
            raise BridgeError(
                "FLAT_FAILED", "cannot lay it flat: %s" % exc,
                ["A bend must be a round bend of one thickness: a sharp "
                 "corner or a corner without a relief cannot be unfolded. "
                 "sheet_check() lists what is wrong; flanges meeting at a "
                 "corner relieve it themselves, or add a corner_seam.",
                 "A part that is not sheet metal has no flat pattern."])


def _holes(flat) -> List[Dict[str, Any]]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopoDS import TopoDS
    out = []
    for face in flat.faces:
        outer = BRepTools.OuterWire_s(TopoDS.Face_s(face))
        for wire in kernel.explore(face, TopAbs_WIRE):
            if wire.IsSame(outer):
                continue
            box = Bnd_Box()
            BRepBndLib.AddOptimal_s(wire, box, False, False)
            lo, hi = box.CornerMin(), box.CornerMax()
            out.append({"centre": ((lo.X() + hi.X()) / 2,
                                   (lo.Y() + hi.Y()) / 2),
                        "half": max(hi.X() - lo.X(), hi.Y() - lo.Y()) / 2})
    return out


def _bend_rows(flat, x0: float, y0: float) -> List[Dict[str, Any]]:
    rows = []
    for i, (a, b, angle) in enumerate(flat.bends):
        info = flat.bend_info[i] if i < len(flat.bend_info) else {}
        rows.append({
            "bend": i + 1, "angle": _num(angle, 3),
            "radius": _num(info.get("radius", 0.0), 4),
            "toward": info.get("toward", ""),
            "length": _num(math.dist(a, b), 3),
            "allowance": _num(info.get("allowance", 0.0), 4),
            "line": [[_num(a[0] - x0, 3), _num(a[1] - y0, 3)],
                     [_num(b[0] - x0, 3), _num(b[1] - y0, 3)]]})
    return rows


@op
def flat_pattern(ws: Workspace, doc: str = "", path: str = "",
                 bend_lines: bool = True, k_factor: Any = None,
                 overwrite: bool = False, app_open: Any = None
                 ) -> Dict[str, Any]:
    """A sheet metal part laid flat: size, bend list, optionally a DXF."""
    entry = ws.get(doc)
    d = _need_part(entry)
    if path:
        path = ops._absolute(path, "flat_pattern")
        if os.path.splitext(path)[1].lower() != ".dxf":
            raise BridgeError("BAD_FORMAT", "a flat pattern is written as "
                              ".dxf, not %r" % os.path.splitext(path)[1])
        ops._refuse_app_file(path, app_open, "writing it")
        if os.path.exists(path) and not overwrite:
            raise BridgeError("WOULD_OVERWRITE", "%s already exists" % path,
                              ["Pass overwrite: true only if the user "
                               "asked."])
    flat = _flat(d, k_factor)
    x0, y0, x1, y1 = flat.box()
    rules = _rules(d)
    k = k_factor if k_factor is not None else rules.get("k_factor")
    area = sum(kernel.face_area(f) for f in flat.faces)
    holes = _holes(flat)
    out: Dict[str, Any] = {
        "doc": entry.handle, "revision": entry.revision,
        "length": _num(max(x1 - x0, y1 - y0), 3),
        "width": _num(min(x1 - x0, y1 - y0), 3),
        "extent_xy": [_num(x1 - x0, 3), _num(y1 - y0, 3)],
        "thickness": _num(flat.thickness, 4), "k_factor": k,
        "area_mm2": _num(area, 2), "holes": len(holes),
        "bend_count": len(flat.bends),
        "bends": _bend_rows(flat, x0, y0),
        "mass_g": _num(area * flat.thickness / 1000.0
                       * float(getattr(d, "density", 1.0) or 1.0), 2),
        "material": d.material,
    }
    errors = [(f.name, f.error) for f in d.sheet_metal.flat_features
              if getattr(f, "error", "")] if d.sheet_metal else []
    if errors:
        out["warnings"] = ["%s: %s" % e for e in errors]
    if path:
        written = sheetmetal.flat_to_dxf(flat, path, bend_lines)
        out["path"] = written
        out["bytes"] = os.path.getsize(written)
        out["layers"] = ["OUTER_PROFILE"] + (
            ["BEND_CENTERLINE"] if bend_lines and flat.bends else [])
    out["summary"] = "flat %s x %s mm, t %s | %d bend%s | %d hole%s%s" % (
        out["length"], out["width"], out["thickness"], len(flat.bends),
        "" if len(flat.bends) == 1 else "s", len(holes),
        "" if len(holes) == 1 else "s",
        " | wrote %s" % os.path.basename(path) if path else "")
    return out


# ---------------------------------------------------------------- sheet check


def _check(level: str, what: str, text: str, **more: Any) -> Dict[str, Any]:
    return dict({"level": level, "check": what, "message": text}, **more)


@op
def sheet_check(ws: Workspace, doc: str = "") -> Dict[str, Any]:
    """Manufacturing rules for a sheet metal part, reported as numbers."""
    from ..core.features import (ContourFlangeFeature, CornerSeamFeature,
                                 FlangeFeature, HemFeature)
    entry = ws.get(doc)
    d = _need_part(entry)
    rules = _rules(d)
    t = rules.get("thickness")
    if not t:
        raise BridgeError("NOT_SHEET_METAL", "no sheet thickness known",
                          ["sheet_rules(thickness=...) sets it."])
    k = rules.get("k_factor")
    r0 = rules.get("bend_radius") or 0.0
    findings: List[Dict[str, Any]] = []
    scope = _scope(d)

    # the rules themselves
    if r0 < 0.5 * t - 1e-9:
        findings.append(_check(
            "error", "bend_radius", "the bend radius %.3g mm is under "
            "0.5 t (%.3g mm): the sheet is likely to crack" % (r0, 0.5 * t),
            value=r0, minimum=0.5 * t))
    elif r0 < t - 1e-9:
        findings.append(_check(
            "note", "bend_radius", "the bend radius %.3g mm is under 1 t "
            "(%.3g mm): fine in soft aluminium, tight in steel" % (r0, t),
            value=r0, minimum=t))
    if k is None or not 0.0 <= k <= 1.0:
        findings.append(_check("error", "k_factor",
                               "the K-factor %s is not between 0 and 1" % k))
    elif not 0.25 <= k <= 0.5:
        findings.append(_check(
            "warning", "k_factor", "the K-factor %.3g is outside the usual "
            "0.25 to 0.5 for steel and aluminium; the flat will be off "
            "unless it was measured for your tooling" % k, value=k))

    # every flange, from what it says
    flanges = []
    seams = 0
    for f in d.features:
        if getattr(f, "suppressed", False):
            continue
        if isinstance(f, CornerSeamFeature):
            seams += 1
        if isinstance(f, (FlangeFeature, ContourFlangeFeature)):
            try:
                ft = float(evaluate(f.thickness, scope))
                fr = float(evaluate(f.bend_radius, scope))
            except Exception:                                  # noqa: BLE001
                continue
            heights = []
            if isinstance(f, FlangeFeature):
                try:
                    heights = [float(evaluate(f.height, scope))]
                except Exception:                              # noqa: BLE001
                    heights = []
            for h in heights:
                leg = h - ft - fr
                row = {"feature": f.name, "height": _num(h, 3),
                       "leg": _num(leg, 3), "min_height": _num(4 * ft, 3),
                       "edges": len(f.edges)}
                flanges.append(row)
                if h < 4 * ft - 1e-9 or leg < 2 * ft - 1e-9:
                    findings.append(_check(
                        "error", "min_flange", "%s: the flange is %.3g mm "
                        "high outside (the leg after the bend %.3g mm); the "
                        "least a press brake holds is 4 t = %.3g mm (leg "
                        "2 t)" % (f.name, h, leg, 4 * ft),
                        feature=f.name, height=h, minimum=4 * ft))
        if isinstance(f, HemFeature):
            flanges.append({"feature": f.name, "hem": True})

    # the flat: unfolds only if every bend is round and ends in relief
    flat = None
    relief: Dict[str, Any] = {"unfolds": False}
    try:
        flat = _flat(d, None)
        relief["unfolds"] = True
    except BridgeError as exc:
        findings.append(_check(
            "error", "relief", str(exc),
            hint="a corner between two bends needs a relief of at least "
                 "t wide and t + r deep"))
    relief["corner_seams"] = seams
    relief["min_width"] = _num(t, 4)
    relief["min_depth"] = _num(t + r0, 4)
    bends: List[Dict[str, Any]] = []
    holes_near: List[Dict[str, Any]] = []
    if flat is not None:
        x0, y0, _x1, _y1 = flat.box()
        bends = _bend_rows(flat, x0, y0)
        for row in bends:
            ratio = row["radius"] / t if t else 0.0
            row["radius_over_t"] = _num(ratio, 3)
            if row["radius"] < 0.5 * t - 1e-9 and not any(
                    f["check"] == "bend_radius" for f in findings):
                findings.append(_check(
                    "error", "bend_radius", "bend %d has a radius of %.3g mm"
                    ", under 0.5 t" % (row["bend"], row["radius"])))
        # a hole near a bend is stretched by it
        for h in _holes(flat):
            for i, (a, b, _ang) in enumerate(flat.bends):
                info = flat.bend_info[i] if i < len(flat.bend_info) else {}
                half_band = info.get("allowance", 0.0) / 2.0
                ax, ay = a
                bx, by = b
                dx, dy = bx - ax, by - ay
                span = dx * dx + dy * dy
                s = 0.0 if span == 0 else max(0.0, min(1.0, (
                    (h["centre"][0] - ax) * dx + (h["centre"][1] - ay) * dy)
                    / span))
                dist = math.dist(h["centre"], (ax + s * dx, ay + s * dy))
                gap = dist - half_band - h["half"]
                if gap < 2 * t - 1e-9:
                    holes_near.append({
                        "hole_at": [_num(h["centre"][0] - x0, 2),
                                    _num(h["centre"][1] - y0, 2)],
                        "bend": i + 1, "distance": _num(gap, 3),
                        "minimum": _num(2 * t, 3)})
                    findings.append(_check(
                        "warning", "hole_to_bend", "a hole at (%.1f, %.1f) "
                        "is %.2f mm from bend %d's tangent; keep 2 t = "
                        "%.3g mm or it will stretch" % (
                            h["centre"][0] - x0, h["centre"][1] - y0, gap,
                            i + 1, 2 * t)))
    errors = [f for f in findings if f["level"] == "error"]
    warns = [f for f in findings if f["level"] == "warning"]
    out = {"doc": entry.handle, "revision": entry.revision,
           "ok": not errors, "rules": rules, "thresholds": RULES,
           "flanges": flanges, "bends": bends, "relief": relief,
           "holes_near_bends": holes_near, "findings": findings}
    out["summary"] = ("sheet check %s | t %.3g r %.3g K %s | %d bend%s | "
                      "%d error%s %d warning%s | rev %d" % (
                          "ok" if not errors else "FAILED", t, r0, k,
                          len(bends), "" if len(bends) == 1 else "s",
                          len(errors), "" if len(errors) == 1 else "s",
                          len(warns), "" if len(warns) == 1 else "s",
                          entry.revision))
    return out


# ---------------------------------------------------------------- frames


@op
def frame_profiles(ws: Workspace, family: str = "") -> Dict[str, Any]:
    """The profile library: families and their sizes."""
    out = []
    for fam in frames.families():
        if family and family.lower() not in (fam.id.lower(),
                                             fam.name.lower()) \
                and family.lower() not in fam.category.lower() \
                and family.lower() not in fam.standard.lower():
            continue
        row = {"id": fam.id, "name": fam.name, "standard": fam.standard,
               "category": fam.category, "kind": fam.kind,
               "columns": list(fam.columns)}
        row["sizes"] = fam.sizes() if family else fam.sizes()[:6] + (
            ["..."] if len(fam.sizes()) > 6 else [])
        row["size_count"] = len(fam.sizes())
        out.append(row)
    if not out:
        raise BridgeError("NOT_FOUND", "no profile family matches %r"
                          % family,
                          ["frame_profiles() lists every family."])
    return {"families": out,
            "summary": "%d profile famil%s" % (
                len(out), "y" if len(out) == 1 else "ies")}


def _skeleton_of(d: AssemblyDocument, skeleton: Any):
    o = find_occurrence(d, skeleton, "skeleton")
    path = component_file(d, o)
    if not fileformat.is_part(path):
        raise BridgeError("WRONG_TYPE", "%s is not a part" % o.name,
                          ["The skeleton is a part of layout sketches."])
    return o, path


def _sketch_of(sketches, which: Any, path: str):
    found = None
    if isinstance(which, int) and not isinstance(which, bool):
        found = which if which in sketches else None
    else:
        text = str(which).strip()
        for sid, (_p, name, _l) in sketches.items():
            if sid > 0 and name == text:
                found = sid
        if found is None and text.isdigit() and int(text) in sketches:
            found = int(text)
    if found is None:
        names = [s[1] for sid, s in sketches.items() if sid > 0 and s[2]]
        raise BridgeError(
            "NO_SKETCH", "the skeleton has no sketch %r with lines" % which,
            ["Sketches with lines: %s" % (", ".join(names) or "none"),
             "Build them in the skeleton part, save it, and place it."])
    return found


def _frame_occurrence(d: AssemblyDocument, frame: Any):
    o = find_occurrence(d, frame, "frame")
    path = component_file(d, o)
    if not frames.is_frame(path):
        raise BridgeError("WRONG_TYPE", "%s is not a frame" % o.name,
                          ["frame_insert() makes one; name it by its "
                           "occurrence, such as Frame0001:1."])
    return o, path


def _member_rows(frame_doc, sketches=None) -> List[Dict[str, Any]]:
    fd = frame_doc.frame
    if sketches is None:
        sketches = frames.skeleton_sketches(frames.skeleton_path(frame_doc))
    rows = []
    for m in fd.members:
        row: Dict[str, Any] = {
            "id": m.id, "profile": m.size, "family": m.family,
            "part": m.part,
            "sketch": sketches[m.sketch][1] if m.sketch in sketches else ""}
        try:
            a, b = frames.run_of(sketches[m.sketch][2], m.lines)
            row["from"] = [_num(c, 3) for c in a]
            row["to"] = [_num(c, 3) for c in b]
            row["length"] = _num(math.dist(a, b), 3)
        except (KeyError, KernelError):
            row["error"] = "its line is gone from the skeleton"
        if m.error:
            row["error"] = m.error
        rows.append(row)
    return rows


@op
def frame_insert(ws: Workspace, doc: str = "", skeleton: Any = "",
                 sketch: Any = "", profile: str = "", size: str = "",
                 lines: Any = "all", frame: Any = "", anchor: str = "mc",
                 offset_a: float = 0.0, offset_b: float = 0.0,
                 rotate: float = 0.0, mirror: bool = False,
                 merge: bool = False, material: str = "",
                 dry_run: bool = False, expected_revision: Optional[int] = None,
                 app_open: Any = None) -> Dict[str, Any]:
    """Members of a profile on skeleton lines, in a frame beside the
    assembly (the first insert makes the frame, later ones add to it)."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    if not d.path:
        raise BridgeError(
            "BAD_PATH", "save the assembly first: the frame's files go in "
            "a folder beside it",
            ["save_document(doc=%r, path=<absolute .icasm>)" % entry.handle])
    sk_occ, sk_path = _skeleton_of(d, skeleton)
    sketches = frames.skeleton_sketches(sk_path)
    sid = _sketch_of(sketches, sketch, sk_path)
    lines_all = sorted(sketches[sid][2])
    if lines in ("all", None, ""):
        picked = lines_all
    else:
        picked = [int(i) for i in (lines if isinstance(lines, list)
                                   else [lines])]
        missing = [i for i in picked if i not in lines_all]
        if missing:
            raise BridgeError("BAD_VALUE", "sketch %s has no line %s"
                              % (sketches[sid][1], missing),
                              ["Its lines: %s" % lines_all])
    try:
        fam = frames.family(profile)
        fam.row(size)
    except KeyError:
        raise BridgeError(
            "NO_PROFILE", "no profile %r size %r" % (profile, size),
            ["frame_profiles() lists families; frame_profiles(family=%r) "
             "lists one's sizes." % (profile or "square")])
    frame_occ = None
    if frame not in ("", None):
        frame_occ, _p = _frame_occurrence(d, frame)
    if not dry_run:
        for target in (os.path.join(d.base_dir, d.title),):
            ops._refuse_app_file(target, app_open, "writing the frame in it")
    box: Dict[str, Any] = {}

    def mutate():
        frame_doc, occ, problems = frames.insert(
            d, sk_occ, sid, picked, profile, size, anchor=anchor,
            offset_a=offset_a, offset_b=offset_b, rotate=rotate,
            mirror=mirror, merge=merge, material=material,
            frame_occurrence=frame_occ)
        box["problems"] = problems
        d.rebuild()
        return frame_doc, occ

    def finish(made, report):
        frame_doc, occ = made
        rows = _member_rows(frame_doc)
        out: Dict[str, Any] = {
            "frame": occ.name, "file": os.path.basename(frame_doc.path),
            "members": rows, "member_count": len(rows),
            "assembly": report_info(report)}
        if box.get("problems"):
            out["warnings"] = list(box["problems"])
        out["summary"] = ("frame %s | %d member%s on %s (%s) | %d in "
                          "the frame | rev @REV@" % (
                              occ.name, len(picked),
                              "" if len(picked) == 1 else "s",
                              sketches[sid][1], size, len(rows)))
        return out

    return _stamped(_apply(entry, mutate, finish, dry_run, "frame_insert",
                           expected_revision))


def _corner_pairs(frame_doc, sketches, within: Optional[Sequence[int]]
                  ) -> List[Tuple[int, int]]:
    """Every two members that meet end to end at an angle."""
    fd = frame_doc.frame
    ends = {}
    for m in fd.members:
        if within is not None and m.id not in within:
            continue
        try:
            ends[m.id] = frames.run_of(sketches[m.sketch][2], m.lines)
        except (KeyError, KernelError):
            continue
    ids = sorted(ends)
    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            pa, qa = ends[a]
            pb, qb = ends[b]
            if not any(math.dist(p, q) < 1e-6 for p in (pa, qa)
                       for q in (pb, qb)):
                continue
            da = [qa[k] - pa[k] for k in range(3)]
            db = [qb[k] - pb[k] for k in range(3)]
            cross = [da[1] * db[2] - da[2] * db[1],
                     da[2] * db[0] - da[0] * db[2],
                     da[0] * db[1] - da[1] * db[0]]
            if math.sqrt(sum(c * c for c in cross)) > 1e-6 * max(
                    1.0, math.dist(pa, qa) * math.dist(pb, qb)):
                pairs.append((a, b))
    return pairs


@op
def frame_treat(ws: Workspace, doc: str = "", frame: Any = "",
                kind: str = "miter", members: Any = None, others: Any = None,
                corners: bool = False, sketch: Any = "", gap: float = 0.0,
                split: bool = True, extend: bool = True,
                point: Any = None, normal: Any = None, offset: float = 0.0,
                amount: float = 0.0, side: str = "b", remove: bool = False,
                dry_run: bool = False, expected_revision: Optional[int] = None,
                app_open: Any = None) -> Dict[str, Any]:
    """End treatments on a frame's members."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    occ, fpath = _frame_occurrence(d, frame)
    ops._refuse_app_file(fpath, app_open, "changing the frame")
    if kind not in frames.TREATMENTS:
        raise BridgeError("BAD_VALUE", "no end treatment %r" % kind,
                          ["Kinds: %s" % ", ".join(frames.TREATMENTS)])
    ids = [int(i) for i in (members or [])]
    box: Dict[str, Any] = {}

    def mutate():
        frame_doc = AssemblyDocument.load(fpath)
        sketches = frames.skeleton_sketches(frames.skeleton_path(frame_doc))
        fd = frame_doc.frame
        if remove:
            n = frames.remove_treatments(
                frame_doc, ids or [m.id for m in fd.members])
            box["removed"] = n
            d.rebuild()
            return frame_doc
        use = list(ids)
        if corners:
            if kind != "miter":
                raise BridgeError("BAD_VALUE", "corners=true is for miters")
            within = None
            if sketch not in ("", None):
                sid = _sketch_of(sketches, sketch, "")
                within = [m.id for m in fd.members if m.sketch == sid]
            elif ids:
                within = ids
            pairs = _corner_pairs(frame_doc, sketches, within)
            if not pairs:
                raise BridgeError(
                    "BAD_VALUE", "no two members meet at an angle "
                    "here", ["members=[a, b] miters two named members."])
            use = [i for pair in pairs for i in pair]
            box["pairs"] = pairs
        params: Dict[str, Any] = {}
        if kind == "miter":
            params = {"gap": gap, "split": split}
        elif kind == "corner":
            params = {"gap": gap, "extend": extend}
        elif kind == "trim_face":
            params = {"point": list(point or []), "normal": list(normal or []),
                      "offset": offset}
        elif kind == "notch":
            params = {"gap": gap}
        elif kind == "lengthen":
            params = {"amount": amount, "side": side}
        try:
            treatment, problems = frames.add_treatment(
                frame_doc, kind, use, [int(i) for i in (others or [])],
                **params)
        except ValueError as exc:
            raise BridgeError("BAD_VALUE", str(exc), [
                "miter takes members two by two; corner and notch take "
                "members and others; trim_face a point and a normal; "
                "lengthen an amount."]) from exc
        box["treatment"], box["problems"] = treatment, problems
        d.rebuild()
        return frame_doc

    def finish(frame_doc, report):
        out: Dict[str, Any] = {"frame": occ.name,
                               "members": _member_rows(frame_doc),
                               "treatments": [
                                   {"id": t.id, "kind": t.kind,
                                    "members": t.members,
                                    "others": t.others}
                                   for t in frame_doc.frame.treatments],
                               "assembly": report_info(report)}
        if box.get("problems"):
            out["warnings"] = list(box["problems"])
        if remove:
            out["summary"] = "removed %d end treatment(s) | rev @REV@" % (
                box.get("removed", 0))
        else:
            n = len(box["pairs"]) if "pairs" in box else len(
                box["treatment"].members)
            out["summary"] = "%s on %s | %d %s | %d treatment(s) in the " \
                "frame | rev @REV@" % (
                    kind, occ.name, n, "corner(s)" if "pairs" in box
                    else "member(s)", len(frame_doc.frame.treatments))
        return out

    return _stamped(_apply(entry, mutate, finish, dry_run, "frame_treat",
                           expected_revision))


def _end_angles(part_doc) -> Tuple[float, float, List[str]]:
    """How far from square each end of a member is cut, in degrees, and
    what else is done to it."""
    from ..core.features import FrameEndsFeature
    cut = next((f for f in part_doc.features
                if isinstance(f, FrameEndsFeature)), None)
    if cut is None:
        return 0.0, 0.0, []
    try:
        length = float(cut.length)
    except (TypeError, ValueError):
        length = 0.0
    angles = {"a": 0.0, "b": 0.0}
    for c in cut.cuts or []:
        z, nz = float(c[2]), float(c[5])
        end = "a" if z < (length + float(cut.extend_a) - float(
            cut.extend_b)) / 2.0 - float(cut.extend_a) else "b"
        angles[end] = math.degrees(math.acos(min(1.0, abs(nz))))
    extra = []
    if cut.notches:
        extra.append("%d notch(es)" % len(cut.notches))
    return angles["a"], angles["b"], extra


@op
def cut_list(ws: Workspace, doc: str = "", frame: Any = "", path: str = "",
             overwrite: bool = False, app_open: Any = None
             ) -> Dict[str, Any]:
    """The pieces to cut: profile, length, end angles, quantity, mass."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    if frame not in ("", None):
        occs = [_frame_occurrence(d, frame)[0]]
    else:
        occs = []
        for o in d.occurrences:
            p = d.component_path(o)
            if p and fileformat.is_assembly(p) and frames.is_frame(p):
                occs.append(o)
    if not occs:
        raise BridgeError("NO_FRAME", "this assembly has no frame",
                          ["frame_insert() makes one on a skeleton."])
    if path:
        path = ops._absolute(path, "cut_list")
        if os.path.splitext(path)[1].lower() != ".csv":
            raise BridgeError("BAD_FORMAT", "a cut list is written as .csv")
        ops._refuse_app_file(path, app_open, "writing it")
        if os.path.exists(path) and not overwrite:
            raise BridgeError("WOULD_OVERWRITE", "%s already exists" % path,
                              ["Pass overwrite: true only if the user "
                               "asked."])
    pieces: List[Dict[str, Any]] = []
    problems: List[str] = []
    for o in occs:
        fpath = component_file(d, o)
        frame_doc = AssemblyDocument.load(fpath)
        for m in frame_doc.frame.members:
            ppath = os.path.join(frame_doc.base_dir, m.part)
            if not m.part or not os.path.exists(ppath):
                problems.append("%s member %d has no part yet" % (o.name,
                                                                  m.id))
                continue
            part = Document.load(ppath, build=False)
            try:
                length = float(part.properties.get("Length", 0.0))
            except ValueError:
                length = 0.0
            a, b, extra = _end_angles(part)
            mass = core_bom.mass_grams(ppath, d.library)
            pieces.append({"frame": o.name, "member": m.id,
                           "profile": m.size, "family": m.family,
                           "length": _num(length, 2),
                           "end_a": _num(a, 2), "end_b": _num(b, 2),
                           "extra": extra,
                           "material": m.material or part.material,
                           "mass_g": None if mass is None else _num(mass, 1)})
    grouped: Dict[Tuple, Dict[str, Any]] = {}
    for p in pieces:
        key = (p["profile"], p["family"], round(p["length"], 1),
               round(p["end_a"], 1), round(p["end_b"], 1),
               tuple(p["extra"]))
        g = grouped.setdefault(key, {
            "profile": p["profile"], "family": p["family"],
            "length": p["length"], "end_a": p["end_a"], "end_b": p["end_b"],
            "extra": p["extra"], "qty": 0, "members": [],
            "mass_each_g": p["mass_g"]})
        g["qty"] += 1
        g["members"].append((p["frame"], p["member"]))
    rows = sorted(grouped.values(), key=lambda r: (
        r["profile"], -r["length"], r["end_a"], r["end_b"]))
    for i, r in enumerate(rows):
        r["item"] = i + 1
        r["members"] = ["%s#%d" % m for m in r["members"]]
    totals: Dict[str, Dict[str, Any]] = {}
    for p in pieces:
        t = totals.setdefault(p["profile"], {"pieces": 0, "length": 0.0,
                                             "mass_g": 0.0})
        t["pieces"] += 1
        t["length"] += p["length"]
        t["mass_g"] += p["mass_g"] or 0.0
    for t in totals.values():
        t["length"] = _num(t["length"], 1)
        t["mass_g"] = _num(t["mass_g"], 1)
    out: Dict[str, Any] = {"doc": entry.handle, "revision": entry.revision,
                           "rows": rows, "pieces": len(pieces),
                           "totals": totals}
    if problems:
        out["warnings"] = problems
    if path:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["item", "profile", "length_mm", "end_a_deg",
                        "end_b_deg", "qty", "mass_each_g", "notes"])
            for r in rows:
                w.writerow([r["item"], r["profile"], r["length"],
                            r["end_a"], r["end_b"], r["qty"],
                            r["mass_each_g"], "; ".join(r["extra"])])
        out["path"] = path
    out["summary"] = "cut list | %d piece%s in %d line%s | %s" % (
        len(pieces), "" if len(pieces) == 1 else "s", len(rows),
        "" if len(rows) == 1 else "s",
        ", ".join("%s: %d pcs (%.2f m)" % (k, v["pieces"], v["length"] / 1000)
                  for k, v in sorted(totals.items())) or "empty")
    return out


# ---------------------------------------------------------------- skeleton


class _Parts:
    """The parts of an assembly as the parameter table reaches them: the
    document the workspace holds if it holds the file, else one read from
    the file. Whatever is changed is built, checked and saved together,
    and put back if any of it fails."""

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        self.docs: Dict[str, Document] = {}
        self.held: Dict[str, Entry] = {}
        self.before: Dict[str, str] = {}
        self.files: Dict[str, bytes] = {}

    def get(self, path: str) -> Document:
        key = os.path.normcase(os.path.abspath(path))
        if key not in self.docs:
            held = self.ws.by_path(path)
            if held is not None and held.doc_type == "part":
                self.docs[key] = held.document
                self.held[key] = held
            else:
                self.docs[key] = Document.load(path)
            self.before[key] = self.docs[key].snapshot()
        return self.docs[key]

    def paths(self) -> Dict[str, Document]:
        return {k: v for k, v in self.docs.items()}

    def commit(self, changed: Sequence[Document], app_open: Any) -> List[str]:
        """Build each changed part, then save it. Raises, leaving every
        part as it was, if one does not build."""
        written = []
        keys = {id(v): k for k, v in self.docs.items()}
        for doc in changed:
            key = keys.get(id(doc))
            if key is None:
                continue
            ops._refuse_app_file(doc.path, app_open, "saving it")
        for doc in changed:
            doc.rebuild()
            rep = doc.last_report
            if not rep.ok:
                raise BridgeError(
                    "FEATURE_FAILED", "%s does not build with that: %s" % (
                        os.path.basename(doc.path), "; ".join(
                            m for _f, m in rep.errors)),
                    ["Nothing was changed."])
        for doc in changed:
            key = keys[id(doc)]
            try:
                self.files[key] = open(doc.path, "rb").read()
            except OSError:
                self.files[key] = b""
            doc.save(doc.path)
            written.append(doc.path)
            if key in self.held:
                self.held[key].touch()
        return written

    def restore(self) -> None:
        for key, doc in self.docs.items():
            try:
                doc.load_dict(json.loads(self.before[key]))
                doc.rebuild()
            except Exception:                                  # noqa: BLE001
                pass
        for key, data in self.files.items():
            doc = self.docs[key]
            try:
                with open(doc.path, "wb") as fh:
                    fh.write(data)
            except OSError:
                pass


def _params(ws: Workspace, d: AssemblyDocument, parts: _Parts
            ) -> AssemblyParameters:
    return AssemblyParameters(d, parts.get, parts.get)


def _need_known(ap: AssemblyParameters, qualified: str) -> None:
    """The part parameter a qualified name says must exist: a part's user
    parameter, or a dimension inside one of its features."""
    from ..core import modelparams
    comp, inner = ap.split(qualified)
    if comp is not None and (inner in comp.document.params
                             or modelparams.find(comp.document, inner)
                             is not None):
        return
    near = ([p.name for p in comp.document.params] if comp is not None
            else [c.prefix for c in ap.components()])
    raise BridgeError(
        "NO_PARAMETER", "no parameter %r" % qualified,
        ["%s: %s" % ("Its parameters" if comp is not None
                     else "Parts", ", ".join(near) or "none"),
         "skeleton_params() lists every parameter: parts' as "
         "<part>_<name>, and the assembly's own."])


@op
def skeleton_params(ws: Workspace, doc: str = "", part: Any = "",
                    model: bool = False) -> Dict[str, Any]:
    """Retrieve the parameters an assembly's parts and the assembly itself
    hold, qualified as an expression reaches them, with what drives what."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    parts = _Parts(ws)
    ap = _params(ws, d, parts)
    want = ""
    if part not in ("", None):
        occ = find_occurrence(d, part, "part")
        want = os.path.normcase(os.path.abspath(component_file(d, occ)))
    comps: List[Dict[str, Any]] = []
    rows = ap.rows()
    by_comp: Dict[str, List[Any]] = {}
    for r in rows:
        if r.model and not model:
            continue
        by_comp.setdefault(r.component.prefix, []).append(r)
    for c in ap.components():
        key = os.path.normcase(os.path.abspath(c.path))
        if want and key != want:
            continue
        comps.append({
            "part": c.prefix, "file": os.path.basename(c.path),
            "parameters": [
                {"name": r.qualified, "own_name": r.name,
                 "expression": r.expression, "value": _num(r.value, 5),
                 **({"driven_by": r.driven} if r.driven else {}),
                 **({"error": r.error} if r.error else {})}
                for r in by_comp.get(c.prefix, [])]})
    drivers = dict(d.drivers)
    own = ops._parameters(d)
    out = {"doc": entry.handle, "revision": entry.revision,
           "assembly_parameters": own, "components": comps,
           "drivers": drivers}
    out["summary"] = "%d component%s | %d parameter%s | %d driven | " \
        "%d assembly parameter%s" % (
            len(comps), "" if len(comps) == 1 else "s",
            sum(len(c["parameters"]) for c in comps),
            "" if sum(len(c["parameters"]) for c in comps) == 1 else "s",
            len(drivers), len(own), "" if len(own) == 1 else "s")
    return out


def _bbox(d: AssemblyDocument) -> Optional[List[float]]:
    shape = ops._assembly_shape(d)
    box = kernel.exact_bounding_box(shape) if shape is not None else None
    return [_num(c, 2) for c in box] if box else None


def _sizes(d: AssemblyDocument) -> Dict[str, List[float]]:
    out = {}
    for o in d.occurrences:
        shape = o.placed()
        if shape is None:
            continue
        box = kernel.exact_bounding_box(shape)
        if box:
            out[o.name] = [_num(box[3] - box[0], 2), _num(box[4] - box[1], 2),
                           _num(box[5] - box[2], 2)]
    return out


@op
def derive_part(ws: Workspace, doc: str = "", part: Any = "", file: str = "",
                drives: Optional[Dict[str, Any]] = None,
                release: Optional[List[str]] = None, name: str = "",
                dry_run: bool = False, expected_revision: Optional[int] = None,
                app_open: Any = None) -> Dict[str, Any]:
    """Make a part follow the skeleton: each parameter in ``drives`` is
    set by an expression over other parts' and the assembly's parameters."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    parts = _Parts(ws)
    if not part and not file:
        raise BridgeError("BAD_VALUE", "name the part: an occurrence, or "
                          "file (an absolute .icpart path) to place it")
    if not drives and not release:
        raise BridgeError(
            "BAD_VALUE", "nothing to derive: give drives={\"width\": "
            "\"skel_W - 40\"} (a parameter of the part and the expression "
            "that sets it)", ["skeleton_params() lists every name an "
                              "expression can use."])
    placed_new: List[Any] = []

    def mutate():
        if file:
            path = ops._absolute(file, "derive_part")
            if not os.path.exists(path):
                raise BridgeError("NOT_FOUND", "no such file: %s" % path)
            occ = next((o for o in d.occurrences
                        if d.component_path(o) and same_path(
                            d.component_path(o), path)), None)
            if occ is None:
                occ = d.place(path, label=name.strip() if name else "")
                placed_new.append(occ)
                d.rebuild()
        else:
            occ = find_occurrence(d, part, "part")
        path = component_file(d, occ)
        ap = _params(ws, d, parts)
        comp = next((c for c in ap.components()
                     if same_path(c.path, path)), None)
        if comp is None:
            raise BridgeError("WRONG_TYPE", "%s is not a part file"
                              % occ.name)
        changed: List[Document] = []
        derived: Dict[str, str] = {}
        for key, expr in (drives or {}).items():
            qualified = key if ap.split(key)[0] is comp else \
                "%s_%s" % (comp.prefix, key)
            _need_known(ap, qualified)
            try:
                changed += [c for c in ap.set(qualified, str(expr))
                            if c not in changed]
            except ExpressionError as exc:
                raise BridgeError("BAD_EXPRESSION", "%s = %s: %s" % (
                    qualified, expr, exc),
                    ["Names an expression can use: skeleton_params()."]
                ) from exc
            derived[qualified] = str(expr)
        for key in release or []:
            ap.release(key if ap.split(key)[0] is comp
                       else "%s_%s" % (comp.prefix, key))
        bad = {k: v for k, v in (getattr(ap, "errors", {}) or {}).items()}
        if bad:
            raise BridgeError("BAD_EXPRESSION", "; ".join(
                "%s: %s" % kv for kv in bad.items()))
        if dry_run:
            return occ, derived, []
        written = parts.commit(changed, app_open)
        d.rebuild()
        return occ, derived, written

    def finish(made, report):
        occ, derived, written = made
        ap = _params(ws, d, parts)
        values = {}
        for q in list(derived):
            for r in ap.rows():
                if r.qualified == q:
                    values[q] = _num(r.value, 5)
        out: Dict[str, Any] = {
            "occurrence": occ.name, "drives": derived, "values": values,
            "drivers": dict(d.drivers), "written": [
                os.path.basename(p) for p in written],
            "assembly": report_info(report)}
        out["summary"] = "derived %s | %s | rev @REV@" % (
            occ.name, ", ".join("%s = %s (%s)" % (k, v, values.get(k))
                                for k, v in derived.items()) or "released")
        return out

    try:
        result = _apply(entry, mutate, finish, dry_run, "derive_part",
                        expected_revision)
    except Exception:
        parts.restore()
        raise
    if dry_run:
        parts.restore()
    return _stamped(result)


@op
def skeleton_set(ws: Workspace, doc: str = "", set: Optional[Dict[str, Any]
                                                              ] = None,
                 dry_run: bool = False,
                 expected_revision: Optional[int] = None,
                 app_open: Any = None) -> Dict[str, Any]:
    """Change master parameters (a skeleton's, any part's, or the
    assembly's); everything derived from them and the frame follow."""
    entry = ws.get(doc)
    d = need_assembly(entry)
    if not set:
        raise BridgeError("BAD_VALUE", "set={\"skel_L\": 800} names the "
                          "parameters to change",
                          ["skeleton_params() lists them."])
    parts = _Parts(ws)
    before = {"sizes": _sizes(d), "bbox": _bbox(d)}
    seen_before: Dict[str, float] = {}

    def mutate():
        ap = _params(ws, d, parts)
        seen_before.update({r.qualified: r.value for r in ap.rows()
                            if not r.model})
        changed: List[Document] = []
        for qualified, expr in set.items():
            expr = str(expr)
            if qualified in d.params:
                d.params.set_expression(qualified, expr)
                d.params.evaluate_all()
                continue
            _need_known(ap, qualified)
            try:
                changed += [c for c in ap.set(qualified, expr)
                            if c not in changed]
            except ExpressionError as exc:
                raise BridgeError("BAD_EXPRESSION", "%s = %s: %s" % (
                    qualified, expr, exc)) from exc
        # the assembly's own parameters may drive parts too
        changed += [c for c in ap.apply() if c not in changed]
        errors = getattr(ap, "errors", {}) or {}
        if errors:
            raise BridgeError("BAD_EXPRESSION", "; ".join(
                "%s: %s" % kv for kv in errors.items()))
        if dry_run:
            for c in changed:
                c.rebuild()
            return changed, [], ap
        written = parts.commit(changed, app_open)
        d.rebuild()
        return changed, written, ap

    def finish(made, report):
        changed, written, _ap = made
        ap = _params(ws, d, parts)
        now = {r.qualified: r.value for r in ap.rows() if not r.model}
        moved = {k: {"from": _num(seen_before.get(k, 0.0), 5),
                     "to": _num(v, 5)} for k, v in now.items()
                 if k in seen_before and abs(v - seen_before[k]) > 1e-9}
        sizes = _sizes(d)
        grew = {n: {"from": before["sizes"].get(n), "to": s}
                for n, s in sizes.items() if before["sizes"].get(n) != s}
        out: Dict[str, Any] = {
            "changed": moved, "components_resized": grew,
            "bbox_before": before["bbox"], "bbox_after": _bbox(d),
            "written": [os.path.basename(p) for p in written],
            "assembly": report_info(report)}
        driven = [k for k in moved if k not in set]
        out["summary"] = ("set %s | %d driven parameter%s followed | "
                          "%d component%s resized | %s | rev @REV@" % (
                              ", ".join("%s=%s" % kv for kv in set.items()),
                              len(driven), "" if len(driven) == 1 else "s",
                              len(grew), "" if len(grew) == 1 else "s",
                              "assembly ok" if report.ok else
                              "assembly has errors"))
        return out

    try:
        result = _apply(entry, mutate, finish, dry_run, "skeleton_set",
                        expected_revision)
    except Exception:
        parts.restore()
        raise
    if dry_run:
        parts.restore()
        d.rebuild()
    return _stamped(result)


# ---------------------------------------------------------------- helpers kept
# (assembly_ops is imported for its side of the registry)
_ = assembly_ops
