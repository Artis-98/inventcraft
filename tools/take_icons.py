"""Check a folder of new icons and take the good ones into the app.

    python tools/take_icons.py [folder] [--apply]

Without --apply it only reports.  Each SVG is checked against the brief in
docs/icons/ICONS.md: a known name, a 24 unit viewBox, no width or height,
only the six colours, no text, images, gradients, filters or styles, and it
must render.  With --apply the good ones are copied into
datum/ui/assets/icons, replacing any there, and the rest are listed.
"""
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

DEFAULT = os.path.join(os.path.dirname(HERE), "icons-incoming")
COLOURS = {"#2b3540", "#b9820f", "#7a8693", "#e0a355", "#69c26b",
           "#d9534f", "none"}
ALLOWED = {"svg", "g", "path", "line", "polyline", "polygon", "rect",
           "circle", "ellipse", "title", "desc"}


def problems(path, known):
    out = []
    name = os.path.splitext(os.path.basename(path))[0]
    if name not in known:
        out.append("not a name in ICONS.md")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return out + ["not valid SVG: %s" % exc]
    if root.tag.split("}")[-1] != "svg":
        out.append("the root is not <svg>")
    box = (root.get("viewBox") or "").split()
    if [float(v) for v in box] != [0, 0, 24, 24] if len(box) == 4 else True:
        out.append("viewBox is %r, not 0 0 24 24" % root.get("viewBox"))
    if root.get("width") or root.get("height"):
        out.append("has width or height")
    for element in root.iter():
        tag = element.tag.split("}")[-1]
        if tag not in ALLOWED:
            out.append("uses <%s>" % tag)
        for key in ("fill", "stroke", "color", "stop-color"):
            value = (element.get(key) or "").strip().lower()
            if value and value not in COLOURS and value != "currentcolor":
                out.append("colour %s" % value)
        style = element.get("style") or ""
        for value in re.findall(r"#[0-9a-fA-F]{3,6}", style):
            if value.lower() not in COLOURS:
                out.append("colour %s in a style" % value)
        if element.get("{http://www.w3.org/1999/xlink}href") or \
                element.get("href"):
            out.append("links to something")
    from PySide6 import QtCore, QtSvg
    renderer = QtSvg.QSvgRenderer(path)
    if not renderer.isValid():
        out.append("does not render")
    return sorted(set(out))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = args[0] if args else DEFAULT
    apply = "--apply" in sys.argv
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])  # noqa
    from datum.ui import icons
    known = set(icons.PAINTERS) | set(icons.BORROWED)
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".svg"))
    others = sorted(f for f in os.listdir(folder)
                    if not f.lower().endswith(".svg"))
    good, bad = [], []
    for name in files:
        found = problems(os.path.join(folder, name), known)
        (bad if found else good).append((name, found))
    for name, found in bad:
        print("REFUSED %s: %s" % (name, "; ".join(found)))
    for name in others:
        print("IGNORED %s: not an SVG" % name)
    print("%d good, %d refused, %d not SVG; %d icons still without a file"
          % (len(good), len(bad), len(others),
             len(known - {os.path.splitext(n)[0] for n, _ in good}
                 - {os.path.splitext(n)[0] for n in os.listdir(
                     icons._ICON_DIR) if n.endswith(".svg")})))
    if apply and good:
        os.makedirs(icons._ICON_DIR, exist_ok=True)
        for name, _ in good:
            shutil.copy2(os.path.join(folder, name),
                         os.path.join(icons._ICON_DIR, name.lower()))
        print("copied %d into %s" % (len(good), icons._ICON_DIR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
