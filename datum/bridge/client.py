"""The MCP server's end of a headless host: start it, talk to it, survive it.

This module never imports OpenCASCADE, Qt or anything under ``datum.core``.
The server that loads it holds the conversation; the host holds the
geometry. If the kernel crashes, it crashes the host, and this starts a
new one and says what was lost.

One request is in flight at a time: a lock is held from sending a request
until its answer is read, so two tool calls arriving together can never
read each other's answers (build123d-mcp ADR 0001 records that bug). A
single host is serial anyway, so the lock costs nothing.
"""

from __future__ import annotations

import itertools
import json
import os
import queue
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional

from .host import MARK

START_SECONDS = 120
# put on the answer queue when the host's output closes
_EOF = object()


class HostLost(RuntimeError):
    """The host died while working, or could not be started."""


class RemoteError(Exception):
    """An op failed in the host; ``data`` is its kind, message and hints."""

    def __init__(self, data: Dict[str, Any]) -> None:
        super().__init__(data.get("message", "failed"))
        self.data = data


def host_command() -> List[str]:
    """How to start a host: the built program, or this Python from source."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--headless", "--serve"]
    return [sys.executable, "-m", "datum.bridge.host"]


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


class HostClient:
    def __init__(self, timeout: float = 300.0) -> None:
        self.timeout = timeout
        self._proc: Optional[subprocess.Popen] = None
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self.restarts = 0
        self.lost_note = ""
        self._lost_since = False

    # -- lifecycle -------------------------------------------------------

    def _reader(self, stream) -> None:
        for raw in stream:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith(MARK):
                self._lines.put(line[len(MARK):])
        # the pipe closed: the process has gone, whatever its exit code
        # says yet (Windows can take a moment to report one)
        self._lines.put(_EOF)

    def start(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = _root() + os.pathsep + env.get("PYTHONPATH", "")
        # a host is already the separate process; it builds in itself
        env.setdefault("DATUM_NO_WORKERS", "1")
        # ...but evaluate may start workers of its own, which is what its
        # variants are for (bridge/explore_ops.py)
        env["DATUM_HEADLESS_HOST"] = "1"
        flags = 0
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._lines = queue.Queue()
        self._proc = subprocess.Popen(
            host_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, cwd=_root(), env=env,
            creationflags=flags)
        threading.Thread(target=self._reader, args=(self._proc.stdout,),
                         daemon=True).start()
        first = self._next(START_SECONDS)
        if first in (None, _EOF) or json.loads(first).get("method") != "ready":
            self.stop()
            raise HostLost("the InventCraft host did not start")

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
            proc.wait(5)
        except Exception:
            proc.kill()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _next(self, timeout: float) -> Optional[str]:
        """The next answer line; None on a timeout, _EOF if the host's
        output closed."""
        try:
            return self._lines.get(timeout=timeout)
        except queue.Empty:
            return None

    def _exit_code(self):
        try:
            return self._proc.wait(5) if self._proc else None
        except Exception:
            return None

    # -- calls -----------------------------------------------------------

    def cancel(self) -> None:
        """Ask the host to stop what it is doing (an evaluate or optimise
        between variants). Safe from another thread while a call waits; a
        host with nothing running ignores it."""
        proc = self._proc
        if proc is None:
            return
        try:
            proc.stdin.write(b'{"jsonrpc":"2.0","method":"cancel"}\n')
            proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def call(self, method: str, params: Optional[Dict[str, Any]] = None,
             progress=None) -> Dict[str, Any]:
        """One request. ``progress(done, total, message)`` is told as a
        long one goes on."""
        with self._lock:
            if not self.alive():
                # one that died under us is a restart; the first start,
                # or one after stop(), is not
                was_lost = self._proc is not None or self._lost_since
                self.start()
                if was_lost:
                    self.restarts += 1
                self._lost_since = False
            ident = next(self._ids)
            message = json.dumps({"jsonrpc": "2.0", "id": ident,
                                  "method": method, "params": params or {}})
            try:
                self._proc.stdin.write((message + "\n").encode("utf-8"))
                self._proc.stdin.flush()
            except OSError:
                self._lost("the host closed while being sent a request")
            while True:
                line = self._next(self.timeout)
                if line is _EOF:
                    self._lost("the host process exited (code %s) while "
                               "working" % self._exit_code())
                if line is None:
                    self._lost("the host did not answer within %.0f s"
                               % self.timeout)
                answer = json.loads(line)
                if answer.get("id") == ident:
                    break
                if answer.get("method") == "progress" and progress:
                    try:
                        note = answer.get("params") or {}
                        progress(note.get("done", 0), note.get("total", 0),
                                 note.get("message", ""))
                    except Exception:
                        pass
        if "error" in answer:
            raise RemoteError(answer["error"].get("data")
                              or {"kind": "INTERNAL",
                                  "message": answer["error"].get("message")})
        return answer.get("result") or {}

    def _lost(self, why: str) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        self.lost_note = why
        self._lost_since = True
        raise HostLost(
            "%s. Documents open in it and not saved are lost; the next "
            "call starts a fresh host." % why)
