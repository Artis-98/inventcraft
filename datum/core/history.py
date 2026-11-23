"""Versions and branches of a file: Vault's check in, Onshape's branches.

Every part, assembly or drawing can keep its history.  Check In takes the
file as it is saved and keeps a copy of it, with who, when and why.  The
copies hang on branches: "main" to start with, and any others made from a
version to try something without losing what was there.  Switching
branch, or restoring a version, puts that copy back in the file's place;
the file on disk is always the one being worked on, so everything that
opens or places it carries on as before.

It all lives beside the files, in a ".icversions" folder in the same
folder, one subfolder per file: the copies, and an index.json saying
which version is which and which branch it is on.  Nothing leaves the
machine, and a project folder copied or zipped carries its history.

Merging a branch into another takes the branch's latest as the other's
next version, which is how a CAD file merges: there is no splicing two
different solids together line by line, so the version chosen wins and
the one it replaced is still in the history.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

FOLDER = ".icversions"
MAIN = "main"


class HistoryError(Exception):
    pass


@dataclass
class Version:
    id: int
    branch: str
    message: str = ""
    author: str = ""
    time: float = 0.0
    parent: int = 0
    digest: str = ""
    file: str = ""
    # the head of the branch this version merged in, if it is a merge
    merged_from: int = 0

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.time))


@dataclass
class History:
    path: str
    versions: Dict[int, Version] = field(default_factory=dict)
    branches: Dict[str, int] = field(default_factory=dict)   # name -> head
    current: str = MAIN

    @property
    def store(self) -> str:
        return store_of(self.path)

    def head(self, branch: Optional[str] = None) -> Optional[Version]:
        vid = self.branches.get(branch or self.current, 0)
        return self.versions.get(vid)

    def line(self, branch: Optional[str] = None) -> List[Version]:
        """A branch's versions, newest first, back to where it began."""
        out = []
        version = self.head(branch)
        seen = set()
        while version is not None and version.id not in seen:
            seen.add(version.id)
            out.append(version)
            version = self.versions.get(version.parent)
        return out

    def all(self) -> List[Version]:
        return sorted(self.versions.values(), key=lambda v: -v.id)

    def save(self) -> None:
        os.makedirs(self.store, exist_ok=True)
        data = {"current": self.current, "branches": dict(self.branches),
                "versions": [asdict(v) for v in self.all()]}
        temp = os.path.join(self.store, "index.json.tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(temp, os.path.join(self.store, "index.json"))


def store_of(path: str) -> str:
    folder, name = os.path.split(os.path.abspath(path))
    return os.path.join(folder, FOLDER, name)


def digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: str) -> History:
    """A file's history; empty, on main, when it has none yet."""
    history = History(path=os.path.abspath(path))
    index = os.path.join(history.store, "index.json")
    if not os.path.exists(index):
        return history
    with open(index, encoding="utf-8") as f:
        data = json.load(f)
    history.current = str(data.get("current", MAIN))
    history.branches = {str(k): int(v)
                        for k, v in (data.get("branches") or {}).items()}
    for raw in data.get("versions") or []:
        version = Version(**{k: raw[k] for k in Version.__dataclass_fields__
                             if k in raw})
        history.versions[version.id] = version
    return history


def changed(path: str, history: Optional[History] = None) -> bool:
    """Whether the file differs from the version it was last set to."""
    history = history or load(path)
    head = history.head()
    if head is None:
        return os.path.exists(path)
    return not os.path.exists(path) or digest(path) != head.digest


def check_in(path: str, message: str = "", author: str = "",
             merged_from: int = 0) -> Version:
    """Keep the file as it is now as the next version on its branch.
    ``merged_from`` is the version of another branch it merges in."""
    if not os.path.exists(path):
        raise HistoryError("save it first: there is no file to check in")
    history = load(path)
    head = history.head()
    stamp = digest(path)
    if head is not None and head.digest == stamp:
        raise HistoryError("nothing has changed since version %d" % head.id)
    vid = max(history.versions, default=0) + 1
    ext = os.path.splitext(path)[1]
    os.makedirs(history.store, exist_ok=True)
    name = "%04d%s" % (vid, ext)
    shutil.copy2(path, os.path.join(history.store, name))
    version = Version(id=vid, branch=history.current, message=message,
                      author=author or _who(), time=time.time(),
                      parent=head.id if head else 0, digest=stamp, file=name,
                      merged_from=merged_from)
    history.versions[vid] = version
    history.branches[history.current] = vid
    history.save()
    return version


def _who() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return ""


def _put_back(history: History, version: Version) -> None:
    source = os.path.join(history.store, version.file)
    if not os.path.exists(source):
        raise HistoryError("version %d's copy is missing" % version.id)
    temp = history.path + ".restoring"
    shutil.copy2(source, temp)
    os.replace(temp, history.path)


def _clean(path: str, history: History, force: bool) -> None:
    if not force and history.head() is not None and changed(path, history):
        raise HistoryError("it has changes that are not checked in: check "
                           "them in first, or they will be lost")


def new_branch(path: str, name: str, from_version: int = 0) -> History:
    """A branch starting at a version (the current one by default), and
    the file switched to it."""
    name = name.strip()
    if not name:
        raise HistoryError("a branch needs a name")
    history = load(path)
    if name in history.branches:
        raise HistoryError("there is a branch called %s already" % name)
    start = history.versions.get(from_version) if from_version \
        else history.head()
    if start is None:
        raise HistoryError("check it in once before branching")
    if from_version and from_version != getattr(history.head(), "id", 0):
        _clean(path, history, False)
        _put_back(history, start)
    history.branches[name] = start.id
    history.current = name
    history.save()
    return history


def switch(path: str, name: str, force: bool = False) -> History:
    """Put a branch's latest in the file's place, and work on it."""
    history = load(path)
    if name not in history.branches:
        raise HistoryError("there is no branch called %s" % name)
    if name == history.current:
        return history
    _clean(path, history, force)
    _put_back(history, history.head(name))
    history.current = name
    history.save()
    return history


def restore(path: str, version_id: int, force: bool = False) -> Version:
    """Put an old version back in the file's place.  It is checked in
    again as the newest on the current branch, so nothing is lost and the
    restore itself is in the history."""
    history = load(path)
    version = history.versions.get(version_id)
    if version is None:
        raise HistoryError("there is no version %d" % version_id)
    _clean(path, history, force)
    _put_back(history, version)
    try:
        return check_in(path, "Restored version %d" % version_id)
    except HistoryError:
        return version          # it was the latest already


def merge(path: str, branch: str, into: str = MAIN,
          message: str = "") -> Version:
    """Take a branch's latest as the next version of another branch, and
    work on that one."""
    history = load(path)
    if branch not in history.branches or into not in history.branches:
        raise HistoryError("there is no such branch")
    if branch == into:
        raise HistoryError("a branch cannot merge into itself")
    _clean(path, history, False)
    source = history.head(branch)
    _put_back(history, source)
    history.current = into
    history.save()
    return check_in(path, message or "Merged %s (version %d)"
                    % (branch, source.id))


def delete_branch(path: str, name: str) -> History:
    """Drop a branch that is not the one being worked on.  Its versions
    stay in the store (a version is never thrown away); only the name
    goes, so the work is no longer offered, and can be found again by
    its version number."""
    history = load(path)
    if name not in history.branches:
        raise HistoryError("there is no branch called %s" % name)
    if name == history.current:
        raise HistoryError("%s is the branch being worked on: switch to "
                           "another first" % name)
    if name == MAIN:
        raise HistoryError("main cannot be deleted")
    del history.branches[name]
    history.save()
    return history


def ancestors(history: History, version_id: int) -> List[int]:
    """A version and every one before it, newest first, the versions a
    merge brought in included."""
    out, seen = [], set()
    queue = [version_id]
    while queue:
        version = history.versions.get(queue.pop(0))
        if version is None or version.id in seen:
            continue
        seen.add(version.id)
        out.append(version.id)
        queue.append(version.parent)
        if version.merged_from:
            queue.append(version.merged_from)
    return sorted(out, reverse=True)


def common_ancestor(history: History, a: str, b: str) -> Optional[Version]:
    """The newest version two branches share: where they parted."""
    head_a, head_b = history.branches.get(a), history.branches.get(b)
    if not head_a or not head_b:
        return None
    mine = set(ancestors(history, head_a))
    for vid in ancestors(history, head_b):
        if vid in mine:
            return history.versions.get(vid)
    return None
