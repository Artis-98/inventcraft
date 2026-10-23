"""0.3.0: DATUM becomes InventCraft, light by default, and Linux updates.

The name changes on screen and on new files; everything a 0.2.x copy left
behind keeps working: its settings, its .pdat and the rest, its file
associations and shortcuts, and the update that brings it here.  The light
scheme is the default and the dark one is a choice, each with its own
colours.  A Linux copy takes its update as one archive whose hash is in
the signed feed, and puts it in place itself.
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness  # noqa: E402,F401

os.environ.setdefault("DATUM_SETTINGS_ORG", "IITEG-tests")

from PySide6 import QtGui, QtWidgets                               # noqa: E402

import datum                                                       # noqa: E402
from datum.core import fileformat, prefs, project, shellreg, swap  # noqa: E402
from datum.core import update                                      # noqa: E402
from datum.core.document import Document                           # noqa: E402
from datum.ui import icons, theme                                  # noqa: E402

FAILS = []
WORK = tempfile.mkdtemp(prefix="datum_batch18_")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOTE = os.path.join(REPO, "examples", "plywood-tote")


def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  " + str(extra)) if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8-sig") as handle:
        return handle.read()


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# ---------------------------------------------------------------- the name
print("the name, and what keeps the old one")
check("shown as InventCraft", datum.APP_NAME == "InventCraft")
check("stored as DATUM", datum.LEGACY_NAME == "DATUM")
check("the preferences folder is the one 0.2.x used",
      prefs.APP_FOLDER == "DATUM")
check("the format marker inside every file is unchanged",
      fileformat.FORMAT == "DATUM")
check("the update feed has not moved", "/datum/" in update.DEFAULT_FEED)
check("the taskbar identity has not moved",
      '"IITEG.DATUM"' in read("datum/app.py"))

# --------------------------------------------------------------- endings
print("file endings")
check("new endings", [fileformat.EXTENSIONS[k] for k in (
    fileformat.PART, fileformat.ASSEMBLY, fileformat.DRAWING,
    fileformat.CAM)] == [".icpart", ".icasm", ".icdraw", ".iccam"])
check("a legacy part is a part", fileformat.is_part("a/Base.pdat")
      and fileformat.is_part("a/Base.icpart")
      and not fileformat.is_part("a/Tote.adat"))
check("a legacy assembly is an assembly",
      fileformat.is_assembly("Tote.adat") and fileformat.is_assembly("T.icasm"))
check("a new name gets the new ending",
      fileformat.ensure_extension("x/Bracket", fileformat.PART)
      == "x/Bracket.icpart")
check("a legacy ending of the right type is kept",
      fileformat.ensure_extension("x/Bracket.pdat", fileformat.PART)
      == "x/Bracket.pdat")
check("an ending of the wrong type is replaced",
      fileformat.ensure_extension("x/Bracket.adat", fileformat.PART)
      == "x/Bracket.icpart")
check("the open dialog offers both",
      "*.icpart" in fileformat.open_filter()
      and "*.pdat" in fileformat.open_filter())
check("a project file is .icproj, and .dproj still opens",
      project.EXTENSION == ".icproj" and project.LEGACY_EXTENSION == ".dproj")
home = os.path.join(WORK, "home")
os.makedirs(home)
check("a fresh machine keeps documents under InventCraft",
      project.documents_folder(home).endswith("InventCraft"))
os.makedirs(os.path.join(home, "DATUM"))
check("one that had DATUM keeps using it",
      project.documents_folder(home).endswith("DATUM"))

# -------------------------------------------------------- legacy documents
print("documents from DATUM")
base = Document.load(os.path.join(TOTE, "Base.pdat"))
check("a .pdat opens and builds", base.shape is not None
      and not base.shape.IsNull())
copy = os.path.join(WORK, "Base.pdat")
shutil.copy2(os.path.join(TOTE, "Base.pdat"), copy)
reopened = Document.load(copy)
written = reopened.save(copy)
check("saving it keeps .pdat, so assemblies still find it",
      written == copy and os.path.exists(copy), written)
fresh = Document()
saved = fresh.save(os.path.join(WORK, "New Part"))
check("a new part is written as .icpart", saved.endswith(".icpart"), saved)
check("and reads back", Document.load(saved) is not None)
with open(os.path.join(TOTE, "Tote.adat"), "rb") as handle:
    check("a DATUM assembly is still a DATUM archive",
          handle.read(2) == b"PK")

# ----------------------------------------------------------------- themes
print("colour schemes")
theme.set_theme("light")
check("light is the default", prefs.Preferences().theme == "light")
check("the light window is near white", theme.C.window == "#f4f4f2")
check("the accent is the beaver's amber", theme.C.accent == "#d5a129")
light_css = theme.stylesheet()
check("no dark colour is left fixed in the stylesheet",
      "#5b636c" not in light_css and "#24272b" not in light_css
      and "rgba(255, 255, 255, 0.10)" not in light_css)
check("the tree's mode tabs follow the scheme",
      "#BrowserModeBar { background: %s;" % theme.C.panel in light_css)
check("the light backdrop is light", min(theme.C.bg_top) > 0.8)
check("a constrained sketch line is dark ink on it",
      QtGui.QColor(theme.C.sketch_line).lightness() < 60)

theme.set_theme("dark")
check("dark is DATUM's as it was", theme.C.window == "#1e2124"
      and theme.C.accent == "#c2ccd8"
      and theme.C.bg_top == (0.0545, 0.0648, 0.0844))
check("what a scheme shipped with follows it",
      theme.shipped("window") == "#1e2124")
check("the dark stylesheet still has its own greys",
      "#5b636c" in theme.stylesheet())
theme.set_theme("nonsense")
check("an unknown scheme falls back to light",
      theme.current_theme() == "light" and theme.C.window == "#f4f4f2")

theme.set_theme("dark")
theme.apply_colours({"bg_top": "#1e2530"})
check("a colour of their own goes over the dark one",
      theme.as_hex(theme.C.bg_top) == "#1e2530")
theme.set_theme("light")
theme.apply_colours({})
check("and does not follow them into the light one",
      theme.C.bg_top == theme.LIGHT["bg_top"])

data = {"theme": "dark", "colours": {"bg_top": "#1e2530"},
        "light_colours": {"sketch_free": "#00ff00", "window": "#000000"}}
loaded = prefs.Preferences.from_dict(data)
check("the scheme is remembered", loaded.theme == "dark")
check("each scheme keeps its own colours",
      loaded.colours_for("dark") == {"bg_top": "#1e2530"}
      and loaded.colours_for("light") == {"sketch_free": "#00ff00"},
      (loaded.colours, loaded.light_colours))
check("and round trips", prefs.Preferences.from_dict(
    loaded.to_dict()).to_dict() == loaded.to_dict())
check("a 0.2.x file, with no scheme in it, opens light",
      prefs.Preferences.from_dict({"colours": {"bg_top": "#1e2530"}}).theme
      == "light")
check("a scheme it does not know opens light",
      prefs.Preferences.from_dict({"theme": "purple"}).theme == "light")

# ------------------------------------------------------------------ icons
print("icons in each scheme")


def darkest(name):
    image = icons.pixmap(name, 24, 1.0).toImage()
    best = 255
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() > 200:
                best = min(best, c.lightness())
    return best


icons.use_theme("light")
light_ink = darkest("extrude")
icons.use_theme("dark")
dark_ink = darkest("extrude")
icons.use_theme("light")
check("light icons are drawn in dark lines", light_ink < 90, light_ink)
check("dark icons in light ones", dark_ink > light_ink + 60,
      (light_ink, dark_ink))
check("the window buttons follow", icons.window_glyph_colour() == "#2b3540")

# ------------------------------------------------------------ preferences
print("the Preferences window")
from datum.ui.prefs_ui import PreferencesDialog                     # noqa: E402

prefs.reset()
theme.set_theme("light")
icons.use_theme("light")
before = dict(prefs.prefs().colours)
dialog = PreferencesDialog()
check("it offers the scheme", dialog.theme_combo.count() == 2
      and dialog.theme_combo.currentData() == "light")
dialog.colour_buttons["sketch_free"].set_colour("#00aa00")
dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("dark"))
dialog.apply()
saved_prefs = prefs.load()
check("the choice of scheme is saved", saved_prefs.theme == "dark")
check("a colour lands in the scheme in use now",
      saved_prefs.light_colours.get("sketch_free") == "#00aa00",
      saved_prefs.light_colours)
check("and not in the other", saved_prefs.colours == before,
      saved_prefs.colours)
check("the window keeps its scheme until the next start",
      theme.current_theme() == "light")
dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("light"))
dialog.reset_colours()
dialog.deleteLater()
prefs.reset()

# ------------------------------------------------------- Windows' side of it
print("file types and shortcuts after an in-app update")
if sys.platform == "win32":
    import winreg

    TEST_BASE = r"Software\IITEG-tests\Classes"

    def set_default(ending, value):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              "%s\\%s" % (TEST_BASE, ending)) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)

    def get_default(ending):
        return shellreg._read_default(winreg, TEST_BASE, ending)

    def wipe(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                names = []
                i = 0
                while True:
                    try:
                        names.append(winreg.EnumKey(key, i))
                    except OSError:
                        break
                    i += 1
            for name in names:
                wipe(path + "\\" + name)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass

    wipe(r"Software\IITEG-tests\Classes")
    set_default(".pdat", "IITEG.DATUM.Part")
    set_default(".ddat", "IITEG.DATUM.Drawing")
    set_default(".icdraw", "SomethingElse.Drawing")
    set_default(".adat", "SomeOtherProgram.Assembly")
    done = shellreg.adopt_new_endings(TEST_BASE)
    check("an associated ending brings its new one along",
          get_default(".icpart") == "IITEG.DATUM.Part", done)
    check("one somebody else owns is left alone",
          get_default(".icasm") == "", get_default(".icasm"))
    check("and so is a new ending already pointing somewhere",
          get_default(".icdraw") == "SomethingElse.Drawing")
    check("one never associated stays unassociated",
          get_default(".iccam") == "")
    check("a second run does nothing", shellreg.adopt_new_endings(
        TEST_BASE) == [])
    wipe(r"Software\IITEG-tests\Classes")
else:
    print("  (registry checks are Windows only)")


def fake_link(path, target):
    with open(path, "wb") as handle:
        handle.write(b"\x4c\x00\x00\x00" + b"\x00" * 60
                     + target.encode("utf-16-le") + b"\x00\x00")


links = os.path.join(WORK, "links")
os.makedirs(os.path.join(links, "DATUM"))
ours = os.path.join(links, "DATUM", "DATUM.lnk")
fake_link(ours, r"C:\Users\x\AppData\Local\Programs\DATUM\DATUM.exe")
other = os.path.join(links, "Other.lnk")
fake_link(other, r"C:\Tools\datum-viewer.exe")
check("our shortcut is recognised", shellreg.is_our_shortcut(ours))
check("somebody else's is not", not shellreg.is_our_shortcut(other))
moved = shellreg.rename_shortcuts([
    (ours, os.path.join(links, "InventCraft", "InventCraft.lnk")),
    (other, os.path.join(links, "Renamed.lnk")),
])
check("ours is renamed InventCraft",
      os.path.exists(os.path.join(links, "InventCraft", "InventCraft.lnk"))
      and not os.path.exists(ours), moved)
check("the empty DATUM folder goes with it",
      not os.path.exists(os.path.join(links, "DATUM")))
check("the other is left where it was", os.path.exists(other))

# --------------------------------------------------------- the Linux update
print("Linux: one archive, trusted through the signed feed")
feed = {"version": "0.3.1", "notes": "Windows notes",
        "manifest": "0.3.1/manifest.json",
        "linux": {"version": "0.3.1", "sha256": "ab" * 32, "size": 1234,
                  "url": "https://github.com/x/y/releases/download/"
                         "v0.3.1/InventCraft-0.3.1-linux-x86_64.tar.gz"}}
on_linux = update.Release.from_dict(feed, "https://f/", "linux")
check("Linux reads its own entry", on_linux.version == "0.3.1"
      and on_linux.package.endswith(".tar.gz")
      and on_linux.package_sha256 == "ab" * 32
      and on_linux.package_size == 1234)
check("and the notes come along", on_linux.notes == "Windows notes")
on_windows = update.Release.from_dict(feed, "https://f/", "win32")
check("Windows ignores it", on_windows.package == ""
      and on_windows.manifest == "0.3.1/manifest.json")
del feed["linux"]
check("with no Linux entry, Linux is offered nothing",
      not update.Release.from_dict(feed, "https://f/", "linux").newer)
checked = update.check("https://f/", fetcher=lambda b, n: json.dumps(
    dict(feed, linux={"version": "9.9.9", "url": "https://x/a.tar.gz",
                      "sha256": "00"})).encode(), platform="linux")
check("check() hands the platform through", checked.version == "9.9.9")
try:
    update.fetch_to("http://example.invalid/a.tar.gz",
                    os.path.join(WORK, "nope"))
    check("a plain http archive is refused", False)
except update.UpdateError:
    check("a plain http archive is refused", True)

install = os.path.join(WORK, "install")
os.makedirs(os.path.join(install, "_internal"))
for rel, body in (("InventCraft", b"old program"),
                  ("_internal/same.txt", b"unchanged"),
                  ("_internal/gone.txt", b"dropped in 0.3.1"),
                  ("unins000.dat", b"not ours to delete")):
    with open(os.path.join(install, rel), "wb") as handle:
        handle.write(body)


def build_archive(path, files):
    with tarfile.open(path, "w:gz") as tar:
        for rel, body in files.items():
            info = tarfile.TarInfo("InventCraft/" + rel)
            info.size = len(body)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(body))
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


source = os.path.join(WORK, "built.tar.gz")
sha = build_archive(source, {"InventCraft": b"new program",
                             "_internal/same.txt": b"unchanged",
                             "_internal/new.txt": b"added in 0.3.1"})


def serve(url, path, progress=None, total=0):
    shutil.copy2(source, path)
    if progress is not None:
        progress(1, 1)
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


release = update.Release(version="0.3.1", package="https://x/a.tar.gz",
                         package_sha256=sha, package_size=10)
plan = update.download_package(release, install, fetcher=serve)
check("what changed is staged", sorted(plan.download)
      == ["InventCraft", "_internal/new.txt"], plan.download)
check("what went is marked to go",
      plan.delete == ["_internal/gone.txt"], plan.delete)
check("the uninstaller's file is never marked",
      "unins000.dat" not in plan.delete)
check("the staged files are there", os.path.exists(os.path.join(
    install, update.STAGING, "_internal", "new.txt")))
check("the unpacked archive is cleared away",
      not os.path.exists(os.path.join(install, update.UNPACK)))
check("and it is pending", update.pending(install) == "0.3.1")

bad = update.Release(version="0.3.1", package="https://x/a.tar.gz",
                     package_sha256="00" * 32)
try:
    update.download_package(bad, install, fetcher=serve)
    check("an archive the feed did not describe is refused", False)
except update.UpdateError:
    check("an archive the feed did not describe is refused", True)
check("and leaves nothing staged", update.pending(install) is None)

update.download_package(release, install, fetcher=serve)
gone = subprocess.Popen([sys.executable, "-c", "pass"])
gone.wait()
check("the swap puts it in place", swap.finish(install, gone.pid,
                                               relaunch=False, timeout=5))
with open(os.path.join(install, "InventCraft"), "rb") as handle:
    check("the program is the new one", handle.read() == b"new program")
check("the new file arrived",
      os.path.exists(os.path.join(install, "_internal", "new.txt")))
check("the dropped one went",
      not os.path.exists(os.path.join(install, "_internal", "gone.txt")))
check("the uninstaller's file stayed",
      os.path.exists(os.path.join(install, "unins000.dat")))
check("staging is cleared", not os.path.exists(
    os.path.join(install, update.STAGING)))

update.download_package(update.Release(
    version="0.3.1", package="https://x/a.tar.gz", package_sha256=sha),
    install, fetcher=serve)
check("nothing to stage when it is already current",
      update.read_plan(install)["download"] == [])
update.clear_staging(install)

# the command line the closing window starts
with open(os.path.join(install, "InventCraft"), "wb") as handle:
    handle.write(b"older again")
update.download_package(release, install, fetcher=serve)
from datum import app as entry                                     # noqa: E402

code = entry.main(["InventCraft", "--finish-update", install,
                   str(gone.pid), "stay"])
with open(os.path.join(install, "InventCraft"), "rb") as handle:
    check("--finish-update does the same from the command line",
          code == 0 and handle.read() == b"new program", code)

# ---------------------------------------------------------- the packaging
print("the build, the installer and the Linux archive")
spec = read("tools/datum.spec")
check("the Windows build is InventCraft.exe, with the beaver",
      'name="InventCraft"' in spec and "inventcraft.ico" in spec
      and '"datum/ui/brand"' in spec)
check("the Linux build carries the beaver too",
      '"datum/ui/brand"' in read("tools/datum_linux.spec"))
release_py = read("tools/release.py")
check("every release carries DATUM.exe as well",
      'LEGACY_EXE_NAME = "DATUM.exe"' in release_py
      and "shutil.copy2(built, os.path.join(DIST, LEGACY_EXE_NAME))"
      in release_py)
iss = read("tools/installer.iss")
check("the installer keeps DATUM's AppId, so it installs over it",
      "{{8C4E2F6A-9D1B-4E57-B3A2-7F0C5D8E1A94}" in iss)
check("and opens both sets of endings", all(
    ending in iss for ending in (".icpart", ".icasm", ".icdraw", ".iccam",
                                 ".pdat", ".adat", ".ddat", ".cdat")))
check("and clears DATUM's old shortcuts", r"{autodesktop}\DATUM.lnk" in iss)
workflow = read(".github/workflows/linux.yml")
check("the Linux archive is no longer a preview",
      "InventCraft-${{ steps.version.outputs.version }}-linux-x86_64.tar.gz"
      in workflow and "preview.tar.gz" not in workflow)
check("and its name is the one the release step fetches",
      'LINUX_ARCHIVE = "InventCraft-%s-linux-x86_64.tar.gz"' in release_py)
script = read("tools/linux/install.sh")
check("the install script registers every ending", all(
    "*" + ending in script for ending in (
        ".icpart", ".icasm", ".icdraw", ".iccam",
        ".pdat", ".adat", ".ddat", ".cdat")))
check("and is plain LF, as a shell wants it", "\r\n" not in open(
    os.path.join(REPO, "tools", "linux", "install.sh"), "rb").read()
    .decode("utf-8"))

shutil.rmtree(WORK, ignore_errors=True)
print()
if FAILS:
    print("%d FAILURES: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all batch 18 tests passed")
sys.exit(0)
