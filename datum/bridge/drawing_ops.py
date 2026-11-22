"""Drawings through the bridge: the +drawing tool group.

A drawing (.icdraw) holds no geometry of its own. It references a part or
an assembly by path, and its views are lines generated from that model
(``core/views.py``'s Generator, hidden line removal), cached in the file so
it opens and prints without loading the model, with a hash of the model to
know when the cache has gone stale. What the bridge adds is the same thing
it adds to assemblies: each change is one call, atomic (a view that cannot
be drawn puts the drawing back as it was) and one undo step, in either
host.

Coordinates an agent gives, and is given back, are millimetres:

* a position on the SHEET is the centre of a view, from the sheet's bottom
  left corner (the sheet is 420 x 297 for A3 landscape);
* a position in a VIEW is model millimetres at 1:1 whatever the view's
  scale, x to the right and y up the page, the origin the middle of the
  view's box (``box_mm`` in a view's answer gives the extents).

The views are laid out for you (``drawing_base_view`` picks a scale at which
a base view and two projections and an isometric share the sheet beside the
title block, ``drawing_projected_view`` puts a view where the standard says),
so a drawing is a handful of calls. ``at`` overrides the position.
"""

from __future__ import annotations

import base64
import json
import math
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from ..core import bom as core_bom
from ..core import drawing as dwg
from ..core import fileformat, hlr, kernel, templates
from ..core import views as viewgen
from ..core.drawing import (ALIGNED, BALLOON, BASE, CENTRE_MARK, CENTRELINE,
                            DETAIL, DIAMETER, DrawingDocument, LEADER, LINEAR,
                            NOTE, PROJECTED, RADIUS, SECTION, Annotation,
                            PartsList, Sheet, View, WITH_HIDDEN)
from . import ops
from .errors import BridgeError
from .workspace import Entry, Workspace, same_path

op = ops.op

GAP = dwg.VIEW_GAP
LABEL = dwg.LABEL_ROOM
AUTO_TEXT = "auto"          # what the automatic centre marks carry as text
PLACES = ("right", "left", "above", "below", "iso")
CORNERS = {"above-right": (1, 1), "above-left": (-1, 1),
           "below-right": (1, -1), "below-left": (-1, -1)}
EDITABLE_VIEW = {"x", "y", "scale", "display", "name", "label_visible",
                 "scale_visible", "hatch", "hatch_pattern", "flat",
                 "tangents", "cut", "centre", "radius", "bounded", "depth",
                 "letter", "orientation"}
REDRAW = {"scale", "display", "hatch", "hatch_pattern", "flat", "tangents",
          "cut", "centre", "radius", "bounded", "depth", "orientation"}
EDITABLE_NOTE = {"text", "prefix", "suffix", "offset", "axis", "size",
                 "bold", "italic"}


# ---------------------------------------------------------------- helpers


_QT: Any = None


def qt_application():
    """Qt for painting a sheet to PDF or a picture, in a host that has no
    window. The system's own platform when there is a desktop (it has the
    fonts a title block is lettered in), the offscreen one when there is
    not."""
    global _QT
    from PySide6 import QtGui
    app = QtGui.QGuiApplication.instance()
    if app is None:
        if sys.platform not in ("win32", "darwin") and not (
                os.environ.get("DISPLAY") or os.environ.get(
                    "WAYLAND_DISPLAY")):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = _QT = QtGui.QGuiApplication(["inventcraft"])
    return app


def need_drawing(entry: Entry) -> DrawingDocument:
    if entry.doc_type != "drawing":
        raise BridgeError(
            "WRONG_TYPE", "%s is a %s; this works on drawings"
            % (entry.handle, entry.doc_type),
            ["drawing_create(source=<a saved part or assembly>) makes "
             "one; open_document() opens an .icdraw."])
    return entry.document


def generator(entry: Entry) -> viewgen.Generator:
    """The view generator of a drawing, kept (with the parts it has read)
    as long as the document is open."""
    held = entry.parts.get("__generator__")
    if held is None:
        held = entry.parts["__generator__"] = viewgen.Generator()
    return held


def _num(v: float, n: int = 3) -> float:
    return round(float(v), n) + 0.0


def model_path(ws: Workspace, source: Any, what: str = "source") -> str:
    """A saved part or assembly, from an open document's handle or a path."""
    if not source:
        raise BridgeError("NO_MODEL", "%s: give the part or assembly to "
                          "draw" % what)
    text = str(source)
    held = None
    if text in ws.entries:
        held = ws.entries[text]
    if held is not None:
        if held.doc_type not in ("part", "assembly"):
            raise BridgeError("WRONG_TYPE", "%s is a %s; a drawing shows a "
                              "part or an assembly" % (text, held.doc_type))
        if not held.path:
            raise BridgeError(
                "NO_MODEL", "%s has never been saved, and a drawing "
                "references a file" % text,
                ["save_document(doc=%r, path=<absolute .icpart>) first." %
                 text])
        return held.path
    path = ops._absolute(text, what)
    if not os.path.exists(path):
        raise BridgeError("NOT_FOUND", "no such file: %s" % path)
    kind = fileformat.type_for_path(path)
    if kind not in (fileformat.PART, fileformat.ASSEMBLY):
        raise BridgeError("BAD_FILE", "%s is not a part or an assembly"
                          % path)
    return path


def _sheet(d: DrawingDocument, name: Any = "") -> Sheet:
    if name in (None, ""):
        sheet = d.active()
        if sheet is None:
            raise BridgeError("NO_VIEW", "the drawing has no sheet")
        return sheet
    for sheet in d.sheets:
        if sheet.name.lower() == str(name).lower() or str(sheet.id) == \
                str(name).lstrip("#"):
            return sheet
    raise BridgeError("NO_VIEW", "no sheet called %r" % name,
                      ["Sheets: %s" % ", ".join(s.name for s in d.sheets)])


def find_view(d: DrawingDocument, ref: Any, sheet: Optional[Sheet] = None,
              what: str = "view") -> Tuple[Sheet, View]:
    """A view by name (``View1``, ``Section A-A``), ``#id`` or id."""
    sheets = [sheet] if sheet is not None else list(d.sheets)
    t = str(ref).strip()
    ident = None
    if isinstance(ref, int) and not isinstance(ref, bool):
        ident = ref
    elif t.startswith("#") and t[1:].isdigit():
        ident = int(t[1:])
    elif t.isdigit():
        ident = int(t)
    for s in sheets:
        for v in s.views:
            if (ident is not None and v.id == ident) or (
                    ident is None and (v.name == t or v.label == t)):
                return s, v
    low = t.lower()
    for s in sheets:
        for v in s.views:
            if ident is None and (v.name.lower() == low
                                  or v.label.lower() == low):
                return s, v
    names = [v.name for s in sheets for v in s.views]
    raise BridgeError(
        "NO_VIEW", "%s: no view %r" % (what, ref),
        ["Views: %s" % (", ".join(names) or "none yet"),
         "drawing_base_view() makes the first."])


def _scale_value(scale: Any) -> Optional[float]:
    if scale in (None, ""):
        return None
    if isinstance(scale, (int, float)) and not isinstance(scale, bool):
        value = float(scale)
    else:
        value = dwg.parse_scale(str(scale))
    if value is None or value <= 0:
        raise BridgeError("BAD_VALUE", "scale %r is not a scale" % (scale,),
                          ["A number (0.5) or a ratio (\"1:2\", \"2:1\")."])
    return value


def _at(at: Any, what: str = "at") -> Optional[Tuple[float, float]]:
    if at in (None, ""):
        return None
    try:
        return (float(at[0]), float(at[1]))
    except Exception:                                   # noqa: BLE001
        raise BridgeError("BAD_VALUE", "%s is [x, y] in mm" % what)


def frame_of(d: DrawingDocument, sheet: Sheet) -> Tuple[float, ...]:
    width, height = sheet.extent()
    border = d.borders.get(sheet.border)
    if border is not None:
        return tuple(border.frame(width, height))
    return (5.0, 5.0, width - 5.0, height - 5.0)


def block_rect(d: DrawingDocument, sheet: Sheet
               ) -> Optional[Tuple[float, float, float, float]]:
    block = d.title_blocks.get(sheet.title_block)
    if block is None:
        return None
    frame = frame_of(d, sheet)
    return (frame[2] - block.width, frame[1], frame[2],
            frame[1] + block.height)


def view_box(sheet: Sheet, view: View) -> Optional[Tuple[float, ...]]:
    """A view's outline on the sheet, with its label's room under it."""
    p = view.projection
    if p is None:
        return None
    b = p.box
    extra = LABEL if view.label_visible else 0.0
    return (view.x + b[0], view.y + b[1] - extra, view.x + b[2],
            view.y + b[3])


def _meets(a, b, gap: float = 1.0) -> bool:
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0]
                or a[3] + gap <= b[1] or b[3] + gap <= a[1])


def _free(d: DrawingDocument, sheet: Sheet, box, ignore=()) -> bool:
    """Whether a box lies inside the frame, off the title block, and clear
    of every other view and parts list."""
    frame = frame_of(d, sheet)
    if box[0] < frame[0] or box[1] < frame[1] or box[2] > frame[2] \
            or box[3] > frame[3]:
        return False
    block = block_rect(d, sheet)
    if block is not None and _meets(box, block):
        return False
    for v in sheet.views:
        if v.id in ignore:
            continue
        other = view_box(sheet, v)
        if other is not None and _meets(box, other, GAP / 2):
            return False
    for table in sheet.parts_lists:
        if _meets(box, table.box()):
            return False
    return True


# ---------------------------------------------------------------- rebuild


def _rebuild(entry: Entry, force: bool = False):
    d = entry.document
    return generator(entry).rebuild(d, force=force)


def _view_problems(d: DrawingDocument) -> Dict[int, str]:
    return {v.id: v.error for s in d.sheets for v in s.views if v.error}


def _apply(entry: Entry, mutate, finish, dry_run: bool = False,
           what: str = "change", expected_revision: Optional[int] = None
           ) -> Dict[str, Any]:
    """One atomic change to a drawing: mutate, draw what needs drawing,
    refuse if a view that drew before (or a new one) cannot be drawn, and
    keep the change as one undo step (the document's own, so Ctrl+Z in
    the app takes it back whole)."""
    d = need_drawing(entry)
    ops._check_revision(entry, expected_revision)
    before = d.snapshot()
    known = set(_view_problems(d))
    failure: Optional[Exception] = None
    result: Dict[str, Any] = {}
    try:
        made = mutate()
        report = _rebuild(entry)
        fresh = {i: m for i, m in _view_problems(d).items()
                 if i not in known}
        if fresh:
            names = []
            for s in d.sheets:
                for v in s.views:
                    if v.id in fresh:
                        names.append("%s: %s" % (v.label, fresh[v.id]))
            raise BridgeError(
                "VIEW_FAILED", "%s: %s" % (what, "; ".join(names)),
                ["Nothing was changed. A cut line must cross the part; a "
                 "detail needs something inside its circle."])
        if report.missing:
            raise BridgeError(
                "NO_MODEL", "%s: the model cannot be found (%s)" % (
                    what, ", ".join(report.missing)),
                ["The drawing references a saved file; it was moved or "
                 "deleted."])
        result = finish(made, report)
    except Exception as exc:                            # noqa: BLE001
        failure = exc
    if failure is not None or dry_run:
        d._restore(before)
        d.modified = bool(d.modified)
        if failure is not None:
            raise failure
        result["dry_run"] = True
        result["doc"] = entry.handle
        result["revision"] = entry.revision
        return result
    d._undo.append(before)
    del d._undo[:-60]
    d._redo.clear()
    d.modified = True
    entry.touch()
    result["doc"] = entry.handle
    result["revision"] = entry.revision
    result["units"] = ops._units(entry)
    result["summary"] = result.get("summary", "").replace(
        "@REV@", str(entry.revision))
    return result


# ---------------------------------------------------------------- reading


def view_info(d: DrawingDocument, sheet: Sheet, v: View) -> Dict[str, Any]:
    scale = d.view_scale(sheet, v)
    out: Dict[str, Any] = {
        "id": v.id, "name": v.name, "kind": v.kind, "label": v.label,
        "at": [_num(v.x), _num(v.y)], "scale": dwg.scale_text(scale),
        "display": d.view_display(sheet, v)}
    if v.parent:
        out["parent"] = v.parent
    try:
        if v.kind in (SECTION, DETAIL):
            raise ValueError("looks the way its cut or parent does")
        direction, _up = generator_orientation(d, sheet, v)
        named = viewgen.named_orientation(direction)
        out["looks"] = named or (
            "iso" if all(abs(c) > 0.3 for c in direction)
            else [_num(c, 4) for c in direction])
    except Exception:                                   # noqa: BLE001
        pass
    if v.kind == SECTION:
        out["cut"] = [_num(c / (d.view_scale(sheet, sheet.view(v.parent)
                                             if sheet.view(v.parent) else v)
                                or 1.0)) for c in v.cut]
        out["letter"] = v.letter
    if v.kind == DETAIL:
        out["letter"] = v.letter
        out["radius_mm"] = _num(v.radius / (d.view_scale(
            sheet, sheet.view(v.parent)) if sheet.view(v.parent) else 1.0))
    if v.projection is not None:
        b = v.projection.box
        out["box_mm"] = [_num(c / scale) for c in b]
        out["extent_mm"] = [_num((b[2] - b[0]) / scale),
                            _num((b[3] - b[1]) / scale)]
        out["box_sheet"] = [_num(v.x + b[0]), _num(v.y + b[1]),
                            _num(v.x + b[2]), _num(v.y + b[3])]
    if v.error:
        out["error"] = v.error
    if v.stale:
        out["stale"] = True
    model = d.view_model(sheet, v)
    if model is not None and v.kind == BASE:
        out["model"] = model.ref.name or model.ref.path
    return out


_ORIENTER: Any = None


def generator_orientation(d, sheet, v):
    """Which way a view looks (it needs no models, so one generator
    serves every drawing)."""
    global _ORIENTER
    if _ORIENTER is None:
        _ORIENTER = viewgen.Generator()
    return _ORIENTER.orientation(d, sheet, v)


def _note_info(d: DrawingDocument, sheet: Sheet, n: Annotation
               ) -> Dict[str, Any]:
    view = sheet.view(n.view)
    scale = d.view_scale(sheet, view) if view is not None else 1.0
    out: Dict[str, Any] = {"id": n.id, "kind": n.kind,
                           "view": view.name if view is not None else ""}
    if n.kind in (dwg.LINEAR, dwg.ALIGNED, dwg.RADIUS, dwg.DIAMETER,
                  dwg.ANGULAR, dwg.ORDINATE):
        out["text"] = n.caption(scale)
        out["value"] = _num(n.measure() / scale
                            if n.kind != dwg.ANGULAR else n.measure())
        out["anchored"] = n.anchored
    elif n.kind == BALLOON:
        out["item"] = n.item
        out["component"] = os.path.basename(n.component)
    else:
        out["text"] = n.text
    if n.sick:
        out["sick"] = True
    return out


def tree(entry: Entry) -> Dict[str, Any]:
    d = need_drawing(entry)
    try:
        _rebuild(entry)
    except Exception:                                   # noqa: BLE001
        pass
    out: Dict[str, Any] = {
        "standard": "%s (%s angle projection)" % (d.standard, d.angle),
        "properties": dict(d.properties), "sheets": []}
    for s in d.sheets:
        w, h = s.extent()
        item: Dict[str, Any] = {
            "name": s.name, "size": s.size, "sheet_mm": [w, h],
            "active": s.id == d.active_sheet,
            "frame": [_num(c, 1) for c in frame_of(d, s)],
            "views": [view_info(d, s, v) for v in s.views],
            "annotations": [_note_info(d, s, n) for n in s.annotations],
        }
        block = block_rect(d, s)
        if block is not None:
            item["title_block"] = [_num(c, 1) for c in block]
        if s.parts_lists:
            item["parts_lists"] = [
                {"id": t.id, "rows": len(t.rows),
                 "columns": list(t.columns), **({"error": t.error}
                                                if t.error else {})}
                for t in s.parts_lists]
        out["sheets"].append(item)
    broken = d.broken_links()
    if broken:
        out["missing_models"] = [b.describe() for b in broken]
    stale = [v.name for s in d.sheets for v in s.views if v.stale]
    if stale:
        out["stale_views"] = stale
        out["note"] = ("the model changed since these were drawn; "
                       "drawing_render / drawing_export draw them again")
    out["path"] = d.path
    return out


# ---------------------------------------------------------------- create


def _unused_path(folder: str, stem: str) -> str:
    ext = fileformat.extension_for(fileformat.DRAWING)
    path = os.path.join(folder, stem + ext)
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, "%s-%d%s" % (stem, n, ext))
    return path


def make_drawing(ws: Workspace, source: Any, size: str = "A3",
                 orientation: str = "landscape", standard: str = "",
                 template: str = "", name: str = "", path: str = "",
                 overwrite: bool = False,
                 props: Optional[Dict[str, Any]] = None
                 ) -> Tuple[DrawingDocument, Dict[str, Any]]:
    """The new drawing and what to say about it (no entry yet: the app
    makes its own tab, a headless host adds an entry)."""
    model = model_path(ws, source, "drawing_create source")
    if size not in dwg.SHEET_SIZES:
        raise BridgeError("BAD_VALUE", "no sheet size %r" % size,
                          ["Sizes: %s" % ", ".join(dwg.SHEET_ORDER)])
    if orientation not in (dwg.LANDSCAPE, dwg.PORTRAIT):
        raise BridgeError("BAD_VALUE", "orientation is landscape or "
                          "portrait")
    if standard and standard not in dwg.STANDARDS:
        raise BridgeError("BAD_VALUE", "standard is ISO (first angle "
                          "projection) or ANSI (third angle)")
    chosen = None
    if template:
        chosen = templates.find(template, os.path.dirname(model))
        if chosen is None:
            raise BridgeError(
                "NOT_FOUND", "no drawing template %r" % template,
                ["Templates: %s" % (", ".join(
                    t.name for t in templates.available(
                        os.path.dirname(model))) or "none")])
    d = templates.new_from(chosen)
    sheet = d.active() or d.add_sheet(size, orientation)
    if chosen is None or size != "A3" or orientation != dwg.LANDSCAPE:
        sheet.size = size
        sheet.orientation = orientation
        sheet.custom = list(dwg.SHEET_SIZES.get(size, (420.0, 297.0)))
    if standard:
        d.standard = standard
    stem = os.path.splitext(os.path.basename(model))[0]
    d.properties["Title"] = name or stem
    for key, value in (props or {}).items():
        d.properties[str(key)] = str(value)
    if path:
        target = fileformat.ensure_extension(
            ops._absolute(path, "drawing_create"), fileformat.DRAWING)
        if os.path.exists(target) and not overwrite:
            raise BridgeError(
                "WOULD_OVERWRITE", "%s already exists" % target,
                ["Pass overwrite: true only if the user asked for it, or "
                 "leave path out to get an unused name."])
    else:
        target = _unused_path(os.path.dirname(model), stem)
    d.path = target
    # what it is a drawing of, so that drawing_base_view needs no source
    d.properties["Source"] = fileformat.relative_path(
        model, os.path.dirname(target))
    d.modified = True
    info = {"path": target, "model": model,
            "sheet": {"name": sheet.name, "size": sheet.size,
                      "orientation": sheet.orientation,
                      "sheet_mm": list(sheet.extent()),
                      "frame": [_num(c, 1) for c in frame_of(d, sheet)]},
            "standard": "%s (%s angle projection)" % (d.standard, d.angle)}
    block = block_rect(d, sheet)
    if block is not None:
        info["sheet"]["title_block"] = [_num(c, 1) for c in block]
    return d, info


@op
def drawing_create(ws: Workspace, source: Any = "", size: str = "A3",
                   orientation: str = "landscape", standard: str = "",
                   template: str = "", name: str = "", path: str = "",
                   overwrite: bool = False,
                   props: Optional[Dict[str, Any]] = None
                   ) -> Dict[str, Any]:
    d, info = make_drawing(ws, source, size, orientation, standard, template,
                           name, path, overwrite, props)
    entry = ws.add(d, "drawing")
    info.update({"doc": entry.handle, "revision": entry.revision,
                 "units": ops._units(entry)})
    info["summary"] = "drawing %s | %s %s | %s | rev %d" % (
        os.path.basename(d.path), d.active().size, d.active().orientation,
        d.standard, entry.revision)
    info["note"] = ("not written yet: save_document() keeps it at %s; add "
                    "views with drawing_base_view()" % d.path)
    return info


# ---------------------------------------------------------------- views


def _reference(d: DrawingDocument, model: str) -> fileformat.ComponentRef:
    return fileformat.ComponentRef(
        path=(fileformat.relative_path(model, d.base_dir) if d.base_dir
              else model),
        name=os.path.basename(model),
        label=os.path.splitext(os.path.basename(model))[0])


def _model_box(entry: Entry, sheet: Sheet, view: View):
    d = entry.document
    shape = generator(entry).model_of(d, sheet, view)
    if shape is None:
        raise BridgeError("NO_MODEL", "the model of %s cannot be read"
                          % view.name)
    return shape, kernel.bounding_box(shape)


def _spans(box, direction, up) -> Tuple[float, float, float]:
    """How big a model looks across and up the page from this direction,
    and how deep it is along it."""
    across, upward = viewgen.outline(box, direction, up)
    look = viewgen._unit(direction)
    depths = [x * look[0] + y * look[1] + z * look[2]
              for x in (box[0], box[3]) for y in (box[1], box[4])
              for z in (box[2], box[5])]
    return across, upward, max(depths) - min(depths)


def _three_view_scale(d: DrawingDocument, sheet: Sheet, spans) -> float:
    """The scale at which a base view with a view beside it and one below
    it, and the room an isometric wants, fit the sheet with the title
    block clear."""
    across, upward, depth = spans
    frame = frame_of(d, sheet)
    block = block_rect(d, sheet)
    room_w = frame[2] - frame[0] - 2 * GAP
    room_h = frame[3] - frame[1] - 2 * GAP
    need_w = across + depth
    need_h = upward + depth
    scale = dwg.fit_scale(room_w - GAP, room_h - GAP - 2 * LABEL, need_w,
                          need_h, fraction=0.95)
    if block is not None:
        # a view that the block would cover is not a fit: the biggest
        # scale at which the lower row clears it, else the next down
        for candidate in [s for s in dwg.SCALES if s <= scale]:
            x0 = frame[0] + GAP
            y1 = frame[3] - GAP
            low = y1 - upward * candidate - GAP - LABEL - depth * candidate
            right = x0 + across * candidate + GAP + depth * candidate
            if low >= frame[1] or right <= block[0]:
                return candidate
        return min(dwg.SCALES[-1], scale)
    return scale


def _single_layout(d: DrawingDocument, sheet: Sheet, spans,
                   assembly: bool) -> Tuple[float, Tuple[float, float]]:
    """A base view on its own (an isometric, say): the largest standard
    scale at which it fills most of the free area, and the centre of that
    area. An assembly leaves the right of the sheet for its parts list."""
    across, upward, _depth = spans
    frame = frame_of(d, sheet)
    block = block_rect(d, sheet)
    width = (frame[2] - frame[0]) - 2 * GAP
    height = (frame[3] - frame[1]) - 2 * GAP - (
        (block[3] - block[1]) if block is not None else 0.0)
    if assembly:
        width *= 0.62
    scale = dwg.fit_scale(width, height, across, upward, fraction=0.85)
    return scale, (frame[0] + GAP + width / 2.0,
                   frame[3] - GAP - height / 2.0)


@op
def drawing_base_view(ws: Workspace, doc: str = "", source: Any = "",
                      orientation: Any = "front", scale: Any = None,
                      at: Any = None, display: str = "hidden",
                      name: str = "", sheet: str = "",
                      label_visible: bool = False, flat: bool = False,
                      up: Any = None, layout: str = "",
                      dry_run: bool = False,
                      expected_revision: Optional[int] = None
                      ) -> Dict[str, Any]:
    """Put a model on the sheet as a base view."""
    entry = ws.get(doc)
    d = need_drawing(entry)
    sh = _sheet(d, sheet)
    if source:
        model = model_path(ws, source, "drawing_base_view source")
    else:
        found = next((v for s in d.sheets for v in s.views
                      if v.kind == BASE), None)
        if found is not None:
            model = found.ref.resolve(d.base_dir) or found.ref.path
        elif d.properties.get("Source"):
            model = os.path.normpath(os.path.join(
                d.base_dir, d.properties["Source"]))
        else:
            raise BridgeError(
                "NO_MODEL", "give source: the part or assembly to draw",
                ["A saved part's path or its open handle."])
    if display not in ("hidden", "visible"):
        raise BridgeError("BAD_VALUE", "display is hidden (hidden edges "
                          "dashed) or visible (visible lines only)")
    if layout not in ("", "three_view", "single"):
        raise BridgeError("BAD_VALUE", "layout is three_view (room for a "
                          "view beside and below) or single (this view "
                          "alone, as big as fits)")
    direction = None
    if isinstance(orientation, (list, tuple)):
        direction = [float(c) for c in orientation]
        named = "front"
    else:
        named = str(orientation or "front").lower()
        if named not in hlr.ORIENTATIONS:
            raise BridgeError("BAD_VIEW", "no orientation %r" % named,
                              ["One of %s, or [x, y, z] to look along."
                               % ", ".join(hlr.ORIENTATIONS)])
    asked = _scale_value(scale)
    position = _at(at)
    others = [v for v in sh.views if v.kind == BASE]
    if not layout:
        layout = ("single" if direction is not None or named == "iso"
                  else "three_view")

    def mutate():
        view = View(kind=BASE, orientation=named, scale=asked or 1.0,
                    display=WITH_HIDDEN if display == "hidden" else
                    dwg.VISIBLE_ONLY, label_visible=label_visible,
                    flat=flat, name=name or "")
        if direction is not None:
            view.direction = direction
            view.up = [float(c) for c in up] if up else [0.0, 0.0, 1.0]
        view.ref = _reference(d, model)
        view.x, view.y = position or (0.0, 0.0)
        d.add_view(sh, view)
        if asked is None or position is None:
            shape, box = _model_box(entry, sh, view)
            dr, upv = viewgen.orientation_of(view)
            spans = _spans(box, dr, upv)
            centre = None
            one = None
            if layout == "single":
                one, centre = _single_layout(
                    d, sh, spans, fileformat.is_assembly(model))
            if asked is None:
                view.scale = (others[0].scale if others and others[0].scale
                              else one if layout == "single"
                              else _three_view_scale(d, sh, spans))
            if position is None:
                frame = frame_of(d, sh)
                s = view.scale
                view.x = frame[0] + GAP + spans[0] * s / 2.0
                view.y = frame[3] - GAP - spans[1] * s / 2.0
                if centre is not None:
                    view.x, view.y = centre
                if others and centre is None:
                    # a second base view: beside the last one's row
                    last = max(others, key=lambda v: v.x)
                    box2 = view_box(sh, last)
                    if box2 is not None:
                        view.x = box2[2] + GAP + spans[0] * s / 2.0
                        view.y = last.y
        view.projection = None
        return view

    def finish(view: View, report):
        info = view_info(d, sh, view)
        warn = _overflow(d, sh)
        out = {"view": info,
               "summary": "base view %s | %s | looks %s | scale %s | "
               "extent %s mm | rev @REV@" % (
                   view.name, os.path.basename(model),
                   info.get("looks", "?"), info["scale"],
                   " x ".join(str(c) for c in info.get("extent_mm", [])))}
        if warn:
            out["warnings"] = warn
        return out

    return _apply(entry, mutate, finish, dry_run, "drawing_base_view",
                  expected_revision)


def _overflow(d: DrawingDocument, sh: Sheet) -> List[str]:
    out = []
    frame = frame_of(d, sh)
    block = block_rect(d, sh)
    for v in sh.views:
        box = view_box(sh, v)
        if box is None:
            continue
        if box[0] < frame[0] - 0.5 or box[1] < frame[1] - 0.5 \
                or box[2] > frame[2] + 0.5 or box[3] > frame[3] + 0.5:
            out.append("%s runs outside the sheet's frame: use a smaller "
                       "scale or a bigger sheet" % v.name)
        elif block is not None and _meets(box, block, 0.0):
            out.append("%s overlaps the title block" % v.name)
        for table in sh.parts_lists:
            if _meets(box, table.box(), 0.0):
                out.append("%s overlaps the parts list: use a smaller "
                           "scale or move the view with edit_feature("
                           "params={x, y})" % v.name)
        for other in sh.views:
            ob = view_box(sh, other)
            if other.id > v.id and ob is not None and _meets(box, ob, 0.0):
                out.append("%s and %s overlap: move one with "
                           "edit_feature(params={x, y}) or use a smaller "
                           "scale" % (v.name, other.name))
    return out


def _projected_orientation(d, sheet, parent, dx, dy):
    pd, pu = generator_orientation(d, sheet, parent)
    if abs(dx) > 1e-6 and abs(dy) > 1e-6:
        return viewgen.iso_orientation(pd, pu, dx, dy)
    return viewgen.projected_orientation(pd, pu, dx, dy, d.angle)


def _place_for(d: DrawingDocument, sheet: Sheet, parent: View, shows: str
               ) -> str:
    """The side of the parent a named view stands on, under the drawing's
    projection standard (first angle puts the right view on the left)."""
    for place, (dx, dy) in (("right", (1, 0)), ("left", (-1, 0)),
                            ("above", (0, 1)), ("below", (0, -1))):
        direction, _up = _projected_orientation(d, sheet, parent, dx, dy)
        if viewgen.named_orientation(direction) == shows:
            return place
    raise BridgeError(
        "BAD_VIEW", "no view beside %s shows %r (a projection is the "
        "view one quarter turn away from its parent)" % (parent.name, shows),
        ["Use place=right|left|above|below, or project from another "
         "view."])


def _beside(parent: View, sh: Sheet, child_box, place: str
            ) -> Tuple[float, float]:
    """Where a view goes against its parent: level with it for a side, in
    line with it for above or below, a gap and a label's room away."""
    pb = view_box(sh, parent) or (parent.x, parent.y, parent.x, parent.y)
    p = parent.projection.box if parent.projection else (0, 0, 0, 0)
    cw, ch = child_box[2] - child_box[0], child_box[3] - child_box[1]
    ccx = (child_box[0] + child_box[2]) / 2.0
    ccy = (child_box[1] + child_box[3]) / 2.0
    if place == "right":
        return (parent.x + p[2] + GAP + cw / 2.0 - ccx + 0.0, parent.y)
    if place == "left":
        return (parent.x + p[0] - GAP - cw / 2.0 - ccx, parent.y)
    if place == "above":
        return (parent.x, parent.y + p[3] + GAP + ch / 2.0 - ccy)
    return (parent.x, parent.y + p[1] - GAP - LABEL - ch / 2.0 - ccy)


@op
def drawing_projected_view(ws: Workspace, doc: str = "", parent: Any = "",
                           place: str = "", shows: str = "",
                           corner: str = "below-right", scale: Any = None,
                           at: Any = None, display: str = "", name: str = "",
                           sheet: str = "", label_visible: bool = False,
                           dry_run: bool = False,
                           expected_revision: Optional[int] = None
                           ) -> Dict[str, Any]:
    """A projection of a view: beside it, above or below it, or the
    isometric off a corner."""
    entry = ws.get(doc)
    d = need_drawing(entry)
    sh = _sheet(d, sheet)
    _s, par = find_view(d, parent, sh, "parent")
    if par.projection is None:
        _rebuild(entry)
    if not place and not shows and at is None:
        place = "below"
    if shows:
        shows = shows.lower()
        if shows == "iso":
            place = "iso"
        else:
            place = _place_for(d, sh, par, shows)
    if place and place not in PLACES:
        raise BridgeError("BAD_VALUE", "place is one of %s"
                          % ", ".join(PLACES))
    if corner not in CORNERS:
        raise BridgeError("BAD_VALUE", "corner is one of %s"
                          % ", ".join(CORNERS))
    asked = _scale_value(scale)
    position = _at(at)
    if position is not None:
        place = place or ("iso" if abs(position[0] - par.x) > 1e-6
                          and abs(position[1] - par.y) > 1e-6 else
                          ("right" if position[0] > par.x else "left")
                          if abs(position[0] - par.x) > 1e-6 else
                          ("above" if position[1] > par.y else "below"))
    if display and display not in ("hidden", "visible"):
        raise BridgeError("BAD_VALUE", "display is hidden or visible")

    def mutate():
        sx, sy = CORNERS[corner]
        probe = {"right": (1, 0), "left": (-1, 0), "above": (0, 1),
                 "below": (0, -1), "iso": (sx, sy)}[place]
        # a first guess on the right side of the parent; the projection
        # looks the way it sits from its parent, so only the side matters
        view = View(kind=PROJECTED, parent=par.id, scale=asked or 0.0,
                    x=par.x + probe[0] * 100.0, y=par.y + probe[1] * 100.0,
                    label_visible=label_visible, name=name or "")
        if place == "iso":
            view.display = "visible"
        if display:
            view.display = (WITH_HIDDEN if display == "hidden"
                            else dwg.VISIBLE_ONLY)
        d.add_view(sh, view)
        view.projection = None
        _rebuild(entry)
        if view.projection is None:
            return view
        if place == "iso":
            _place_iso(entry, sh, par, view, sx, sy, asked, position)
        elif position is not None:
            view.x, view.y = position
        else:
            box = view.projection.box
            view.x, view.y = _beside(par, sh, box, place)
        return view

    def finish(view: View, report):
        info = view_info(d, sh, view)
        out = {"view": info,
               "summary": "projected view %s of %s | looks %s | scale %s |"
               " at %s | rev @REV@" % (
                   view.name, par.name, info.get("looks", "?"),
                   info["scale"], info["at"])}
        warn = _overflow(d, sh)
        if warn:
            out["warnings"] = warn
        return out

    return _apply(entry, mutate, finish, dry_run, "drawing_projected_view",
                  expected_revision)


def _place_iso(entry, sh, par, view, sx, sy, asked, position) -> None:
    """The isometric goes in the corner the orthographic views leave: its
    column is the side view's, its row the lower view's. It takes the
    largest standard scale (not above its parent's) at which it fits; its
    size at another scale follows from the one drawn, so only the scale
    that is kept is drawn again."""
    d = entry.document
    siblings = [v for v in sh.views if v.parent == par.id and v is not view
                and v.kind == PROJECTED and v.projection is not None]
    col = next((v for v in siblings if abs(v.y - par.y) < 1e-6
                and (v.x - par.x) * sx > 0), None)
    row = next((v for v in siblings if abs(v.x - par.x) < 1e-6
                and (v.y - par.y) * sy > 0), None)
    drawn_at = d.view_scale(sh, view)
    parent_scale = d.view_scale(sh, par)
    candidates = ([asked] if asked else
                  [s for s in dwg.SCALES if s <= parent_scale + 1e-9])
    pbox = par.projection.box
    chosen = None
    for s in candidates:
        k = s / drawn_at
        b = [c * k for c in view.projection.box]
        cw, ch = b[2] - b[0], b[3] - b[1]
        x = col.x if col is not None else (
            par.x + sx * ((pbox[2] if sx > 0 else -pbox[0]) + GAP
                          + cw / 2.0))
        y = row.y if row is not None else (
            par.y + sy * ((pbox[3] if sy > 0 else -pbox[1]) + GAP
                          + ch / 2.0))
        if position is not None:
            x, y = position
        probe = (x + b[0], y + b[1] - LABEL, x + b[2], y + b[3])
        chosen = (s, x, y)
        if position is not None or _free(d, sh, probe, ignore={view.id}):
            break
    if chosen is None:
        return
    s, view.x, view.y = chosen
    if abs(s - drawn_at) > 1e-9:
        view.scale = s
        view.projection = None
        generator(entry).redraw(d, sh, [view])


@op
def drawing_section_view(ws: Workspace, doc: str = "", parent: Any = "",
                         cut: Any = None, place: str = "",
                         scale: Any = None, at: Any = None, name: str = "",
                         sheet: str = "", hatch: bool = True,
                         bounded: bool = False, dry_run: bool = False,
                         expected_revision: Optional[int] = None
                         ) -> Dict[str, Any]:
    """A section: the parent cut along a line, and the cut half looked at."""
    entry = ws.get(doc)
    d = need_drawing(entry)
    sh = _sheet(d, sheet)
    _s, par = find_view(d, parent, sh, "parent")
    if par.projection is None:
        _rebuild(entry)
    if par.projection is None:
        raise BridgeError("VIEW_FAILED", "%s has not been drawn" % par.name)
    pscale = d.view_scale(sh, par)
    box = par.projection.box
    bm = [c / pscale for c in box]
    line = _cut_line(cut, bm)
    asked = _scale_value(scale)
    position = _at(at)
    horizontal_cut = abs(line[3] - line[1]) < abs(line[2] - line[0])
    place = place or ("below" if horizontal_cut else "right")
    if place not in ("right", "left", "above", "below"):
        raise BridgeError("BAD_VALUE", "place is right, left, above or "
                          "below")

    def mutate():
        letter = d.next_letter()
        view = View(kind=SECTION, parent=par.id, letter=letter,
                    cut=[c * pscale for c in line], bounded=bounded,
                    hatch=hatch, scale=asked or 0.0, name=name or "",
                    x=par.x + (100.0 if place == "right" else
                               -100.0 if place == "left" else 0.0),
                    y=par.y + (100.0 if place == "above" else
                               -100.0 if place == "below" else 0.0),
                    label_visible=True)
        d.add_view(sh, view)
        view.projection = None
        _rebuild(entry)
        if view.projection is not None:
            if position is not None:
                view.x, view.y = position
            else:
                view.x, view.y = _beside(par, sh, view.projection.box,
                                         place)
                if not _free(d, sh, view_box(sh, view), ignore={view.id}):
                    _scan_spot(d, sh, view, (view.x, view.y))
        return view

    def finish(view: View, report):
        info = view_info(d, sh, view)
        out = {"view": info, "summary": "section %s-%s of %s | scale %s | "
               "at %s | rev @REV@" % (view.letter, view.letter, par.name,
                                      info["scale"], info["at"])}
        warn = _overflow(d, sh)
        if warn:
            out["warnings"] = warn
        return out

    return _apply(entry, mutate, finish, dry_run, "drawing_section_view",
                  expected_revision)


def _cut_line(cut: Any, bm) -> List[float]:
    """A cut as two points in the parent's own model mm (x right, y up the
    page, the middle of the view the origin)."""
    if not isinstance(cut, dict):
        raise BridgeError(
            "BAD_VALUE", "cut is {\"direction\": \"vertical\"|"
            "\"horizontal\", \"at\": mm} or {\"from\": [x, y], \"to\": "
            "[x, y]}",
            ["at is measured on the parent from the middle of its box; a "
             "vertical line at 0 cuts the part in half left from right."])
    if "from" in cut or "to" in cut:
        a, b = _at(cut.get("from"), "cut.from"), _at(cut.get("to"),
                                                      "cut.to")
        if a is None or b is None:
            raise BridgeError("BAD_VALUE", "cut needs from and to")
        if math.dist(a, b) < 1e-6:
            raise BridgeError("BAD_VALUE", "cut.from and cut.to are the "
                              "same point")
        return [a[0], a[1], b[0], b[1]]
    direction = str(cut.get("direction", "vertical")).lower()
    where = float(cut.get("at", 0.0))
    if direction == "vertical":
        return [where, bm[1] - 8.0, where, bm[3] + 8.0]
    if direction == "horizontal":
        return [bm[0] - 8.0, where, bm[2] + 8.0, where]
    raise BridgeError("BAD_VALUE", "direction is vertical or horizontal")


@op
def drawing_detail_view(ws: Workspace, doc: str = "", parent: Any = "",
                        centre: Any = None, radius: Any = None,
                        scale: Any = None, at: Any = None, name: str = "",
                        sheet: str = "", dry_run: bool = False,
                        expected_revision: Optional[int] = None
                        ) -> Dict[str, Any]:
    """An enlarged circle of a view."""
    entry = ws.get(doc)
    d = need_drawing(entry)
    sh = _sheet(d, sheet)
    _s, par = find_view(d, parent, sh, "parent")
    if par.projection is None:
        _rebuild(entry)
    if par.projection is None:
        raise BridgeError("VIEW_FAILED", "%s has not been drawn" % par.name)
    pscale = d.view_scale(sh, par)
    bm = [c / pscale for c in par.projection.box]
    middle = _at(centre, "centre")
    if middle is None:
        middle = ((bm[0] + bm[2]) / 2.0, (bm[1] + bm[3]) / 2.0)
    r = float(radius) if radius not in (None, "") else max(
        3.0, 0.22 * min(bm[2] - bm[0], bm[3] - bm[1]))
    if r <= 0:
        raise BridgeError("BAD_VALUE", "radius must be above zero (mm)")
    asked = _scale_value(scale) or min(
        dwg.SCALES[0], pscale * 2.0 if pscale * 2.0 in dwg.SCALES
        else pscale * 2.0)
    position = _at(at)

    def mutate():
        view = View(kind=DETAIL, parent=par.id, letter=d.next_letter(),
                    centre=[middle[0] * pscale, middle[1] * pscale],
                    radius=r * pscale, scale=asked, name=name or "",
                    label_visible=True, scale_visible=True,
                    x=par.x + 100.0, y=par.y)
        d.add_view(sh, view)
        view.projection = None
        _rebuild(entry)
        if view.projection is not None:
            if position is not None:
                view.x, view.y = position
            else:
                _detail_spot(d, sh, par, view)
        return view

    def finish(view: View, report):
        info = view_info(d, sh, view)
        out = {"view": info, "summary": "detail %s of %s | scale %s | at "
               "%s | rev @REV@" % (view.letter, par.name, info["scale"],
                                   info["at"])}
        warn = _overflow(d, sh)
        if warn:
            out["warnings"] = warn
        return out

    return _apply(entry, mutate, finish, dry_run, "drawing_detail_view",
                  expected_revision)


def _scan_spot(d, sh, view, near) -> bool:
    """Put a view that may stand anywhere (a section, a detail) on the
    free place nearest ``near``: a grid over the frame, nearest first."""
    box = view.projection.box
    frame = frame_of(d, sh)
    cw, ch = box[2] - box[0], box[3] - box[1]
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    step = 6.0
    spots = []
    x = frame[0] + cw / 2.0
    while x <= frame[2] - cw / 2.0 + 1e-6:
        y = frame[1] + LABEL + ch / 2.0
        while y <= frame[3] - ch / 2.0 + 1e-6:
            spots.append((x, y))
            y += step
        x += step
    spots.sort(key=lambda p: math.dist(p, near))
    for x, y in spots:
        view.x, view.y = x - cx, y - cy
        if _free(d, sh, view_box(sh, view), ignore={view.id}):
            return True
    return False


def _detail_spot(d, sh, par, view) -> None:
    box = view.projection.box
    near = _beside(par, sh, box, "right")
    view.x, view.y = near
    if not _free(d, sh, view_box(sh, view), ignore={view.id}):
        _scan_spot(d, sh, view, near)


# ---------------------------------------------------------------- annotate


def _snap_view(entry: Entry, sh: Sheet, view: View):
    d = entry.document
    gen = generator(entry)
    shape = gen.model_of(d, sh, view)
    direction, up = gen.orientation(d, sh, view)
    return (shape, direction, up, view.projection.centre
            if view.projection else (0.0, 0.0), d.view_scale(sh, view))


def _need_drawn(entry: Entry, sh: Sheet, view: View) -> None:
    if view.projection is None:
        _rebuild(entry)
    if view.projection is None:
        raise BridgeError("VIEW_FAILED", "%s has not been drawn: %s"
                          % (view.name, view.error or "no model"))


def _vertex_pair(entry, sh, view, axis: str):
    """The two model vertices that stand furthest apart across (axis x) or
    up (axis y) the view, with references so the dimension follows the
    model; None where the outline has no vertex there."""
    shape, direction, up, middle, scale = _snap_view(entry, sh, view)
    if shape is None:
        return None
    pts = viewgen.projected_vertices(shape, direction, up, middle, scale)
    if not pts:
        return None
    k = 0 if axis == "x" else 1
    lo = min(p[0][k] for p in pts)
    hi = max(p[0][k] for p in pts)
    other = 1 - k
    first = min((p for p in pts if abs(p[0][k] - lo) < 0.05),
                key=lambda p: p[0][other])
    second = min((p for p in pts if abs(p[0][k] - hi) < 0.05),
                 key=lambda p: p[0][other])
    return first, second, shape


def _ref(shape, index: int):
    from ..core.naming import ShapeRef
    pool = kernel.vertices(shape)
    return ShapeRef.capture(pool[index], "vertex", index, within=shape)


def _overall(entry, sh, view, axis: str, gap: float):
    d = entry.document
    box = view.projection.box
    pair = _vertex_pair(entry, sh, view, axis)
    if pair is not None:
        (pa, ia), (pb, ib), shape = pair[0], pair[1], pair[2]
        points = [[pa[0], pa[1]], [pb[0], pb[1]]]
        anchors = [_ref(shape, ia), _ref(shape, ib)]
    else:
        points = ([[box[0], box[1]], [box[2], box[1]]] if axis == "x"
                  else [[box[2], box[1]], [box[2], box[3]]])
        anchors = []
    if axis == "x":
        offset = [0.0, (box[1] - points[0][1]) - gap]
    else:
        offset = [(box[2] - points[0][0]) + gap, 0.0]
    return Annotation(kind=LINEAR, view=view.id, points=points,
                      anchors=anchors, axis=axis, offset=offset)


def _end_on_circles(entry, sh, view):
    """Every distinct circle seen end on in a view: (centre, radius_sheet,
    count) in the view's own sheet millimetres."""
    shape, direction, up, middle, scale = _snap_view(entry, sh, view)
    if shape is None:
        return []
    marks, _lines = viewgen.centre_features(shape, direction, up, middle,
                                            scale, overhang=0.0)
    out: Dict[Tuple[float, ...], List[Any]] = {}
    for centre, reach in marks:
        key = (round(reach, 3),)
        out.setdefault(key, []).append((centre, reach))
    result = []
    for key, items in sorted(out.items(), key=lambda kv: -kv[0][0]):
        result.append((items[0][0], items[0][1], len(items)))
    return result


@op
def drawing_dimension(ws: Workspace, doc: str = "", view: Any = "",
                      kind: str = "overall", between: Any = None,
                      at: Any = None, axis: str = "", offset: Any = None,
                      text: str = "", prefix: str = "", sheet: str = "",
                      dry_run: bool = False,
                      expected_revision: Optional[int] = None
                      ) -> Dict[str, Any]:
    """Dimension a view: overall size, a distance, a diameter or radius."""
    entry = ws.get(doc)
    d = need_drawing(entry)
    sh = _sheet(d, sheet)
    _s, v = find_view(d, view, sh)
    if kind not in ("overall", "linear", "aligned", "diameter", "radius"):
        raise BridgeError(
            "BAD_VALUE", "kind is overall (width and height), linear, "
            "aligned, diameter or radius")
    if axis not in ("", "x", "y"):
        raise BridgeError("BAD_VALUE", "axis is x (across the page) or y "
                          "(up it)")
    _need_drawn(entry, sh, v)
    scale = d.view_scale(sh, v)
    off = None
    if offset not in (None, ""):
        try:
            off = [float(offset[0]), float(offset[1])]
        except Exception:                               # noqa: BLE001
            raise BridgeError("BAD_VALUE", "offset is [x, y] in sheet mm")

    def mutate():
        made: List[Annotation] = []
        if kind == "overall":
            axes = [axis] if axis else ["x", "y"]
            for a in axes:
                note = _overall(entry, sh, v, a, 12.0 if not off else
                                (off[1] if a == "x" else off[0]))
                if text:
                    note.text = text
                made.append(note)
        elif kind in ("linear", "aligned"):
            pair = _pair(between)
            pts, anchors = [], []
            shape, direction, up, middle, _sc = _snap_view(entry, sh, v)
            for p in pair:
                sheet_pt = [p[0] * scale, p[1] * scale]
                moved, ref = viewgen.snap(shape, direction, up, sheet_pt,
                                          middle, scale, 0.05 * scale + 0.3)
                pts.append(moved)
                anchors.append(ref)
            ax = axis
            if kind == "linear" and not ax:
                ax = "x" if abs(pts[1][0] - pts[0][0]) >= abs(
                    pts[1][1] - pts[0][1]) else "y"
            note = Annotation(
                kind=LINEAR if kind == "linear" else ALIGNED, view=v.id,
                points=pts, anchors=anchors if any(anchors) else [],
                axis=ax if kind == "linear" else "",
                offset=off or ([0.0, -12.0] if ax == "x"
                               else [12.0, 0.0]) if kind == "linear"
                else (off or [0.0, 12.0]), text=text, prefix=prefix)
            made.append(note)
        else:
            sym = DIAMETER if kind == "diameter" else RADIUS
            circles = _end_on_circles(entry, sh, v)
            wanted = _at(at, "at")
            if wanted is not None:
                wanted = (wanted[0] * scale, wanted[1] * scale)
                circles = [c for c in circles if math.dist(
                    c[0], wanted) < max(0.5, c[1])]
                if not circles:
                    raise BridgeError(
                        "NO_MATCH", "no circle seen end on at %s in %s"
                        % (list(at), v.name),
                        ["at is the circle's centre in view mm (origin "
                         "the middle of the view); drawing_note("
                         "kind=\"hole_notes\") lists the holes."])
            if not circles:
                raise BridgeError(
                    "NO_MATCH", "%s shows no round hole or boss end on"
                    % v.name, ["Look at the view from along the hole's "
                               "axis (a top view of a hole in a plate)."])
            shape, direction, up, middle, _sc = _snap_view(entry, sh, v)
            for centre, reach, count in circles:
                r = reach
                tip = [centre[0] + r * math.cos(math.radians(45)),
                       centre[1] + r * math.sin(math.radians(45))]
                note = Annotation(
                    kind=sym, view=v.id, points=[list(centre), tip],
                    offset=off or [6.0, 6.0], text=text,
                    prefix=prefix or ("%dx " % count if count > 1 else ""))
                ref = viewgen.snap_circle(shape, direction, up, centre, r,
                                          middle, scale)
                note.anchors = [ref, None] if ref is not None else []
                made.append(note)
        for note in made:
            note.value = note.measure()
            d.add_annotation(sh, note)
        return made

    def finish(made: List[Annotation], report):
        rows = [_note_info(d, sh, n) for n in made]
        return {"dimensions": rows,
                "summary": "%d dimension%s on %s: %s | rev @REV@" % (
                    len(rows), "" if len(rows) == 1 else "s", v.name,
                    ", ".join(r["text"] for r in rows))}

    return _apply(entry, mutate, finish, dry_run, "drawing_dimension",
                  expected_revision)


def _pair(between: Any) -> List[List[float]]:
    try:
        a, b = between
        return [[float(a[0]), float(a[1])], [float(b[0]), float(b[1])]]
    except Exception:                                   # noqa: BLE001
        raise BridgeError(
            "BAD_VALUE", "between is [[x1, y1], [x2, y2]] in view mm",
            ["Read the view's box_mm from its answer or from "
             "model_tree(); a point near a model corner snaps to it and "
             "the dimension follows the model."])


@op
def drawing_note(ws: Workspace, doc: str = "", view: Any = "",
                 kind: str = "note", text: str = "", at: Any = None,
                 tip: Any = None, offset: Any = None, sheet: str = "",
                 dry_run: bool = False,
                 expected_revision: Optional[int] = None
                 ) -> Dict[str, Any]:
    """Text on a view, or the automatic hole notes and centre marks."""
    entry = ws.get(doc)
    d = need_drawing(entry)
    sh = _sheet(d, sheet)
    _s, v = find_view(d, view, sh)
    if kind not in ("note", "leader", "hole_notes", "centre_marks"):
        raise BridgeError("BAD_VALUE", "kind is note, leader, hole_notes "
                          "or centre_marks")
    if kind in ("note", "leader") and not text:
        raise BridgeError("BAD_VALUE", "give the text")
    _need_drawn(entry, sh, v)
    scale = d.view_scale(sh, v)
    place = _at(at, "at")
    pointed = _at(tip, "tip")

    def mutate():
        made: List[Annotation] = []
        box = v.projection.box
        if kind == "note":
            spot = ((place[0] * scale, place[1] * scale) if place else
                    (box[0], box[3] + 6.0))
            made.append(Annotation(kind=NOTE, view=v.id,
                                   points=[[spot[0], spot[1]]], text=text))
        elif kind == "leader":
            if pointed is None:
                raise BridgeError("BAD_VALUE", "a leader needs tip: [x, y] "
                                  "in view mm, where the arrow points")
            t = [pointed[0] * scale, pointed[1] * scale]
            lab = ((place[0] * scale - t[0], place[1] * scale - t[1])
                   if place else (14.0, 14.0))
            made.append(Annotation(kind=LEADER, view=v.id, points=[t],
                                   offset=list(lab), text=text))
        else:
            shape, direction, up, middle, _sc = _snap_view(entry, sh, v)
            if kind == "hole_notes":
                found = viewgen.hole_notes(shape, direction, up, middle,
                                           scale)
                if not found:
                    raise BridgeError(
                        "NO_MATCH", "%s shows no hole end on" % v.name,
                        ["Hole notes read holes seen along their axis."])
                for label, spot, _n in found:
                    made.append(Annotation(
                        kind=LEADER, view=v.id, points=[list(spot)],
                        offset=list(offset) if offset else [10.0, 10.0],
                        text=label))
            else:
                sh.annotations = [
                    a for a in sh.annotations
                    if not (a.view == v.id and a.text == AUTO_TEXT
                            and a.kind in (CENTRE_MARK, CENTRELINE))]
                marks, lines = viewgen.centre_features(
                    shape, direction, up, middle, scale)
                for centre, reach in marks:
                    made.append(Annotation(
                        kind=CENTRE_MARK, view=v.id,
                        points=[[centre[0], centre[1]]], value=reach,
                        text=AUTO_TEXT))
                for a, b in lines:
                    made.append(Annotation(
                        kind=CENTRELINE, view=v.id,
                        points=[[a[0], a[1]], [b[0], b[1]]],
                        text=AUTO_TEXT))
                if not made:
                    raise BridgeError("NO_MATCH", "%s has no round "
                                      "feature to mark" % v.name)
        for note in made:
            d.add_annotation(sh, note)
        return made

    def finish(made, report):
        rows = [_note_info(d, sh, n) for n in made]
        return {"annotations": rows[:30], "count": len(rows),
                "summary": "%d %s on %s | rev @REV@" % (
                    len(rows), kind.replace("_", " "), v.name)}

    return _apply(entry, mutate, finish, dry_run, "drawing_note",
                  expected_revision)


@op
def drawing_parts_list(ws: Workspace, doc: str = "", view: Any = "",
                       balloons: bool = True, columns: Any = None,
                       recurse: bool = False, sheet: str = "",
                       dry_run: bool = False,
                       expected_revision: Optional[int] = None
                       ) -> Dict[str, Any]:
    """A parts list of the sheet's assembly, and a balloon on each part."""
    entry = ws.get(doc)
    d = need_drawing(entry)
    sh = _sheet(d, sheet)
    if view:
        _s, v = find_view(d, view, sh)
    else:
        v = sh.base_view()
        if v is None:
            raise BridgeError("NO_VIEW", "the sheet has no base view of an "
                              "assembly to list",
                              ["drawing_base_view(source=<.icasm>) first."])
    _need_drawn(entry, sh, v)
    gen = generator(entry)
    targets = gen.balloon_targets(d, sh, v)
    if not targets:
        raise BridgeError(
            "WRONG_TYPE", "%s is not drawn from an assembly, so there is "
            "no parts list" % v.name,
            ["A parts list and balloons are for assemblies: draw an "
             ".icasm."])
    if columns is not None and (not isinstance(columns, list) or not all(
            c in core_bom.DEFAULT_WIDTHS for c in columns)):
        raise BridgeError("BAD_VALUE", "columns come from %s"
                          % ", ".join(core_bom.DEFAULT_WIDTHS))

    def mutate():
        model = d.view_model(sh, v)
        table = PartsList(view=model.id if model else v.id, recurse=recurse)
        if columns:
            table.columns = list(columns)
        frame = frame_of(d, sh)
        block = block_rect(d, sh)
        table.x = frame[2]
        table.y = (block[3] if block is not None else frame[1])
        d.add_parts_list(sh, table)
        _rebuild(entry, force=False)
        if table.error:
            raise BridgeError("VIEW_FAILED", "parts list: %s" % table.error)
        added: List[Annotation] = []
        if balloons:
            existing = {a.component for a in sh.annotations_for(v.id)
                        if a.kind == BALLOON}
            pbox = v.projection.box
            cx, cy = (pbox[0] + pbox[2]) / 2.0, (pbox[1] + pbox[3]) / 2.0
            ring = max(pbox[2] - pbox[0], pbox[3] - pbox[1]) * 0.62 + 16.0
            for index, target in enumerate(targets):
                if target[0] in existing:
                    continue
                angle = math.pi * 0.75 - 2.0 * math.pi * index / max(
                    len(targets), 1)
                seat = (cx + math.cos(angle) * ring,
                        cy + math.sin(angle) * ring)
                # inside the frame, not off the paper
                frame = frame_of(d, sh)
                seat = (min(max(v.x + seat[0], frame[0] + 6.0),
                            frame[2] - 6.0) - v.x,
                        min(max(v.y + seat[1], frame[1] + 6.0),
                            frame[3] - 6.0) - v.y)
                point = viewgen.nearest_corner(target, seat)
                note = Annotation(
                    kind=BALLOON, view=v.id, points=[[point[0], point[1]]],
                    offset=[seat[0] - point[0], seat[1] - point[1]],
                    component=target[0])
                d.add_annotation(sh, note)
                added.append(note)
            _rebuild(entry)
        return table, added

    def finish(made, report):
        table, added = made
        rows = [{"item": r.item, "qty": r.quantity,
                 "part_number": r.part_number,
                 "description": r.description,
                 "material": r.material, "mass": r.mass}
                for r in table.rows]
        return {"parts_list": {"id": table.id, "rows": rows},
                "balloons": len(added),
                "summary": "parts list of %d item%s%s | rev @REV@" % (
                    len(rows), "" if len(rows) == 1 else "s",
                    (" | %d balloon%s" % (len(added), "" if len(added) == 1
                                          else "s")) if balloons else "")}

    return _apply(entry, mutate, finish, dry_run, "drawing_parts_list",
                  expected_revision)


# ---------------------------------------------------------------- output


def _properties(entry: Entry):
    """{Model.*} for each sheet's title block, from its first base view."""
    d = entry.document
    gen = generator(entry)
    found: Dict[int, Dict[str, str]] = {}
    for s in d.sheets:
        base = s.base_view()
        if base is None or not base.ref.path:
            continue
        path = base.ref.resolve(d.base_dir) if d.base_dir else None
        if path is None:
            continue
        try:
            shape, model = viewgen.load_model(path, gen.library)
        except Exception:                               # noqa: BLE001
            shape, model = None, None
        found[s.id] = viewgen.model_properties(path, shape, model,
                                               gen.library)
    return lambda sheet: found.get(sheet.id, {})


def _refreshed(entry: Entry) -> int:
    """Draw views again whose model changed since they were drawn."""
    report = _rebuild(entry)
    if report.stale:
        entry.document.modified = True
        _rebuild(entry, force=True)
        return len(report.stale)
    return 0


def _sheets_for(d: DrawingDocument, sheet: str):
    return [_sheet(d, sheet)] if sheet else list(d.sheets)


@op
def drawing_render(ws: Workspace, doc: str = "", sheet: str = "",
                   width: int = 1100, dry_run: bool = False
                   ) -> Dict[str, Any]:
    """The sheet as a picture, the way it prints: views, hatching,
    dimensions, notes, the title block."""
    entry = ws.get(doc)
    d = need_drawing(entry)
    sh = _sheet(d, sheet)
    refreshed = _refreshed(entry)
    if not sh.views:
        raise BridgeError("NO_VIEW", "the sheet has no views yet",
                          ["drawing_base_view() puts a model on it."])
    qt_application()
    from ..ui import drawingexport
    width = max(200, min(int(width), 3000))
    w_mm, _h = sh.extent()
    dpi = width / (w_mm / 25.4)
    handle, temp = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    try:
        drawingexport.to_image(d, sh, temp, dpi=dpi,
                               properties=_properties(entry))
        with open(temp, "rb") as f:
            png = f.read()
    finally:
        try:
            os.remove(temp)
        except OSError:
            pass
    from PySide6 import QtGui
    image = QtGui.QImage.fromData(png)
    out = {"doc": entry.handle, "revision": entry.revision,
           "sheet": sh.name, "width": image.width(),
           "height": image.height(),
           "png_base64": base64.b64encode(png).decode("ascii"),
           "views": len(sh.views), "annotations": len(sh.annotations)}
    if refreshed:
        out["refreshed_views"] = refreshed
    problems = [v.label + ": " + v.error for v in sh.views if v.error]
    if problems:
        out["problems"] = problems
    return out


@op
def drawing_export(ws: Workspace, path: str, doc: str = "",
                   sheet: str = "", overwrite: bool = False,
                   app_open: Any = None) -> Dict[str, Any]:
    """The drawing as PDF (every sheet), or one sheet as DXF, SVG or PNG,
    chosen by the extension of the absolute path."""
    entry = ws.get(doc)
    d = need_drawing(entry)
    path = ops._absolute(path, "drawing_export")
    ops._refuse_app_file(path, app_open, "exporting onto it")
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".pdf", ".dxf", ".svg", ".png"):
        raise BridgeError("BAD_FORMAT", "cannot export a drawing as %r"
                          % ext, ["Formats: .pdf .dxf .svg .png"])
    if os.path.exists(path) and not overwrite:
        raise BridgeError("WOULD_OVERWRITE", "%s already exists" % path,
                          ["Pass overwrite: true only if the user asked."])
    if not any(s.views for s in d.sheets):
        raise BridgeError("NO_VIEW", "the drawing has no views to export")
    refreshed = _refreshed(entry)
    qt_application()
    from ..ui import drawingexport
    props = _properties(entry)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if ext == ".pdf":
        drawingexport.to_pdf(d, path, None, props)
    else:
        sh = _sheet(d, sheet)
        if ext == ".dxf":
            drawingexport.to_dxf(d, sh, path, props)
        elif ext == ".svg":
            drawingexport.to_svg(d, sh, path, props)
        else:
            drawingexport.to_image(d, sh, path, 150.0, props)
    out = {"path": path, "bytes": os.path.getsize(path),
           "sheets": len(d.sheets) if ext == ".pdf" else 1,
           "summary": "exported %s (%d bytes)" % (os.path.basename(path),
                                                  os.path.getsize(path))}
    if refreshed:
        out["refreshed_views"] = refreshed
    return out


# ---------------------------------------------------------------- editing


def _find_item(d: DrawingDocument, feature: Any):
    """A view, annotation, parts list or sheet by name or #id."""
    t = str(feature).strip()
    ident = None
    if isinstance(feature, int) and not isinstance(feature, bool):
        ident = feature
    elif t.startswith("#") and t[1:].isdigit():
        ident = int(t[1:])
    elif t.isdigit():
        ident = int(t)
    for s in d.sheets:
        for v in s.views:
            if (ident is not None and v.id == ident) or (
                    ident is None and v.name == t):
                return "view", s, v
        for n in s.annotations:
            if ident is not None and n.id == ident:
                return "annotation", s, n
        for p in s.parts_lists:
            if ident is not None and p.id == ident:
                return "parts_list", s, p
        if (ident is not None and s.id == ident) or (
                ident is None and s.name == t):
            return "sheet", s, s
    names = [v.name for s in d.sheets for v in s.views]
    raise BridgeError(
        "NO_VIEW", "no view, annotation or sheet %r" % (feature,),
        ["Views: %s" % (", ".join(names) or "none"),
         "Annotations and parts lists are named by their #id from "
         "model_tree()."])


def edit_item(ws: Workspace, entry: Entry, feature: Any,
              params: Optional[Dict[str, Any]], suppress: Optional[bool],
              delete: bool, delete_dependents: bool, rename: str,
              dry_run: bool, expected_revision: Optional[int]
              ) -> Dict[str, Any]:
    """edit_feature on a drawing: a view (by name), or an annotation,
    parts list or sheet (by #id): move it, change what it shows, rename
    or delete it."""
    d = need_drawing(entry)
    kind, sh, item = _find_item(d, feature)
    if suppress is not None:
        raise BridgeError("BAD_VALUE", "drawings have no suppression; "
                          "delete the item instead")
    changes = dict(params or {})
    if rename:
        changes["name"] = rename
    if not (changes or delete):
        if kind == "view":
            return {"doc": entry.handle, "revision": entry.revision,
                    "view": view_info(d, sh, item)}
        if kind == "annotation":
            return {"doc": entry.handle, "revision": entry.revision,
                    "annotation": _note_info(d, sh, item)}
        return {"doc": entry.handle, "revision": entry.revision,
                "item": kind}

    def descendants(view: View) -> List[View]:
        out, queue = [], [view.id]
        while queue:
            cur = queue.pop()
            for c in sh.children_of(cur):
                out.append(c)
                queue.append(c.id)
        return out

    def mutate():
        if delete:
            if kind == "view":
                below = descendants(item)
                if below and not delete_dependents:
                    raise BridgeError(
                        "HAS_DEPENDENTS", "%s has views derived from it: %s"
                        % (item.name, ", ".join(v.name for v in below)),
                        ["Pass delete_dependents: true to delete them too."],
                        dependents=[{"id": v.id, "name": v.name}
                                    for v in below])
                d.remove_view(sh, item.id, children=True)
            elif kind == "annotation":
                d.remove_annotation(sh, item.id)
            elif kind == "parts_list":
                d.remove_parts_list(sh, item.id)
            else:
                if not d.remove_sheet(item.id):
                    raise BridgeError("BAD_VALUE", "a drawing keeps at "
                                      "least one sheet")
            return None
        if kind == "view":
            unknown = set(changes) - EDITABLE_VIEW
            if unknown:
                raise BridgeError(
                    "BAD_OP", "a view takes: %s (not %s)" % (
                        ", ".join(sorted(EDITABLE_VIEW)),
                        ", ".join(sorted(unknown))))
            dx = dy = 0.0
            for key, value in changes.items():
                if key == "scale":
                    item.scale = _scale_value(value) or 0.0
                elif key == "display":
                    if value not in ("hidden", "visible"):
                        raise BridgeError("BAD_VALUE", "display is hidden "
                                          "or visible")
                    item.display = (WITH_HIDDEN if value == "hidden"
                                    else dwg.VISIBLE_ONLY)
                elif key in ("x", "y"):
                    if key == "x":
                        dx = float(value) - item.x
                    else:
                        dy = float(value) - item.y
                    setattr(item, key, float(value))
                elif key in ("cut", "centre"):
                    if key == "cut" and item.kind == SECTION:
                        par = sh.view(item.parent)
                        ps = d.view_scale(sh, par) if par else 1.0
                        line = _cut_line(value, [-1, -1, 1, 1] if not par
                                         or par.projection is None else
                                         [c / ps for c in
                                          par.projection.box])
                        item.cut = [c * ps for c in line]
                    else:
                        par = sh.view(item.parent)
                        ps = d.view_scale(sh, par) if par else 1.0
                        pt = _at(value, key)
                        item.centre = [pt[0] * ps, pt[1] * ps]
                elif key == "radius":
                    par = sh.view(item.parent)
                    ps = d.view_scale(sh, par) if par else 1.0
                    item.radius = float(value) * ps
                elif key == "orientation":
                    if value not in hlr.ORIENTATIONS:
                        raise BridgeError("BAD_VIEW", "no orientation %r"
                                          % value)
                    item.orientation = value
                    item.direction, item.up = [], []
                else:
                    setattr(item, key, value)
            if dx or dy:
                for v in descendants(item):
                    v.x += dx
                    v.y += dy
            if set(changes) & REDRAW:
                for v in [item] + descendants(item):
                    v.projection = None
        elif kind == "annotation":
            unknown = set(changes) - EDITABLE_NOTE
            if unknown:
                raise BridgeError("BAD_OP", "an annotation takes: %s"
                                  % ", ".join(sorted(EDITABLE_NOTE)))
            for key, value in changes.items():
                setattr(item, key, value)
        elif kind == "parts_list":
            for key, value in changes.items():
                if key not in ("columns", "x", "y", "corner", "recurse",
                               "heading"):
                    raise BridgeError("BAD_OP", "a parts list takes "
                                      "columns, x, y, corner, recurse, "
                                      "heading")
                setattr(item, key, value)
        else:
            for key, value in changes.items():
                if key == "name":
                    item.name = str(value)
                elif key in ("size", "orientation"):
                    setattr(item, key, value)
                    if key == "size":
                        item.custom = list(dwg.SHEET_SIZES.get(
                            value, item.custom))
                else:
                    raise BridgeError("BAD_OP", "a sheet takes name, size "
                                      "and orientation")
        d.modified = True
        return item

    def finish(made, report):
        out: Dict[str, Any] = {}
        if delete:
            out["deleted"] = str(feature)
            out["summary"] = "deleted %s | rev @REV@" % feature
        elif kind == "view":
            out["view"] = view_info(d, sh, item)
            out["summary"] = "changed %s (%s) | rev @REV@" % (
                item.name, ", ".join(sorted(changes)))
        else:
            out["summary"] = "changed %s | rev @REV@" % kind
        return out

    return _apply(entry, mutate, finish, dry_run, "edit_feature",
                  expected_revision)


def properties(ws: Workspace, entry: Entry, parameters, remove, props,
               material: str, expected_revision: Optional[int]
               ) -> Dict[str, Any]:
    """The drawing's own properties: Title, Author, Company, Revision,
    Date, and any others (a title block reads them)."""
    d = need_drawing(entry)
    if parameters or remove or material:
        raise BridgeError("WRONG_TYPE", "a drawing has properties only "
                          "(Title, Author, Company, Revision, Date...)",
                          ["properties(props={...}); its parameters and "
                           "material belong to the model."])
    if props:
        ops._check_revision(entry, expected_revision)
        d.push_undo()
        for key, value in props.items():
            d.properties[str(key)] = str(value)
        d.modified = True
        entry.touch()
    return {"doc": entry.handle, "revision": entry.revision,
            "properties": dict(d.properties)}


def facts() -> Dict[str, Any]:
    """What the drawings guide is written from."""
    return {
        "sizes": {k: list(dwg.SHEET_SIZES[k]) for k in dwg.SHEET_ORDER},
        "standards": {"ISO": "first angle", "ANSI": "third angle"},
        "columns": list(core_bom.DEFAULT_WIDTHS),
        "orientations": list(hlr.ORIENTATIONS),
        "scales": [dwg.scale_text(v) for v in dwg.SCALES],
        "templates": [t.name for t in templates.available("")],
    }
