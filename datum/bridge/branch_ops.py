"""Branches through the bridge: work on a copy of a design, then merge it
or throw it away.

Storage (decision): the core's own versions (``core/history.py``), the same
store the app's Versions panel reads. Every file keeps its history in a
``.icversions`` folder beside it: a copy of the file at each check-in, with
who, when and why, hanging on branches ("main" to start with). So there is
nothing new to learn or keep in step: a branch an agent makes shows in the
app's Versions panel, and a version the user checked in is a branch point
for an agent. The price is that a branch is a file on disk, so the document
must be saved; a new, unsaved document cannot branch.

* ``create`` makes a branch at the current version and switches to it;
* ``switch`` puts another branch's latest in the document's place (one
  undo step in the app), and is refused while the document holds changes
  that are not checked in, since they would be lost;
* ``check_in`` saves the document and keeps it as the next version of the
  current branch;
* ``merge`` takes another branch into the current one. If the current
  branch has not moved since the other parted from it, that is a plain
  fast-forward. If both moved, parts are merged feature by feature (a
  three-way merge against the version they parted at: what only one side
  changed is taken; what both changed the same way is taken once; what
  both changed differently is a conflict), and a conflict refuses the
  whole merge and names every one of them, never choosing for you;
* ``discard`` drops a branch's name (its versions stay in the store).

``diff`` accepts ``branch:<name>`` and ``version:<id>`` as either end, so
a branch is reviewed against main before it is merged.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from ..core import history
from . import ops
from .errors import BridgeError
from .workspace import Entry, Workspace

op = ops.op

ACTIONS = ("list", "create", "switch", "check_in", "merge", "discard")
# the parts of a part's snapshot that are bookkeeping, not design
IGNORED = ("next_id", "view")


# ---------------------------------------------------------------- helpers


def _path(entry: Entry) -> str:
    path = entry.path
    if not path or not os.path.exists(path):
        raise BridgeError(
            "BAD_PATH", "%s has no file yet: a branch is a branch of a "
            "saved file" % entry.handle,
            ["save_document(doc=%r, path=<absolute path>) first."
             % entry.handle])
    return path


# bookkeeping a design is not: what the window hides and where it looks
BOOKKEEPING = IGNORED + ("hidden_planes", "hidden_bodies",
                         "hidden_sketches", "shown_sketches",
                         "origin_autohidden", "appearance")


def _same_design(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    keys = (set(a) | set(b)) - set(BOOKKEEPING)
    return all(a.get(k) == b.get(k) for k in keys)


def _unsaved(entry: Entry) -> bool:
    """Whether the open document holds changes its file does not: the
    tab's modified mark (the app sets it when the user edits), or a
    design that differs from the saved file. Ops do not set the mark in a
    headless host, and an agent's edit in the app does not always, so the
    design itself is compared."""
    if getattr(entry.document, "modified", False):
        return True
    path = entry.path
    if not path or not os.path.exists(path):
        return True
    try:
        return not _same_design(json.loads(entry.document.snapshot()),
                                _load_snapshot(path))
    except Exception:                                   # noqa: BLE001
        return True


def _dirty(entry: Entry, hist: history.History) -> Optional[str]:
    """Why the document holds work that is not checked in, or None."""
    if _unsaved(entry):
        return "it has unsaved changes"
    if hist.head() is not None and history.changed(entry.path, hist):
        return "the saved file differs from its last version"
    return None


def _need_clean(entry: Entry, hist: history.History, what: str) -> None:
    why = _dirty(entry, hist)
    if why:
        raise BridgeError(
            "UNSAVED_CHANGES", "%s %s, and %s would replace them" % (
                entry.handle, why, what),
            ["branch(action=\"check_in\", message=...) keeps them as a "
             "version first.",
             "Or take them back: undo, or snapshot restore."])


def _branch(hist: history.History, name: str) -> str:
    if not name:
        raise BridgeError("BAD_VALUE", "give the branch's name")
    if name not in hist.branches:
        raise BridgeError(
            "NO_BRANCH", "no branch called %r" % name,
            ["Branches: %s" % (", ".join(hist.branches) or "none yet"),
             "branch(action=\"create\", name=...) makes one."])
    return name


def _version_info(v: history.Version) -> Dict[str, Any]:
    return {"id": v.id, "branch": v.branch, "message": v.message,
            "author": v.author, "when": v.when}


def _version_file(hist: history.History, version_id: int) -> str:
    v = hist.versions.get(version_id)
    if v is None:
        raise BridgeError("NOT_FOUND", "there is no version %d" % version_id,
                          ["Versions: %s" % ", ".join(
                              str(x.id) for x in hist.all()[:20])])
    return os.path.join(hist.store, v.file)


def _load_snapshot(path: str) -> Dict[str, Any]:
    return json.loads(ops.open_file(path).snapshot())


def state_of(entry: Entry, which: str) -> Tuple[str, Dict[str, Any]]:
    """``branch:<name>`` or ``version:<id>`` as a state ``diff`` compares."""
    path = _path(entry)
    hist = history.load(path)
    kind, _, value = str(which).partition(":")
    if kind == "branch":
        _branch(hist, value)
        head = hist.head(value)
        if value == hist.current and _dirty(entry, hist) is not None:
            return ("branch %s (as open, not checked in)" % value,
                    json.loads(entry.document.snapshot()))
        return ("branch %s (version %d)" % (value, head.id),
                _load_snapshot(os.path.join(hist.store, head.file)))
    try:
        vid = int(value)
    except ValueError:
        raise BridgeError("BAD_VALUE", "version:<number>")
    return ("version %d" % vid,
            _load_snapshot(_version_file(hist, vid)))


def _reload(entry: Entry, path: str, source: Optional[str] = None) -> None:
    """Put a file's content into the open document, in place, as one undo
    step (the tab and its handle stay). ``source`` is another file to take
    the content from (the file at ``path`` by default)."""
    d = entry.document
    fresh = ops.open_file(source or path)
    data = json.loads(fresh.snapshot())
    if entry.doc_type == "part":
        d.push_undo()
        d.load_dict(data)
        d.rebuild()
    elif entry.doc_type == "assembly":
        before = d.snapshot()
        d.load_dict(data)
        d.rebuild()
        d._undo.append(before)
        del d._undo[:-60]
        d._redo.clear()
    else:
        before = d.snapshot()
        d._restore(json.dumps(data))
        if hasattr(fresh, "cache_dict"):
            d.load_cache(fresh.cache_dict())
        d._undo.append(before)
        del d._undo[:-60]
        d._redo.clear()
    d.modified = False


def _summary(entry: Entry, hist: history.History) -> Dict[str, Any]:
    head = hist.head()
    return {"doc": entry.handle, "revision": entry.revision,
            "branch": hist.current,
            "head": _version_info(head) if head else None}


# ---------------------------------------------------------------- merge


def _short(v: Any) -> Any:
    text = json.dumps(v, default=str)
    return v if len(text) <= 100 else text[:97] + "..."


_MISSING = object()


def _item_key(*lists: Any) -> Optional[str]:
    """Which key names the items of lists of dicts ("id", else "name"),
    when every item of every list has it."""
    items = [x for lst in lists if isinstance(lst, list) for x in lst]
    if not items or not all(isinstance(x, dict) for x in items):
        return None
    for key in ("id", "name"):
        if all(key in x for x in items):
            return key
    return None


def _node(b: Any, o: Any, t: Any, path: tuple, out: List[Tuple[tuple, Any,
          Any, Any, str]]) -> Any:
    """Three versions of one thing, merged: what only one side changed is
    taken, what both changed alike is taken once, dicts are merged key by
    key and lists of records item by item (by id or name); what both
    changed differently is recorded in ``out`` (path, base, ours, theirs,
    why) and ours is kept. ``_MISSING`` is "not there"."""
    if o == t:
        return o
    if o == b:
        return t
    if t == b:
        return o
    if isinstance(o, dict) and isinstance(t, dict)             and isinstance(b, (dict, type(_MISSING))):
        base = b if isinstance(b, dict) else {}
        res: Dict[str, Any] = {}
        for k in list(o) + [k for k in t if k not in o]:
            v = _node(base.get(k, _MISSING), o.get(k, _MISSING),
                      t.get(k, _MISSING), path + (k,), out)
            if v is not _MISSING:
                res[k] = v
        for k in base:
            if k not in o and k not in t:
                continue
        if b is _MISSING:
            out.append((path, _MISSING, o, t, "both branches added a "
                        "different one with the same id"))
        return res
    if isinstance(o, list) and isinstance(t, list)             and isinstance(b, (list, type(_MISSING))):
        base = b if isinstance(b, list) else []
        key = _item_key(base, o, t)
        if key is not None:
            return _merge_records(base, o, t, key, path, out)
    why = ""
    if o is _MISSING or t is _MISSING:
        why = "one branch deleted it, the other changed it"
    out.append((path, b, o, t, why))
    return o


def _merge_records(base: list, ours: list, theirs: list, key: str,
                   path: tuple, out) -> list:
    bi = {x[key]: x for x in base}
    oi = {x[key]: x for x in ours}
    ti = {x[key]: x for x in theirs}
    merged: Dict[Any, Any] = {}
    for ident in dict.fromkeys(list(bi) + list(oi) + list(ti)):
        v = _node(bi.get(ident, _MISSING), oi.get(ident, _MISSING),
                  ti.get(ident, _MISSING), path + ((key, ident),), out)
        merged[ident] = v
    order, bad = _order([x[key] for x in base], [x[key] for x in ours],
                        [x[key] for x in theirs],
                        lambda i: merged.get(i, _MISSING) is not _MISSING)
    if bad:
        out.append((path + ("order",), _MISSING, _MISSING, _MISSING, bad))
    return [merged[i] for i in order]


def _order(base: List[Any], ours: List[Any], theirs: List[Any], keep
           ) -> Tuple[List[Any], Optional[str]]:
    """The merged order of ids. A side that did not reorder the ids both
    have in common follows the one that did; both reordering them
    differently is a conflict. What only the other side added goes in
    after the item that came before it there."""
    def common(seq, other):
        return [i for i in seq if i in other]
    ours_moved = common(ours, base) != common(base, ours)
    theirs_moved = common(theirs, base) != common(base, theirs)
    if ours_moved and theirs_moved and common(ours, theirs) != common(
            theirs, ours):
        return [i for i in ours if keep(i)],             "both branches reordered them differently"
    primary, secondary = (theirs, ours) if theirs_moved and not ours_moved         else (ours, theirs)
    out = [i for i in primary if keep(i)]
    for n, i in enumerate(secondary):
        if i in out or not keep(i):
            continue
        before = [j for j in secondary[:n] if j in out]
        at = out.index(before[-1]) + 1 if before else 0
        out.insert(at, i)
    return out, None


def _label(name_of: Dict[Any, str], path: tuple) -> Tuple[str, str, str]:
    """(kind, name, field path) of a conflict path."""
    top = path[0] if path else ""
    if top == "features" and len(path) > 1 and isinstance(path[1], tuple):
        ident = path[1][1]
        return "feature", name_of.get(("f", ident), str(ident)), ".".join(
            _step(p) for p in path[2:])
    if top == "parameters" and len(path) > 1 and isinstance(path[1], tuple):
        return "parameter", str(path[1][1]), ".".join(
            _step(p) for p in path[2:])
    return "document", str(top), ".".join(_step(p) for p in path[1:])


def _step(p: Any) -> str:
    return "%s=%s" % p if isinstance(p, tuple) else str(p)


def three_way(base: Dict[str, Any], ours: Dict[str, Any],
              theirs: Dict[str, Any]
              ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Merge three snapshots of a part: (the merged snapshot, conflicts)."""
    raw: List[Tuple[tuple, Any, Any, Any, str]] = []
    merged: Dict[str, Any] = {}
    for k in dict.fromkeys(list(ours) + list(theirs)):
        if k in IGNORED:
            continue
        v = _node(base.get(k, _MISSING), ours.get(k, _MISSING),
                  theirs.get(k, _MISSING), (k,), raw)
        if v is not _MISSING:
            merged[k] = v
    merged["next_id"] = max(ours.get("next_id", 0), theirs.get("next_id", 0))
    if "view" in ours:
        merged["view"] = ours["view"]
    names: Dict[Any, str] = {}
    for snap in (base, theirs, ours):
        for f in snap.get("features", []):
            names[("f", f["id"])] = f.get("name", str(f["id"]))
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for path, b, o, t, why in raw:
        kind, name, where = _label(names, path)
        item = grouped.setdefault((kind, name),
                                  {"kind": kind, "name": name})
        if why:
            item["why"] = why
        if where or not why:
            item.setdefault("fields", {})[where or "value"] = {
                "base": "-" if b is _MISSING else _short(b),
                "ours": "-" if o is _MISSING else _short(o),
                "theirs": "-" if t is _MISSING else _short(t)}
    return merged, list(grouped.values())


def _plan_merge(entry: Entry, hist: history.History, name: str
                ) -> Dict[str, Any]:
    """What merging ``name`` into the current branch would do: a
    fast-forward, nothing, or a merged snapshot (and conflicts)."""
    current = hist.current
    ours_head, theirs_head = hist.head(current), hist.head(name)
    if theirs_head is None or ours_head is None:
        raise BridgeError("NO_BRANCH", "%s has no versions to merge"
                          % (name if theirs_head is None else current))
    if theirs_head.id in history.ancestors(hist, ours_head.id):
        return {"kind": "nothing", "theirs": theirs_head,
                "ours": ours_head}
    base = history.common_ancestor(hist, current, name)
    if base is not None and base.id == ours_head.id:
        return {"kind": "fast_forward", "theirs": theirs_head,
                "ours": ours_head, "base": base}
    if entry.doc_type != "part":
        return {"kind": "conflicts", "theirs": theirs_head,
                "ours": ours_head, "base": base,
                "conflicts": [{
                    "kind": "document", "name": entry.doc_type,
                    "why": "both branches changed it, and only parts are "
                           "merged feature by feature"}]}
    snap_o = _load_snapshot(os.path.join(hist.store, ours_head.file))
    snap_t = _load_snapshot(os.path.join(hist.store, theirs_head.file))
    snap_b = (_load_snapshot(os.path.join(hist.store, base.file))
              if base is not None else
              {"features": [], "parameters": []})
    merged, conflicts = three_way(snap_b, snap_o, snap_t)
    return {"kind": "conflicts" if conflicts else "merged",
            "theirs": theirs_head, "ours": ours_head, "base": base,
            "merged": merged, "conflicts": conflicts}


def _conflict_error(name: str, current: str, conflicts) -> BridgeError:
    lines = []
    for c in conflicts[:8]:
        what = "%s %s" % (c["kind"], c["name"])
        if c.get("fields"):
            what += " (%s)" % ", ".join(
                f or "value" for f in c["fields"])
        if c.get("why"):
            what += ": %s" % c["why"]
        lines.append(what)
    return BridgeError(
        "MERGE_CONFLICT", "merging %s into %s found %d conflict%s, so "
        "nothing was merged: %s" % (
            name, current, len(conflicts),
            "" if len(conflicts) == 1 else "s", "; ".join(lines)),
        ["Nothing was changed. Make the two branches agree on those "
         "(edit_feature on one of them), then merge again; or merge "
         "the other way round after switching.",
         "diff(before=\"branch:%s\", after=\"branch:%s\") shows each "
         "side." % (current, name)],
        conflicts=conflicts, branch=name, into=current)


# ---------------------------------------------------------------- the tool


@op
def branch(ws: Workspace, doc: str = "", action: str = "list",
           name: str = "", message: str = "", dry_run: bool = False,
           expected_revision: Optional[int] = None, app_open: Any = None
           ) -> Dict[str, Any]:
    """list, create, switch, check_in, merge or discard branches of a
    saved document; see this module's docstring."""
    entry = ws.get(doc)
    if entry.doc_type not in ("part", "assembly", "drawing"):
        raise BridgeError("WRONG_TYPE", "branches are for parts, "
                          "assemblies and drawings")
    if action not in ACTIONS:
        raise BridgeError("BAD_VALUE", "action is one of %s"
                          % ", ".join(ACTIONS))
    name = (name or "").strip()
    if action == "list":
        path = entry.path
        hist = history.load(path) if path else history.History(path="")
        out = {"doc": entry.handle, "revision": entry.revision,
               "current": hist.current,
               "saved": bool(path and os.path.exists(path)),
               "branches": [], "versions": []}
        for bname, vid in hist.branches.items():
            v = hist.versions.get(vid)
            out["branches"].append({
                "name": bname, "current": bname == hist.current,
                "head": vid, "message": v.message if v else "",
                "versions": len(hist.line(bname))})
        out["versions"] = [_version_info(v) for v in hist.line()[:20]]
        if path and os.path.exists(path):
            why = _dirty(entry, hist) if hist.head() else None
            out["unsaved"] = _unsaved(entry)
            if hist.head() is None:
                out["note"] = ("never checked in: branch(action=\"create\") "
                               "or \"check_in\" makes the first version")
            elif why:
                out["not_checked_in"] = why
        out["summary"] = "on %s | %d branch%s | %d version%s here" % (
            hist.current, len(hist.branches),
            "" if len(hist.branches) == 1 else "es", len(out["versions"]),
            "" if len(out["versions"]) == 1 else "s")
        return out

    path = _path(entry)
    ops._refuse_app_file(path, app_open, "branching it")
    ops._check_revision(entry, expected_revision)
    hist = history.load(path)
    try:
        return _act(ws, entry, path, hist, action, name, message, dry_run)
    except history.HistoryError as exc:
        raise BridgeError("BAD_VALUE", str(exc))


def _act(ws: Workspace, entry: Entry, path: str, hist: history.History,
         action: str, name: str, message: str, dry_run: bool
         ) -> Dict[str, Any]:
    if action == "check_in":
        entry.document.save(path)
        try:
            v = history.check_in(path, message or "Checked in %s"
                                 % hist.current)
        except history.HistoryError as exc:
            out = _summary(entry, history.load(path))
            out["checked_in"] = False
            out["note"] = str(exc)
            out["summary"] = "nothing to check in | %s" % str(exc)
            return out
        out = _summary(entry, history.load(path))
        out["checked_in"] = True
        out["version"] = _version_info(v)
        out["summary"] = "checked in version %d on %s" % (v.id, v.branch)
        return out

    if action == "create":
        if not name:
            raise BridgeError("BAD_VALUE", "give the new branch's name")
        if name in hist.branches:
            raise BridgeError("BAD_VALUE", "there is a branch called %s "
                              "already" % name, ["branch(action=\"switch\")"])
        if _unsaved(entry):
            raise BridgeError(
                "UNSAVED_CHANGES", "%s has unsaved changes" % entry.handle,
                ["branch(action=\"check_in\") saves them as a version of "
                 "%s first, so the branch starts from them."
                 % hist.current])
        if hist.head() is None or history.changed(path, hist):
            history.check_in(path, "Before branch %s" % name)
        history.new_branch(path, name)
        out = _summary(entry, history.load(path))
        out["created"] = name
        out["summary"] = "created branch %s at version %d and switched to " \
            "it" % (name, out["head"]["id"])
        return out

    if action == "switch":
        _branch(hist, name)
        if name == hist.current:
            out = _summary(entry, hist)
            out["summary"] = "already on %s" % name
            return out
        _need_clean(entry, hist, "switching")
        before_rev = entry.revision
        history.switch(path, name)
        _reload(entry, path)
        entry.touch()
        out = _summary(entry, history.load(path))
        out["switched_to"] = name
        out["summary"] = "switched to %s (version %d) | rev %d" % (
            name, out["head"]["id"], entry.revision)
        if entry.doc_type == "part":
            try:
                out["changes"] = ops._compare(
                    entry, before_rev, "current")["summary"]
            except Exception:                           # noqa: BLE001
                pass
        return out

    if action == "discard":
        _branch(hist, name)
        history.delete_branch(path, name)
        out = _summary(entry, history.load(path))
        out["discarded"] = name
        out["summary"] = "discarded branch %s (its versions stay in the " \
            "store)" % name
        return out

    # merge
    _branch(hist, name)
    if name == hist.current:
        raise BridgeError("BAD_VALUE", "%s is the branch being worked on; "
                          "merge another into it" % name)
    _need_clean(entry, hist, "merging")
    plan = _plan_merge(entry, hist, name)
    current = hist.current
    if plan["kind"] == "nothing":
        out = _summary(entry, hist)
        out["merged"] = False
        out["summary"] = "%s is up to date with %s: nothing to merge" % (
            current, name)
        return out
    if plan["kind"] == "conflicts":
        raise _conflict_error(name, current, plan["conflicts"])
    if dry_run:
        out = _summary(entry, hist)
        out.update({"dry_run": True, "merged": False,
                    "would": plan["kind"].replace("_", " "),
                    "summary": "merging %s into %s would %s, no "
                    "conflicts" % (name, current,
                                   plan["kind"].replace("_", " "))})
        return out
    before_rev = entry.revision
    d = entry.document
    if plan["kind"] == "fast_forward":
        source = os.path.join(hist.store, plan["theirs"].file)
        _reload(entry, path, source)
    else:
        # build the merged part on a scratch document first: a merge that
        # does not build is refused with the file untouched
        from ..core.document import Document
        scratch = Document()
        scratch.load_dict(plan["merged"])
        scratch.rebuild()
        bad = [(fid, msg) for fid, msg in scratch.last_report.errors]
        if bad:
            raise BridgeError(
                "MERGE_CONFLICT", "the merged part does not build: %s" %
                "; ".join("%s: %s" % (fid, msg) for fid, msg in bad[:4]),
                ["Nothing was changed. The two branches' changes do not "
                 "work together; make them agree and merge again."],
                conflicts=[{"kind": "build", "name": "merged part",
                            "why": str(bad[0][1])}], branch=name,
                into=current)
        d.push_undo()
        d.load_dict(plan["merged"])
        d.rebuild()
    d.save(path)
    try:
        version = history.check_in(
            path, message or "Merged %s (version %d)" % (
                name, plan["theirs"].id), merged_from=plan["theirs"].id)
    except history.HistoryError:
        # the two designs are the same: nothing to record but the merge
        raise BridgeError(
            "BAD_VALUE", "%s and %s hold the same design; there is "
            "nothing to merge" % (current, name))
    entry.touch()
    out = _summary(entry, history.load(path))
    out["merged"] = True
    out["how"] = plan["kind"].replace("_", " ")
    out["version"] = _version_info(version)
    out["summary"] = "merged %s into %s (%s) as version %d | rev %d" % (
        name, current, out["how"], version.id, entry.revision)
    if entry.doc_type == "part":
        try:
            out["changes"] = ops._compare(entry, before_rev,
                                          "current")["summary"]
            out["rebuild"] = ops._report(d)
        except Exception:                               # noqa: BLE001
            pass
    return out
