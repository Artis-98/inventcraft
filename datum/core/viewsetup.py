"""Which way a document calls Front and Top, and where its Home view is.

Inventor keeps both in the document.  Set Current View as Front (or Top)
takes the view exactly as it is on screen, at whatever angle, and the view
cube turns to match: a part modelled at some odd angle is looked at square
on a face of its own, that view is made Front, and from then on Front,
Top, Right and the rest, in the model and in the views a drawing places
of it, are square to the part rather than to the world.  Set Current View
as Home is where a click on the house beside the cube goes: the camera
exactly as it was (Fixed Distance), or looking the same way and fitted to
whatever the part has since become (Fit to View).  A document without
either has the stock ones: Front looks along +Y with Z up, and Home is
the isometric, fitted.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

from . import hlr

Vec = Tuple[float, float, float]

DEFAULT_FRONT: Vec = (0.0, -1.0, 0.0)     # the face called Front faces -Y
DEFAULT_TOP: Vec = (0.0, 0.0, 1.0)

# each named face, outward, as the stock setup has it
FACES: Dict[str, Vec] = {
    "front": (0.0, -1.0, 0.0), "back": (0.0, 1.0, 0.0),
    "left": (-1.0, 0.0, 0.0), "right": (1.0, 0.0, 0.0),
    "top": (0.0, 0.0, 1.0), "bottom": (0.0, 0.0, -1.0),
}


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(float(a[i]) * float(b[i]) for i in range(3))


def _cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _unit(v: Sequence[float]) -> Optional[Vec]:
    size = math.sqrt(_dot(v, v))
    if size < 1e-9:
        return None
    return _clean([float(c) / size for c in v])


def _clean(v: Sequence[float]) -> Vec:
    return tuple(0.0 if abs(c) < 1e-12 else float(c) for c in v)  # type: ignore


def _square_to(v: Sequence[float], normal: Sequence[float]) -> Optional[Vec]:
    """``v`` with any part along ``normal`` taken out, made unit."""
    along = _dot(v, normal)
    return _unit([v[i] - along * normal[i] for i in range(3)])


def _frame(front: Sequence[float], top: Sequence[float]
           ) -> Optional[Tuple[Vec, Vec]]:
    """Front and Top made unit and square to each other; None when they
    cannot be (no length, or the two along one line)."""
    f = _unit(front)
    if f is None:
        return None
    t = _square_to(top, f)
    if t is None:
        return None
    return f, t


@dataclass
class ViewSetup:
    front: Vec = DEFAULT_FRONT
    top: Vec = DEFAULT_TOP
    # None for the stock isometric; otherwise {"fit": bool, "camera":
    # [eye, centre, up, scale, orthographic]}, the camera as it was set
    home: Optional[Dict[str, Any]] = field(default=None)

    # -- Front and Top --------------------------------------------------------

    def is_default(self) -> bool:
        return (_dot(self.front, DEFAULT_FRONT) > 1.0 - 1e-9
                and _dot(self.top, DEFAULT_TOP) > 1.0 - 1e-9)

    def right(self) -> Vec:
        return _cross(self.top, self.front)

    def turn(self, v: Sequence[float]) -> Vec:
        """A direction of the stock setup, in this one: the rotation the
        view cube is turned by."""
        r, f, t = self.right(), self.front, self.top
        # the stock right is +X, its front -Y and its top +Z
        return _clean([v[0] * r[i] - v[1] * f[i] + v[2] * t[i]
                       for i in range(3)])

    def local(self, v: Sequence[float]) -> Vec:
        """A direction in the world, as the stock setup would have it: the
        turn undone."""
        return _clean((_dot(v, self.right()), -_dot(v, self.front),
                       _dot(v, self.top)))

    def face_normal(self, name: str) -> Vec:
        """The outward direction of the face this document calls ``name``."""
        return self.turn(FACES[name])

    def face_at(self, normal: Sequence[float]) -> Optional[str]:
        """What this document calls the face facing this way."""
        for name in FACES:
            if _dot(self.face_normal(name), normal) > 0.999:
                return name
        return None

    def orientation(self, name: str) -> Tuple[Vec, Vec]:
        """A named view as hlr has them, (look along, up), turned to this
        document's Front and Top."""
        look, up = hlr.ORIENTATIONS[name]
        return self.turn(look), self.turn(up)

    def set_front(self, look: Sequence[float], up: Sequence[float]) -> None:
        """Set Current View as Front: the view exactly as it is, at any
        angle, is Front, and up the screen is Top."""
        frame = _frame([-c for c in look], up)
        if frame is not None:
            self.front, self.top = frame

    def set_top(self, look: Sequence[float], up: Sequence[float]) -> None:
        """Set Current View as Top: the view exactly as it is looks down on
        Top, and down the screen, towards the viewer, is Front."""
        frame = _frame([-c for c in look], [-c for c in up])
        if frame is not None:
            self.top, self.front = frame

    def reset_front(self) -> None:
        self.front, self.top = DEFAULT_FRONT, DEFAULT_TOP

    # -- saved ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"front": list(self.front),
                               "top": list(self.top)}
        if self.home:
            out["home"] = {"fit": bool(self.home.get("fit")),
                           "camera": self.home.get("camera")}
        return out

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ViewSetup":
        setup = cls()
        if not isinstance(data, dict):
            return setup
        try:
            frame = _frame([float(c) for c in data.get("front",
                                                      DEFAULT_FRONT)][:3],
                           [float(c) for c in data.get("top",
                                                      DEFAULT_TOP)][:3])
        except (TypeError, ValueError, IndexError):
            frame = None
        if frame is not None and len(frame[0]) == 3:
            setup.front, setup.top = frame
        home = data.get("home")
        if isinstance(home, dict) and home.get("camera"):
            setup.home = {"fit": bool(home.get("fit")),
                          "camera": home.get("camera")}
        return setup


_read: Dict[str, Tuple[float, ViewSetup]] = {}


def of_file(path: str) -> ViewSetup:
    """The setup saved in a part or an assembly file; the stock one for a
    file that has none or cannot be read.  Remembered until it changes."""
    from . import fileformat

    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return ViewSetup()
    known = _read.get(path)
    if known is not None and known[0] == stamp:
        return known[1]
    try:
        setup = ViewSetup.from_dict(fileformat.read(path).geometry.get("view"))
    except Exception:
        setup = ViewSetup()
    _read[path] = (stamp, setup)
    return setup
