"""The documents a host has open, and what it knows about each.

A document is known to an agent by a short handle, ``d1``, ``d2``, rather
than by its path: a new part has no path until it is saved, and a path is
long, differs in case and slashes from one tool to the next, and changes
on Save As. Each document carries a revision that goes up on every change
the bridge makes, which is what lets a caller say "I last saw revision 41"
and be told when something else has moved it on since.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .errors import BridgeError


def same_path(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return (os.path.normcase(os.path.abspath(a))
            == os.path.normcase(os.path.abspath(b)))


@dataclass
class Entry:
    handle: str
    document: Any
    doc_type: str = "part"
    revision: int = 1
    # named copies of the document, taken by snapshot(); in memory only:
    # name -> {"state": the document as JSON, "revision": when taken}
    snapshots: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # the document as it was at each recent revision, for diff()
    history: Dict[int, str] = field(default_factory=dict)
    # the names a build gave sketch entities, by sketch feature id:
    # name -> ("point" | "entity", id); see sketchir
    sketch_names: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    # find_geometry's handles: code -> the ShapeRef fingerprint it names;
    # see refs.handle_for. Kept while the document is open.
    handles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # hashes of code features that came in with an opened file, and so
    # are not the agent's to trust by writing them again (see build)
    foreign_code: set = field(default_factory=set)
    # asked before an agent's code feature is trusted: (feature name,
    # source) -> allowed. None in a headless host, where the agent's own
    # code is trusted for the session (it could as well run_script); the
    # app sets one that shows the user the source.
    code_gate: Optional[Callable[[str, str], bool]] = None
    # the app's own revision of the document the last time the bridge
    # looked (ui/session.py's OpenDocument.revision): when it has moved,
    # the user has edited it, and this entry's revision moves with it
    source_mark: int = 0
    # for an assembly: the parts its occurrence references are resolved in,
    # by file, built once and kept until the file changes (assembly_ops)
    parts: Dict[str, Any] = field(default_factory=dict)
    # the workspace this entry is in (set by Workspace.add)
    workspace: Any = field(default=None, repr=False)

    HISTORY = 50

    @property
    def path(self) -> str:
        return getattr(self.document, "path", "") or ""

    def touch(self) -> int:
        self.revision += 1
        self.record()
        return self.revision

    def record(self) -> None:
        """Keep the document as it is now under its revision."""
        snap = getattr(self.document, "snapshot", None)
        if snap is None:
            return
        try:
            self.history[self.revision] = snap()
        except Exception:
            return
        for old in sorted(self.history)[:-self.HISTORY]:
            del self.history[old]


# every open document's entry, by the document, for code that is handed
# only a document (the core's requirement check, through refs)
import weakref  # noqa: E402

_ENTRIES: "weakref.WeakValueDictionary[int, Entry]" =     weakref.WeakValueDictionary()


def entry_of(document) -> Optional[Entry]:
    return _ENTRIES.get(id(document))


class Workspace:
    """Every document one host has open."""

    # what a handle starts with: the proxy routes by it ("d" is a headless
    # host's document, "g" one open in the app)
    PREFIX = "d"

    def __init__(self) -> None:
        self.entries: Dict[str, Entry] = {}
        self.active: str = ""
        self._next = 1

    def should_cancel(self) -> bool:
        """Asked between the steps of a long request. A host that can be
        told to stop (the app's Stop button) answers True; the request
        then fails as CANCELLED and rolls back like any failed build."""
        return False

    def progress(self, done: int, total: int, message: str = "") -> None:
        """Told by a long request how far it has got (evaluate, optimise).
        A host that can pass it on does; here it is dropped."""

    def add(self, document: Any, doc_type: str = "part") -> Entry:
        handle = "%s%d" % (self.PREFIX, self._next)
        self._next += 1
        entry = Entry(handle, document, doc_type)
        entry.workspace = self
        _ENTRIES[id(document)] = entry
        entry.record()
        self.entries[handle] = entry
        self.active = handle
        return entry

    def by_path(self, path: str) -> Optional[Entry]:
        for entry in self.entries.values():
            if same_path(entry.path, path):
                return entry
        return None

    def get(self, handle: Optional[str] = None) -> Entry:
        """The document asked for, or the only one, or the active one."""
        if handle:
            entry = self.entries.get(handle)
            if entry is None:
                entry = self.by_path(handle)
            if entry is None:
                raise BridgeError(
                    "NO_DOCUMENT", "no open document %r" % handle,
                    ["Open documents: %s" % (", ".join(self.entries)
                                             or "none")])
            return entry
        if not self.entries:
            raise BridgeError("NO_DOCUMENT", "no document is open",
                              ["Use new_document or open_document first."])
        if self.active in self.entries:
            return self.entries[self.active]
        return next(iter(self.entries.values()))

    def close(self, handle: str) -> None:
        self.entries.pop(handle, None)
        if self.active == handle:
            self.active = next(iter(self.entries), "")

    def listing(self) -> List[Dict[str, Any]]:
        return [{"doc": e.handle, "type": e.doc_type, "path": e.path,
                 "title": getattr(e.document, "title", ""),
                 "units": getattr(e.document, "units", "mm"),
                 "revision": e.revision, "active": e.handle == self.active}
                for e in self.entries.values()]
