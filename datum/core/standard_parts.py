"""Standard parts for Place from Library, Inventor's Content Center.

Two sources, one way of placing:

* steel profiles are the Frame Generator's own families (frames.py), so
  the library and Insert Frame always offer exactly the same categories,
  standards and sizes, your own families included;
* bolts, screws, nuts and washers are tables here, by ISO standard.

A part is written to a file the first time a size is asked for and reused
after.  The file remembers what it is (``Document.library``), which is how
Change Size knows what to offer when it is opened again on a placed part.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

PROFILE = "profile"
FASTENER = "fastener"

# The head and shank of a bolt, a nut, a washer: (size, then the columns).
# Values from the standards' nominal dimensions, in mm.
HEX_BOLT_ISO_4017 = [            # s across flats, k head height
    ["M3", 3.0, 5.5, 2.0], ["M4", 4.0, 7.0, 2.8], ["M5", 5.0, 8.0, 3.5],
    ["M6", 6.0, 10.0, 4.0], ["M8", 8.0, 13.0, 5.3], ["M10", 10.0, 16.0, 6.4],
    ["M12", 12.0, 18.0, 7.5], ["M16", 16.0, 24.0, 10.0],
    ["M20", 20.0, 30.0, 12.5], ["M24", 24.0, 36.0, 15.0],
]
SOCKET_HEAD_ISO_4762 = [         # dk head diameter, k head height, s key
    ["M3", 3.0, 5.5, 3.0, 2.5], ["M4", 4.0, 7.0, 4.0, 3.0],
    ["M5", 5.0, 8.5, 5.0, 4.0], ["M6", 6.0, 10.0, 6.0, 5.0],
    ["M8", 8.0, 13.0, 8.0, 6.0], ["M10", 10.0, 16.0, 10.0, 8.0],
    ["M12", 12.0, 18.0, 12.0, 10.0], ["M16", 16.0, 24.0, 16.0, 14.0],
    ["M20", 20.0, 30.0, 20.0, 17.0], ["M24", 24.0, 36.0, 24.0, 19.0],
]
HEX_NUT_ISO_4032 = [             # s across flats, m height
    ["M3", 3.0, 5.5, 2.4], ["M4", 4.0, 7.0, 3.2], ["M5", 5.0, 8.0, 4.7],
    ["M6", 6.0, 10.0, 5.2], ["M8", 8.0, 13.0, 6.8], ["M10", 10.0, 16.0, 8.4],
    ["M12", 12.0, 18.0, 10.8], ["M16", 16.0, 24.0, 14.8],
    ["M20", 20.0, 30.0, 18.0], ["M24", 24.0, 36.0, 21.5],
]
WASHER_ISO_7089 = [              # d1 hole, d2 outside, h thickness
    ["M3", 3.2, 7.0, 0.5], ["M4", 4.3, 9.0, 0.8], ["M5", 5.3, 10.0, 1.0],
    ["M6", 6.4, 12.0, 1.6], ["M8", 8.4, 16.0, 1.6], ["M10", 10.5, 20.0, 2.0],
    ["M12", 13.0, 24.0, 2.5], ["M16", 17.0, 30.0, 3.0],
    ["M20", 21.0, 37.0, 3.0], ["M24", 25.0, 44.0, 4.0],
]
BOLT_LENGTHS = [6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65,
                70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 180, 200]


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

    def sizes(self) -> List[str]:
        return [str(r[0]) for r in self.rows]

    def row(self, size: str) -> Dict[str, float]:
        for r in self.rows:
            if str(r[0]) == size:
                return {c: float(v) for c, v in zip(self.columns, r[1:])}
        raise KeyError("%s has no size %s" % (self.name, size))


def fastener_families() -> List[Family]:
    return [
        Family("iso-4017", "Hex Head Bolt, full thread", "ISO 4017",
               "Fasteners/Bolts", "hex_bolt", ["d", "s", "k"],
               HEX_BOLT_ISO_4017, True, list(BOLT_LENGTHS), 20.0),
        Family("iso-4762", "Socket Head Cap Screw", "ISO 4762",
               "Fasteners/Bolts", "socket_head", ["d", "dk", "k", "s"],
               SOCKET_HEAD_ISO_4762, True, list(BOLT_LENGTHS), 20.0),
        Family("iso-4032", "Hex Nut", "ISO 4032", "Fasteners/Nuts", "nut",
               ["d", "s", "m"], HEX_NUT_ISO_4032),
        Family("iso-7089", "Plain Washer", "ISO 7089", "Fasteners/Washers",
               "washer", ["d1", "d2", "h"], WASHER_ISO_7089),
    ]


def profile_families() -> List[Family]:
    """The Frame Generator's families, as the library lists them: read
    from frames.families() every time, so the two never differ."""
    from . import frames

    out = []
    for fam in frames.families():
        out.append(Family(fam.id, fam.name, fam.standard,
                          "Structural Shapes/" + (fam.category or "Custom"),
                          PROFILE, list(fam.columns),
                          [list(r) for r in fam.rows], True,
                          [100, 250, 500, 1000, 1500, 2000, 3000, 6000],
                          1000.0))
    return out


def families() -> List[Family]:
    return profile_families() + fastener_families()


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
            if Document.load(path).library == chosen:
                return path
        except Exception:
            pass
    if fam.kind == PROFILE:
        _write_profile(path, fam, chosen)
    else:
        doc = _fastener(fam, chosen)
        doc.library = dict(chosen)
        doc.save(path)
    return path


def _write_profile(path: str, fam: Family, chosen: Dict[str, Any]) -> None:
    from . import frames
    from .document import Document

    member = frames.Member(id=1, family=fam.id, size=chosen["size"])
    frames.write_member_part(path, member, frames.family(fam.id),
                             float(chosen["length"]))
    doc = Document.load(path)
    doc.library = dict(chosen)
    doc.properties["Description"] = description(chosen)
    doc.rebuild()
    doc.save(path)


def _fastener(fam: Family, chosen: Dict[str, Any]):
    """A bolt, screw, nut or washer as an ordinary part: sketches extruded,
    its sizes in the part's parameters.  The head sits on the XY plane and
    a shank runs down -Z, so it drops onto a face head up."""
    from .document import Document
    from .features import CUT, JOIN, ExtrudeFeature, SketchFeature
    from .sketch import Sketch, SketchPlane

    dims = fam.row(chosen["size"])
    doc = Document()
    for key, value in dims.items():
        doc.params.add(key, "%g" % value)
    length = float(chosen.get("length", 0.0))
    if fam.needs_length:
        doc.params.add("L", "%g" % length)

    def plane(z: float) -> SketchPlane:
        return SketchPlane((0.0, 0.0, z), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0),
                           name="XY Plane")

    def extrude(name, sketch, distance, operation=JOIN, flip=False):
        feature = SketchFeature(name=name)
        feature.sketch = sketch
        doc.add_feature(feature)
        solid = ExtrudeFeature(name=name.replace("Sketch", "Extrusion"))
        solid.sketch_id = feature.id
        solid.distance = distance
        solid.operation = operation
        solid.reversed = flip
        doc.add_feature(solid)

    hexagon = 1.1547005383792515      # across corners over across flats
    if fam.kind in ("hex_bolt", "socket_head"):
        shank = Sketch(plane(0.0), "Shank Sketch")
        shank.add_circle((0.0, 0.0), dims["d"] / 2.0)
        extrude("Shank Sketch", shank, "L", flip=True)
        head = Sketch(plane(0.0), "Head Sketch")
        if fam.kind == "hex_bolt":
            head.add_polygon((0.0, 0.0), dims["s"] * hexagon / 2.0, 6)
        else:
            head.add_circle((0.0, 0.0), dims["dk"] / 2.0)
        extrude("Head Sketch", head, "k")
        if fam.kind == "socket_head":
            key = Sketch(plane(dims["k"]), "Socket Sketch")
            key.add_polygon((0.0, 0.0), dims["s"] * hexagon / 2.0, 6)
            extrude("Socket Sketch", key, "%g" % (dims["k"] * 0.6), CUT,
                    flip=True)
    elif fam.kind == "nut":
        body = Sketch(plane(0.0), "Nut Sketch")
        body.add_polygon((0.0, 0.0), dims["s"] * hexagon / 2.0, 6)
        body.add_circle((0.0, 0.0), dims["d"] / 2.0)
        extrude("Nut Sketch", body, "m")
    elif fam.kind == "washer":
        body = Sketch(plane(0.0), "Washer Sketch")
        body.add_circle((0.0, 0.0), dims["d2"] / 2.0)
        body.add_circle((0.0, 0.0), dims["d1"] / 2.0)
        extrude("Washer Sketch", body, "h")
    doc.material = "Steel, Mild"
    doc.properties["Description"] = description(chosen)
    doc.properties["Part Number"] = part_name(chosen)
    doc.properties["Stock Number"] = chosen["size"]
    doc.rebuild()
    return doc


def spec_of(path: str) -> Optional[Dict[str, Any]]:
    """What a part file was made from in the library, or None."""
    from .document import Document

    if not path or not os.path.exists(path):
        return None
    key = (os.path.normcase(os.path.abspath(path)),
           os.path.getmtime(path))
    if key not in _seen:
        try:
            _seen[key] = dict(Document.load(path).library or {}) or None
        except Exception:
            _seen[key] = None
    return _seen[key]


_seen: Dict[Tuple[str, float], Optional[Dict[str, Any]]] = {}
