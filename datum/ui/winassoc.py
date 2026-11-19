"""InventCraft's file types in Windows Explorer: each kind its own icon.

The installer registers them (tools/installer.iss), but only when it runs,
and an installed copy updates itself without running it again.  So a copy
first installed before the file types had their own icons, or installed
with the box unticked, never got them, and Explorer showed every
InventCraft file as a blank page.  This does the same registration from
the program itself, for the current user, when it starts: the same
ProgIDs and icons as the installer, pointed at wherever this copy is.

It only ever writes under HKEY_CURRENT_USER\\Software\\Classes, and it
leaves alone an extension that some other program has been given; a
choice the user made in Explorer ("Open with... Always") is theirs and is
not touched either.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

PROGIDS: Dict[str, Tuple[str, str]] = {
    "IITEG.DATUM.Part": ("InventCraft Part", "part.ico"),
    "IITEG.DATUM.Assembly": ("InventCraft Assembly", "assembly.ico"),
    "IITEG.DATUM.Cam": ("InventCraft CAM Sheet", "cam.ico"),
    "IITEG.DATUM.Drawing": ("InventCraft Drawing", "drawing.ico"),
}
EXTENSIONS: Dict[str, str] = {
    ".icpart": "IITEG.DATUM.Part", ".icasm": "IITEG.DATUM.Assembly",
    ".iccam": "IITEG.DATUM.Cam", ".icdraw": "IITEG.DATUM.Drawing",
    # DATUM's own, from before 0.3.0
    ".pdat": "IITEG.DATUM.Part", ".adat": "IITEG.DATUM.Assembly",
    ".cdat": "IITEG.DATUM.Cam", ".ddat": "IITEG.DATUM.Drawing",
}


def icon_folder() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "assets", "filetypes")


def plan(exe: str, folder: str) -> List[Tuple[str, str]]:
    """Every (key under Software\\Classes, value) this copy wants."""
    out = []
    for progid, (title, ico) in PROGIDS.items():
        out.append((progid, title))
        out.append((progid + "\\DefaultIcon",
                    '"%s"' % os.path.join(folder, ico)))
        out.append((progid + "\\shell\\open\\command",
                    '"%s" "%%1"' % exe))
    for ext, progid in EXTENSIONS.items():
        out.append((ext, progid))
    return out


def register(exe: str = "", folder: str = "",
             base: str = r"Software\Classes") -> int:
    """Write what is missing or out of date.  Returns how many values it
    wrote; 0 when everything was already in place, or off Windows."""
    if sys.platform != "win32":
        return 0
    import winreg
    exe = exe or sys.executable
    folder = folder or icon_folder()
    if not all(os.path.exists(os.path.join(folder, ico))
               for _t, ico in PROGIDS.values()):
        return 0
    written = 0
    for key, value in plan(exe, folder):
        path = base + "\\" + key
        current = None
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                current = winreg.QueryValueEx(k, "")[0]
        except OSError:
            current = None
        if key.startswith(".") and current and not current.startswith(
                "IITEG.DATUM."):
            continue        # another program's: leave it be
        if current == value:
            continue
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0,
                                winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, value)
        written += 1
    if written and base == r"Software\Classes":
        # Explorer redraws file icons only once it is told they changed
        try:
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None,
                                                 None)
        except Exception:  # noqa: BLE001
            pass
    return written


def register_if_installed() -> int:
    """On start, in an installed (frozen) copy only: running from the
    source tree must not point Explorer at a Python interpreter."""
    if not getattr(sys, "frozen", False):
        return 0
    try:
        return register()
    except Exception:  # noqa: BLE001
        return 0
