"""Who is using this, and how they want it to look.

Two unrelated-looking things live in one file for one reason: both belong
to the person, not to the document.  A part carries the name of whoever
designed it because that is a fact about the part; the colour of the
background is a fact about the person looking at it, and it has no
business being saved into a file somebody else will open.

So this is the user's own corner: a small JSON file next to their own
materials, outside the installation, which an update replaces wholesale
and must never touch.

It deliberately holds no credentials.  Nothing here talks to a server, and
a store of secrets with nothing to unlock is a liability rather than a
feature.  If something ever does need one, it goes in the operating
system's keyring, not in a plain file beside the preferences.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

APP_FOLDER = "DATUM"
ORG_FOLDER = "IITEG"
FILE_NAME = "preferences.json"

# the appearance keys the Display page is allowed to set, which is a short
# list on purpose: these are the ones somebody actually wants to change
COLOUR_KEYS = (
    "bg_top", "bg_bottom",
    "sketch_line", "sketch_free", "sketch_construction",
)


# how the view orbits under the mouse: freely about any axis, or as a
# turntable that spins about Z and keeps Z pointing up the screen
ORBIT_FREE = "free"
ORBIT_TURNTABLE = "turntable"
ORBITS = (ORBIT_FREE, ORBIT_TURNTABLE)

# the colour schemes: InventCraft's light one, and the dark one DATUM had
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = (THEME_LIGHT, THEME_DARK)

# Which mouse button turns the view and which slides it; the wheel always
# zooms.  "shift_middle" is the wheel held down with Shift, Inventor's
# orbit.  A left button drag that navigates still leaves a plain click
# selecting, and the selection box moves to Shift and the left button.
MOUSE_LEFT = "left"
MOUSE_MIDDLE = "middle"
MOUSE_SHIFT_MIDDLE = "shift_middle"
MOUSE_RIGHT = "right"
ORBIT_BUTTONS = (MOUSE_RIGHT, MOUSE_SHIFT_MIDDLE, MOUSE_MIDDLE, MOUSE_LEFT)
PAN_BUTTONS = (MOUSE_MIDDLE, MOUSE_LEFT, MOUSE_RIGHT)
# the ready-made sets: (name, orbit, pan)
MOUSE_SCHEMES = (
    ("InventCraft", MOUSE_RIGHT, MOUSE_MIDDLE),
    ("Inventor", MOUSE_SHIFT_MIDDLE, MOUSE_MIDDLE),
    ("Pan with the left button", MOUSE_RIGHT, MOUSE_LEFT),
)


def config_dir() -> str:
    """Where this machine keeps the user's own DATUM files.

    Honours ``DATUM_CONFIG_DIR`` so a test run cannot disturb the
    preferences of whoever is actually working in the application.
    """
    forced = os.environ.get("DATUM_CONFIG_DIR")
    if forced:
        return forced
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    if base:
        return os.path.join(base, ORG_FOLDER, APP_FOLDER)
    return os.path.join(os.path.expanduser("~"), ".config", APP_FOLDER.lower())


def config_path(name: str = FILE_NAME) -> str:
    return os.path.join(config_dir(), name)


@dataclass
class Preferences:
    """Everything the application remembers about its user."""

    # who they are.  Stamped onto new documents, and read by a title block.
    name: str = ""
    initials: str = ""
    company: str = ""
    # which colour scheme, and the colours they have changed in each:
    # theme colour name -> "#rrggbb".  Kept apart, so a dark backdrop
    # chosen for the dark scheme does not end up behind the light one.
    theme: str = THEME_LIGHT
    colours: Dict[str, str] = field(default_factory=dict)        # dark
    light_colours: Dict[str, str] = field(default_factory=dict)
    # folders whose documents may run their cLogic without asking.  Kept
    # here, on this machine, because a file must never vouch for itself.
    trusted_folders: List[str] = field(default_factory=list)
    orbit: str = ORBIT_FREE
    # what a new part or assembly is drawn in
    units: str = "mm"
    # the SpaceMouse's speeds, deadzone and axis directions, as its
    # settings window last left them
    spacemouse: Dict[str, Any] = field(default_factory=dict)
    # the mouse: which button orbits, which pans, and which way the wheel
    # zooms
    mouse_orbit: str = MOUSE_RIGHT
    mouse_pan: str = MOUSE_MIDDLE
    zoom_reversed: bool = False
    # how many of the files a save replaces are kept in OldVersions beside
    # it, as Inventor's setting is: 0 none, a negative number every one
    old_versions: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "initials": self.initials,
                "company": self.company, "theme": self.theme,
                "colours": dict(self.colours),
                "light_colours": dict(self.light_colours),
                "trusted_folders": list(self.trusted_folders),
                "orbit": self.orbit, "units": self.units,
                "spacemouse": dict(self.spacemouse),
                "mouse_orbit": self.mouse_orbit,
                "mouse_pan": self.mouse_pan,
                "zoom_reversed": self.zoom_reversed,
                "old_versions": self.old_versions}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Preferences":
        colours = data.get("colours") or {}
        light = data.get("light_colours") or {}
        return cls(
            name=str(data.get("name", "")),
            initials=str(data.get("initials", "")),
            company=str(data.get("company", "")),
            theme=(str(data.get("theme")) if data.get("theme") in THEMES
                   else THEME_LIGHT),
            colours={str(k): str(v) for k, v in colours.items()
                     if k in COLOUR_KEYS and _is_colour(v)},
            light_colours={str(k): str(v) for k, v in light.items()
                           if k in COLOUR_KEYS and _is_colour(v)},
            trusted_folders=[str(f) for f in
                             data.get("trusted_folders", []) or [] if f],
            orbit=(str(data.get("orbit")) if data.get("orbit") in ORBITS
                   else ORBIT_FREE),
            units=_units(data.get("units")),
            spacemouse=(dict(data.get("spacemouse"))
                        if isinstance(data.get("spacemouse"), dict) else {}),
            mouse_orbit=(str(data.get("mouse_orbit"))
                         if data.get("mouse_orbit") in ORBIT_BUTTONS
                         else MOUSE_RIGHT),
            mouse_pan=(str(data.get("mouse_pan"))
                       if data.get("mouse_pan") in PAN_BUTTONS
                       and data.get("mouse_pan") != data.get("mouse_orbit")
                       else MOUSE_MIDDLE),
            zoom_reversed=bool(data.get("zoom_reversed", False)),
            old_versions=_count(data.get("old_versions"), 1))

    def colours_for(self, theme: str) -> Dict[str, str]:
        """The colours changed in one scheme."""
        return self.light_colours if theme == THEME_LIGHT else self.colours

    def set_colours_for(self, theme: str, colours: Dict[str, str]) -> None:
        if theme == THEME_LIGHT:
            self.light_colours = dict(colours)
        else:
            self.colours = dict(colours)

    def stamp(self, properties: Dict[str, str],
              key: str = "Designer") -> Dict[str, str]:
        """Fill in the fields a new document should already know.

        Only the blank ones: a document that says who drew it is stating a
        fact, and opening it on somebody else's machine does not change
        who that was.
        """
        if self.name and not properties.get(key):
            properties[key] = self.name
        if self.company and not properties.get("Company"):
            properties["Company"] = self.company
        return properties

    def save(self, path: str = "") -> str:
        target = path or config_path()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)
            handle.write("\n")
        return target


def _units(value: Any) -> str:
    from .units import LENGTHS
    return str(value) if value in LENGTHS else "mm"


def _count(value: Any, default: int) -> int:
    try:
        return max(-1, min(999, int(value)))
    except (TypeError, ValueError):
        return default


def _is_colour(value: Any) -> bool:
    text = str(value)
    return (len(text) == 7 and text.startswith("#")
            and all(c in "0123456789abcdefABCDEF" for c in text[1:]))


def load(path: str = "") -> Preferences:
    """Read the file, or hand back the defaults if there is not one yet."""
    target = path or config_path()
    if not os.path.exists(target):
        return Preferences()
    try:
        with open(target, encoding="utf-8") as handle:
            return Preferences.from_dict(json.load(handle))
    except (OSError, ValueError):
        # a corrupt preferences file is not worth refusing to start over
        return Preferences()


_PREFS: Optional[Preferences] = None


def prefs() -> Preferences:
    """The one set of preferences the application is running with."""
    global _PREFS
    if _PREFS is None:
        _PREFS = load()
    return _PREFS


def reset() -> None:
    """Forget them, so the next ask re-reads the file.  For tests, and for
    the moment the Preferences window writes a new one."""
    global _PREFS
    _PREFS = None
