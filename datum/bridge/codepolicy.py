"""Whether code an agent writes may run in a headless host, and how.

Code is one of the most useful things an agent can write: a hole table, a
computed pattern, a family of parts a dialog cannot express. It is also
the one thing that runs with the user's privileges, so the server decides
how much of it to allow, and the host it starts reads that here.

``safe`` (the default)
    Scripts and code features are checked against the safe-mode allowlist
    (``safemode.py``) before they run: math-like imports only, no file
    access, no ``eval``/``exec``, no dunder tricks. ``run_script`` also runs
    with safe-mode builtins.
``full``
    No allowlist. For a user who reads what the agent writes, or trusts it.
``off``
    No agent code at all: ``run_script`` and ``build_project`` code refuse,
    and a code feature waits for trust, as code that came in a file does.

In the running app the person is asked about each code feature's source
(``ui/agent_bridge.py``), so this applies to the headless host, where the
server asks them through their client instead (see "asking first" below).
Code that came in with a file is never trusted by any of these: it waits
for the user in every mode.
"""

from __future__ import annotations

import os

ENV = "INVENTCRAFT_CODE"
MODES = ("safe", "full", "off")
DEFAULT = "safe"


def mode() -> str:
    """The mode the server was started with (``--code``)."""
    value = os.environ.get(ENV, DEFAULT).strip().lower()
    return value if value in MODES else DEFAULT


def set_mode(value: str) -> str:
    """Set it for this process and every host it starts from now on."""
    value = (value or DEFAULT).strip().lower()
    if value not in MODES:
        raise ValueError("--code must be one of %s" % ", ".join(MODES))
    os.environ[ENV] = value
    return value


# ------------------------------------------------------------ asking first
#
# Started by the server, a headless host asks before agent code runs: the
# server shows the user the source through their client (MCP elicitation)
# and they allow it, once for that exact source (its hash, as the app
# does) or for the rest of the session. Until then a code feature waits
# for trust, as code that came in a file does, and the host lists it in
# the answer (``code_to_allow``) for the server to ask about. A host used
# straight from Python, as the tests do, does not ask.

ASK_ENV = "INVENTCRAFT_CODE_ASK"

# code features this call could not run because nobody has allowed them
# yet: {"feature", "hash", "source", "doc"}; cleared by ops.call
pending: list = []


def asks() -> bool:
    """Whether agent code waits for the user to allow it."""
    return os.environ.get(ASK_ENV, "0") == "1"


def set_asks(on: bool) -> bool:
    """For this process and every host it starts from now on."""
    os.environ[ASK_ENV] = "1" if on else "0"
    return bool(on)


class allowing:
    """While a call the user allowed as a whole runs (a script they read,
    a project whose code they read), the code features it makes from that
    code run without asking again, in this host and the hosts it starts."""

    def __init__(self, on: bool = True) -> None:
        self.on = bool(on)
        self.was = None

    def __enter__(self) -> "allowing":
        if self.on:
            self.was = os.environ.get(ASK_ENV)
            os.environ[ASK_ENV] = "0"
        return self

    def __exit__(self, *exc) -> None:
        if self.on:
            if self.was is None:
                os.environ.pop(ASK_ENV, None)
            else:
                os.environ[ASK_ENV] = self.was
