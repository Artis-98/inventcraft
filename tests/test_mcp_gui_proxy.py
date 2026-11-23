"""The MCP server reaching the app: a real MCP client, the real server (a
subprocess), and the real window with its bridge on, in this process.

The client side runs in a thread; this thread turns the Qt event loop.

Checked: status says the app is connected; new documents go where --host
says (auto: the app; headless: a headless host; gui with the bridge off: an
error, no silent fallback); a build lands in the app as one undo step;
run_script on an app document runs in a headless host and arrives as data,
one undo step, and the app never runs it; a document open in the app is
edited there by its handle.
"""
import asyncio
import json
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402
from PySide6 import QtWidgets  # noqa: E402

from datum.core import prefs as core_prefs  # noqa: E402
from datum.ui.main_window import MainWindow  # noqa: E402
from datum.ui.theme import stylesheet  # noqa: E402

FAILS = []
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(stylesheet())
win = MainWindow()
win.resize(1100, 750)
win.show()
app.processEvents()
bridge = win.agent_bridge


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


MAIN = queue.Queue()          # what a client thread asks the Qt thread to do


def on_main(fn):
    """Run ``fn`` on the Qt thread, from the client's thread."""
    box = {}
    done = threading.Event()
    MAIN.put((fn, box, done))
    if not done.wait(30):
        raise TimeoutError("the Qt thread did not run it")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def pumped(fn, timeout=240):
    box = {}

    def work():
        try:
            box["r"] = fn()
        except BaseException as exc:                   # noqa: BLE001
            box["e"] = exc

    t = threading.Thread(target=work, daemon=True)
    t.start()
    end = time.monotonic() + timeout
    while t.is_alive() and time.monotonic() < end:
        app.processEvents()
        while not MAIN.empty():
            job, jbox, jdone = MAIN.get()
            try:
                jbox["r"] = job()
            except BaseException as exc:               # noqa: BLE001
                jbox["e"] = exc
            jdone.set()
        time.sleep(0.002)
    if t.is_alive():
        raise TimeoutError("scenario did not finish")
    if "e" in box:
        raise box["e"]
    return box["r"]


def texts(result):
    return [c.text for c in result.content if getattr(c, "type", "") == "text"]


def payload(result):
    for t in reversed(texts(result)):
        try:
            return json.loads(t)
        except ValueError:
            continue
    return {}


PLATE = [
    {"op": "parameter", "name": "w", "value": 100},
    {"op": "sketch", "id": "s1", "plane": "XY", "entities": [
        {"rect": {"center": [0, 0], "size": ["w", 60]}}]},
    {"op": "extrude", "id": "e1", "sketch": "$s1", "distance": 8},
]


def scenario(extra_args, body, handler=None):
    async def main():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "datum.mcp", "--code-ask", "no"] + extra_args,
            cwd=ROOT, env=dict(os.environ, PYTHONPATH=ROOT))
        async with stdio_client(params) as (read, write):
            async with ClientSession(
                    read, write, message_handler=handler) as session:
                await session.initialize()
                return await body(session)
    return pumped(lambda: asyncio.run(main()))


def scenario_raw(coro_fn):
    return pumped(lambda: asyncio.run(coro_fn()))


# ---------------------------------------------------------------- bridge off
print("the app's bridge is off")


async def when_off(s):
    st = payload(await s.call_tool("status", {}))
    r = await s.call_tool("new_document", {})
    return st, payload(r)


st, made = scenario([], when_off)
check("status says no app is connected",
      st["gui_host"]["connected"] is False, st.get("gui_host"))
check("auto then makes the document headless", made.get("doc") == "d1", made)


async def gui_only_off(s):
    r = await s.call_tool("new_document", {})
    return r.is_error, payload(r)


err, data = scenario(["--host", "gui"], gui_only_off)
check("--host gui does not fall back", err and
      data.get("kind") == "GUI_HOST_UNAVAILABLE", data)

# ---------------------------------------------------------------- bridge on
core_prefs.prefs().allow_agents = True
bridge.apply_preferences()
check("the bridge is on", bridge.listening, bridge.error)

state = {}


async def with_app(s):
    out = {}
    st = payload(await s.call_tool("status", {}))
    out["status"] = st
    r = await s.call_tool("new_document", {"name": "proxy plate"})
    out["new"] = payload(r)
    r = await s.call_tool("build", {"ops": PLATE})
    out["build"] = payload(r)
    out["build_error"] = r.is_error
    out["undo_after_build"] = None
    return out


out = scenario([], with_app)
check("status says the app is connected", out["status"]["gui_host"][
    "connected"] is True, out["status"].get("gui_host"))
check("auto makes the new document in the app", out["new"].get("doc") == "g1",
      out["new"])
check("a build with no doc goes to it", not out["build_error"]
      and "build ok" in out["build"].get("summary", ""), out["build"])
d = win.document
check("it is on the window's document, one undo step",
      len(d.features) == 2 and len(d._undo) == 1, (len(d.features),
                                                   len(d._undo)))


async def script_and_more(s):
    out = {}
    out["tree"] = payload(await s.call_tool("model_tree", {"doc": "g1"}))
    r = await s.call_tool("run_script", {"doc": "g1", "code": (
        "sk = sketch(plane='XY', entities=[{'circle': "
        "{'center': [0, 0], 'd': 10}}])\n"
        "extrude(sk, 5, operation='cut')\n"
        "print('ran in a child')")})
    out["script"] = payload(r)
    out["script_error"] = r.is_error
    out["status"] = payload(await s.call_tool("status", {}))
    return out


n0 = len(d._undo)
out = scenario([], script_and_more)
check("model_tree reads the app's document", out["tree"].get("doc") == "g1"
      and len(out["tree"]["features"]) == 2, out["tree"])
check("run_script on an app document works", not out["script_error"]
      and "run_script" in out["script"].get("summary", ""), out["script"])
check("its output came back", "ran in a child" in out["script"].get(
    "output", ""), out["script"])
check("and landed in the app as ONE undo step",
      len(d._undo) == n0 + 1 and len(d.features) > 2, (len(d._undo),
                                                      len(d.features)))
win._shortcut_actions["undo"].trigger()
app.processEvents()
check("Ctrl+Z takes the whole script's change back", len(d.features) == 2)
check("the status lists the app's document", any(
    x.get("doc") == "g1" and x.get("host") == "gui"
    for x in out["status"]["documents"]), out["status"]["documents"])


# ---------------------------------------------------------------- routing
print("one document, one host")
import tempfile  # noqa: E402

import datum.mcp.server as srv  # noqa: E402

def acall(fn, *args, **kwargs):
    """A tool that asks the client (roots, elicitation) is a coroutine
    taking the request context first; these tests have no client."""
    return asyncio.run(fn(None, *args, **kwargs))


WORK = tempfile.mkdtemp(prefix="datum_gui_proxy_")
os.environ["INVENTCRAFT_ALLOW_DIRS"] = WORK       # datum/mcp/safety.py
P1 = os.path.join(WORK, "shared.icpart")


def txt(result):
    """A tool's answer as a dict: its payload, or its error data."""
    if isinstance(result, dict):
        return result
    for t in reversed(texts(result)):
        try:
            return json.loads(t)
        except ValueError:
            continue
    return {"text": texts(result)}


def in_proc(fn):
    return pumped(fn)


srv.HOST_MODE = "headless"
h1 = in_proc(lambda: srv.new_document())
in_proc(lambda: acall(srv.build, ops=PLATE, doc=h1["doc"]))
saved = in_proc(lambda: acall(srv.save_document, doc=h1["doc"], path=P1))
check("a headless host made and saved a file", h1["doc"] == "d1"
      and os.path.exists(P1), (h1, saved))
srv.HOST_MODE = "auto"
n_tabs = len(win.session.documents)
opened = in_proc(lambda: acall(srv.open_document, P1))
check("with the app up, open_document opens it in the app",
      opened["doc"].startswith("g") and len(win.session.documents)
      == n_tabs + 1, opened)
gp = opened["doc"]
again = in_proc(lambda: acall(srv.open_document, P1))
check("opening it again returns the app's handle, no copy",
      again["doc"] == gp and again.get("already_open")
      and len(win.session.documents) == n_tabs + 1, again)
tree = in_proc(lambda: srv.model_tree(doc=P1))
check("a path as doc means the app's handle", txt(tree).get("doc") == gp, tree)
tree = in_proc(lambda: srv.model_tree(doc=P1.upper().replace(
    WORK.upper(), WORK)))
check("whatever the case of the path (Windows)",
      os.name != "nt" or txt(tree).get("doc") == gp, tree)

refused = in_proc(lambda: acall(srv.save_document, doc="d1"))
data = txt(refused)
check("a headless host will not save over a file the app has open",
      getattr(refused, "is_error", False)
      and data.get("kind") == "FILE_OPEN_IN_APP" and gp in data.get(
          "message", "") and data.get("hints"), data)
other = os.path.join(WORK, "elsewhere.icpart")
fine = in_proc(lambda: acall(srv.save_document, doc="d1", path=other))
check("another path is fine", txt(fine).get("path", "").endswith(
    "elsewhere.icpart"), fine)

# the user edits what the agent has read: the next change says what moved
gdoc = [e for e in win.session.documents if e.path and os.path.normcase(
    e.path) == os.path.normcase(P1)][0].document
in_proc(lambda: srv.model_tree(doc=gp))
gdoc.params.add("by_the_user", "9")
gdoc.modified = True
win.session.by_document(gdoc).note_change()
spin_until = time.monotonic() + 0.3
while time.monotonic() < spin_until:
    app.processEvents()
stale = in_proc(lambda: acall(srv.build, doc=gp, ops=[
    {"op": "parameter", "name": "q", "value": 1}]))
sd = txt(stale)
check("a change after the user's edit is refused, with a summary",
      getattr(stale, "is_error", False) and sd.get("kind") == "STALE_REVISION"
      and "by_the_user" in json.dumps(sd.get("changes", {})), sd)
again = in_proc(lambda: srv.model_tree(doc=gp))
ok = in_proc(lambda: acall(srv.build, doc=gp, ops=[
    {"op": "parameter", "name": "q", "value": 1}]))
check("after reading again it goes through", not getattr(
    ok, "is_error", False), ok)
in_proc(lambda: srv.host.stop())


# ---------------------------------------------------------------- selection
print("the selection, and being told about it")
from datum.core import kernel  # noqa: E402

updates = []


async def on_message(message):
    note = getattr(message, "root", message)
    if getattr(note, "method", "") == "notifications/resources/updated":
        updates.append((time.monotonic(), str(note.params.uri)))


def count(uri):
    return sum(1 for _t, u in updates if u == uri)


async def waited(pred, seconds=8.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return pred()


def edge_at(x, y, z):
    for e in kernel.edges(gdoc.shape):
        c = kernel.shape_centre(e)
        if abs(c[0] - x) < 1e-3 and abs(c[1] - y) < 1e-3                 and abs(c[2] - z) < 1e-3:
            return e
    raise AssertionError("no edge")


picks = []


async def selecting(s):
    out = {}
    await s.subscribe_resource("ic://selection")
    await s.subscribe_resource("ic://documents")
    await s.subscribe_resource("ic://doc/%s/tree" % gp)
    caps = s.server_capabilities
    out["subscribe_cap"] = bool(caps.resources and caps.resources.subscribe)
    await asyncio.sleep(1.2)              # the watcher takes its baseline
    out["quiet"] = len(updates)
    n_sel = count("ic://selection")

    def pick():
        picks[:] = [edge_at(50, 0, 8), edge_at(-50, 0, 8)]
        win.viewport.selected_shapes = lambda: list(picks)
    on_main(pick)
    out["heard"] = await waited(lambda: count("ic://selection") > n_sel)
    out["sel"] = payload(await s.call_tool("get_selection", {}))
    res = await s.read_resource("ic://selection")
    out["resource"] = json.loads(res.contents[0].text)
    out["status"] = payload(await s.call_tool("status", {}))
    vol0 = payload(await s.call_tool("inspect", {"doc": gp}))["volume"]
    edges = [e["ref"] for e in out["sel"].get("edges", [])]
    r = await s.call_tool("build", {"doc": gp, "ops": [
        {"op": "fillet", "radius": 2, "edges": edges}]})
    out["fillet"] = payload(r)
    out["fillet_error"] = r.is_error
    vol1 = payload(await s.call_tool("inspect", {"doc": gp}))["volume"]
    out["dvol"] = vol0 - vol1
    # the agent's own change is not told back to it as the user's
    n_tree = count("ic://doc/%s/tree" % gp)
    await asyncio.sleep(1.5)
    out["own_edit_silent"] = count("ic://doc/%s/tree" % gp) == n_tree
    # a burst of clicks is one notification
    n_sel = count("ic://selection")

    def burst():
        for i in range(10):
            picks[:] = [edge_at(0, 30, 8)] if i % 2 == 0 else []
            for _ in range(3):
                app.processEvents()
                time.sleep(0.01)
        picks[:] = []
    on_main(burst)
    await asyncio.sleep(2.0)
    out["burst"] = count("ic://selection") - n_sel
    # the user edits the tree
    n_tree = count("ic://doc/%s/tree" % gp)

    def user_edit():
        gdoc.params.add("by_hand_2", "4")
        gdoc.modified = True
        win.rebuild()
    on_main(user_edit)
    out["tree_heard"] = await waited(
        lambda: count("ic://doc/%s/tree" % gp) > n_tree)
    n_docs = count("ic://documents")
    r = await s.call_tool("build", {"doc": gp, "ops": [
        {"op": "parameter", "name": "stale_try", "value": 1}]})
    out["after_user_edit"] = payload(r)       # refused: it has not read
    out["stale_error"] = r.is_error
    await s.call_tool("model_tree", {"doc": gp})
    r = await s.call_tool("build", {"doc": gp, "ops": [
        {"op": "parameter", "name": "stale_try", "value": 1}]})
    out["after_reading"] = r.is_error
    on_main(lambda: win.agent_bridge.execute("new_document", {}))
    out["docs_heard"] = await waited(
        lambda: count("ic://documents") > n_docs)
    return out


out = scenario([], selecting, on_message)
check("the server advertises resource subscriptions", out["subscribe_cap"])
check("nothing is announced while nothing happens", out["quiet"] == 0,
      updates)
check("picking in the app sends notifications/resources/updated",
      out["heard"], updates)
sel = out["sel"]
check("get_selection gives the two edges by role", len(sel.get("edges", []))
      == 2 and all(e["via"] == "role" and e["count"] == 1
                   for e in sel["edges"]), sel)
check("ic://selection says the same", out["resource"].get("edges")
      == sel.get("edges") and out["resource"]["doc"] == gp)
check("and status carries it", out["status"].get("selection", {}).get(
    "counts") == {"edges": 2}, out["status"].get("selection"))
check("a fillet on the selected refs builds", not out["fillet_error"]
      and "fillet" in json.dumps(out["fillet"]).lower(), out["fillet"])
want = 2 * (1 - 3.14159265 / 4) * 4 * 60
check("and rounds exactly those edges", abs(out["dvol"] - want) < 6,
      (out["dvol"], want))
check("the agent is not told about its own change", out["own_edit_silent"])
check("a burst of clicks is at most two notifications", out["burst"] <= 2,
      out["burst"])
check("a tree edit by the user is announced", out["tree_heard"], updates)
check("the agent's next change is refused, saying what the user did",
      out["stale_error"] and out["after_user_edit"].get("kind")
      == "STALE_REVISION" and "by_hand_2" in json.dumps(
          out["after_user_edit"].get("changes")), out["after_user_edit"])
check("and goes through once it has read the document again",
      out["after_reading"] is False)
check("a document opening is announced", out["docs_heard"], updates)
del win.viewport.selected_shapes


print("the same, on a subscriptions/listen stream (2026-07-28 clients)")
from mcp import Client  # noqa: E402
from mcp.client.subscriptions import ResourceUpdated  # noqa: E402


async def listening():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "datum.mcp"], cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=ROOT))
    out = {}
    async with Client(params) as client:
        out["version"] = client.protocol_version
        async with client.listen(
                resource_subscriptions=["ic://selection"]) as sub:
            await asyncio.sleep(1.2)

            def pick():
                picks[:] = [edge_at(0, 30, 8)]
                win.viewport.selected_shapes = lambda: list(picks)
            on_main(pick)

            async def first():
                async for event in sub:
                    if isinstance(event, ResourceUpdated):
                        return event.uri
            try:
                out["uri"] = await asyncio.wait_for(first(), 8)
            except asyncio.TimeoutError:
                out["uri"] = None
    return out


heard = scenario_raw(listening)
check("a listen stream is told the selection changed (modern era)",
      heard["uri"] == "ic://selection", heard)
del win.viewport.selected_shapes

async def headless_flag(s):
    r = await s.call_tool("new_document", {})
    return payload(r)


made = scenario(["--host", "headless"], headless_flag)
check("--host headless makes it headless even with the app there",
      made.get("doc") == "d1", made)

core_prefs.prefs().allow_agents = False
bridge.apply_preferences()
bridge.shutdown()

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all gui proxy tests passed")
sys.exit(0)
