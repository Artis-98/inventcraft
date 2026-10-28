"""Updates from GitHub (0.3.3): the signed feed is asked for on the GitHub
release first and on the server when GitHub has none or cannot be
reached; a test feed is asked alone."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from datum.core import update                                     # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


FEED = {"version": "9.9.9", "windows": {
    "version": "9.9.9", "url": "https://github.com/x/InventCraft.tar.xz",
    "sha256": "0" * 64, "size": 10}}
asked = []


def serving(*bases):
    def fetch(base, name):
        asked.append(base)
        if base in bases:
            return json.dumps(FEED).encode("utf-8")
        raise update.UpdateError("%s%s said 404" % (base, name))
    return fetch


print("GitHub first")
check("the GitHub address is the newest release's",
      update.GITHUB_FEED.endswith("/releases/latest/download/")
      and update.FEEDS[0] == update.GITHUB_FEED)
asked.clear()
release = update.check(fetcher=serving(update.GITHUB_FEED), platform="win32")
check("it answers from GitHub", release.version == "9.9.9"
      and asked == [update.GITHUB_FEED], asked)

print("the server when GitHub has nothing")
asked.clear()
release = update.check(fetcher=serving(update.DEFAULT_FEED), platform="win32")
check("it falls back to the server", release.version == "9.9.9"
      and asked == [update.GITHUB_FEED, update.DEFAULT_FEED], asked)

print("neither")
asked.clear()
try:
    update.check(fetcher=serving(), platform="win32")
    check("it says so", False)
except update.UpdateError as exc:
    check("it says why, for both", "404" in str(exc)
          and str(exc).count("said 404") == 2, str(exc))

print("a test feed is asked alone")
asked.clear()
other = "https://api.iiteg.com/datum-test/"
release = update.check(other, fetcher=serving(other), platform="win32")
check("only that one", asked == [other], asked)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
sys.exit(0)
