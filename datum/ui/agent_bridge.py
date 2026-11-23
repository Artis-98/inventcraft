"""The running app, as a host an agent can drive.

Off until the user turns on Preferences > AI > Allow agents. Then a named
pipe (``QLocalServer``) serves the same ops a headless host does
(``datum/bridge/ops.py``) over the documents open in this window, so an
agent edits what the person is looking at and the person sees it happen.

What keeps that safe:

* **Pairing.** The pipe answers only a client that proves it holds the
  secret in the user's ``bridge.json`` (``bridge/pairing.py``), and then
  only requests that carry a MAC and a nonce used once. Anything else is
  refused without being run, and the connection is closed.
* **The main thread.** Requests arrive on the pipe, wait in a queue, and
  run one at a time on the Qt thread, because the document and the window
  are only ever touched there. A request whose connection has gone, or
  that was stopped, is dropped and never runs late (the Fusion 360 server's
  rule for its queue).
* **One undo step.** The ops already put one step on the document's own
  undo stack per ``build``, ``edit_feature``, ``properties``... so Ctrl+Z
  takes a whole agent change back. The window is refreshed afterwards the
  way its own undo does it (``MainWindow.rebuild``).
* **Autosave.** Before each change the document is written to
  ``agent-autosave/`` in the config folder (the last five per document).
* **Badge and Stop.** While a request runs, or waits, the status bar says
  "Agent working" with a Stop button. Stop drops what is queued and ends
  the running build between its ops, rolling it back.
* **No agent code.** ``run_script`` is refused here: the server runs it in a
  headless host and brings back build ops, which are only data
  (``script_apply``). A ``code`` op, the one way code reaches a document,
  stops and shows the user the source first (``ask_code``).
* **What the user does.** The window's selection and tabs are watched
  (``ChangeTracker``) and their settled state is kept as version numbers;
  the server asks for them with ``poll`` (answered at once, outside the
  queue, so it neither shows the badge nor blocks input) and tells its
  client with ``notifications/resources/updated``. ``get_selection`` names
  what is picked by provenance roles, as references.
* **No surprises.** An agent never changes a document while the user is in a
  sketch or a feature dialog on it, and never closes their documents.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import time
import uuid
import traceback
from typing import Any, Callable, Dict, List, Optional

from PySide6 import QtCore, QtNetwork, QtWidgets

from ..bridge import PROTOCOL_VERSION, ops, pairing, selection
from ..bridge.errors import BridgeError, classify
from ..bridge.workspace import Entry, Workspace
from ..core import fileformat, prefs, rules
from . import theme

# -- what is served ------------------------------------------------------------

# code is never run here; the user's documents are theirs to close
REFUSED = {
    "run_script": ("run_script does not run in the app: the server runs it "
                   "in a separate host and brings the result back as build "
                   "ops. Through the MCP server this is automatic."),
    "script_exec": "scripts never run in the app",
    "script_plan": "scripts never run in the app",
    "close_document": ("documents open in the app are the user's to close, "
                       "not an agent's"),
}
# every op that can change a document, so the window is shown the result
MUTATING = {"build", "edit_feature", "properties", "requirements",
            "snapshot", "script_apply", "save_document",
            "place_component", "constrain", "model_states", "branch",
            "drawing_base_view", "drawing_projected_view",
            "drawing_section_view", "drawing_detail_view",
            "drawing_dimension", "drawing_note", "drawing_parts_list",
            "sheet_rules", "frame_insert", "frame_treat", "derive_part",
            "skeleton_set", "optimise", "parametrize"}
DRAWING_EDITS = {"drawing_base_view", "drawing_projected_view",
                 "drawing_section_view", "drawing_detail_view",
                 "drawing_dimension", "drawing_note", "drawing_parts_list"}

MAX_CONNECTIONS = 4
AUTH_SECONDS = 10
LOCKOUT_FAILURES = 5
LOCKOUT_SECONDS = 30
KEEP_AUTOSAVES = 5


def _will_change(method: str, p: Dict[str, Any]) -> bool:
    """Whether this call will change the document, so that it is saved
    first: a read, or a dry run, is not."""
    if method in ("build", "script_apply"):
        return not p.get("dry_run")
    if method == "edit_feature":
        return bool(p.get("params") or p.get("suppress") is not None
                    or p.get("move_to") is not None or p.get("delete")
                    or p.get("rename")) and not p.get("dry_run")
    if method == "properties":
        return bool(p.get("parameters") or p.get("remove")
                    or p.get("props") or p.get("material"))
    if method in ("place_component", "constrain") or method in DRAWING_EDITS:
        return not p.get("dry_run")
    if method in ("frame_insert", "frame_treat", "derive_part",
                  "skeleton_set"):
        return not p.get("dry_run")
    if method == "sheet_rules":
        return any(p.get(k) is not None for k in (
            "thickness", "bend_radius", "k_factor", "gap")) \
            and not p.get("dry_run")
    if method == "model_states":
        return p.get("action", "list") != "list" and not p.get("dry_run")
    if method == "branch":
        # switching and merging replace the document's content; check_in
        # and create only write the file (and its history)
        return p.get("action") in ("switch", "merge")             and not p.get("dry_run")
    if method == "requirements":
        return bool(p.get("set") or p.get("remove"))
    if method == "snapshot":
        return p.get("action") == "restore"
    if method == "optimise":
        return bool(p.get("apply")) and not p.get("dry_run")
    if method == "parametrize":
        return not p.get("dry_run")
    return False


# -- asking the user about code ------------------------------------------------


def ask_code(parent, name: str, source: str) -> bool:
    """Show the user an agent's code feature and ask whether it may run.

    Replaceable, so a test can answer; the default is No."""
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("An agent wants to add code")
    dialog.setMinimumSize(560, 420)
    layout = QtWidgets.QVBoxLayout(dialog)
    note = QtWidgets.QLabel(
        "An AI agent wants to add a code feature, \"%s\", to your document. "
        "It runs every time the part rebuilds, with your own privileges, "
        "and could do anything a Python program can. Read it first.\n\n"
        "Allowing it lets exactly this source run, for this session only."
        % name)
    note.setWordWrap(True)
    layout.addWidget(note)
    view = QtWidgets.QPlainTextEdit(source)
    view.setReadOnly(True)
    font = view.font()
    font.setFamily("Consolas")
    view.setFont(font)
    layout.addWidget(view, 1)
    buttons = QtWidgets.QDialogButtonBox()
    allow = buttons.addButton("Allow this code",
                              QtWidgets.QDialogButtonBox.AcceptRole)
    deny = buttons.addButton("Don't allow",
                             QtWidgets.QDialogButtonBox.RejectRole)
    deny.setDefault(True)
    allow.clicked.connect(dialog.accept)
    deny.clicked.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog.exec() == QtWidgets.QDialog.Accepted


# -- the documents, as the bridge sees them ------------------------------------


class GuiWorkspace(Workspace):
    """The window's open documents as a ``Workspace``.

    The entries wrap the very documents the tabs hold (nothing is copied),
    under handles ``g1``, ``g2``... that stay as long as the tab does.
    ``sync()`` follows the tab strip: a tab opened by the user appears, one
    they close goes, and a document whose own revision moved since the last
    look has been edited by the user, which moves its revision here too
    (so an agent's ``expected_revision`` stops it editing blind)."""

    PREFIX = "g"

    def __init__(self, bridge: "AgentBridge") -> None:
        super().__init__()
        self.bridge = bridge
        self._keys: Dict[str, str] = {}

    def should_cancel(self) -> bool:
        return self.bridge.check_cancel()

    def progress(self, done: int, total: int, message: str = "") -> None:
        """A long request (evaluate) says how far it is: sent to whoever
        asked, and shown on the badge."""
        job = self.bridge.current
        if job is not None:
            job.conn.send({"method": "progress", "params": {
                "done": done, "total": total, "message": message}})
            self.bridge.badge.show_working(
                "%s %d/%d" % (job.method, done, total),
                len(self.bridge.queue))

    def sync(self) -> None:
        session = self.bridge.window.session
        live: Dict[str, Entry] = {}
        for opened in session.documents:
            handle = self._keys.get(opened.key)
            entry = self.entries.get(handle) if handle else None
            if entry is None or entry.document is not opened.document:
                entry = self.add(opened.document, opened.doc_type)
                entry.code_gate = self.bridge.code_gate
                entry.source_mark = opened.revision
                ops._foreign_code(entry)
                self._keys[opened.key] = entry.handle
            elif entry.source_mark != opened.revision:
                entry.source_mark = opened.revision
                entry.touch()
            live[entry.handle] = entry
        for handle in list(self.entries):
            if handle not in live:
                del self.entries[handle]
        self._keys = {k: h for k, h in self._keys.items() if h in live}
        active = session.active
        self.active = self._keys.get(active.key, "") if active else ""
        if self.active not in self.entries:
            self.active = next(iter(self.entries), "")

    def get(self, handle: Optional[str] = None) -> Entry:
        self.sync()
        return super().get(handle)

    def opened_of(self, entry: Entry):
        """The tab's session entry for a bridge entry."""
        return self.bridge.window.session.by_document(entry.document)


# -- the badge ---------------------------------------------------------------------


class AgentBadge(QtWidgets.QWidget):
    """In the status bar: quiet while agents are merely allowed, a badge with
    a Stop button while one is working."""

    def __init__(self, bridge: "AgentBridge") -> None:
        super().__init__()
        self.setObjectName("agentBadge")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(4, 0, 8, 0)
        row.setSpacing(6)
        self.label = QtWidgets.QLabel("")
        row.addWidget(self.label)
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.setToolTip(
            "Stop the agent: what is waiting is dropped, and a build that "
            "is running is rolled back at its next step.")
        self.stop_button.setFixedHeight(20)
        self.stop_button.clicked.connect(bridge.stop)
        row.addWidget(self.stop_button)
        self.show_idle(False, 0)

    def show_idle(self, listening: bool, connections: int) -> None:
        self.stop_button.setVisible(False)
        self.label.setStyleSheet("color: %s;" % theme.C.text_dim)
        self.label.setText("Agents: connected" if connections
                           else "Agents: allowed")
        self.label.setToolTip(
            "Preferences > AI > Allow agents is on. An agent that has paired "
            "with this window can edit the open documents; each change is "
            "one undo step.")
        self.setVisible(listening)

    def show_working(self, what: str, waiting: int) -> None:
        self.label.setStyleSheet(
            "color: %s; font-weight: bold;" % theme.C.warn)
        self.label.setText("Agent working" + (
            " (%d waiting)" % waiting if waiting else ""))
        self.label.setToolTip(what)
        self.stop_button.setVisible(True)
        self.setVisible(True)


class _InputBlocker(QtCore.QObject):
    """While a request runs, the window ignores the user, except for the
    Stop button (and any dialog the request itself raised, such as the one
    that asks about code). A request pumps the event loop between its steps
    so that Stop can be heard, and without this a click on the model would
    be heard too."""

    BLOCKED = {
        QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
        QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseMove,
        QtCore.QEvent.Wheel, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease,
        QtCore.QEvent.ShortcutOverride, QtCore.QEvent.ContextMenu,
        QtCore.QEvent.DragEnter, QtCore.QEvent.Drop,
    }

    def __init__(self, window, badge: QtWidgets.QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.badge = badge
        self.active = False

    def blocks(self, obj, event) -> bool:
        if not self.active:
            return False
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        kind = event.type()
        if kind == QtCore.QEvent.Close and obj is self.window:
            return True
        if kind == QtCore.QEvent.Shortcut:
            return True
        if kind not in self.BLOCKED or not isinstance(obj, QtWidgets.QWidget):
            # a window's own copy of an input event (QWidgetWindow) goes
            # through; it is the widget it is handed to that decides
            return False
        while obj is not None:
            if obj is self.badge:
                return False
            obj = obj.parent()
        return True

    def eventFilter(self, obj, event) -> bool:                 # noqa: N802
        return self.blocks(obj, event)


# -- connections -----------------------------------------------------------------


class _Job:
    def __init__(self, conn: "_Connection", ident: Any, method: str,
                 params: Dict[str, Any]) -> None:
        self.conn = conn
        self.ident = ident
        self.method = method
        self.params = params
        self.cancelled = False


class _Connection(QtCore.QObject):
    """One client on the pipe: authenticate it, then check each request."""

    def __init__(self, bridge: "AgentBridge",
                 socket: QtNetwork.QLocalSocket) -> None:
        super().__init__(bridge)
        self.bridge = bridge
        self.socket = socket
        self.alive = True
        self._finished = False
        self.authed = False
        self.buffer = bytearray()
        self.used: set = set()
        self.server_nonce = pairing.new_nonce()
        self.client_nonce = ""
        socket.readyRead.connect(self._read)
        socket.disconnected.connect(self._gone)
        QtCore.QTimer.singleShot(AUTH_SECONDS * 1000, self._auth_timeout)
        self.send({"event": "challenge", "nonce": self.server_nonce,
                   "protocol": PROTOCOL_VERSION,
                   "pairing": pairing.PROTOCOL})

    # -- wire

    def send(self, message: Dict[str, Any]) -> None:
        if not self.alive:
            return
        try:
            data = json.dumps(message).encode("utf-8") + b"\n"
        except (TypeError, ValueError) as exc:
            data = json.dumps({"id": message.get("id"), "error": {
                "code": 1, "message": "the answer could not be written",
                "data": {"kind": "INTERNAL", "hints": [],
                         "message": "the answer could not be written: %s"
                         % exc}}}).encode("utf-8") + b"\n"
        self.socket.write(data)
        self.socket.flush()

    def refuse(self, ident: Any, kind: str, message: str) -> None:
        """Say no, and hang up: nothing that fails a check is kept."""
        self.send({"id": ident, "error": {
            "code": 1, "message": message,
            "data": {"kind": kind, "message": message, "hints": []}}})
        self.close()

    def close(self) -> None:
        if self.alive:
            self.socket.disconnectFromServer()

    def _gone(self) -> None:
        if not self.alive and self._finished:
            return
        self.alive = False
        self._finished = True
        self.bridge.connection_closed(self)

    def _auth_timeout(self) -> None:
        if self.alive and not self.authed:
            self.close()

    # -- reading

    def _read(self) -> None:
        self.buffer += bytes(self.socket.readAll())
        if len(self.buffer) > pairing.MAX_LINE and b"\n" not in self.buffer:
            self.close()
            return
        while self.alive and b"\n" in self.buffer:
            at = self.buffer.index(b"\n")
            line = bytes(self.buffer[:at])
            del self.buffer[:at + 1]
            if line.strip():
                self._handle(line)

    def _handle(self, line: bytes) -> None:
        try:
            message = json.loads(line.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("not an object")
        except ValueError:
            self.refuse(None, "BAD_REQUEST", "that was not a JSON request")
            return
        ident = message.get("id")
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(
                params if params is not None else {}, dict):
            self.refuse(ident, "BAD_REQUEST", "a request has a method and "
                        "an object of params")
            return
        params = params or {}
        secret = self.bridge.secret
        if not secret:
            self.refuse(ident, "AUTH_FAILED", "the bridge is off")
            return
        if not self.authed:
            self._authenticate(ident, method, params, secret)
            return
        nonce, mac = message.get("nonce"), message.get("mac")
        if not isinstance(nonce, str) or not isinstance(mac, str) \
                or not 8 <= len(nonce) <= 64:
            self.refuse(ident, "AUTH_FAILED",
                        "a request carries a nonce and a mac")
            return
        if nonce in self.used:
            self.refuse(ident, "REPLAY", "that request was already seen")
            return
        expected = pairing.request_mac(secret, self.server_nonce,
                                       self.client_nonce, ident, nonce,
                                       method, params)
        if not pairing.same(mac, expected):
            self.bridge.note_auth_failure()
            self.refuse(ident, "AUTH_FAILED", "the request's mac is wrong")
            return
        self.used.add(nonce)
        if len(self.used) > 20000:
            self.refuse(ident, "AUTH_FAILED", "too many requests on one "
                        "connection; connect again")
            return
        if method == "cancel":
            self.bridge.cancel_for(self)
            running = self.bridge.current
            if running is not None and running.conn is self:
                self.bridge._cancel = True
            self.send({"id": ident, "result": {"ok": True}})
            return
        if method == "poll":
            # what the user has done: version numbers only, answered at
            # once and outside the queue (no badge, no input block)
            self.send({"id": ident, "result": self.bridge.tracker.state()})
            return
        self.bridge.enqueue(_Job(self, ident, method, params))

    def _authenticate(self, ident, method, params, secret) -> None:
        client_nonce = params.get("client_nonce")
        proof = params.get("proof")
        if method != "auth" or not isinstance(client_nonce, str) \
                or not isinstance(proof, str) \
                or not 8 <= len(client_nonce) <= 64:
            self.refuse(ident, "AUTH_FAILED",
                        "pair first: the first request is auth")
            return
        expected = pairing.client_proof(secret, self.server_nonce,
                                        client_nonce)
        if not pairing.same(proof, expected):
            self.bridge.note_auth_failure()
            self.refuse(ident, "AUTH_FAILED",
                        "the proof does not match this app's secret")
            return
        self.authed = True
        self.client_nonce = client_nonce
        from .. import APP_NAME, __version__
        self.send({"id": ident, "result": {
            "server_proof": pairing.server_proof(
                secret, self.server_nonce, client_nonce),
            "host": "gui", "app": APP_NAME, "version": __version__,
            "protocol": PROTOCOL_VERSION, "pid": os.getpid()}})
        self.bridge.update_badge()


# -- what the user does ------------------------------------------------------------

_UNSET = object()


class _Settled:
    """A value that counts as changed once it has stopped moving: a burst
    of clicks, or a drag, is one change, not fifty."""

    def __init__(self, settle: float) -> None:
        self.settle = settle
        self.raw: Any = _UNSET
        self.since = 0.0
        self.published: Any = _UNSET

    def feed(self, value: Any, now: float) -> bool:
        """True when a settled value differs from the one published (never
        for the first one: that is the baseline)."""
        if value != self.raw:
            self.raw, self.since = value, now
        if self.raw != self.published and now - self.since >= self.settle:
            first = self.published is _UNSET
            self.published = self.raw
            return not first
        return False


class ChangeTracker(QtCore.QObject):
    """Watches the window for what an agent would want to hear about: the
    selection, the documents that are open, and each document's revision
    (a tree edited by the user). It does not push: it keeps version numbers
    that a ``poll`` reads, and the server turns a change into a
    notification (why polling)."""

    TICK_MS = 100
    SETTLE = 0.15

    def __init__(self, bridge: "AgentBridge") -> None:
        super().__init__(bridge)
        self.bridge = bridge
        self.selection_version = 0
        self.documents_version = 0
        self.docs: Dict[str, int] = {}
        self._selection = _Settled(self.SETTLE)
        self._documents = _Settled(self.SETTLE)
        self._trees = _Settled(self.SETTLE)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(self.TICK_MS)
        self.timer.timeout.connect(self.tick)

    def start(self) -> None:
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()

    def state(self) -> Dict[str, Any]:
        return {"selection": self.selection_version,
                "documents": self.documents_version,
                "docs": dict(self.docs),
                "agent_busy": self.bridge.current is not None}

    def tick(self, now: Optional[float] = None) -> None:
        bridge = self.bridge
        # a request that is running moves the documents itself, and its
        # own changes are not the user's
        if bridge.current is not None or not bridge.listening \
                or not any(c.authed for c in bridge.connections):
            return
        now = time.monotonic() if now is None else now
        try:
            ws = bridge.workspace
            ws.sync()
            handles = tuple(sorted(
                (h, e.path) for h, e in ws.entries.items()))
            revs = tuple(sorted((h, e.revision)
                                for h, e in ws.entries.items()))
            if self._documents.feed(handles, now):
                self.documents_version += 1
            if self._trees.feed(revs, now):
                self.docs = dict(revs)
            elif not self.docs and self._trees.published is not _UNSET:
                self.docs = dict(self._trees.published)
            if self._selection.feed(bridge.selection_state(), now):
                self.selection_version += 1
        except Exception:                                   # noqa: BLE001
            pass                  # a watcher must never trouble the window


# -- the bridge --------------------------------------------------------------------


class AgentBridge(QtCore.QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.server: Optional[QtNetwork.QLocalServer] = None
        self.secret = ""
        self.error = ""
        self.pairing_info: Dict[str, Any] = {}
        self.connections: List[_Connection] = []
        self.queue: "collections.deque[_Job]" = collections.deque()
        self.current: Optional[_Job] = None
        self.workspace = GuiWorkspace(self)
        self.badge = AgentBadge(self)
        self.tracker = ChangeTracker(self)
        window.statusBar().addPermanentWidget(self.badge)
        self.blocker = _InputBlocker(window, self.badge)
        QtWidgets.QApplication.instance().installEventFilter(self.blocker)
        self._cancel = False
        self._running = False
        self._denied: set = set()
        self._failures: List[float] = []
        self.last_autosave = ""
        # names the copies of documents never saved, this session only
        self._session = uuid.uuid4().hex
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.shutdown)

    # -- on and off

    @property
    def listening(self) -> bool:
        try:
            return self.server is not None and self.server.isListening()
        except RuntimeError:               # Qt has already deleted it
            return False

    def apply_preferences(self) -> None:
        """Start or stop the bridge as Preferences say."""
        want = prefs.prefs().allow_agents
        if want and not self.listening:
            self.start()
        elif not want and self.listening:
            self.stop_serving()

    def start(self) -> bool:
        """Make a secret, write the pairing file, listen. Off on any
        failure, with the reason in ``error``."""
        self.error = ""
        name = pairing.pipe_name()
        server = QtNetwork.QLocalServer(self)
        server.setSocketOptions(QtNetwork.QLocalServer.UserAccessOption)
        if not server.listen(name):
            if os.name != "nt":
                # a socket file left by a crash; a live one still answers
                probe = QtNetwork.QLocalSocket()
                probe.connectToServer(name)
                if not probe.waitForConnected(300):
                    QtNetwork.QLocalServer.removeServer(name)
                    server.listen(name)
            if not server.isListening():
                self.error = ("could not open the pipe %s: %s (is another "
                              "InventCraft already allowing agents?)"
                              % (name, server.errorString()))
                server.deleteLater()
                self._tell(self.error)
                return False
        try:
            from .. import __version__
            self.secret = pairing.new_secret()
            self.pairing_info = pairing.write_pairing(
                self.secret, {"version": __version__})
        except OSError as exc:
            # no secret on disk, no bridge: it fails closed
            server.close()
            server.deleteLater()
            self.secret = ""
            self.error = "could not write the pairing file: %s" % exc
            self._tell(self.error)
            return False
        server.newConnection.connect(self._accept)
        self.server = server
        self.workspace.sync()
        self.tracker.start()
        self.update_badge()
        self._tell("Agents are allowed: pairing file %s"
                   % pairing.pairing_path())
        return True

    def stop_serving(self) -> None:
        self.tracker.stop()
        self.stop()
        for conn in list(self.connections):
            conn.close()
        self.connections.clear()
        server, self.server = self.server, None
        if server is not None:
            server.close()
            server.deleteLater()
        self.secret = ""
        pairing.remove_pairing(os.getpid())
        self.update_badge()

    def shutdown(self) -> None:
        if self.listening or self.secret:
            self.stop_serving()

    def _tell(self, text: str) -> None:
        try:
            self.window.status_message.setText(text)
        except Exception:
            pass

    # -- connections

    def _accept(self) -> None:
        while self.server is not None and self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            now = time.monotonic()
            self._failures = [t for t in self._failures
                              if now - t < LOCKOUT_SECONDS]
            if len(self._failures) >= LOCKOUT_FAILURES \
                    or len(self.connections) >= MAX_CONNECTIONS:
                socket.disconnectFromServer()
                socket.deleteLater()
                continue
            conn = _Connection(self, socket)
            self.connections.append(conn)
            self.update_badge()

    def connection_closed(self, conn: _Connection) -> None:
        if conn in self.connections:
            self.connections.remove(conn)
        # nothing a gone client asked for is to run: it has given up
        self.cancel_for(conn)
        try:
            conn.socket.deleteLater()
        except RuntimeError:
            pass                      # the server took it with it
        self.update_badge()

    def note_auth_failure(self) -> None:
        self._failures.append(time.monotonic())

    def update_badge(self) -> None:
        if self.current is not None or self.queue:
            return
        self.badge.show_idle(
            self.listening, sum(1 for c in self.connections if c.authed))

    # -- the queue

    def enqueue(self, job: _Job) -> None:
        self.queue.append(job)
        self.badge.show_working(job.method, len(self.queue))
        QtCore.QTimer.singleShot(0, self.pump)

    def cancel_for(self, conn: _Connection) -> None:
        for job in self.queue:
            if job.conn is conn:
                job.cancelled = True

    def stop(self) -> None:
        """The Stop button: drop what waits, and end what runs."""
        dropped = [j for j in self.queue if not j.cancelled]
        self.queue.clear()
        for job in dropped:
            self._reply_error(job, BridgeError(
                "CANCELLED", "stopped by the user before it ran",
                ["The user pressed Stop in the app. Ask what they want "
                 "before trying again."]))
        if self.current is not None:
            self._cancel = True
        self.update_badge()

    def check_cancel(self) -> bool:
        """Asked between the steps of a running request. The event loop is
        turned (the window's input blocked) so that a click on Stop is
        heard."""
        if self.current is None:
            return False
        QtWidgets.QApplication.processEvents()
        return self._cancel

    def pump(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            while self.queue:
                job = self.queue.popleft()
                if job.cancelled or not job.conn.alive:
                    continue
                self._run(job)
                QtWidgets.QApplication.processEvents()
        finally:
            self._running = False
            self.update_badge()

    def _run(self, job: _Job) -> None:
        self.current = job
        self._cancel = False
        self.badge.show_working(job.method, len(self.queue))
        self.blocker.active = True
        QtWidgets.QApplication.processEvents()          # draw the badge
        try:
            result = self.execute(job.method, job.params)
            job.conn.send({"id": job.ident, "result": result})
        except Exception as exc:                        # noqa: BLE001
            self._reply_error(job, exc)
        finally:
            self.blocker.active = False
            self.current = None
            self._cancel = False

    def _reply_error(self, job: _Job, exc: BaseException) -> None:
        data = classify(exc)
        if data["kind"] == "INTERNAL":
            data["trace"] = traceback.format_exc(limit=8)
        job.conn.send({"id": job.ident, "error": {
            "code": 1, "message": data["message"], "data": data}})

    # -- running one request, on the main thread

    def code_gate(self, name: str, source: str) -> bool:
        """The user decides, once per source, whether an agent's code runs."""
        key = rules.code_hash(source)
        if key in self._denied:
            return False
        if ask_code(self.window, name, source):
            return True
        self._denied.add(key)
        return False

    def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run one op against the window's documents. Never raises a thing
        the caller cannot classify; never runs agent code."""
        if method in REFUSED:
            raise BridgeError("NOT_IN_GUI_HOST", REFUSED[method],
                              ["Scripts run in a headless host, and their "
                               "result is applied here as data."])
        ws = self.workspace
        ws.sync()
        local = getattr(self, "_op_" + method, None)
        if local is not None:
            return local(**params)
        if method not in ops.OPS:
            return ops.call(ws, method, params)            # UNKNOWN_METHOD
        entry = None
        if method in MUTATING:
            try:
                entry = ws.get(params.get("doc") or None)
            except BridgeError:
                entry = None                    # the op says what is wrong
        changing = entry is not None and _will_change(method, params)
        if changing:
            self._before_change(entry)
        had_body = entry is not None and _has_body(entry)
        seen = _signature(entry) if entry is not None else None
        result = ops.call(ws, method, params)
        if entry is not None and (method in MUTATING):
            if seen != _signature(entry) or changing:
                self._after_change(entry, had_body)
            if changing and isinstance(result, dict):
                result["autosave"] = self.last_autosave
            if method in ("save_document", "branch"):
                # the tab's modified mark and the title follow the save
                self.window.refresh_tabs()
                self.window._update_title()
        return result

    # the bridge's own ops --------------------------------------------------

    def _op_status(self) -> Dict[str, Any]:
        out = ops.status(self.workspace)
        out["host"] = "gui"
        out["pid"] = os.getpid()
        out["agent_busy"] = self.current is not None
        out["autosave_folder"] = self._autosave_folder()
        out["selection"] = self.selection_brief()
        return out

    def _op_find_open(self, path: str) -> Dict[str, Any]:
        """Which handle holds a file, if the app has it open (part b's
        routing asks this: a document open here is edited here)."""
        entry = self.workspace.by_path(path)
        return {"doc": entry.handle if entry else None}

    def _op_get_selection(self, doc: str = "") -> Dict[str, Any]:
        """What the user has picked now, as references (see
        ``bridge/selection.py``). The window shows one document at a
        time, and only that one has a selection."""
        ws = self.workspace
        ws.sync()
        active = ws.entries.get(ws.active)
        asked = ws.get(doc or None) if doc else active
        base: Dict[str, Any] = {"where": "gui",
                                "version": self.tracker.selection_version}
        if asked is None:
            return dict(base, doc=None, empty=True,
                        summary="nothing selected (no document is open)")
        if active is None or asked.handle != active.handle:
            return dict(base, doc=asked.handle, revision=asked.revision,
                        empty=True, active_doc=ws.active,
                        summary="nothing selected: the app is showing %s, "
                        "not %s" % (ws.active or "no document", asked.handle))
        out = self._selection_of(active)
        out.update(base)
        out.update(doc=active.handle, revision=active.revision)
        out["summary"] = selection.summary_of(out)
        out["empty"] = out["summary"] == "nothing selected"
        return out

    def _picked(self) -> List[Any]:
        """The model geometry picked in the viewport."""
        try:
            return list(self.window.viewport.selected_shapes())
        except Exception:                                   # noqa: BLE001
            return []

    def _selection_of(self, entry: Entry) -> Dict[str, Any]:
        win = self.window
        document = entry.document
        out: Dict[str, Any] = {"mode": "part" if entry.doc_type == "part"
                               else entry.doc_type}
        if win.editor.active:
            out["mode"] = "sketch"
            fid = getattr(win, "_sketch_feature_id", None)
            feature = document.feature(fid) if fid is not None and hasattr(
                document, "feature") else None
            names = (entry.sketch_names.get(fid) or {}) if fid is not None \
                else {}
            back = {(kind, ident): n for n, (kind, ident) in names.items()}
            sk = win.editor.sketch

            def label(kind, ident):
                return back.get((kind, ident), "#%s%d" % (
                    "e" if kind == "entity" else "p", ident))

            ents = []
            for eid in win.editor.selected_entities:
                e = sk.entities.get(eid) if sk is not None else None
                ents.append({"ref": label("entity", eid), "id": eid,
                             "kind": getattr(e, "kind", "")})
            pts = [{"ref": label("point", pid), "id": pid}
                   for pid in win.editor.selected_points]
            dims = []
            for cid in win.editor.selected_dimensions:
                c = sk.constraints.get(cid) if sk is not None else None
                dims.append({"id": cid, "name": getattr(c, "name", "")})
            out["sketch"] = {"name": feature.name if feature else "",
                             "feature": fid, "entities": ents,
                             "points": pts, "dimensions": dims}
            return out
        if entry.doc_type == "part":
            picks = selection.describe_picks(entry, self._picked())
            for key in ("faces", "edges", "vertices", "truncated"):
                if picks.get(key):
                    out[key] = picks[key]
            ids = win.browser.selected_feature_ids() if not win.in_assembly \
                else []
            feats = []
            for fid in ids:
                f = document.feature(fid)
                if f is not None:
                    feats.append({"id": fid, "name": f.name,
                                  "ref": f.name, "type": f.type_name})
            if feats:
                out["features"] = feats
        elif entry.doc_type == "assembly" and win.in_assembly:
            ids = []
            for oid in (win.viewport.selected_components()
                        + win.assembly_ui.browser.selected_occurrence_ids()):
                if oid not in ids:
                    ids.append(oid)
            occ = []
            for oid in ids:
                o = document.occurrence(oid)
                if o is not None:
                    occ.append({"id": oid, "name": o.label,
                                "path": getattr(o.ref, "path", "")})
            if occ:
                out["occurrences"] = occ
        return out

    def selection_state(self) -> Any:
        """A cheap value that changes when the selection does (the tracker
        compares it; nothing is resolved)."""
        win = self.window
        try:
            if win.on_start_page or win.session.active is None:
                return ("none",)
            key = win.session.active.key
            if win.editor.active:
                return (key, "sketch", getattr(win, "_sketch_feature_id", 0),
                        tuple(win.editor.selected_entities),
                        tuple(win.editor.selected_points),
                        tuple(win.editor.selected_dimensions))
            if win.in_assembly:
                return (key, "assembly",
                        tuple(win.viewport.selected_components()),
                        tuple(win.assembly_ui.browser
                              .selected_occurrence_ids()))
            if win.in_cam or win.in_drawing:
                return (key, "other")
            shapes = []
            for s in self._picked():
                try:
                    shapes.append(hash(s))
                except TypeError:
                    shapes.append(id(s))
            return (key, "part", tuple(shapes),
                    tuple(win.browser.selected_feature_ids()))
        except Exception:                                   # noqa: BLE001
            return ("error", time.monotonic())

    def selection_brief(self) -> Dict[str, Any]:
        """For ``status``: what is picked, counted, without references."""
        state = self.selection_state()
        out: Dict[str, Any] = {"version": self.tracker.selection_version}
        active = self.workspace.entries.get(self.workspace.active)
        out["doc"] = active.handle if active else None
        counts: Dict[str, int] = {}
        if len(state) >= 4 and state[1] == "part":
            shapes = self._picked()
            from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
            counts = {
                "faces": sum(1 for s in shapes
                             if s.ShapeType() == TopAbs_FACE),
                "edges": sum(1 for s in shapes
                             if s.ShapeType() == TopAbs_EDGE),
                "features": len(state[3])}
        elif len(state) >= 4 and state[1] == "assembly":
            counts = {"occurrences": len(set(state[2]) | set(state[3]))}
        elif len(state) >= 6 and state[1] == "sketch":
            counts = {"sketch_items": len(state[3]) + len(state[4])
                      + len(state[5])}
        counts = {k: v for k, v in counts.items() if v}
        out["counts"] = counts
        out["summary"] = (", ".join("%d %s" % (v, k.replace("_", " "))
                                    for k, v in counts.items())
                          if counts else "nothing selected")
        if counts:
            out["note"] = "get_selection() names them as references"
        return out

    def _op_new_document(self, type: str = "part", units: str = "mm",
                         name: str = "") -> Dict[str, Any]:
        if type not in ("part", "assembly"):
            raise BridgeError("NOT_YET", "new %s documents come in a later "
                              "phase; parts and assemblies are supported "
                              "now" % type)
        from ..core import units as ucore
        if type == "assembly":
            from ..core.assembly import AssemblyDocument
            document = AssemblyDocument()
        else:
            from ..core.document import Document
            document = Document()
        document.units = ucore.known(units)
        if name:
            document.properties["Title"] = name
        self.window._adopt(document, fileformat.ASSEMBLY
                           if type == "assembly" else fileformat.PART)
        self.workspace.sync()
        entry = self.workspace.entries[self.workspace.active]
        return {"doc": entry.handle, "revision": entry.revision,
                "units": ops._units(entry)}

    def _op_drawing_create(self, source: Any = "", size: str = "A3",
                           orientation: str = "landscape",
                           standard: str = "", template: str = "",
                           name: str = "", path: str = "",
                           overwrite: bool = False,
                           props: Any = None) -> Dict[str, Any]:
        """A new drawing in a tab of its own (a drawing's model is a file,
        so there is nothing here to be edited out from under the user)."""
        from ..bridge import drawing_ops
        document, info = drawing_ops.make_drawing(
            self.workspace, source, size, orientation, standard, template,
            name, path, overwrite, props)
        self.window._adopt(document, fileformat.DRAWING)
        self.workspace.sync()
        entry = self.workspace.entries[self.workspace.active]
        info.update({"doc": entry.handle, "revision": entry.revision,
                     "units": ops._units(entry)})
        info["summary"] = "drawing %s | %s %s | %s | rev %d" % (
            os.path.basename(document.path), document.active().size,
            document.active().orientation, document.standard,
            entry.revision)
        info["note"] = ("not written yet: save_document() keeps it at %s"
                        % document.path)
        return info

    def _op_open_document(self, path: str) -> Dict[str, Any]:
        path = ops._absolute(path, "open_document")
        held = self.workspace.by_path(path)
        if held is not None:
            return {"doc": held.handle, "revision": held.revision,
                    "already_open": True, "type": held.doc_type}
        if not os.path.exists(path):
            raise BridgeError("NOT_FOUND", "no such file: %s" % path)
        if not self.window.open_path(path):
            raise BridgeError("BAD_FILE", "the app could not open %s" % path,
                              ["It told the user why."])
        self.workspace.sync()
        entry = self.workspace.by_path(path)
        if entry is None:
            raise BridgeError("BAD_FILE", "%s did not open as a document"
                              % path)
        out = {"doc": entry.handle, "type": entry.doc_type,
               "revision": entry.revision, "units": ops._units(entry)}
        waiting = ops._waiting(entry)
        if waiting:
            out["waiting_for_trust"] = waiting
            out["note"] = ("its code features do not run until the user "
                           "allows them in the app (icLogic panel)")
        return out

    # what the window needs after a change ------------------------------------

    def _autosave_folder(self) -> str:
        return os.path.join(prefs.config_dir(), "agent-autosave")

    def _before_change(self, entry: Entry) -> None:
        opened = self.workspace.opened_of(entry)
        win = self.window
        if opened is not None and opened is win.session.active:
            if win.editor.active or win._active_dialog is not None:
                raise BridgeError(
                    "USER_BUSY", "the user is in the middle of a %s on %s"
                    % ("sketch" if win.editor.active else "feature dialog",
                       entry.handle),
                    ["Ask them to finish or cancel it, then try again."])
        document = entry.document
        if hasattr(document, "note_change"):
            # what the user did and nobody has noted yet is a step of its
            # own, not folded into the agent's
            document.note_change()
        self.last_autosave = self._autosave(entry)

    def _autosave_key(self, entry: Entry) -> str:
        """What names this document's copies, and no other's: its title,
        its handle, and which document it is (its file, or for one never
        saved this session). Handles like g1 come back every session, so
        a handle alone would let one document's copies prune another's."""
        document = entry.document
        stem = "".join(c if c.isalnum() or c in "-_" else "_"
                       for c in (getattr(document, "title", "")
                                 or "Untitled"))[:40]
        where = getattr(document, "path", "") or ""
        which = (os.path.normcase(os.path.abspath(where)) if where
                 else "unsaved:%s" % self._session)
        tag = hashlib.sha1(which.encode("utf-8")).hexdigest()[:8]
        return "%s-%s-%s" % (stem, entry.handle, tag)

    def _autosave(self, entry: Entry) -> str:
        """The document as it is, to the autosave folder. A failure is
        reported, not fatal: the undo stack still has the step."""
        document = entry.document
        folder = self._autosave_folder()
        try:
            os.makedirs(folder, exist_ok=True)
            key = self._autosave_key(entry)
            kind = getattr(document, "doc_type", fileformat.PART)
            ext = fileformat.extension_for(kind)
            path = os.path.join(folder, "%s-%s%s" % (
                key, time.strftime("%Y%m%d-%H%M%S"), ext))
            n = 1
            while os.path.exists(path):
                n += 1
                path = os.path.join(folder, "%s-%s-%d%s" % (
                    key, time.strftime("%Y%m%d-%H%M%S"), n, ext))
            from .. import APP_NAME, __version__
            fileformat.write(path, kind, document.to_dict(),
                             units=getattr(document, "units", "mm"),
                             created=getattr(document, "created", None),
                             application="%s %s" % (APP_NAME, __version__))
            # this document's copies only: the key, then the time
            ours = re.compile(re.escape(key) + r"-\d{8}-\d{6}(-\d+)?"
                              + re.escape(ext) + "$")
            mine = sorted((os.path.join(folder, n)
                           for n in os.listdir(folder) if ours.match(n)),
                          key=os.path.getmtime)
            for old in mine[:-KEEP_AUTOSAVES]:
                try:
                    os.remove(old)
                except OSError:
                    pass
            return path
        except Exception as exc:                        # noqa: BLE001
            return "FAILED: %s" % exc

    def _after_change(self, entry: Entry, had_body: bool) -> None:
        """Show the window what the ops did to a document, as its own undo
        and redo do: a rebuild of the active document, and the tab strip."""
        win = self.window
        document = entry.document
        opened = self.workspace.opened_of(entry)
        if opened is None:
            return
        if hasattr(document, "note_change"):
            # the ops left their undo step on the stack. What the rebuild
            # below writes to the document (the origin planes stepping
            # aside once there is a body) is not a change of its own to
            # undo: unsettled, it takes the state as it is, as after an
            # undo (Document.undo does the same)
            document._settled = None
        if opened is win.session.active and not win.on_start_page \
                and win.in_drawing and entry.doc_type == "drawing":
            win.drawing_ui.rebuild()
            opened.note_change()
            win.refresh_tabs()
        elif opened is win.session.active and not win.on_start_page \
                and (opened.is_part or win.in_assembly):
            win.rebuild()
            if not had_body and _has_body(entry):
                win.viewport.fit_all()
        else:
            opened.note_change()
            win.refresh_tabs()
        entry.source_mark = opened.revision
        win.status_message.setText("Agent changed %s" % entry.handle)


def _has_body(entry: Entry) -> bool:
    shape = getattr(entry.document, "shape", None)
    return shape is not None and not shape.IsNull()


def _signature(entry: Entry):
    """What shows that an op did something to a document, or reloaded it
    (a dry run loads the document again, which makes new feature objects
    the window's tree must be shown)."""
    return (entry.revision,
            tuple(id(f) for f in getattr(entry.document, "features", [])))
