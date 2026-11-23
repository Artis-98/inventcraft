"""What the MCP server lets an agent run, and who may reach it.

--code safe|full|off decides how agent code runs in a headless host
(bridge/codepolicy.py), and an HTTP server that other machines can reach
needs a token (mcp/server.py).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.bridge import codepolicy  # noqa: E402
from datum.bridge.host import InProcessHost  # noqa: E402
from datum.core import rules as core_rules  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


BLOCK = [
    {"op": "parameter", "name": "w", "value": "100"},
    {"op": "sketch", "name": "Base", "plane": "XY",
     "entities": [{"rect": {"center": [0, 0], "size": ["w", 40]}}]},
    {"op": "extrude", "name": "Block", "sketch": "Base", "distance": 20},
]
PLAIN = "body = box(5, 5, 5).move(0, 0, 20)"
# a dunder, which safe mode refuses and code features otherwise allow
# (they never get import at all: see rules.run_code)
REACHES_OUT = "h = (5).__add__(0)\nbody = box(h, 5, 5).move(0, 0, 20)"


def code_op(name, source):
    return {"op": "code", "name": name, "operation": "join",
            "source": source}




async def through_a_client():
    """The server asks the user in their client (MCP elicitation)."""
    import json
    import tempfile
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.types import ElicitResult
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = tempfile.mkdtemp(prefix="ic-ask-")
    env = dict(os.environ, PYTHONPATH=root, DATUM_CONFIG_DIR=cfg)
    for key in (codepolicy.ENV, codepolicy.ASK_ENV, codepolicy.SESSION_ENV,
                codepolicy.ALLOWED_ENV):
        env.pop(key, None)
    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "datum.mcp"], cwd=root,
                                   env=env)

    def data(result):
        for c in reversed(result.content):
            try:
                return json.loads(c.text)
            except (AttributeError, ValueError):
                continue
        return {}

    asked = []

    def answer(allow, session=False):
        async def fn(_ctx, p):
            asked.append(p.message)
            if allow is None:
                return ElicitResult(action="decline")
            return ElicitResult(action="accept", content={
                "allow": allow, "for_session": session})
        return fn

    async def run(callback, steps):
        kw = {"elicitation_callback": callback} if callback else {}
        async with stdio_client(params) as (rd, wr):
            async with ClientSession(rd, wr, **kw) as s:
                await s.initialize()
                await s.call_tool("new_document", {})
                await s.call_tool("build", {"ops": BLOCK})
                return [await s.call_tool(name, args)
                        for name, args in steps]

    # yes, once
    del asked[:]
    r, = await run(answer(True), [("build", {"ops": [code_op("Cap", PLAIN)],
                                             "detail": True})])
    d = data(r)
    check("client: the user is shown the source and asked",
          len(asked) == 1 and PLAIN in asked[0], asked)
    check("client: allowed, the code feature runs in the same answer",
          not r.is_error and "Cap" not in d.get("waiting_for_trust", [])
          and any("allowed by the user" in n for n in d.get("notes", [])),
          d.get("notes"))
    check("client: the source is not echoed back in the answer",
          "code_to_allow" not in d, list(d))

    # no
    del asked[:]
    r, = await run(answer(False), [("build", {"ops": [code_op("Cap", PLAIN)],
                                              "detail": True})])
    d = data(r)
    check("client: declined, the feature waits for trust",
          not r.is_error and "Cap" in d.get("waiting_for_trust", [])
          and any("did not allow" in n for n in d.get("notes", [])),
          d.get("notes"))

    # a client that cannot ask
    r1, r2 = await run(None, [
        ("build", {"ops": [code_op("Cap", PLAIN)], "detail": True}),
        ("run_script", {"code": "param('w', 120)"})])
    d = data(r1)
    check("client cannot ask: the code feature waits for trust",
          "Cap" in d.get("waiting_for_trust", [])
          and any("cannot ask" in n for n in d.get("notes", [])),
          d.get("notes"))
    check("client cannot ask: run_script is refused",
          r2.is_error and data(r2).get("kind") == "CODE_NOT_ALLOWED",
          data(r2))

    # a script, declined; then allowed for the session
    del asked[:]
    r, = await run(answer(None), [("run_script",
                                   {"code": "param('w', 120)"})])
    check("client: a declined script does not run",
          r.is_error and data(r).get("kind") == "USER_DECLINED", data(r))
    del asked[:]
    r1, r2 = await run(answer(True, session=True), [
        ("run_script", {"code": "param('w', 120)"}),
        ("build", {"ops": [code_op("Cap", PLAIN)], "detail": True})])
    check("client: an allowed script runs",
          not r1.is_error and any("agent code ran" in n
                                  for n in data(r1).get("notes", [])),
          data(r1))
    check("client: allowed for the session, the next code is not asked about",
          len(asked) == 1 and not r2.is_error
          and "Cap" not in data(r2).get("waiting_for_trust", []),
          (len(asked), data(r2).get("notes")))


def host_with_block():
    h = InProcessHost()
    h.call("new_document")
    r = h.call("build", {"ops": BLOCK})
    assert r["ok"], r
    return h


print("--code safe, the default")
os.environ.pop(codepolicy.ENV, None)
check("safe is the default", codepolicy.mode() == "safe")
core_rules._TRUSTED_CODE.clear()
h = host_with_block()
r = h.call("build", {"ops": [code_op("Cap", PLAIN)]})
check("plain code builds", r["ok"], r.get("error"))
check("and the answer says agent code will run, checked in safe mode",
      any("agent code will run, checked in safe mode" in n
          for n in r.get("notes", [])), r.get("notes"))
r = h.call("build", {"ops": [code_op("Reach", REACHES_OUT)]})
check("code using a dunder is refused before it is trusted",
      not r["ok"] and r["error"]["kind"] == "SAFE_MODE", r.get("error"))
check("and the refusal says how to allow it",
      "--code full" in " ".join(r["error"].get("hints", [])),
      r.get("error"))
check("the refused source was not trusted",
      not core_rules.code_trusted(REACHES_OUT))

print("--code full")
codepolicy.set_mode("full")
core_rules._TRUSTED_CODE.clear()
h = host_with_block()
r = h.call("build", {"ops": [code_op("Reach", REACHES_OUT)]})
check("code safe mode would refuse builds", r["ok"], r.get("error"))
check("without saying safe mode",
      not any("safe mode" in n for n in r.get("notes", [])), r.get("notes"))

print("--code off")
codepolicy.set_mode("off")
core_rules._TRUSTED_CODE.clear()
h = host_with_block()
r = h.call("build", {"ops": [code_op("Cap", PLAIN)]})
check("a code feature lands but waits for trust",
      r["ok"] and "Cap" in r.get("waiting_for_trust", []), r.get("summary"))
check("and the answer says code is off",
      any("--code off" in n for n in r.get("notes", [])), r.get("notes"))
check("nothing was trusted", not core_rules.code_trusted(PLAIN))

print("asking first, in the host")
codepolicy.set_mode("safe")
codepolicy.set_asks(True)
core_rules._TRUSTED_CODE.clear()
h = host_with_block()
r0 = r = h.call("build", {"ops": [code_op("Cap", PLAIN)]})
asked = r.get("code_to_allow") or []
check("a code feature nobody allowed lands, waiting for trust",
      r["ok"] and "Cap" in r.get("waiting_for_trust", []), r.get("summary"))
check("and the answer lists it for the server to ask about, with its source",
      [a["feature"] for a in asked] == ["Cap"] and asked[0]["source"] == PLAIN,
      asked)
check("it was not trusted", not core_rules.code_trusted(PLAIN))
r = h.call("build", {"ops": [code_op("Cap2", PLAIN)], "dry_run": True})
check("a dry run asks about nothing", not r.get("code_to_allow"), r)
r = h.call("code_allow", {"hashes": [asked[0]["hash"]], "doc": asked[0]["doc"],
                          "before": r0["after"]})
check("allowed by hash, the part is rebuilt and nothing waits",
      r["ok"] and not r.get("waiting_for_trust") and r.get("after"), r)
check("and that exact source is trusted", core_rules.code_trusted(PLAIN))
r = h.call("build", {"ops": [code_op("Again", PLAIN)]})
check("the same source again is not asked about",
      r["ok"] and not r.get("code_to_allow"), r.get("code_to_allow"))
r = h.call("build", {"ops": [code_op("Other", PLAIN + "\n")]})
check("one character changed and it is asked about again",
      [a["feature"] for a in r.get("code_to_allow") or []] == ["Other"],
      r.get("code_to_allow"))
r = h.call("code_allow", {"session": True})
check("allowed for the session, asking is off", not codepolicy.asks())
r = h.call("build", {"ops": [code_op("Free", PLAIN + "  \n")]})
check("and new code runs without asking",
      r["ok"] and not r.get("code_to_allow")
      and "Free" not in r.get("waiting_for_trust", []), r)

print("allowed for the session, under --code full")
codepolicy.set_mode("full")
core_rules._TRUSTED_CODE.clear()
h = host_with_block()
h.call("code_allow", {"session": True})
check("session safe mode is the default", codepolicy.unseen_runs_safe())
r = h.call("build", {"ops": [code_op("Reach", REACHES_OUT)]})
check("unseen code that safe mode refuses does not run, even with full",
      not r["ok"] and r["error"]["kind"] == "SAFE_MODE", r.get("error"))
check("and the refusal says why",
      "for this session" in " ".join(r["error"].get("hints", [])),
      r.get("error"))
r = h.call("build", {"ops": [code_op("Cap", PLAIN)]})
check("plain unseen code runs, checked in safe mode",
      r["ok"] and any("allowed for the session, not by itself" in n
                      for n in r.get("notes", [])), r.get("notes"))
core_rules.trust_code_hashes([core_rules.code_hash(REACHES_OUT)])
r = h.call("build", {"ops": [code_op("Seen", REACHES_OUT)]})
check("a source the user allowed by itself runs without safe mode",
      r["ok"], r.get("error"))
core_rules._TRUSTED_CODE.clear()
with codepolicy.allowing():
    r = h.call("build", {"ops": [code_op("Read", REACHES_OUT)]})
check("so does code from a script the user read as a whole",
      r["ok"], r.get("error"))
check("and session safe mode is back after it", codepolicy.unseen_runs_safe())
core_rules._TRUSTED_CODE.clear()
h.call("code_allow", {"session": True, "session_safe": False})
check("the user can untick session safe mode",
      not codepolicy.unseen_runs_safe())
r = h.call("build", {"ops": [code_op("Free2", REACHES_OUT)]})
check("then unseen code runs as --code full says", r["ok"], r.get("error"))
os.environ.pop(codepolicy.SESSION_ENV, None)
codepolicy.set_mode("safe")

codepolicy.set_asks(True)
with codepolicy.allowing():
    check("a call the user allowed as a whole does not ask",
          not codepolicy.asks())
check("and asking is back after it", codepolicy.asks())
codepolicy.set_asks(False)
os.environ.pop(codepolicy.ASK_ENV, None)
check("a host used straight from Python does not ask",
      not codepolicy.asks())

print("bad values")
try:
    codepolicy.set_mode("sometimes")
    check("an unknown mode is refused", False)
except ValueError:
    check("an unknown mode is refused", True)
os.environ[codepolicy.ENV] = "sometimes"
check("an unknown value in the environment reads as safe",
      codepolicy.mode() == "safe")
os.environ.pop(codepolicy.ENV, None)

print("the server's side")
try:
    from datum.mcp import server
except ImportError as exc:        # the mcp SDK is an optional dependency
    print("  SKIP  the mcp SDK is not installed: %s" % exc)
    server = None

if server is not None:
    codepolicy.set_mode("safe")
    refused, safe = server._code_policy(False)
    check("run_script under --code safe always runs in safe mode",
          refused is None and safe is True)
    codepolicy.set_mode("full")
    refused, safe = server._code_policy(False)
    check("under --code full the agent may turn safe mode off",
          refused is None and safe is False)
    codepolicy.set_mode("off")
    refused, _ = server._code_policy(True)
    check("under --code off run_script is refused",
          refused is not None and refused.is_error)
    codepolicy.set_mode("safe")
    os.environ.pop(codepolicy.ENV, None)

    result = {"ok": True}
    server._note_code(result, True)
    check("a script's answer says it ran, and in safe mode",
          result["notes"] == ["agent code ran in a separate process, "
                              "in safe mode"], result)

    for host, local in (("127.0.0.1", True), ("localhost", True),
                        ("::1", True), ("[::1]", True), ("0.0.0.0", False),
                        ("192.168.1.20", False), ("my-pc", False)):
        check("%s is %s" % (host, "this machine" if local else "reachable"),
              server._loopback(host) is local)

    saved = os.environ.pop("INVENTCRAFT_MCP_TOKEN", None)
    try:
        server.main(["--transport", "streamable-http", "--bind", "0.0.0.0"])
        check("--bind 0.0.0.0 without a token refuses to start", False)
    except SystemExit as exc:
        check("--bind 0.0.0.0 without a token refuses to start",
              exc.code == 2)
    if saved is not None:
        os.environ["INVENTCRAFT_MCP_TOKEN"] = saved

    def ask(app, headers):
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "method": "POST", "path": "/mcp",
                 "headers": headers}
        asyncio.run(app(scope, receive, send))
        return sent

    reached = []

    async def inner(scope, receive, send):
        reached.append(scope["path"])

    guarded = server._BearerToken(inner, "s3cret")
    sent = ask(guarded, [])
    check("no token: 401, and the server is not reached",
          sent and sent[0]["status"] == 401 and not reached, sent)
    sent = ask(guarded, [(b"authorization", b"Bearer wrong")])
    check("a wrong token: 401", sent and sent[0]["status"] == 401
          and not reached, sent)
    ask(guarded, [(b"authorization", b"Bearer s3cret")])
    check("the right token reaches the server", reached == ["/mcp"], reached)
    check("no token configured: the app is served as it is",
          server._http_app("127.0.0.1", "").__class__.__name__
          != "_BearerToken")

    print("asking the user, through a client")
    asyncio.run(through_a_client())

print()
if FAILS:
    print("%d FAILURE(S): %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
