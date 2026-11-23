"""The app as an MCP host: the bridge inside the window (phase 3a).

The window is built in this process, the bridge is switched on through the
preferences, and a real client talks to it over the real named pipe from a
thread while this one turns the Qt event loop (what the app does all day).

What is checked, in the order of the plan's section 10:

* it is off by default, and fails closed: a wrong secret, a request before
  pairing, a wrong MAC and a replayed nonce are all refused and none of
  them runs;
* a build through it is ONE undo step, and the window's own Ctrl+Z puts
  the document back; edits, properties and requirements likewise;
* an autosave is made before each change;
* Stop drops what is queued and ends the running build (rolled back);
* run_script is refused in the app, and a code op asks the user, once;
* an agent never changes a document under a sketch or dialog the user
  has open on it; a user's own edit moves the revision.
"""
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401  every modal answers itself

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from datum.bridge import pairing  # noqa: E402
from datum.bridge.client import RemoteError  # noqa: E402
from datum.bridge.gui_client import GuiClient, GuiUnavailable, _Pipe  # noqa: E402
from datum.core import prefs as core_prefs  # noqa: E402
from datum.core import rules  # noqa: E402
from datum.core.document import Document  # noqa: E402
from datum.core.features import PrimitiveFeature  # noqa: E402
from datum.ui import agent_bridge  # noqa: E402
from datum.ui.main_window import MainWindow  # noqa: E402
from datum.ui.theme import stylesheet  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_gui_host_")
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1200, 800)
win.show()
app.processEvents()
bridge = win.agent_bridge


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def pumped(fn, *args, timeout=120, **kwargs):
    """Run ``fn`` in a thread (a client blocks on the pipe) while this
    thread turns the event loop, as the running app does."""
    box = {}

    def work():
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:                   # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    end = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.002)
    if thread.is_alive():
        raise TimeoutError("the call did not finish")
    if "error" in box:
        raise box["error"]
    return box["result"]


def spin(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.002)


def rpc(client, method, **params):
    return pumped(client.call, method, params)


def kind_of(client, method, **params):
    try:
        rpc(client, method, **params)
    except RemoteError as exc:
        return exc.data.get("kind")
    return None


PLATE = [
    {"op": "parameter", "name": "w", "value": 100},
    {"op": "parameter", "name": "h", "value": 60},
    {"op": "parameter", "name": "t", "value": 8},
    {"op": "sketch", "id": "s1", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": ["w", "h"]}},
        {"circle": {"center": [0, 0], "d": 20}}]},
    {"op": "extrude", "id": "e1", "sketch": "$s1", "distance": "t"},
    {"op": "fillet", "radius": 5, "edges": {"along": "z"}},
]


def ctrl_z():
    """What pressing Ctrl+Z does: the window's own action for it."""
    action = win._shortcut_actions["undo"]
    assert action.shortcut().toString() == "Ctrl+Z", action.shortcut()
    action.trigger()
    app.processEvents()


# ============================================================ off by default
print("off by default")
check("the preference is off", core_prefs.prefs().allow_agents is False)
check("nothing is listening", not bridge.listening)
check("there is no pairing file", not os.path.exists(pairing.pairing_path()))
probe = GuiClient().probe()
check("a client finds nobody", probe["connected"] is False, probe)
check("and the badge is hidden", not bridge.badge.isVisible())

# ============================================================ switching on
print("turning it on")
core_prefs.prefs().allow_agents = True
bridge.apply_preferences()
check("it listens", bridge.listening, bridge.error)
check("a secret exists", len(bridge.secret) == 64)
data = pairing.read_pairing()
check("the pairing file holds it and the pipe",
      data["secret"] == bridge.secret and data["pipe"] == pairing.pipe_name())
check("and is cut down to the user", data.get("restricted") is True, data)
check("the badge shows agents are allowed",
      bridge.badge.isVisible() and "allowed" in bridge.badge.label.text(),
      bridge.badge.label.text())
check("with no Stop button yet", not bridge.badge.stop_button.isVisible())

# ============================================================ fails closed
print("pairing is required")
before_docs = len(win.session.documents)


def raw():
    return _Pipe(data["pipe"])


def read_json(pipe, timeout=5):
    line = pipe.line(timeout)
    return json.loads(line.decode("utf-8")) if line else None


def attempt(secret, nonce_ok=True):
    """Pair by hand with ``secret``; the answer to auth."""
    pipe = raw()
    hello = read_json(pipe)
    client_nonce = pairing.new_nonce()
    pipe.send((json.dumps({"id": 1, "method": "auth", "params": {
        "client_nonce": client_nonce,
        "proof": pairing.client_proof(secret, hello["nonce"],
                                      client_nonce)}}) + "\n").encode())
    answer = read_json(pipe)
    return pipe, hello, client_nonce, answer


pipe, _h, _c, answer = pumped(attempt, "ab" * 32)
check("a wrong secret is refused", answer and
      answer["error"]["data"]["kind"] == "AUTH_FAILED", answer)
closed = False
try:
    pumped(pipe.line, 3)
except OSError:
    closed = True
check("and the connection is closed on it", closed or pumped(
    pipe.line, 1) is None)


def unpaired_request():
    pipe = raw()
    read_json(pipe)
    pipe.send(b'{"id": 1, "method": "new_document", "params": {}}\n')
    return read_json(pipe)


answer = pumped(unpaired_request)
check("a request before pairing is refused",
      answer and answer["error"]["data"]["kind"] == "AUTH_FAILED", answer)
check("and was not run", len(win.session.documents) == before_docs)


def bad_mac_and_replay():
    pipe, hello, cnonce, answer = attempt(data["secret"])
    ok = answer and answer.get("result", {}).get("host") == "gui"
    proved = pairing.same(answer["result"]["server_proof"],
                          pairing.server_proof(data["secret"], hello["nonce"],
                                               cnonce))
    params = {}
    nonce = pairing.new_nonce()
    pipe.send((json.dumps({"id": 2, "method": "new_document",
                           "params": params, "nonce": nonce,
                           "mac": "00" * 32}) + "\n").encode())
    wrong = read_json(pipe)
    pipe2, hello2, cnonce2, _a = attempt(data["secret"])
    good = {"id": 2, "method": "status", "params": {}, "nonce": nonce,
            "mac": pairing.request_mac(data["secret"], hello2["nonce"],
                                       cnonce2, 2, nonce, "status", {})}
    pipe2.send((json.dumps(good) + "\n").encode())
    first = read_json(pipe2)
    pipe2.send((json.dumps(good) + "\n").encode())
    second = read_json(pipe2)
    return ok, proved, wrong, first, second


ok, proved, wrong, first, second = pumped(bad_mac_and_replay)
check("the right secret pairs", ok)
check("and the app proves it holds the secret too", proved)
check("a wrong MAC is refused",
      wrong and wrong["error"]["data"]["kind"] == "AUTH_FAILED", wrong)
check("and was not run", len(win.session.documents) == before_docs)
check("a good request is answered", first and "result" in first, first)
check("the same request again (a replay) is refused",
      second and second["error"]["data"]["kind"] == "REPLAY", second)

client = GuiClient()
st = rpc(client, "status")
check("a paired client gets the app's status",
      st["host"] == "gui" and st["pid"] == os.getpid(), st)
check("through the client's own pairing", client.info.get("host") == "gui")

# ============================================================ a build is one undo
print("a build is one undo step")
made = rpc(client, "new_document", units="mm", name="agent plate")
doc = made["doc"]
check("a new document opens in the app as g1", doc == "g1", made)
check("as a tab the user can see", len(win.session.documents) == 1
      and win.session.active.document is win.document)
d = win.document
check("it starts with nothing to undo", len(d._undo) == 0, len(d._undo))
r = rpc(client, "build", doc=doc, ops=PLATE)
check("a plate builds through the bridge", r["ok"], r.get("error"))
check("on the window's own document", len(d.features) == 3
      and d.shape is not None and not d.shape.IsNull())
check("one build is exactly one undo step", len(d._undo) == 1, len(d._undo))
check("the answer says where the autosave went", os.path.exists(
    (r.get("autosave") or "").replace("FAILED: ", "?")), r.get("autosave"))
rev1 = r["revision"]
win_vol_ok = abs(r["after"]["volume"] - (100 * 60 * 8 - 3.14159265 * 100 * 8
                 - (4 - 3.14159265) * 25 * 8)) < 400
check("with the volume the ops report", win_vol_ok, r["after"]["volume"])

ctrl_z()
check("Ctrl+Z takes the whole build back", len(d.features) == 0
      and len(d._undo) == 0 and not d.params.names(),
      (len(d.features), len(d._undo)))
win._shortcut_actions["redo"].trigger()
app.processEvents()
check("and Ctrl+Y does it again", len(d.features) == 3)
ctrl_z()
check("undone again", len(d.features) == 0)

# a second, different change: each its own step
r = rpc(client, "build", doc=doc, ops=PLATE)
rev = r["revision"]
names = {f["type"]: f["name"] for f in
         rpc(client, "model_tree", doc=doc)["features"]}
r2 = rpc(client, "edit_feature", doc=doc, feature=names["fillet"],
         params={"radius": 3})
check("an edit_feature is one step", r2["ok"] and len(d._undo) == 2,
      (r2.get("error"), len(d._undo)))
fillet = [f for f in d.features if f.type_name.lower().startswith("fillet")][0]
check("and changed the fillet", str(fillet.radius) == "3", fillet.radius)
ctrl_z()
fillet = [f for f in d.features if f.type_name.lower().startswith("fillet")][0]
check("Ctrl+Z puts the radius back, keeps the plate",
      str(fillet.radius) == "5" and len(d.features) == 3, fillet.radius)
r3 = rpc(client, "properties", doc=doc, parameters={"w": 120})
check("properties is one step", len(d._undo) == 2, len(d._undo))
ctrl_z()
check("and Ctrl+Z puts the parameter back",
      d.params["w"].expression == "100", d.params["w"].expression)
rpc(client, "requirements", doc=doc, set=[
    {"name": "thin", "metric": "bbox", "axis": "z", "max": 20}])
check("requirements is one step", len(d._undo) == 2, len(d._undo))
ctrl_z()
check("undone", len(d.requirements) == 0)
r = rpc(client, "build", doc=doc, dry_run=True, ops=[
    {"op": "fillet", "radius": 1, "edges": {"along": "x"}}])
check("a dry run changes nothing and adds no step",
      r["dry_run"] and len(d._undo) == 1, len(d._undo))
check("and the window's tree still lists the real features",
      all(f in d.features for f in win.document.features))

# ============================================================ autosave
print("autosave")
folder = os.path.join(core_prefs.config_dir(), "agent-autosave")
saved = sorted(os.listdir(folder), key=lambda n: os.path.getmtime(
    os.path.join(folder, n))) if os.path.isdir(folder) else []
check("copies were written before changes", len(saved) >= 3, saved)
latest = os.path.join(folder, saved[-1])
copy = Document.load(latest)
check("and can be opened again", copy is not None)
count_before = len(copy.features)
rpc(client, "build", doc=doc, ops=[
    {"op": "parameter", "name": "extra", "value": 1}])
newest = sorted(os.listdir(folder), key=lambda n: os.path.getmtime(
    os.path.join(folder, n)))[-1]
check("the copy is of the document BEFORE the change",
      "extra" not in Document.load(os.path.join(folder, newest)).params.names()
      and count_before == len(Document.load(
          os.path.join(folder, newest)).features))
# copies with the same handle from another document (an earlier session's
# g1) are not this document's to prune, however old
strangers = []
for n in range(8):
    p = os.path.join(folder, "Other-%s-0badc0de-2020010%d-000000.icpart"
                     % (doc, n % 9))
    with open(p, "w") as f:
        f.write("{}")
    os.utime(p, (1, 1))
    strangers.append(p)
for n in range(7):
    rpc(client, "build", doc=doc, ops=[
        {"op": "parameter", "name": "prune%d" % n, "value": n}])
check("pruning keeps to this document's own copies",
      all(os.path.exists(p) for p in strangers),
      [os.path.basename(p) for p in strangers if not os.path.exists(p)])
mine = [n for n in os.listdir(folder) if ("-%s-" % doc) in n and n not in
        {os.path.basename(p) for p in strangers}]
check("and keeps the last five of them", len(mine) == 5, mine)
for p in strangers:
    os.remove(p)
for n in range(7):
    ctrl_z()
ctrl_z()

# ============================================================ Stop
print("Stop")
check("the Stop button is not shown while idle",
      not bridge.badge.stop_button.isVisible())
client2 = GuiClient()
rpc(client2, "status")


def hold_pump():
    real = bridge.pump
    bridge.pump = lambda: None
    return real


real_pump = hold_pump()
big = PLATE + [{"op": "parameter", "name": "p%d" % i, "value": i}
               for i in range(1, 6)]
results = {}


def slow(c, key, method, **p):
    try:
        results[key] = c.call(method, p)
    except Exception as exc:                           # noqa: BLE001
        results[key] = exc


t1 = threading.Thread(target=slow, args=(client, "a", "build"),
                      kwargs={"doc": doc, "ops": big}, daemon=True)
t2 = threading.Thread(target=slow, args=(client2, "b", "status"), daemon=True)
t1.start()
t2.start()
end = time.monotonic() + 20
while len(bridge.queue) < 2 and time.monotonic() < end:
    app.processEvents()
    time.sleep(0.002)
check("two requests are waiting in the queue", len(bridge.queue) == 2,
      len(bridge.queue))
check("the badge says an agent is working, with Stop",
      bridge.badge.stop_button.isVisible()
      and "working" in bridge.badge.label.text(), bridge.badge.label.text())

calls = {"n": 0}
real_cancel = agent_bridge.GuiWorkspace.should_cancel


def pressing_stop(self):
    calls["n"] += 1
    if calls["n"] == 3:           # two ops are done; the user presses Stop
        bridge.badge.stop_button.click()
    return real_cancel(self)


agent_bridge.GuiWorkspace.should_cancel = pressing_stop
undo_before = len(d._undo)
features_before = len(d.features)
bridge.pump = real_pump
real_pump()
end = time.monotonic() + 20
while len(results) < 2 and time.monotonic() < end:
    app.processEvents()
    time.sleep(0.002)
agent_bridge.GuiWorkspace.should_cancel = real_cancel
t1.join(5)
t2.join(5)
check("the running build was ended by Stop", isinstance(results.get("a"),
      dict) and results["a"]["ok"] is False
      and results["a"]["error"]["kind"] == "CANCELLED", results.get("a"))
check("and rolled back", results["a"].get("rolled_back") is True
      and len(d.features) == features_before
      and len(d._undo) == undo_before, (len(d.features), len(d._undo)))
check("the queued request was cancelled too, not run late",
      isinstance(results.get("b"), RemoteError)
      and results["b"].data["kind"] == "CANCELLED", results.get("b"))
check("the badge is quiet again", not bridge.badge.stop_button.isVisible()
      and bridge.current is None and not bridge.queue)

# input is ignored while a request runs, except for Stop
blocker = bridge.blocker
blocker.active = True
press = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress,
                          QtCore.QPointF(5, 5), QtCore.QPointF(5, 5),
                          QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                          QtCore.Qt.NoModifier)
check("while a request runs a click on the model is ignored",
      blocker.blocks(win.viewport, press))
check("but a click on Stop is heard",
      not blocker.blocks(bridge.badge.stop_button, press))
check("and the window cannot be closed under it",
      blocker.blocks(win, QtGui.QCloseEvent()))
blocker.active = False
check("when nothing runs, nothing is blocked",
      not blocker.blocks(win.viewport, press))

# a client that goes away has its queued request dropped, not run late
gone = GuiClient()
rpc(gone, "status")
real_pump = hold_pump()
undo_before = len(d._undo)
thread = threading.Thread(target=slow, args=(gone, "c", "build"),
                          kwargs={"doc": doc, "ops": [
                              {"op": "parameter", "name": "late",
                               "value": 1}]}, daemon=True)
thread.start()
end = time.monotonic() + 10
while not bridge.queue and time.monotonic() < end:
    app.processEvents()
    time.sleep(0.002)
gone._pipe.close()
spin(0.3)
bridge.pump = real_pump
real_pump()
spin(0.2)
check("a request whose client has gone never runs",
      "late" not in d.params.names() and len(d._undo) == undo_before)

# ============================================================ no agent code
print("no agent code in the app")
check("run_script is refused", kind_of(client, "run_script", doc=doc,
                                       code="x = 1") == "NOT_IN_GUI_HOST")
check("so is the script's own host op", kind_of(
    client, "script_exec", data={}, code="x=1") == "NOT_IN_GUI_HOST")
check("so is planning one", kind_of(
    client, "script_plan", data={}, code="x=1") == "NOT_IN_GUI_HOST")
check("the user's documents are theirs to close",
      kind_of(client, "close_document", doc=doc) == "NOT_IN_GUI_HOST")
check("and the document is still open", len(win.session.documents) == 1)

# a plan (build ops as data) is applied like any build: one undo step
n0 = len(d._undo)
prep = rpc(client, "script_prepare", doc=doc)
check("script_prepare gives the document as data",
      prep["data"]["features"] and prep["revision"] >= 1)
plan = {"ops": [{"op": "parameter", "name": "viaplan", "value": 7}],
        "origin": {}, "notes": [], "output": "hello", "sketch_names": {}}
r = rpc(client, "script_apply", doc=doc, plan=plan)
check("a plan is applied as ops", r["ok"] and r["output"] == "hello", r)
check("as one undo step", len(d._undo) == n0 + 1)
ctrl_z()
check("that Ctrl+Z takes back", "viaplan" not in d.params.names())

print("a code op asks the user, once")
asked = []


def answering(value):
    def ask(parent, name, source):
        asked.append((name, source))
        return value
    return ask


real_ask = agent_bridge.ask_code
CODE = {"op": "code", "name": "Posts", "operation": "new",
        "source": "body = box(10, 10, 10)"}
agent_bridge.ask_code = answering(False)
r = rpc(client, "build", doc=doc, ops=[CODE])
check("the user was shown the source", len(asked) == 1
      and asked[0][1] == CODE["source"], asked)
check("a No leaves the feature waiting for trust, the build intact",
      r["ok"] and not rules.code_trusted(CODE["source"])
      and r.get("waiting_for_trust") == ["Posts"], r.get("waiting_for_trust"))
ctrl_z()
rpc(client, "build", doc=doc, ops=[dict(CODE, name="Posts2")])
check("the same source is not asked about again", len(asked) == 1, asked)
ctrl_z()
agent_bridge.ask_code = answering(True)
other = dict(CODE, source="body = box(20, 10, 10)", name="Posts3")
r = rpc(client, "build", doc=doc, ops=[other])
check("a Yes lets exactly that source run",
      r["ok"] and rules.code_trusted(other["source"])
      and not r.get("waiting_for_trust") and len(asked) == 2, asked)
n = len(asked)
rpc(client, "build", doc=doc, ops=[dict(other, name="Posts4")])
check("and it is asked once", len(asked) == n)
agent_bridge.ask_code = real_ask
ctrl_z()
ctrl_z()

# ============================================================ the user wins
print("the user is not worked under")
win._active_dialog = object()
n = len(d._undo)
try:
    rpc(client, "build", doc=doc, ops=[
        {"op": "parameter", "name": "x", "value": 1}])
    busy = None
except RemoteError as exc:
    busy = exc.data.get("kind")
win._active_dialog = None
check("a feature dialog open: the agent is told USER_BUSY", busy == "USER_BUSY",
      busy)
check("and the document is as it was", "x" not in d.params.names()
      and len(d._undo) == n)

seen = rpc(client, "model_tree", doc=doc)["revision"]
d.params.add("by_hand", "3")
d.modified = True
win.rebuild()
now = rpc(client, "model_tree", doc=doc)["revision"]
check("an edit the user makes moves the revision", now > seen, (seen, now))
check("so an agent that has not read it is refused", kind_of(
    client, "build", doc=doc, expected_revision=seen, ops=[
        {"op": "parameter", "name": "z", "value": 1}]) == "STALE_REVISION")
try:
    rpc(client, "build", doc=doc, expected_revision=seen, ops=[
        {"op": "parameter", "name": "z", "value": 1}])
    stale = {}
except RemoteError as exc:
    stale = exc.data
changes = stale.get("changes") or {}
check("and told what the user changed: the parameter", "by_hand" in (
    changes.get("parameters") or {}).get("added", {}), changes)
check("in the message too", "by_hand" in stale.get("message", "")
      or "parameter" in stale.get("message", ""), stale.get("message"))
d.features[0].name = "Renamed By User"
d.modified = True
win.rebuild()
try:
    rpc(client, "build", doc=doc, expected_revision=seen, ops=[
        {"op": "parameter", "name": "z", "value": 1}])
    stale = {}
except RemoteError as exc:
    stale = exc.data
changes = stale.get("changes") or {}
check("an edited feature is listed by name", any(
    "Renamed By User" == e["name"] for e in changes.get("edited", [])),
    changes)
check("and a revision no longer kept says so rather than guess",
      rpc(client, "model_tree", doc=doc)["revision"] > seen)

# ============================================================ opening files
print("opening files")
disk = Document()
box = PrimitiveFeature()
box.kind, box.a, box.b, box.c, box.operation = "box", "30", "20", "10", "new"
disk.add_feature(box)
disk.rebuild()
path = os.path.join(WORK, "on_disk.icpart")
disk.save(path)
op = rpc(client, "open_document", path=path)
check("a file opens as a tab of its own", op["doc"] == "g2"
      and op["type"] == "part" and len(win.session.documents) == 2, op)
again = rpc(client, "open_document", path=path)
check("and opening it again finds it", again.get("already_open")
      and again["doc"] == "g2")
check("the app can say which handle holds a file",
      rpc(client, "find_open", path=path)["doc"] == "g2")
st = rpc(client, "status")
check("status lists both documents as the app's",
      [x["doc"] for x in st["documents"]] == ["g1", "g2"], st["documents"])
r = rpc(client, "build", doc="g2", ops=[
    {"op": "fillet", "radius": 1, "edges": {"along": "z"}}])
check("a document that is not the active tab is changed too",
      r["ok"] and win.session.by_path(path).document.features[-1].type_name
      .lower().startswith("fillet"), r.get("error"))
other_doc = win.session.by_path(path).document
check("with its own undo step", len(other_doc._undo) == 1)

# ============================================================ assemblies
print("an assembly in the app")
made = rpc(client, "new_document", type="assembly", name="agent stand")
adoc = made["doc"]
check("an assembly opens in the app as a tab", adoc == "g3"
      and rpc(client, "model_tree", doc=adoc)["type"] == "assembly", made)
asm = win.session.active.document
check("the window shows it as an assembly", win.in_assembly
      and win.assembly is asm)
r = rpc(client, "place_component", doc=adoc, file=path, name="Block")
check("a part is placed from its file, grounded", r["occurrence"]["grounded"]
      and "autosave" in r and len(asm._undo) == 1, r.get("occurrence"))
check("the window drew it", len(asm.occurrences) == 1
      and asm.occurrences[0].shape is not None)
r = rpc(client, "place_component", doc=adoc, file=path, name="Block")
r = rpc(client, "constrain", doc=adoc, kind="flush",
        a="Block:1/origin.XY", b="Block:2/origin.XY")
check("a constraint is one undo step", r["dof"]["Block:2"] == 3
      and len(asm._undo) == 3, (r.get("dof"), len(asm._undo)))
r = rpc(client, "constrain", doc=adoc, kind="flush", offset=50,
        a="Block:1/origin.XZ", b="Block:2/origin.XZ")
check("so is the next", len(asm._undo) == 4 and len(asm.constraints) == 2)
ctrl_z()
check("Ctrl+Z in the app takes one constraint back, whole",
      len(asm.constraints) == 1 and asm.occurrences[0].shape is not None,
      len(asm.constraints))
chk = rpc(client, "assembly_check", doc=adoc, interference=False)
check("assembly_check reads the app's document", chk["components"] == 2
      and chk["constraints"] == 1 and chk["dof"] == 3, chk["summary"])
check("a conflict is refused in the app and nothing is added",
      kind_of(client, "constrain", doc=adoc, kind="flush", offset=9,
              a="Block:1/origin.XY", b="Block:2/origin.XY")
      == "CONSTRAINT_FAILED" and len(asm.constraints) == 1
      and len(asm._undo) == 3)
b = rpc(client, "bom", doc=adoc)
check("bom counts the part twice", b["flat"][0]["qty"] == 2, b["flat"])

# ============================================================ phase 4b
print("model states, a drawing and branches in the app")
made = rpc(client, "new_document", name="bolt")
bolt_doc = made["doc"]
rpc(client, "build", doc=bolt_doc, ops=[
    {"op": "parameter", "name": "len", "value": 30},
    {"op": "parameter", "name": "dia", "value": 6},
    {"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"circle": {"center": [0, 0], "d": "dia"}}]},
    {"op": "extrude", "id": "e", "sketch": "$s", "distance": "len",
     "name": "Shank"}])
bolt_path = os.path.join(WORK, "ABolt.icpart")
rpc(client, "save_document", doc=bolt_doc, path=bolt_path)
bolt = win.session.by_path(bolt_path).document
steps = len(bolt._undo)
r = rpc(client, "model_states", doc=bolt_doc, action="create",
        name="M6x40", parameters={"len": "40"})
check("a model state is one undo step in the app",
      len(bolt._undo) == steps + 1 and r["active"] == "Primary"
      and "M6x40" in bolt.model_states, r["summary"])
r = rpc(client, "model_states", doc=bolt_doc, action="activate",
        name="M6x40")
check("activating one makes the app's part that state",
      abs(rpc(client, "inspect", doc=bolt_doc)["bbox"][2] - 40) < 1e-6
      and bolt.model_states.active == "M6x40", r["summary"])
ctrl_z()
check("Ctrl+Z takes the activation back: Primary again",
      bolt.model_states.active == "Primary"
      and abs(rpc(client, "inspect", doc=bolt_doc)["bbox"][2] - 30) < 1e-6,
      bolt.model_states.active)
check("the tree names the states", rpc(client, "model_tree", doc=bolt_doc)[
    "model_states"]["names"] == ["Primary", "M6x40"])

# a drawing, in a tab of its own
n_docs = len(win.session.documents)
r = rpc(client, "drawing_create", source=bolt_path, size="A4")
dwg_doc = r["doc"]
check("a drawing opens as a tab, and the window shows it",
      len(win.session.documents) == n_docs + 1 and win.in_drawing
      and r["path"].endswith("ABolt.icdraw"), r["summary"])
drawing = win.drawing
steps = len(drawing._undo)
r = rpc(client, "drawing_base_view", doc=dwg_doc, orientation="front")
check("a base view is one undo step in the app, and is drawn",
      len(drawing._undo) == steps + 1
      and drawing.sheets[0].views[0].projection is not None
      and "autosave" in r, r["summary"])
r = rpc(client, "drawing_projected_view", doc=dwg_doc, parent="View1",
        shows="top")
r = rpc(client, "drawing_dimension", doc=dwg_doc, view="View1",
        kind="overall")
check("views and dimensions land on the app's sheet",
      len(drawing.sheets[0].views) == 2
      and len(drawing.sheets[0].annotations) == 2, r["summary"])
ctrl_z()
check("Ctrl+Z takes the last change (the dimensions) back, whole",
      len(drawing.sheets[0].annotations) == 0
      and len(drawing.sheets[0].views) == 2)
check("a section that misses is refused in the app, nothing changes",
      kind_of(client, "drawing_section_view", doc=dwg_doc, parent="View1",
              cut={"direction": "vertical", "at": 900}) == "VIEW_FAILED"
      and len(drawing.sheets[0].views) == 2)
img = rpc(client, "drawing_render", doc=dwg_doc, width=700)
check("drawing_render draws the app's sheet", img["width"] == 700
      and len(img["png_base64"]) > 5000)
pdf = os.path.join(WORK, "ABolt.pdf")
r = rpc(client, "drawing_export", doc=dwg_doc, path=pdf)
check("drawing_export writes a PDF from the app",
      open(pdf, "rb").read(5) == b"%PDF-", r)
check("and does not overwrite it", kind_of(
    client, "drawing_export", doc=dwg_doc, path=pdf) == "WOULD_OVERWRITE")
sv = rpc(client, "save_document", doc=dwg_doc)
check("the drawing saves from the app", os.path.exists(sv["path"])
      and not drawing.modified, sv)

# branches: switching is one undo step, and refused over unsaved work
check("a branch of a document with unsaved work is refused",
      kind_of(client, "branch", doc=bolt_doc, action="create",
              name="longer") == "UNSAVED_CHANGES")
rpc(client, "save_document", doc=bolt_doc)
r = rpc(client, "branch", doc=bolt_doc, action="create", name="longer")
check("a branch is made from the app's saved part",
      r["branch"] == "longer", r)
rpc(client, "properties", doc=bolt_doc, parameters={"len": 45})
check("switching over unsaved work is refused in the app",
      kind_of(client, "branch", doc=bolt_doc, action="switch",
              name="main") == "UNSAVED_CHANGES")
r = rpc(client, "branch", doc=bolt_doc, action="check_in",
        message="45 mm")
check("check_in saves the app's file and keeps a version",
      r["checked_in"] and not bolt.modified, r.get("summary"))
steps = len(bolt._undo)
r = rpc(client, "branch", doc=bolt_doc, action="switch", name="main")
check("switching branch is one undo step, and rebuilds the part",
      len(bolt._undo) == steps + 1
      and abs(rpc(client, "inspect", doc=bolt_doc)["bbox"][2] - 30) < 1e-6,
      r["summary"])

# ============================================================ the selection
print("what the user has selected")
made = rpc(client, "new_document", name="pick me")
sel_doc = made["doc"]
rpc(client, "build", doc=sel_doc, ops=[
    {"op": "parameter", "name": "w", "value": 100},
    {"op": "parameter", "name": "t", "value": 8},
    {"op": "sketch", "id": "s1", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": ["w", 60]}, "id": "r"},
        {"circle": {"center": [0, 0], "d": 20}}]},
    {"op": "extrude", "id": "e1", "sketch": "$s1", "distance": "t"}])
sd = win.session.by_document(win.document).document
check("the new tab is the one shown", sd is win.document)
sel0 = rpc(client, "get_selection")
check("with nothing selected it says so", sel0["empty"] is True
      and sel0["doc"] == sel_doc, sel0)

from datum.core import kernel as _kernel  # noqa: E402


def edge_at(x, y, z, shape):
    for e in _kernel.edges(shape):
        c = _kernel.shape_centre(e)
        if abs(c[0] - x) < 1e-3 and abs(c[1] - y) < 1e-3 \
                and abs(c[2] - z) < 1e-3:
            return e
    raise AssertionError("no edge at %s" % [(x, y, z)])


def face_at(x, y, z, shape):
    for f in _kernel.faces(shape):
        c = _kernel.shape_centre(f)
        if abs(c[0] - x) < 1e-3 and abs(c[1] - y) < 1e-3 \
                and abs(c[2] - z) < 1e-3:
            return f
    raise AssertionError("no face at %s" % [(x, y, z)])


body = sd.shape
picks = [edge_at(50, 0, 8, body), edge_at(-50, 0, 8, body),
         face_at(0, 0, 8, body)]
win.viewport.selected_shapes = lambda: list(picks)
sel = rpc(client, "get_selection")
check("two edges and a face are reported", len(sel.get("edges", [])) == 2
      and len(sel.get("faces", [])) == 1, sel)
check("edges by the faces they lie between, found by role",
      all(e["via"] == "role" and ".edge(" in e["ref"] and e["count"] == 1
          for e in sel["edges"]), sel["edges"])
check("the face by what made it", sel["faces"][0]["ref"].endswith(".end")
      and sel["faces"][0]["via"] == "role", sel["faces"])
check("each also has a handle", all(x["handle"].startswith("@")
      for x in sel["edges"] + sel["faces"]))
check("the summary says what is picked", "2 edges" in sel["summary"]
      and "1 face" in sel["summary"], sel["summary"])
check("it is for the document shown", sel["doc"] == sel_doc
      and sel["mode"] == "part")
st = rpc(client, "status")
check("status carries the selection too", st["selection"]["counts"] == {
    "faces": 1, "edges": 2}, st.get("selection"))
check("a document that is not shown has none", rpc(
    client, "get_selection", doc="g1")["empty"] is True)

vol0 = rpc(client, "inspect", doc=sel_doc)["volume"]
n_undo = len(sd._undo)
edges = [e["ref"] for e in sel["edges"]]
r = rpc(client, "build", doc=sel_doc, ops=[
    {"op": "fillet", "radius": 2, "edges": edges}])
check("fillet the selected edges: it builds", r["ok"], r.get("error"))
vol1 = rpc(client, "inspect", doc=sel_doc)["volume"]
want = 2 * (1 - 3.14159265 / 4) * 4 * 60
check("and rounded exactly those two edges", abs((vol0 - vol1) - want) < 6,
      (vol0 - vol1, want))
check("as one undo step", len(sd._undo) == n_undo + 1)
ctrl_z()
check("that Ctrl+Z takes back", len(sd.features) == 2, len(sd.features))

print("a widened part: the same edges, by role")
rpc(client, "properties", doc=sel_doc, parameters={"w": 140})
body = sd.shape
picks[:] = [edge_at(70, 0, 8, body)]
sel2 = rpc(client, "get_selection")
check("a pick on the changed part is named by role again",
      sel2["edges"][0]["via"] == "role", sel2["edges"])
ctrl_z()

print("while sketching")
del picks[:]


class _Sk:
    entities = {4: type("E", (), {"kind": "line"})()}
    constraints = {}


win.editor.sketch = _Sk()
win.editor.selected_entities = [4]
win.editor.selected_points = []
win.editor.selected_dimensions = []
sk = rpc(client, "get_selection")
check("sketch entities are named", sk["mode"] == "sketch"
      and sk["sketch"]["entities"][0]["ref"] == "#e4", sk)
win.editor.sketch = None
win.editor.selected_entities = []

print("what the app tells the server, without being asked")
del picks[:]
spin(0.6)
p0 = rpc(client, "poll")
check("a poll is answered at once, outside the queue",
      {"selection", "documents", "docs", "agent_busy"} <= set(p0), p0)
real_pump = hold_pump()
held = rpc(client, "poll")
bridge.pump = real_pump
check("even while requests are held back", held["selection"]
      == p0["selection"] and not bridge.badge.stop_button.isVisible())
for n in range(6):                  # a burst of clicks
    picks[:] = [face_at(0, 0, 8, sd.shape)] if n % 2 == 0 else []
    spin(0.03)
picks[:] = [face_at(0, 0, 0, sd.shape)]
spin(0.7)
p1 = rpc(client, "poll")
check("a burst of picks is one change", p1["selection"] == p0["selection"] + 1,
      (p0["selection"], p1["selection"]))
spin(0.5)
check("and nothing else moved", rpc(client, "poll")["selection"]
      == p1["selection"])
sd.params.add("typed_by_user", "5")
sd.modified = True
win.rebuild()
spin(0.6)
p2 = rpc(client, "poll")
check("a tree edit by the user moves its revision",
      p2["docs"][sel_doc] > p1["docs"][sel_doc], (p1["docs"], p2["docs"]))
check("but the agent's own changes are told as such: not busy",
      p2["agent_busy"] is False)
n_docs = p2["documents"]
rpc(client, "new_document", name="another")
spin(0.6)
check("a document opening moves the documents version",
      rpc(client, "poll")["documents"] == n_docs + 1)
del win.viewport.selected_shapes

# ============================================================ saving
sv = rpc(client, "save_document", doc="g2")
check("an agent can save a document where it came from",
      sv["path"] == path and not other_doc.modified, sv)
check("but not over another file without being told",
      kind_of(client, "save_document", doc="g1", path=path)
      == "WOULD_OVERWRITE")

# ============================================================ explore
print("evaluate and optimise in the app")
made = rpc(client, "new_document", units="mm", name="explore plate")
xdoc = made["doc"]
rpc(client, "build", doc=xdoc, ops=[
    {"op": "parameter", "name": "w", "value": 100},
    {"op": "parameter", "name": "t", "value": 8},
    {"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": ["w", 50]}, "id": "r"},
        {"circle": {"center": [0, 0], "d": 10}, "id": "c"}]},
    {"op": "extrude", "sketch": "$s", "distance": "t", "name": "Plate"}])
rpc(client, "requirements", doc=xdoc, set=[
    {"name": "edge", "metric": "clearance", "a": "Plate.side(c)",
     "b": "Plate.side(r.right)", "min": 20}])
xd = win.document
xrev = rpc(client, "model_tree", doc=xdoc)["revision"]
xundo = len(xd._undo)
xjson = json.dumps(xd.to_dict(), sort_keys=True)
told = []
ev = pumped(client.call, "evaluate", {"doc": xdoc, "variations": [
    {"t": 4}, {"t": 6}, {"w": 30}]},
    progress=lambda d, t, m: told.append((d, t)))
check("evaluate runs in the app on the window's own workers",
      ev["evaluated"] == 4 and "evaluate ok" in ev["summary"]
      and not ev["cancelled"], ev["summary"])
check("with progress sent back as it goes",
      told and told[-1] == (4, 4), told)
check("without changing the document: no revision, no undo step",
      rpc(client, "model_tree", doc=xdoc)["revision"] == xrev
      and len(xd._undo) == xundo
      and json.dumps(xd.to_dict(), sort_keys=True) == xjson)
check("and no autosave was made for a read",
      "autosave" not in ev)
op = rpc(client, "optimise", doc=xdoc, vary={"t": [2, 12], "w": [30, 140]},
         budget=10)
check("optimise searches in the app and applies nothing", op["feasible"]
      and not op["applied"] and len(xd._undo) == xundo
      and json.dumps(xd.to_dict(), sort_keys=True) == xjson, op["summary"])
op = rpc(client, "optimise", doc=xdoc, vary={"t": [2, 12], "w": [30, 140]},
         budget=10, apply=True, expected_revision=xrev)
check("apply is ONE undo step in the app", op["applied"]
      and len(xd._undo) == xundo + 1
      and abs(float(xd.params["w"].value) - op["best"]["vary"]["w"]) < 1e-6,
      (op.get("summary"), len(xd._undo), xundo))
ctrl_z()
check("and Ctrl+Z takes the whole optimisation back",
      float(xd.params["w"].value) == 100.0
      and float(xd.params["t"].value) == 8.0 and len(xd._undo) == xundo)
# Stop from the badge, between variants
calls["n"] = 0
stopped_at = {"n": 0}
real_cancel2 = agent_bridge.GuiWorkspace.should_cancel


def pressing_stop2(self):
    stopped_at["n"] += 1
    if stopped_at["n"] == 6:
        bridge.badge.stop_button.click()
    return real_cancel2(self)


agent_bridge.GuiWorkspace.should_cancel = pressing_stop2
big = pumped(client.call, "evaluate", {"doc": xdoc, "grid": {
    "t": [2 + i * 0.25 for i in range(30)]}, "baseline": False})
agent_bridge.GuiWorkspace.should_cancel = real_cancel2
check("Stop in the app ends an evaluate between variants",
      big["cancelled"] and sum(1 for r in big["rows"] if r.get("ok")) < 30
      and "cancelled" in big["summary"], big["summary"])
check("and the badge is quiet again", not bridge.badge.stop_button.isVisible()
      and bridge.current is None)

# ============================================================ import to a tree
print("a STEP back into a tree in the app")
src = rpc(client, "new_document", units="mm", name="step source")
rpc(client, "build", doc=src["doc"], ops=[
    {"op": "sketch", "id": "s", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": [80, 50]}, "id": "r"}]},
    {"op": "extrude", "sketch": "$s", "distance": 8, "name": "Plate"},
    {"op": "fillet", "radius": 5, "edges": {"along": "z"}},
    {"op": "sketch", "id": "h", "plane": "XY", "entities": [
        {"point": [-20, 0], "id": "p"}]},
    {"op": "hole", "sketch": "$h", "diameter": 7, "points": ["p"],
     "through": True},
    {"op": "pattern", "parents": ["Hole"], "count1": 3, "spacing1": 20,
     "dir1": "X"}])
stp = os.path.join(WORK, "imported.step")
rpc(client, "export", doc=src["doc"], path=stp)
made = rpc(client, "new_document", units="mm", name="dumb solid")
idoc = made["doc"]
rpc(client, "build", doc=idoc, ops=[
    {"op": "import", "path": stp.replace("\\", "/")}])
imp = win.document
inames = [f.name for f in imp.features]
irev = rpc(client, "model_tree", doc=idoc)["revision"]
iundo = len(imp._undo)
ijson = json.dumps(imp.to_dict(), sort_keys=True)
rc = rpc(client, "recognize", doc=idoc)
check("recognize reads the import in the app", rc["prismatic"]
      and rc["coverage"]["faces"]["share"] == 1.0
      and any(f["type"] == "hole" and f["count"] == 3
              for f in rc["features"]), rc["summary"])
check("and changes nothing: no revision, no undo step",
      rpc(client, "model_tree", doc=idoc)["revision"] == irev
      and len(imp._undo) == iundo
      and json.dumps(imp.to_dict(), sort_keys=True) == ijson)
dry = rpc(client, "parametrize", doc=idoc, dry_run=True)
check("a dry run changes nothing either", "dry run ok" in dry["summary"]
      and len(imp._undo) == iundo and [f.name for f in imp.features]
      == inames, dry["summary"])
pz = rpc(client, "parametrize", doc=idoc, expected_revision=irev)
check("parametrize replaces the import in the app",
      "parametrize ok" in pz["summary"] and "Imported Body" not in
      [f.name for f in imp.features] and len(imp.features) > 3
      and "hole_d" in imp.params.names(), pz["summary"])
check("as ONE undo step", len(imp._undo) == iundo + 1,
      (len(imp._undo), iundo))
check("with the volume of the import",
      abs(pz["after"]["volume"] - rc["check"]["volume_original"]) < 0.5,
      (pz["after"], rc["check"]))
ctrl_z()
check("and Ctrl+Z gives the dumb solid back whole",
      [f.name for f in imp.features] == inames
      and json.dumps(imp.to_dict(), sort_keys=True) == ijson)

# ============================================================ switching off
print("turning it off")
secret = bridge.secret
core_prefs.prefs().allow_agents = False
bridge.apply_preferences()
check("it stops listening", not bridge.listening)
check("the pairing file is gone", not os.path.exists(pairing.pairing_path()))
down = GuiClient().probe()
check("and nobody can reach it", down["connected"] is False, down)
try:
    pumped(client.call, "status", {})
    answered = True
except GuiUnavailable:
    answered = False
check("a connected client is cut off", not answered)
core_prefs.prefs().allow_agents = True
bridge.apply_preferences()
check("turned on again it has a new secret",
      bridge.listening and bridge.secret != secret)
core_prefs.prefs().allow_agents = False
bridge.apply_preferences()
bridge.shutdown()

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all gui host tests passed")
sys.exit(0)
