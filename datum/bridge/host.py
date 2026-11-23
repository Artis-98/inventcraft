"""The headless host: a copy of InventCraft with no window, serving ops.

The MCP server starts one of these and talks to it over its stdin and
stdout, one JSON-RPC 2.0 message per line, the way the window talks to its
geometry workers (``core/worker.py``). OpenCASCADE prints to the console
now and then, so the real stdout is sent to nowhere and answers go out on a
private copy of it, each line marked so that nothing else can be mistaken
for one.

A host holds documents for as long as it lives. If the kernel takes it
down, the server starts another; what was open and unsaved is lost, and the
server says so rather than pretending otherwise.

    python -m datum.bridge.host           from source
    InventCraft.exe --headless --serve    from the installed build

Nothing here imports Qt.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Dict

MARK = "\x1eICBRIDGE "


class InProcessHost:
    """The same ops, called directly: for tests, and for running without
    a second process when containment is not wanted."""

    def __init__(self) -> None:
        from .workspace import Workspace
        self.workspace = Workspace()

    def call(self, method: str, params: Dict[str, Any] = None
             ) -> Dict[str, Any]:
        from . import ops
        return ops.call(self.workspace, method, params or {})


def _answer(ident, result=None, error=None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"jsonrpc": "2.0", "id": ident}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def serve() -> int:
    """Answer requests until stdin closes."""
    answers = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    try:
        quiet = os.open(os.devnull, os.O_WRONLY)
        os.dup2(quiet, 1)
        sys.stdout = open(os.devnull, "w")
    except OSError:
        pass
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

    from . import ops
    from .errors import classify
    from .workspace import Workspace

    import queue
    import threading

    class HeadlessWorkspace(Workspace):
        """What a long request can ask of the process around it: has the
        server said stop, and tell the server how far it has got."""

        def __init__(self) -> None:
            super().__init__()
            self.stop = threading.Event()

        def should_cancel(self) -> bool:
            return self.stop.is_set()

        def progress(self, done: int, total: int, message: str = "") -> None:
            say({"jsonrpc": "2.0", "method": "progress",
                 "params": {"done": done, "total": total,
                            "message": message}})

    workspace = HeadlessWorkspace()

    def say(message: Dict[str, Any]) -> None:
        answers.write(MARK + json.dumps(message) + "\n")
        answers.flush()

    from .. import __version__
    from . import PROTOCOL_VERSION
    say({"jsonrpc": "2.0", "method": "ready",
         "params": {"pid": os.getpid(), "version": __version__,
                    "protocol": PROTOCOL_VERSION}})

    # Requests are read on a thread of their own so that a "cancel" sent
    # while one is running (a long evaluate) is heard at once; everything
    # else waits its turn on the queue, in order.
    waiting: "queue.Queue[Any]" = queue.Queue()

    def read() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                waiting.put(("bad", None))
                continue
            if request.get("method") == "cancel" and "id" not in request:
                workspace.stop.set()
                continue
            waiting.put(("call", request))
        waiting.put(("end", None))

    threading.Thread(target=read, name="host-stdin", daemon=True).start()
    while True:
        kind, request = waiting.get()
        if kind == "end":
            break
        if kind == "bad":
            say(_answer(None, error={"code": -32700, "message": "bad JSON"}))
            continue
        ident = request.get("id")
        workspace.stop.clear()
        try:
            result = ops.call(workspace, request.get("method", ""),
                              request.get("params") or {})
            say(_answer(ident, result))
        except Exception as exc:                    # noqa: BLE001
            data = classify(exc)
            if data["kind"] == "INTERNAL":
                data["trace"] = traceback.format_exc(limit=8)
            say(_answer(ident, error={"code": 1, "message": data["message"],
                                      "data": data}))
    return 0


if __name__ == "__main__":
    sys.exit(serve())
