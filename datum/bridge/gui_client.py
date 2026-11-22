"""The MCP server's end of the app's bridge: connect, pair, talk.

The running application can serve the same ops a headless host does, over a
named pipe, once the user has turned Preferences > AI > Allow agents on
(``ui/agent_bridge.py``). This module is how the MCP server reaches it. It
never imports Qt, OpenCASCADE or anything under ``datum.core`` but the
plain preferences module, for the folder the pairing file is in.

One request is in flight at a time, as with ``HostClient``. Unlike a
headless host, the app is not the server's to restart: when it cannot be
reached the answer is ``GuiUnavailable`` and the documents stay where they
are, in the app.

The pipe is a Windows named pipe (opened by name, read by polling it so a
timeout is possible) or, elsewhere, a Unix socket in the temporary folder,
which is where Qt's local server puts one.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import threading
import time
from typing import Any, Dict, Optional

from . import pairing
from .client import RemoteError

CALL_TIMEOUT = 300.0
CONNECT_TIMEOUT = 5.0
# after a failed attempt, do not try again for this long: a tool call that
# only wants to know whether the app is there must not cost a wait each time
RETRY_AFTER = 2.0


class GuiUnavailable(RuntimeError):
    """The app's bridge cannot be reached right now."""

    def __init__(self, message: str, kind: str = "GUI_HOST_UNAVAILABLE"):
        super().__init__(message)
        self.kind = kind


class _Pipe:
    """A byte stream to the app, with a timeout on reading."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._buffer = b""
        if sys.platform == "win32":
            self._open_windows()
        else:
            self._open_unix()

    # windows ----------------------------------------------------------
    def _open_windows(self) -> None:
        import msvcrt
        path = "\\\\.\\pipe\\" + self.name
        deadline = time.monotonic() + CONNECT_TIMEOUT
        while True:
            try:
                self._file = open(path, "r+b", buffering=0)
                break
            except FileNotFoundError:
                raise
            except OSError:
                # every instance of the pipe is busy for a moment
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        self._handle = msvcrt.get_osfhandle(self._file.fileno())

    def _available_windows(self) -> int:
        import _winapi
        return _winapi.PeekNamedPipe(self._handle, 0)[0]

    # unix -------------------------------------------------------------
    def _open_unix(self) -> None:
        import socket
        folder = os.environ.get("TMPDIR") or "/tmp"
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(CONNECT_TIMEOUT)
        self._sock.connect(os.path.join(folder, self.name))

    # both -------------------------------------------------------------
    def send(self, data: bytes) -> None:
        if sys.platform == "win32":
            self._file.write(data)
        else:
            self._sock.sendall(data)

    def line(self, timeout: float) -> Optional[bytes]:
        """The next line, or None when ``timeout`` runs out first. A closed
        pipe is an OSError."""
        deadline = time.monotonic() + timeout
        while True:
            at = self._buffer.find(b"\n")
            if at >= 0:
                got, self._buffer = self._buffer[:at], self._buffer[at + 1:]
                return got
            if len(self._buffer) > pairing.MAX_LINE:
                raise OSError("the app sent a line that is too long")
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            if sys.platform == "win32":
                waiting = self._available_windows()
                if not waiting:
                    time.sleep(min(0.01, left))
                    continue
                chunk = self._file.read(min(waiting, 1 << 20))
            else:
                self._sock.settimeout(left)
                try:
                    chunk = self._sock.recv(1 << 20)
                except OSError as exc:
                    if "timed out" in str(exc):
                        return None
                    raise
            if not chunk:
                raise OSError("the app closed the pipe")
            self._buffer += chunk

    def close(self) -> None:
        try:
            if sys.platform == "win32":
                self._file.close()
            else:
                self._sock.close()
        except Exception:
            pass


class GuiClient:
    def __init__(self, timeout: float = CALL_TIMEOUT) -> None:
        self.timeout = timeout
        self._pipe: Optional[_Pipe] = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._secret = ""
        self._server_nonce = ""
        self._client_nonce = ""
        self._not_before = 0.0
        self.last_error = ""
        self.info: Dict[str, Any] = {}

    # -- connecting --------------------------------------------------------

    def connected(self) -> bool:
        return self._pipe is not None

    def _drop(self) -> None:
        pipe, self._pipe = self._pipe, None
        if pipe is not None:
            pipe.close()

    def _read(self, timeout: float) -> Dict[str, Any]:
        line = self._pipe.line(timeout)
        if line is None:
            raise OSError("no answer within %.0f s" % timeout)
        return json.loads(line.decode("utf-8"))

    def _connect(self) -> None:
        try:
            pair = pairing.read_pairing()
        except pairing.PairingError as exc:
            raise GuiUnavailable(str(exc)) from exc
        try:
            self._pipe = _Pipe(pair["pipe"])
        except OSError as exc:
            raise GuiUnavailable(
                "the app does not answer on its pipe (%s): it is not "
                "running, or was closed without cleaning up" % exc) from exc
        try:
            hello = self._read(CONNECT_TIMEOUT)
            if hello.get("event") != "challenge":
                raise OSError("the app did not open with a challenge")
            server_nonce = str(hello["nonce"])
            client_nonce = pairing.new_nonce()
            ident = next(self._ids)
            self._pipe.send((json.dumps({
                "id": ident, "method": "auth", "params": {
                    "client_nonce": client_nonce,
                    "proof": pairing.client_proof(
                        pair["secret"], server_nonce, client_nonce)},
            }) + "\n").encode("utf-8"))
            answer = self._read(CONNECT_TIMEOUT)
        except (OSError, ValueError, KeyError) as exc:
            self._drop()
            raise GuiUnavailable("pairing with the app failed: %s" % exc
                                 ) from exc
        if "error" in answer:
            self._drop()
            raise GuiUnavailable(
                (answer["error"].get("data") or {}).get(
                    "message", "the app refused the pairing"),
                "GUI_PAIRING_FAILED")
        result = answer.get("result") or {}
        # the app must hold the secret too: a pipe by that name made by
        # something else could not answer this
        if not pairing.same(result.get("server_proof", ""),
                            pairing.server_proof(pair["secret"],
                                                 server_nonce,
                                                 client_nonce)):
            self._drop()
            raise GuiUnavailable(
                "what answered on the app's pipe did not know the secret",
                "GUI_PAIRING_FAILED")
        self._secret = pair["secret"]
        self._server_nonce = server_nonce
        self._client_nonce = client_nonce
        self.info = {k: v for k, v in result.items() if k != "server_proof"}

    def ensure(self, force: bool = False) -> None:
        """Be connected and paired, or raise GuiUnavailable."""
        if self._pipe is not None:
            return
        now = time.monotonic()
        if not force and now < self._not_before:
            raise GuiUnavailable(self.last_error or
                                 "the app's bridge is not reachable")
        try:
            self._connect()
            self.last_error = ""
        except GuiUnavailable as exc:
            self.last_error = str(exc)
            self._not_before = time.monotonic() + RETRY_AFTER
            raise

    def probe(self) -> Dict[str, Any]:
        """Whether the app is there and paired, and why not if it is not."""
        with self._lock:
            try:
                self.ensure(force=True)
            except GuiUnavailable as exc:
                return {"connected": False, "reason": str(exc),
                        "kind": exc.kind}
            return {"connected": True, **self.info}

    def close(self) -> None:
        with self._lock:
            self._drop()

    # -- calls ---------------------------------------------------------------

    def _message(self, ident: int, method: str, params: Dict[str, Any]
                 ) -> Dict[str, Any]:
        nonce = pairing.new_nonce()
        return {"id": ident, "method": method, "params": params,
                "nonce": nonce,
                "mac": pairing.request_mac(
                    self._secret, self._server_nonce, self._client_nonce,
                    ident, nonce, method, params)}

    def cancel(self) -> None:
        """Ask the app to stop the request it is running for this client (an
        evaluate between variants). Safe from another thread while a call
        waits; the answer to it is ignored."""
        pipe = self._pipe
        if pipe is None:
            return
        try:
            pipe.send((json.dumps(self._message(
                next(self._ids), "cancel", {})) + "\n").encode("utf-8"))
        except (OSError, ValueError, AttributeError, KeyError):
            pass

    def call(self, method: str, params: Optional[Dict[str, Any]] = None,
             progress=None) -> Dict[str, Any]:
        """One request. ``progress(done, total, message)`` is told as a long
        one goes on, and each time it is told the wait starts again."""
        params = params or {}
        with self._lock:
            self.ensure()
            ident = next(self._ids)
            message = self._message(ident, method, params)
            try:
                self._pipe.send((json.dumps(message) + "\n").encode("utf-8"))
                deadline = time.monotonic() + self.timeout
                while True:
                    left = deadline - time.monotonic()
                    line = self._pipe.line(max(left, 0.0))
                    if line is None:
                        # give up on it: closing the pipe tells the app, which
                        # drops the request if it has not started it
                        self._drop()
                        self._not_before = time.monotonic() + RETRY_AFTER
                        raise GuiUnavailable(
                            "the app did not answer within %.0f s; it may "
                            "still be working on it" % self.timeout,
                            "GUI_HOST_UNAVAILABLE")
                    answer = json.loads(line.decode("utf-8"))
                    if answer.get("id") == ident:
                        break
                    if answer.get("method") == "progress":
                        deadline = time.monotonic() + self.timeout
                        if progress:
                            note = answer.get("params") or {}
                            try:
                                progress(note.get("done", 0),
                                         note.get("total", 0),
                                         note.get("message", ""))
                            except Exception:
                                pass
            except (OSError, ValueError) as exc:
                self._drop()
                self.last_error = "the app closed the pipe: %s" % exc
                self._not_before = time.monotonic() + RETRY_AFTER
                raise GuiUnavailable(self.last_error) from exc
        if "error" in answer:
            data = answer["error"].get("data") or {
                "kind": "INTERNAL", "message": answer["error"].get("message")}
            if data.get("kind") in ("AUTH_FAILED", "REPLAY"):
                with self._lock:
                    self._drop()
            raise RemoteError(data)
        return answer.get("result") or {}
