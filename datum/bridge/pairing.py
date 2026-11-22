"""Pairing: how the app and an agent's server prove they are the same user's.

The app's bridge (``ui/agent_bridge.py``) is off until the user turns it on.
Turning it on makes a fresh secret and writes it, with the name of the
pipe, to a file in the user's own configuration folder (``bridge.json``).
The user can read the file; nobody else can: on Windows its access list is
cut down to the current user with ``icacls``, elsewhere it is mode 0600.
Turning the bridge off, or closing the app, deletes it. DPAPI was
considered and left out on purpose: the file is meant to be readable by the
person it belongs to, and another process running as that same user is
inside the same trust boundary either way (the pyRevit server's
``pairing.py`` says the same of its DPAPI blob).

The secret never crosses the pipe. Each connection is a challenge and a
proof, in both directions:

    app    -> challenge   a random server nonce
    client -> auth        HMAC(secret, "client|" server_nonce "|" client_nonce)
    app    -> proof       HMAC(secret, "server|" server_nonce "|" client_nonce)

so the app knows the client holds the secret and the client knows it is
talking to the app that wrote it. Every request after that carries a
nonce that is used once and a MAC over (both nonces, the request id, the
nonce, the method and the canonical parameters); a replayed or altered
request is refused, and anything that does not check out is refused
without being run: the bridge fails closed.

This module has no Qt and no OpenCASCADE: the server that talks to the app
loads it too.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
from typing import Any, Dict, Optional

FILE_NAME = "bridge.json"
PROTOCOL = 1
# the longest line either side will read: a build of a few hundred ops is
# tens of kilobytes, a whole document a few megabytes
MAX_LINE = 16 * 1024 * 1024


class PairingError(RuntimeError):
    """No pairing to be had: the file is missing, unreadable or odd."""


# ---------------------------------------------------------------- the file


def config_dir() -> str:
    from ..core import prefs
    return prefs.config_dir()


def pairing_path() -> str:
    return os.path.join(config_dir(), FILE_NAME)


def pipe_name() -> str:
    """The pipe's name: one per user and configuration folder, so a test
    run, which has a folder of its own, never meets the real app's."""
    who = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    tag = hashlib.sha1(("%s|%s" % (who, os.path.normcase(
        os.path.abspath(config_dir())))).encode("utf-8")).hexdigest()[:12]
    return "inventcraft-bridge-%s" % tag


def new_secret() -> str:
    return secrets.token_hex(32)


def _restrict(path: str) -> bool:
    """Leave the file to its owner. Returns whether it worked, which the
    status says; the file's folder is the user's own anyway."""
    if sys.platform == "win32":
        user = os.environ.get("USERNAME")
        if not user:
            return False
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            done = subprocess.run(
                ["icacls", path, "/inheritance:r", "/grant:r",
                 "%s:(F)" % user],
                capture_output=True, timeout=20, creationflags=flags)
            return done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


def write_pairing(secret: str, extra: Optional[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
    """Make the file for this run of the bridge; its contents."""
    path = pairing_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"protocol": PROTOCOL, "pipe": pipe_name(), "secret": secret,
            "pid": os.getpid(), "created": time.time()}
    data.update(extra or {})
    # created empty and restricted first, so the secret is never in a file
    # others could read, not even for a moment
    temp = path + ".%d.tmp" % os.getpid()
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)
    data["restricted"] = _restrict(temp)
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1)
        handle.write("\n")
    os.replace(temp, path)
    return data


def remove_pairing(pid: Optional[int] = None) -> None:
    """Delete the file, if it is still this process's (a second copy of the
    app must not revoke the first one's pairing by closing)."""
    path = pairing_path()
    try:
        if pid is not None:
            with open(path, encoding="utf-8") as handle:
                if json.load(handle).get("pid") != pid:
                    return
        os.remove(path)
    except (OSError, ValueError):
        pass


def read_pairing() -> Dict[str, Any]:
    path = pairing_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise PairingError(
            "no pairing file (%s): the app is not running, or Preferences "
            "> AI > Allow agents is off" % path) from None
    except (OSError, ValueError) as exc:
        raise PairingError("the pairing file %s cannot be read: %s"
                           % (path, exc)) from exc
    if not isinstance(data, dict) or data.get("protocol") != PROTOCOL \
            or not isinstance(data.get("secret"), str) \
            or not isinstance(data.get("pipe"), str) \
            or len(data["secret"]) != 64:
        raise PairingError("the pairing file %s is not one this server "
                           "understands" % path)
    return data


# ---------------------------------------------------------------- the proofs


def _mac(secret: str, text: str) -> str:
    return hmac.new(bytes.fromhex(secret), text.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def new_nonce() -> str:
    return secrets.token_hex(16)


def client_proof(secret: str, server_nonce: str, client_nonce: str) -> str:
    return _mac(secret, "client|%s|%s" % (server_nonce, client_nonce))


def server_proof(secret: str, server_nonce: str, client_nonce: str) -> str:
    return _mac(secret, "server|%s|%s" % (server_nonce, client_nonce))


def canonical(params: Any) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def request_mac(secret: str, server_nonce: str, client_nonce: str,
                ident: Any, nonce: str, method: str, params: Any) -> str:
    return _mac(secret, "req|%s|%s|%s|%s|%s|%s" % (
        server_nonce, client_nonce, ident, nonce, method,
        canonical(params)))


def same(a: str, b: str) -> bool:
    """Compare two proofs in constant time."""
    try:
        return hmac.compare_digest(str(a).encode("ascii"),
                                   str(b).encode("ascii"))
    except (UnicodeError, TypeError):
        return False
