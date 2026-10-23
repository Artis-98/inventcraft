"""Old versions: the file a save replaces, kept beside it, as Inventor does.

Every save first copies the file it is about to replace into a folder
called OldVersions next to it, numbered: ``Bracket.0001.icpart``,
``Bracket.0002.icpart`` and so on, the highest the most recent.  A file
that goes bad, or an afternoon's edits that turn out to be a mistake, can
then be undone by opening an older copy.  Preferences says how many are
kept, Inventor's way: 0 keeps none, a negative number keeps every one.

Copied, never moved.  The new file is written beside the target and swapped
in only once it is complete (see fileformat.write), and the old one must
still be in its place if that write fails; copying it away first keeps both
promises.  A copy that cannot be made never stops the save: the version is
a convenience, the save is the work.
"""

from __future__ import annotations

import os
import re
import shutil
from typing import List, Optional, Tuple

FOLDER = "OldVersions"
DEFAULT_KEEP = 1            # Inventor's own default


def folder_for(path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(path)), FOLDER)


def versions(path: str) -> List[Tuple[int, str]]:
    """Every kept version of a file, oldest first, as (number, path)."""
    where = folder_for(path)
    stem, ext = os.path.splitext(os.path.basename(path))
    pattern = re.compile(r"^%s\.(\d{4,})%s$" % (re.escape(stem),
                                                re.escape(ext)),
                         re.IGNORECASE)
    found = []
    try:
        names = os.listdir(where)
    except OSError:
        return found
    for name in names:
        match = pattern.match(name)
        if match:
            found.append((int(match.group(1)), os.path.join(where, name)))
    return sorted(found)


def stash(path: str, keep: int = DEFAULT_KEEP) -> Optional[str]:
    """Keep the file at ``path`` as its next old version, before a save
    replaces it.  Returns the copy's path, or None when nothing was kept."""
    if keep == 0 or not os.path.isfile(path):
        return None
    try:
        where = folder_for(path)
        os.makedirs(where, exist_ok=True)
        existing = versions(path)
        number = (existing[-1][0] + 1) if existing else 1
        stem, ext = os.path.splitext(os.path.basename(path))
        target = os.path.join(where, "%s.%04d%s" % (stem, number, ext))
        shutil.copy2(path, target)
        if keep > 0:
            for _number, old in versions(path)[:-keep]:
                try:
                    os.remove(old)
                except OSError:
                    pass
        return target
    except OSError:
        return None


def keep_setting() -> int:
    """How many the person wants kept, from Preferences."""
    try:
        from . import prefs
        return int(prefs.prefs().old_versions)
    except Exception:                                   # noqa: BLE001
        return DEFAULT_KEEP
