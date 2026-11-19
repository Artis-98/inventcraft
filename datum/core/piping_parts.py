"""A pipe run's parts: the tube, and its insulation beside it.

Each is an ordinary part with one Pipe Run feature, the route and the
section kept in it, so the part builds on its own.  The Frame Generator
only ever changes that feature and the part's properties; whatever is
put on the part after it stays.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from . import piping


def _write(path: str, role: str, member, geo, d: float, t: float,
           description: str, material: str) -> bool:
    from .document import Document
    from .features import PipeRunFeature
    from .frames import _live
    r = geo.route
    wanted = {"family": geo.fam.id, "size": member.size, "role": role,
              "d": float(d), "t": float(t), "radius": float(r.radius),
              "points": [[round(c, 6) for c in p] for p in r.points]}
    props = {"Description": description,
             "Stock Number": member.size,
             "Length": "%.3f" % r.length,
             "Bends": str(len(r.bends)),
             "Bend Radius": "%g" % r.radius if r.bends else ""}
    doc = _live(path, Document)
    if doc is None and os.path.exists(path):
        try:
            doc = Document.load(path, build=False)
        except Exception:
            doc = None
    if doc is None:
        doc = Document()
    feature = next((f for f in doc.features
                    if isinstance(f, PipeRunFeature)), None)
    same = feature is not None and all(
        getattr(feature, k) == v for k, v in wanted.items()) and all(
        doc.properties.get(k) == v for k, v in props.items()) and (
        not material or doc.material == material)
    if same:
        return False
    if feature is None:
        feature = PipeRunFeature(name="Insulation" if role == "insulation"
                                 else "Pipe Run")
        doc.add_feature(feature, 0)
    for key, value in wanted.items():
        setattr(feature, key, value)
    if material:
        doc.material = material
    doc.properties.update(props)
    doc.rebuild()
    doc.save(path)
    return True


def write_pipe_part(path: str, member, geo) -> bool:
    """The tube's part, written only when something in it changed; True
    when it was."""
    dims = geo.dims
    material = member.material or "Copper"
    return _write(path, "pipe", member, geo, dims["d"], dims["t"],
                  "%s %s" % (geo.fam.name, piping.size_label(dims)),
                  material)


def sync_insulation(frame_doc, member, geo) -> bool:
    """The insulation's part and its place beside the tube: made, kept up
    or taken away as the member's insulation now is.  True when anything
    changed."""
    base = frame_doc.base_dir
    changed = False
    if member.insulation <= 0:
        if member.insulation_occurrence:
            frame_doc.remove_occurrence(member.insulation_occurrence)
            member.insulation_occurrence = 0
            changed = True
        if member.insulation_part:
            path = os.path.join(base, member.insulation_part) \
                if base else member.insulation_part
            member.insulation_part = ""
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
            changed = True
        return changed
    thk = member.insulation
    material = member.insulation_material or piping.INSULATION_MATERIAL
    if not member.insulation_part:
        stem = os.path.splitext(member.part)[0]
        member.insulation_part = stem + " Insulation.icpart"
        changed = True
    path = os.path.join(base, member.insulation_part) \
        if base else member.insulation_part
    d = geo.dims["d"]
    if _write(path, "insulation", member, geo, d + 2 * thk, thk,
              "Insulation %g mm, %s, for %s tube"
              % (thk, material, piping.size_label(geo.dims)), material):
        changed = True
    by_id = {o.id: o for o in frame_doc.occurrences}
    occurrence = by_id.get(member.insulation_occurrence)
    if occurrence is None:
        occurrence = frame_doc.place(path)
        member.insulation_occurrence = occurrence.id
        changed = True
    occurrence.grounded = True
    if occurrence.placement.to_dict() != geo.placement.to_dict():
        occurrence.placement = geo.placement
        changed = True
    return changed


def write_fitting_part(path: str, fitting) -> bool:
    """A fitting's part: one Pipe Fitting feature.  Written only when it
    is not there yet or its sizes changed."""
    from .document import Document
    from .features import PipeFittingFeature
    from . import piping_fittings
    doc = None
    if os.path.exists(path):
        try:
            doc = Document.load(path, build=False)
        except Exception:
            doc = None
    if doc is None:
        doc = Document()
    feature = next((f for f in doc.features
                    if isinstance(f, PipeFittingFeature)), None)
    sockets = [dict(s) for s in fitting.sockets]
    if feature is not None and feature.kind == fitting.kind \
            and feature.sockets == sockets:
        return False
    if feature is None:
        feature = PipeFittingFeature(name=piping_fittings.NAMES[fitting.kind])
        doc.add_feature(feature, 0)
    feature.kind, feature.sockets = fitting.kind, sockets
    doc.material = "Copper"
    doc.properties["Description"] = "%s mm, EN 1254-1 solder fitting" \
        % fitting.label
    doc.properties["Stock Number"] = fitting.label
    doc.rebuild()
    doc.save(path)
    return True


def sync_fittings(frame_doc, planned) -> bool:
    """The frame's fittings as the pipes now meet: each placed where it
    goes, the ones no longer needed taken out.  True when anything
    changed."""
    fd = frame_doc.frame
    base = frame_doc.base_dir
    held = {f.get("key"): f for f in fd.fittings}
    by_id = {o.id: o for o in frame_doc.occurrences}
    changed, keep, written = False, [], set()
    for fitting in planned:
        path = os.path.join(base, fitting.part_name) if base \
            else fitting.part_name
        if fitting.part_name not in written:
            if write_fitting_part(path, fitting):
                changed = True
            written.add(fitting.part_name)
        record = held.pop(fitting.key, None)
        occurrence = by_id.get(record["occurrence"]) if record else None
        if occurrence is None:
            occurrence = frame_doc.place(path)
            changed = True
        occurrence.grounded = True
        placed = fitting.placement()
        if occurrence.placement.to_dict() != placed.to_dict():
            occurrence.placement = placed
            changed = True
        keep.append({"key": fitting.key, "part": fitting.part_name,
                     "occurrence": occurrence.id})
    for record in held.values():
        if record.get("occurrence") in by_id:
            frame_doc.remove_occurrence(record["occurrence"])
        changed = True
        if record.get("part") not in written:
            path = os.path.join(base, record["part"]) if base \
                else record["part"]
            if not any(k["part"] == record["part"] for k in keep):
                try:
                    os.remove(path)
                except OSError:
                    pass
    if [dict(k) for k in keep] != [dict(f) for f in fd.fittings]:
        changed = True
    fd.fittings = keep
    return changed


def pipe_part_info(path: str) -> Dict[str, Any]:
    """What a pipe part is, read from its Pipe Run feature: {} for any
    other part."""
    from . import fileformat
    try:
        features = (fileformat.read(path).geometry or {}).get("features", [])
    except Exception:
        return {}
    for f in features:
        if isinstance(f, dict) and f.get("type") == "pipe_run":
            return f
    return {}
