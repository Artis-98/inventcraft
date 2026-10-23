"""Which way a document calls Front and Top, and where its Home view is.

Inventor keeps both in the document.  Set Current View as Front (or Top)
relabels the view cube for that part, and Front, Top, Right and the rest
of the named views follow it, in the model and in the views a drawing
places of it.  Set Current View as Home is where a click on the house
beside the cube goes: the camera exactly as it was (Fixed Distance), or
looking the same way and fitted to whatever the part has since become
(Fit to View).  A document without either has the stock ones: Front looks
along +Y with Z up, and Home is the isometric, fitted.
"""

from __future__ import annotations

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

_AXES: Tuple[Vec, ...] = ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
                          (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
                          (0.0, 0.0, 1.0), (0.0, 0.0, -1.0))


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(float(a[i]) * float(b[i]) for i in range(3))


def _cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def snap(v: Sequence[float], square_to: Optional[Sequence[float]] = None
         ) -> Vec:
    """The axis direction nearest ``v``; with ``square_to``, the nearest
    of those square to it."""
    axes = [a for a in _AXES
            if square_to is None or abs(_dot(a, square_to)) < 1e-9]
    return max(axes, key=lambda a: _dot(a, v))


def _clean(v: Sequence[float]) -> Vec:
    return tuple(0.0 if abs(c) < 1e-12 else float(c) for c in v)  # type: ignore


@dataclass
class ViewSetup:
    front: Vec = DEFAULT_FRONT
    top: Vec = DEFAULT_TOP
    # None for the stock isometric; otherwise {"fit": bool, "camera":
    # [eye, centre, up, scale, orthographic]}, the camera as it was set
    home: Optional[Dict[str, Any]] = field(default=None)

    # -- Front and Top --------------------------------------------------------

    def is_default(self) -> bool:
        return (tuple(self.front) == DEFAULT_FRONT
                and tuple(self.top) == DEFAULT_TOP)

    def right(self) -> Vec:
        return _cross(self.top, self.front)

    def turn(self, v: Sequence[float]) -> Vec:
        """A direction of the stock setup, in this one."""
        r, f, t = self.right(), self.front, self.top
        # the stock right is +X, its front -Y and its top +Z
        return _clean([v[0] * r[i] - v[1] * f[i] + v[2] * t[i]
                       for i in range(3)])

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
        """Set Current View as Front: the face looked at is Front, and
        whichever way is up on the screen is Top."""
        front = snap([-c for c in look])
        self.front, self.top = front, snap(up, square_to=front)

    def set_top(self, look: Sequence[float], up: Sequence[float]) -> None:
        """Set Current View as Top: the face looked at is Top, and the one
        at the bottom of the screen, nearest the viewer, is Front."""
        top = snap([-c for c in look])
        self.top, self.front = top, snap([-c for c in up], square_to=top)

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
            front = snap([float(c) for c in data.get("front", DEFAULT_FRONT)])
            top = snap([float(c) for c in data.get("top", DEFAULT_TOP)],
                       square_to=front)
            setup.front, setup.top = front, top
        except (TypeError, ValueError, IndexError):
            pass
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
