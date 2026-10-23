"""Keyboard shortcuts: every command that has one, and the person's own.

One table, so the keys the window answers to, the Shortcuts page in
Preferences and the README can never disagree about what M does.  The
defaults are Inventor's where Inventor has one: M measures, V and G free
move and free rotate, C constrains in an assembly.

What somebody changes is kept in Preferences as command -> keys, only for
the commands they changed, so a default retuned later still reaches
everybody who never touched it.  An empty string there means "no key".
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6 import QtGui

from ..core import prefs as core_prefs

# (command, what it does, the keys it comes with)
COMMANDS: List[Tuple[str, str, str]] = [
    ("new", "New document", "Ctrl+N"),
    ("open", "Open", "Ctrl+O"),
    ("save", "Save", "Ctrl+S"),
    ("save_as", "Save As", "Ctrl+Shift+S"),
    ("close", "Close the document", "Ctrl+W"),
    ("undo", "Undo", "Ctrl+Z"),
    ("redo", "Redo", "Ctrl+Y"),
    ("redo_alt", "Redo, the second key", "Ctrl+Shift+Z"),
    ("parameters", "Parameters", "Ctrl+P"),
    ("local_update", "Local Update", "Ctrl+U"),
    ("next_document", "Next document", "Ctrl+Tab"),
    ("previous_document", "Previous document", "Ctrl+Shift+Tab"),
    ("copy", "Copy components", "Ctrl+C"),
    ("paste", "Paste components", "Ctrl+V"),
    ("measure", "Measure", "M"),
    ("sketch", "Start 2D Sketch", "S"),
    ("extrude", "Extrude", "E"),
    ("revolve", "Revolve", "R"),
    ("hole", "Hole", "H"),
    ("fillet", "Fillet", "F"),
    ("line", "Sketch: Line", "L"),
    ("circle", "Sketch: Circle; in an assembly, Constrain", "C"),
    ("arc", "Sketch: Arc", "A"),
    ("rectangle", "Sketch: Rectangle", "Ctrl+R"),
    ("dimension", "Sketch: Dimension", "D"),
    ("place", "Place Component (assembly, CAM sheet)", "P"),
    ("free_move", "Free Move (assembly, CAM sheet)", "V"),
    ("free_rotate", "Free Rotate (assembly)", "G"),
    ("cam_sheet", "CAM: Sheet settings", "Ctrl+E"),
]

DEFAULTS: Dict[str, str] = {command: keys for command, _what, keys
                            in COMMANDS}
LABELS: Dict[str, str] = {command: what for command, what, _keys
                          in COMMANDS}


def normal(keys: str) -> str:
    """Keys as Qt writes them, so "ctrl+s" and "Ctrl+S" are one thing."""
    return QtGui.QKeySequence(keys or "").toString(
        QtGui.QKeySequence.PortableText)


def effective(overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Every command's keys: the person's own where they set one."""
    chosen = (core_prefs.prefs().shortcuts if overrides is None
              else overrides)
    out = dict(DEFAULTS)
    for command, keys in (chosen or {}).items():
        if command in out:
            out[command] = normal(keys)
    return out


def changes(keys: Dict[str, str]) -> Dict[str, str]:
    """Only what differs from the defaults, for Preferences to keep."""
    return {command: normal(value) for command, value in keys.items()
            if command in DEFAULTS
            and normal(value) != normal(DEFAULTS[command])}


def clashes(keys: Dict[str, str]) -> Dict[str, List[str]]:
    """Keys given to more than one command: keys -> those commands."""
    seen: Dict[str, List[str]] = {}
    for command, value in keys.items():
        if value:
            seen.setdefault(normal(value), []).append(command)
    return {k: v for k, v in seen.items() if len(v) > 1}
