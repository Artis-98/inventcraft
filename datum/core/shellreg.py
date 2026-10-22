"""Windows' side of the rename from DATUM to InventCraft.

A copy that updated itself from 0.2.x took in the new program but not what
the installer does around it: the new file endings are not registered, and
the Start menu and the desktop still say DATUM.  Both are put right here,
once, the first time the new version runs.

Nothing is forced on anybody.  The new endings are only claimed where the
old ones already open in this program, which is the person having said yes
to that once already.  A shortcut is only renamed when it really is one of
ours, pointing at DATUM.exe.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

from . import fileformat

# DATUM's ProgIDs, which the installer keeps using for every ending, old
# and new, so the two always open the same way
PROGIDS = {
    fileformat.PART: "IITEG.DATUM.Part",
    fileformat.ASSEMBLY: "IITEG.DATUM.Assembly",
    fileformat.DRAWING: "IITEG.DATUM.Drawing",
    fileformat.CAM: "IITEG.DATUM.Cam",
}
CLASSES = r"Software\Classes"


def _read_default(winreg, base: str, ending: str) -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            "%s\\%s" % (base, ending)) as key:
            value, _kind = winreg.QueryValueEx(key, "")
            return str(value or "")
    except OSError:
        return ""


def adopt_new_endings(base: str = CLASSES) -> List[str]:
    """Open .icpart and the rest the way .pdat and the rest already open.

    Returns the endings it registered, which is none on a second run.
    """
    if sys.platform != "win32":
        return []
    import winreg

    done = []
    for kind, progid in PROGIDS.items():
        legacy = fileformat.LEGACY_EXTENSIONS[kind]
        ending = fileformat.EXTENSIONS[kind]
        if _read_default(winreg, base, legacy) != progid:
            continue                    # never associated: theirs to decide
        if _read_default(winreg, base, ending):
            continue                    # already pointing somewhere
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              "%s\\%s" % (base, ending)) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, progid)
        done.append(ending)
    if done and base == CLASSES:
        try:
            import ctypes
            # SHCNE_ASSOCCHANGED, so Explorer shows the new icons at once
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        except Exception:                                   # noqa: BLE001
            pass
    return done


def _desktop() -> Optional[str]:
    try:
        import ctypes
        from ctypes import wintypes
        buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        # CSIDL_DESKTOPDIRECTORY: wherever the desktop really is, which on
        # a OneDrive machine is not under the profile
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0,
                                                  buffer) == 0:
            return buffer.value
    except Exception:                                       # noqa: BLE001
        pass
    profile = os.environ.get("USERPROFILE")
    return os.path.join(profile, "Desktop") if profile else None


def _shortcut_moves() -> List[Tuple[str, str]]:
    moves = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        programs = os.path.join(appdata, "Microsoft", "Windows",
                                "Start Menu", "Programs")
        moves.append((os.path.join(programs, "DATUM", "DATUM.lnk"),
                      os.path.join(programs, "InventCraft",
                                   "InventCraft.lnk")))
    desktop = _desktop()
    if desktop:
        moves.append((os.path.join(desktop, "DATUM.lnk"),
                      os.path.join(desktop, "InventCraft.lnk")))
    return moves


def is_our_shortcut(path: str) -> bool:
    """Whether a .lnk points at DATUM.exe.

    A shortcut file keeps its target as text, in the ANSI and the UTF-16
    halves of its link information, so looking for the name is enough to
    tell one of ours from some other DATUM somebody has.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read(64 * 1024)
    except OSError:
        return False
    if not data.startswith(b"\x4c\x00\x00\x00"):
        return False
    lowered = data.lower()
    return (b"datum.exe" in lowered
            or "datum.exe".encode("utf-16-le") in lowered)


def rename_shortcuts(moves: Optional[List[Tuple[str, str]]] = None
                     ) -> List[str]:
    """DATUM's shortcuts, renamed InventCraft.  They keep pointing at
    DATUM.exe, which is the same program, so nothing they open changes."""
    if moves is None:
        if sys.platform != "win32":
            return []
        moves = _shortcut_moves()
    done = []
    for old, new in moves:
        if not os.path.exists(old) or os.path.exists(new):
            continue
        if not is_our_shortcut(old):
            continue
        try:
            os.makedirs(os.path.dirname(new), exist_ok=True)
            os.replace(old, new)
        except OSError:
            continue
        folder = os.path.dirname(old)
        if os.path.basename(folder) == "DATUM":
            try:
                os.rmdir(folder)            # only when it is now empty
            except OSError:
                pass
        done.append(new)
    return done


def settle_rename() -> None:
    """Everything above, for an installed copy.  Never raises."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    for step in (adopt_new_endings, rename_shortcuts):
        try:
            step()
        except Exception:                                   # noqa: BLE001
            pass
