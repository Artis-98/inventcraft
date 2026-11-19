"""Standard parts for Place from Library, Inventor's Content Center.

Two sources, one way of placing:

* steel profiles are the Frame Generator's own families (frames.py), so
  the library and Insert Frame always offer exactly the same categories,
  standards and sizes, your own families included;
* bolts, screws, nuts and washers are tables here, by ISO standard.

A part is written to a file the first time a size is asked for and reused
after.  The file remembers what it is (``Document.standard_part``), which is how
Change Size knows what to offer when it is opened again on a placed part.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

PROFILE = "profile"
FASTENER = "fastener"

@dataclass
class Family:
    """A table of standard sizes of one part, as the library lists it."""

    id: str
    name: str
    standard: str
    category: str               # where it sits in the library's tree
    kind: str                   # profile, hex_bolt, socket_head, nut, washer
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    needs_length: bool = False
    lengths: List[float] = field(default_factory=list)
    default_length: float = 0.0
    drive: str = ""             # hex, torx, slot, cross, or none
    ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    source: str = ""
    licence: str = ""

    def sizes(self) -> List[str]:
        return [str(r[0]) for r in self.rows]

    def row(self, size: str) -> Dict[str, float]:
        for r in self.rows:
            if str(r[0]) == size:
                return {c: float(v) for c, v in zip(self.columns, r[1:])}
        raise KeyError("%s has no size %s" % (self.name, size))

    def lengths_for(self, size: str) -> List[float]:
        """The standard lengths a size comes in: the family's, inside the
        size's range when the standard gives one."""
        lo, hi = self.ranges.get(size, (0.0, float("inf")))
        return [v for v in self.lengths if lo - 1e-6 <= v <= hi + 1e-6]             or list(self.lengths)

    def default_length_for(self, size: str) -> float:
        """A length to start from: about three diameters, inside the
        size's range."""
        choices = self.lengths_for(size)
        if not choices:
            return self.default_length
        try:
            d = self.row(size).get("d", 0.0)
        except KeyError:
            d = 0.0
        if not d or self.kind == PROFILE:
            return self.default_length if self.default_length in choices                 else choices[len(choices) // 2]
        return min(choices, key=lambda v: abs(v - 3.0 * d))


def fastener_families() -> List[Family]:
    """The bolts, screws, nuts, washers, pins, rings and bearings of the
    standard library (datum/stdlib), each read once."""
    from . import stdlib

    out = []
    for t in stdlib.fasteners() + stdlib.bearings():
        out.append(Family(t.id, t.name, t.standard, t.category, t.kind,
                          list(t.columns), [list(r) for r in t.rows],
                          t.kind in NEEDS_LENGTH, list(t.lengths),
                          20.0 if t.kind != "rod" else 1000.0, t.drive,
                          dict(t.ranges), t.source, t.licence))
    return out


# what is sized by its length as well as its size
NEEDS_LENGTH = {"hex_bolt", "square_bolt", "socket_head", "shoulder",
                "dome", "countersunk", "cheese", "pan", "set_screw", "pin",
                "taper_pin", "spring_pin", "headed_pin", "rod"}


def profile_families() -> List[Family]:
    """The Frame Generator's families, as the library lists them: read
    from frames.families() every time, so the two never differ."""
    from . import frames

    out = []
    for fam in frames.families():
        out.append(Family(fam.id, fam.name, fam.standard,
                          fam.category if fam.kind == "pipe" else
                          "Structural Shapes/" + (fam.category or "Custom"),
                          PROFILE, list(fam.columns),
                          [list(r) for r in fam.rows], True,
                          [100, 250, 500, 1000, 1500, 2000, 3000, 6000],
                          1000.0))
    return out


_fasteners: Optional[List[Family]] = None


def families() -> List[Family]:
    global _fasteners
    if _fasteners is None:
        _fasteners = fastener_families()
    return profile_families() + list(_fasteners)


def family(family_id: str) -> Family:
    for fam in families():
        if fam.id == family_id:
            return fam
    raise KeyError("the library has no %s" % family_id)


# ------------------------------------------------------------- the spec

def spec(family_id: str, size: str, length: float = 0.0) -> Dict[str, Any]:
    fam = family(family_id)
    out = {"family": fam.id, "size": str(size)}
    if fam.needs_length:
        out["length"] = float(length or fam.default_length)
    return out


def part_name(chosen: Dict[str, Any]) -> str:
    """The file name a size is kept under: ISO 4017 M8 x 30."""
    fam = family(chosen["family"])
    text = "%s %s" % (fam.standard or fam.name, chosen["size"])
    if fam.needs_length:
        text += " x %s" % _trim(chosen.get("length", fam.default_length))
    return re.sub(r"[^A-Za-z0-9_. -]+", "-", text).strip()


def _trim(value: float) -> str:
    text = "%.3f" % float(value)
    return text.rstrip("0").rstrip(".")


def description(chosen: Dict[str, Any]) -> str:
    fam = family(chosen["family"])
    text = "%s %s %s" % (fam.name, fam.standard, chosen["size"])
    if fam.needs_length:
        text += " x %s" % _trim(chosen.get("length", 0.0))
    return text


def write_part(chosen: Dict[str, Any], folder: str) -> str:
    """The part file for a size, written into ``folder`` unless one made
    for exactly this is already there.  Returns its path."""
    from . import fileformat
    from .document import Document

    fam = family(chosen["family"])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, part_name(chosen)
                        + fileformat.extension_for(fileformat.PART))
    if os.path.exists(path):
        try:
            if Document.load(path).standard_part == chosen:
                return path
        except Exception:
            pass
    if fam.kind == PROFILE:
        _write_profile(path, fam, chosen)
    else:
        doc = _fastener(fam, chosen)
        doc.standard_part = dict(chosen)
        doc.save(path)
    return path


def _write_profile(path: str, fam: Family, chosen: Dict[str, Any]) -> None:
    from . import frames
    from .document import Document

    member = frames.Member(id=1, family=fam.id, size=chosen["size"])
    frames.write_member_part(path, member, frames.family(fam.id),
                             float(chosen["length"]))
    doc = Document.load(path)
    doc.standard_part = dict(chosen)
    doc.properties["Description"] = description(chosen)
    doc.rebuild()
    doc.save(path)


def _fastener(fam: Family, chosen: Dict[str, Any]):
    """A bolt, screw, nut, washer, pin, ring or bearing as an ordinary
    part (fastener_parts.py), its sizes in the part's parameters."""
    from . import fastener_parts
    from .document import Document

    dims = fam.row(chosen["size"])
    doc = Document()
    for key, value in dims.items():
        doc.params.add(key, "%g" % value)
    length = float(chosen.get("length", 0.0))
    if fam.needs_length:
        doc.params.add("L", "%g" % length)
    fastener_parts.build(doc, fam.kind, fam.drive, dims, length)
    fastener_parts.add_thread(doc, fam.kind, dims, length)
    doc.material = "Steel, Mild"
    doc.properties["Description"] = description(chosen)
    doc.properties["Part Number"] = part_name(chosen)
    doc.properties["Stock Number"] = chosen["size"]
    doc.rebuild()
    return doc


# ------------------------------------------------- files from your folders

NATIVE = (".icpart", ".icasm")
FOREIGN = (".step", ".stp", ".iges", ".igs")
PLACEABLE = NATIVE + FOREIGN


def placeable(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in PLACEABLE


def part_for_file(path: str, folder: str) -> str:
    """What an assembly places for a file from one of your own library
    folders: a part or assembly as it is, a STEP or IGES file as a part
    holding its body, written into ``folder`` the first time and reused
    after, the way Inventor's Import keeps a part for each."""
    from . import fileformat
    from .document import Document
    from .features import ImportFeature

    if os.path.splitext(path)[1].lower() not in FOREIGN:
        return path
    source = os.path.normcase(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_. -]+", "-",
                  os.path.splitext(os.path.basename(path))[0]).strip() \
        or "Imported"
    extension = fileformat.extension_for(fileformat.PART)
    for n in range(1, 1000):
        target = os.path.join(folder, stem + ("" if n == 1 else " (%d)" % n)
                              + extension)
        if not os.path.exists(target):
            break
        try:
            held = next((f for f in Document.load(target).features
                         if isinstance(f, ImportFeature)), None)
        except Exception:
            held = None
        if held is not None and os.path.normcase(
                os.path.abspath(held.path)) == source:
            return target
    doc = Document()
    feature = ImportFeature()
    feature.path = os.path.abspath(path)
    feature.name = stem
    feature.operation = "new"
    doc.add_feature(feature)
    doc.properties["Description"] = stem
    doc.rebuild()
    doc.save(target)
    return target


def spec_of(path: str) -> Optional[Dict[str, Any]]:
    """What a part file was made from in the library, or None."""
    from .document import Document

    if not path or not os.path.exists(path):
        return None
    key = (os.path.normcase(os.path.abspath(path)),
           os.path.getmtime(path))
    if key not in _seen:
        try:
            _seen[key] = dict(Document.load(path).standard_part or {}) or None
        except Exception:
            _seen[key] = None
    return _seen[key]


_seen: Dict[Tuple[str, float], Optional[Dict[str, Any]]] = {}
