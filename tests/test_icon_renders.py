"""Rendered icons (tools/icons/render3d.py) in the window.

A PNG beside an icon's SVG is drawn instead of it, the dark scheme's own
render in a dark scheme; every render has both; a render scaled to a
toolbar's 20 pixels keeps its shape (it is not blank or a smudge); and an
icon with no render is still its drawing.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

from PySide6 import QtGui, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from datum.ui import icons  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + ("  " + str(extra) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


folder = icons._ICON_DIR
light = sorted(os.path.basename(p)[:-4] for p in
               glob.glob(os.path.join(folder, "*.png"))
               if not p.endswith(".dark.png"))
dark = {os.path.basename(p)[:-9] for p in
        glob.glob(os.path.join(folder, "*.dark.png"))}
check("there are rendered icons", len(light) > 20, len(light))
check("every render has its dark scheme's render too",
      set(light) == dark, sorted(set(light) ^ dark)[:5])
check("and an SVG drawing beside it, for anything that wants one",
      all(os.path.exists(os.path.join(folder, n + ".svg")) for n in light),
      [n for n in light if not os.path.exists(os.path.join(folder,
                                                           n + ".svg"))][:5])


def opaque(pm):
    img = pm.toImage()
    return sum(1 for y in range(img.height()) for x in range(img.width())
               if QtGui.QColor(img.pixel(x, y)).alpha() > 128
               or img.pixelColor(x, y).alpha() > 128)


try:
    icons.use_theme("light")
    lit = icons.pixmap("fillet", 20).toImage()
    icons.use_theme("dark")
    dim = icons.pixmap("fillet", 20).toImage()
    check("a dark scheme draws the dark render", lit != dim)
    icons.use_theme("light")
    sizes = {n: opaque(icons.pixmap(n, 20)) for n in light}
    thin = [n for n, k in sizes.items() if k < 20 * 20 * 0.18]
    check("each render fills its 20 pixels enough to read", not thin,
          thin[:8])
    check("an icon with no render is still its drawing",
          opaque(icons.pixmap("line", 20)) > 0
          and "line" not in light)
finally:
    icons.use_theme("light")

print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all passed")
