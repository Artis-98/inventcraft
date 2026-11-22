"""``python -m datum.mcp --selftest`` (and ``InventCraft.exe --mcp
--selftest``): is this install able to serve an agent?

It starts the server exactly as a client would (a child process on stdio),
talks to it with the MCP client, and runs a tiny job in a temporary
folder: list the tools, make a part, build a plate with a hole, inspect it
against what it should measure, render it, save it, and check that a path
outside the allowed folders is refused. It prints one line per step with
the time it took, then PASS or FAIL, and returns the exit code (0 or 1).
Nothing is left behind and no document of the user's is touched.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from typing import Any, Callable, List, Optional, Tuple

TIMEOUT = 180.0


def _command() -> Tuple[str, List[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp"]
    return sys.executable, ["-m", "datum.mcp"]


def _payload(result: Any) -> Any:
    for block in reversed(getattr(result, "content", []) or []):
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                continue
    return {}


async def _run(steps: List[Tuple[str, float, str]], tmp: str) -> None:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    exe, args = _command()
    env = dict(os.environ)
    env["INVENTCRAFT_ALLOW_DIRS"] = tmp
    here = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    if not getattr(sys, "frozen", False):
        env["PYTHONPATH"] = here + os.pathsep + env.get("PYTHONPATH", "")
    params = StdioServerParameters(command=exe, args=args, env=env, cwd=tmp)

    def step(name: str, started: float, ok: bool, note: str = "") -> None:
        steps.append((name, time.time() - started, "" if ok else
                      "FAIL " + note if note else ("" if ok else "FAIL")))
        if not ok:
            raise RuntimeError("%s: %s" % (name, note or "failed"))

    t = time.time()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            step("start server and handshake", t, True)

            t = time.time()
            tools = (await session.list_tools()).tools
            names = {x.name for x in tools}
            need = {"build", "inspect", "render_view", "save_document",
                    "new_document", "model_tree"}
            step("list tools (%d)" % len(tools), t,
                 need <= names, "missing %s" % sorted(need - names))

            t = time.time()
            made = _payload(await session.call_tool("new_document", {}))
            doc = made.get("doc", "")
            step("new_document", t, bool(doc), json.dumps(made)[:200])

            t = time.time()
            ops = [
                {"op": "parameter", "name": "w", "value": 40},
                {"op": "parameter", "name": "t", "value": 5},
                {"op": "sketch", "id": "s", "plane": "XY", "entities": [
                    {"rect": {"center": [0, 0], "size": ["w", 30]},
                     "id": "r"},
                    {"circle": {"center": [0, 0], "d": 8}, "id": "c"}]},
                {"op": "extrude", "id": "e", "sketch": "$s",
                 "distance": "t"},
            ]
            built = await session.call_tool("build", {"ops": ops,
                                                      "doc": doc})
            data = _payload(built)
            step("build a plate", t, not built.is_error,
                 json.dumps(data)[:300])

            t = time.time()
            want = {"bbox": [40, 30, 5], "solids": 1, "valid": True}
            got = await session.call_tool("inspect",
                                          {"doc": doc, "expected": want})
            data = _payload(got)
            step("inspect against 40 x 30 x 5", t,
                 not got.is_error
                 and (data.get("verdict") or {}).get("pass") is True,
                 json.dumps(data)[:300])

            t = time.time()
            img = await session.call_tool("render_view", {"doc": doc})
            has_png = any(getattr(c, "type", "") == "image"
                          for c in img.content)
            step("render_view (picture)", t, not img.is_error and has_png)

            t = time.time()
            target = os.path.join(tmp, "selftest.icpart")
            saved = await session.call_tool(
                "save_document", {"doc": doc, "path": target})
            step("save_document", t,
                 not saved.is_error and os.path.isfile(target),
                 json.dumps(_payload(saved))[:300])

            t = time.time()
            reopened = await session.call_tool("open_document",
                                               {"path": target})
            step("open the saved file", t, not reopened.is_error,
                 json.dumps(_payload(reopened))[:300])

            t = time.time()
            outside = os.path.join(os.path.dirname(tmp), "ic_outside.icpart")
            refused = await session.call_tool(
                "save_document", {"doc": doc, "path": outside})
            kind = _payload(refused).get("kind", "")
            step("a path outside the allowed folders is refused", t,
                 bool(refused.is_error) and kind == "PATH_NOT_ALLOWED"
                 and not os.path.exists(outside), kind)


def run(out: Optional[Callable[[str], None]] = None) -> int:
    out = out or (lambda s: print(s, flush=True))
    tmp = tempfile.mkdtemp(prefix="ic_selftest_")
    steps: List[Tuple[str, float, str]] = []
    started = time.time()
    error = ""
    try:
        asyncio.run(asyncio.wait_for(_run(steps, tmp), TIMEOUT))
    except asyncio.TimeoutError:
        error = "timed out after %d s" % TIMEOUT
    except BaseException as exc:                          # noqa: BLE001
        while getattr(exc, "exceptions", None):          # an ExceptionGroup
            exc = exc.exceptions[0]
        error = str(exc) or exc.__class__.__name__
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for name, secs, note in steps:
        out("  %-52s %6.2f s %s" % (name, secs, note))
    total = time.time() - started
    if error:
        out("  FAILED: %s" % error)
        out("FAIL  inventcraft-mcp selftest (%.1f s)" % total)
        return 1
    out("PASS  inventcraft-mcp selftest: %d steps, %.1f s" % (
        len(steps), total))
    return 0
