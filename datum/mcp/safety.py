"""What the server refuses, caps or asks about, before a call reaches a host
(plan section 10).

* File access: a path an agent names must lie inside the client's MCP roots
  when it gives some, otherwise inside the project folder (the server's
  working directory). Folders the user adds with ``--allow-dir`` (or the
  ``INVENTCRAFT_ALLOW_DIRS`` variable, ``os.pathsep`` separated) count in
  both cases, since the user chose them.
* Irreversible writes: overwriting a file that keeps no old version of
  itself needs the user's yes: an elicitation when the client has them,
  else ``confirm=true`` after the agent has asked.
* Output size: lists are paged (``offset``/``limit``) and every answer is
  held to a byte budget, with a note that says how to get the rest.

Everything here is pure policy: no host is called, so it is tested without
one (tests/test_mcp_server.py, ``safety`` section).
"""

from __future__ import annotations

import json
import os
import warnings
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

# folders the user allowed on the command line / in the environment
ALLOW_DIRS: List[str] = []
# the project folder: where the server was started (Claude Code starts it
# in the project)
PROJECT_DIR = os.getcwd()

DOC_EXTENSIONS = (".icpart", ".icasm", ".icdraw", ".pdat", ".adat")

MAX_BYTES = int(os.environ.get("INVENTCRAFT_MCP_MAX_BYTES", "40000") or 40000)
# images: the longest side a render may ask for, and the biggest PNG (in
# base64 characters) that is sent back
MAX_IMAGE_SIDE = 2000
MAX_IMAGE_B64 = 2_000_000


def norm(path: str) -> str:
    """A path as it is compared: absolute, symlinks and ``..`` resolved,
    case folded where the file system does."""
    return os.path.normcase(os.path.realpath(os.path.abspath(
        os.path.expanduser(str(path)))))


def inside(path: str, folder: str) -> bool:
    p, f = norm(path), norm(folder)
    if p == f:
        return True
    try:
        return os.path.commonpath([p, f]) == f
    except ValueError:                 # another drive
        return False


def add_allow_dirs(dirs: Iterable[str]) -> None:
    for d in dirs:
        if d and norm(d) not in [norm(x) for x in ALLOW_DIRS]:
            ALLOW_DIRS.append(os.path.abspath(os.path.expanduser(d)))


def env_allow_dirs() -> List[str]:
    return [d for d in os.environ.get("INVENTCRAFT_ALLOW_DIRS", "").split(
        os.pathsep) if d.strip()]


def root_paths(uris: Iterable[Any]) -> List[str]:
    """Local folders of MCP roots (file:// URIs). Roots of another scheme
    cannot hold a file and are ignored."""
    out = []
    for uri in uris:
        parsed = urlparse(str(uri))
        if parsed.scheme != "file":
            continue
        path = url2pathname(unquote(parsed.path))
        if parsed.netloc and parsed.netloc != "localhost":
            path = "//%s%s" % (parsed.netloc, path)
        out.append(path)
    return out


async def client_roots(ctx: Any) -> Optional[List[str]]:
    """The client's roots as folders; None when it gives none (it does not
    have the capability, or the connection cannot be asked)."""
    try:
        from mcp.types import ClientCapabilities, RootsCapability
        session = ctx.session
        if not session.check_client_capability(
                ClientCapabilities(roots=RootsCapability())):
            return None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            got = await session.list_roots()
    except Exception:                                    # noqa: BLE001
        return None
    return root_paths(r.uri for r in got.roots)


def allowed_folders(roots: Optional[List[str]]) -> List[str]:
    base = list(roots) if roots else [PROJECT_DIR]
    return base + list(ALLOW_DIRS) + env_allow_dirs()


def check_paths(paths: Iterable[Any], roots: Optional[List[str]],
                what: str = "path") -> Optional[Dict[str, Any]]:
    """None when every path is allowed, else the error to return."""
    folders = allowed_folders(roots)
    for given in paths:
        if not given or not isinstance(given, str):
            continue
        if not any(inside(given, f) for f in folders):
            return {
                "kind": "PATH_NOT_ALLOWED",
                "message": "%s %r is outside the folders this server may "
                           "use" % (what, given),
                "allowed": [os.path.abspath(f) for f in folders],
                "source": "the client's roots" if roots
                          else "the project folder and --allow-dir",
                "hints": ["Use a path inside one of the allowed folders.",
                          "Or ask the user to start the server with "
                          "--allow-dir <folder> (or add the folder as a "
                          "root in the client)."]}
    return None


async def gate(ctx: Any, *paths: Any, what: str = "path"
               ) -> Optional[Dict[str, Any]]:
    """Check the paths a call names against the roots, if it names any."""
    named = [p for p in paths if p and isinstance(p, str)]
    if not named:
        return None
    return check_paths(named, await client_roots(ctx), what)


def gate_ops(ops: Any) -> List[str]:
    """The file paths in a list of build ops (``import`` ops read one)."""
    out = []
    for item in ops if isinstance(ops, list) else []:
        if isinstance(item, dict) and item.get("op") == "import" \
                and isinstance(item.get("path"), str):
            out.append(item["path"])
    return out


# ---------------------------------------------------------------- overwrite


def keeps_old_version(path: str) -> bool:
    """A document file that a save replaces keeps the old one in
    OldVersions (core/oldversions.py), so overwriting it can be undone."""
    if os.path.splitext(path)[1].lower() not in DOC_EXTENSIONS:
        return False
    try:
        from ..core import oldversions
        return oldversions.keep_setting() != 0
    except Exception:                                    # noqa: BLE001
        return False


async def _supports_elicitation(ctx: Any) -> bool:
    try:
        from mcp.types import ClientCapabilities, ElicitationCapability
        return bool(ctx.session.check_client_capability(
            ClientCapabilities(elicitation=ElicitationCapability())))
    except Exception:                                    # noqa: BLE001
        return False


async def confirm_overwrite(ctx: Any, path: str, overwrite: bool,
                            confirm: bool, what: str = "file"
                            ) -> Optional[Dict[str, Any]]:
    """None to go on; else the error to return. Only asks when the call
    really would write over an existing file that keeps no copy of itself."""
    if not (overwrite and path and isinstance(path, str)
            and os.path.exists(path)):
        return None
    if keeps_old_version(path):
        return None
    if confirm:
        return None
    if await _supports_elicitation(ctx):
        try:
            from pydantic import BaseModel, Field

            class Sure(BaseModel):
                overwrite: bool = Field(
                    False, description="Replace the existing file")

            got = await ctx.elicit(
                "Replace the existing %s %s? Nothing keeps a copy of it."
                % (what, path), Sure)
            if getattr(got, "action", "") == "accept" and got.data.overwrite:
                return None
            return {"kind": "USER_DECLINED",
                    "message": "the user did not agree to replace %s" % path,
                    "hints": ["Do not repeat it: use another path, or ask "
                              "what they want."]}
        except Exception:                                # noqa: BLE001
            pass                       # no usable back channel: confirm
    return {"kind": "CONFIRM_REQUIRED",
            "message": "%s exists and keeps no old version of itself; "
                       "overwriting it cannot be undone" % path,
            "hints": ["Ask the user whether to replace it. If they agree, "
                      "repeat the call with overwrite=true and "
                      "confirm=true.",
                      "Or write to a new path."]}


# ---------------------------------------------------------------- budgets


def clamp_side(value: Any, default: int) -> Tuple[int, bool]:
    """A render size held to MAX_IMAGE_SIDE; (value, was it capped)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default, False
    n = max(n, 16)
    return (MAX_IMAGE_SIDE, True) if n > MAX_IMAGE_SIDE else (n, False)


def size_of(data: Any) -> int:
    return len(json.dumps(data, ensure_ascii=False, default=str))


def page(result: Any, keys: Iterable[str], offset: int = 0,
         limit: int = 0, default_limit: int = 0,
         max_bytes: int = 0, also: Iterable[str] = ()) -> Any:
    """Page the lists named by ``keys`` and hold the answer to a byte
    budget. Adds ``paging`` ({key: {total, offset, returned, next_offset}})
    and a ``truncated`` note only when something was left out, so a small
    answer comes back unchanged. ``also`` names lists that are only cut to
    fit the byte budget (they take no offset)."""
    if not isinstance(result, dict):
        return result
    max_bytes = max_bytes or MAX_BYTES
    limit = int(limit or default_limit or 0)
    offset = max(int(offset or 0), 0)
    lists = [k for k in keys if isinstance(result.get(k), list)]
    out = dict(result)
    notes: Dict[str, Any] = {}
    for k in lists:
        seq = result[k]
        end = len(seq) if not limit else min(len(seq), offset + limit)
        if offset or end < len(seq):
            out[k] = seq[offset:end]
            notes[k] = {"total": len(seq), "offset": offset,
                        "returned": end - offset,
                        "next_offset": end if end < len(seq) else None}
    paged = list(lists)
    lists += [k for k in also if isinstance(result.get(k), list)
              and k not in lists]
    # the byte budget: halve the longest list until it fits
    guard = 0
    while size_of(out) > max_bytes and guard < 40:
        guard += 1
        longest = max(lists, key=lambda k: len(out[k]), default=None)
        if longest is None or len(out[longest]) <= 1:
            break
        seq = result[longest]
        start = notes.get(longest, {}).get(
            "offset", offset if longest in paged else 0)
        keep = max(len(out[longest]) // 2, 1)
        out[longest] = seq[start:start + keep]
        notes[longest] = {"total": len(seq), "offset": start,
                          "returned": keep,
                          "next_offset": start + keep
                          if start + keep < len(seq) else None}
    if notes:
        out["paging"] = notes
        out["truncated"] = ("%s left out (answer capped at %d bytes or the "
                            "limit); ask again with offset=next_offset "
                            "(and a smaller limit)" % (
                                ", ".join(k for k, v in notes.items()
                                          if v["next_offset"] is not None)
                                or "nothing", max_bytes))
        if all(v["next_offset"] is None for v in notes.values()):
            del out["truncated"]
    return out


def cap_text(text: str, max_chars: int = 400_000) -> str:
    """The last net: no text block goes past max_chars."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [cut at %d characters]" % max_chars
