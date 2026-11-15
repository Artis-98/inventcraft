"""The pictures on ic.iiteg.com that the other shot scripts do not make.

Usage:  python tests/shot_ic_site.py out_dir

The start page, a part with the Extrude window open, the excavator in
Midnight Navy (dark) and Olive Moss (light), and the excavator in German.
Each runs as its own process with its own preferences, because a scheme
and a language are chosen when the window starts.  The rest of the site's
pictures come from shot_site.py, shot_site_more.py, shot_site_baseview.py,
shot_site_bom.py, shot_site_drawing.py and shot_cart.py.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "examples", "excavator")

if len(sys.argv) >= 3 and sys.argv[1] == "--one":
    which, out = sys.argv[2], sys.argv[3]
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import harness  # noqa: F401
    from PySide6 import QtCore, QtGui, QtWidgets
    from datum.core import prefs as user_prefs
    from datum.ui import icons, theme
    # as the application starts: the scheme goes on before anything is built
    theme.set_theme(user_prefs.prefs().theme)
    icons.use_theme(theme.current_theme())
    theme.apply_colours()
    from datum.ui.main_window import MainWindow
    from datum.ui.theme import stylesheet

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet())
    app.setWindowIcon(icons.app_icon())
    win = MainWindow()
    win.resize(1500 if which in ("start", "extrude") else 1600,
               950 if which in ("start", "extrude") else 958)
    win.show()

    def settle(ms=600):
        timer = QtCore.QElapsedTimer()
        timer.start()
        while timer.elapsed() < ms:
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents,
                                                 20)

    def shot():
        settle(300)
        if win.stack.currentWidget() is not win.start_page:
            win.viewport.redraw()
        settle(200)
        chrome = win.grab()
        if which == "extrude":
            # the Extrude window floats over the view, so the screen is
            # what has it
            g = win.frameGeometry()
            chrome = win.screen().grabWindow(0, g.x(), g.y(), g.width(),
                                             g.height())
        elif win.stack.currentWidget() is not win.start_page:
            scratch = out + "_vp.png"
            win.viewport.grab_image(scratch)
            image = QtGui.QImage(scratch)
            if not image.isNull():
                at = win.viewport.mapTo(win, QtCore.QPoint(0, 0))
                painter = QtGui.QPainter(chrome)
                painter.drawImage(QtCore.QRect(at.x(), at.y(),
                                               win.viewport.width(),
                                               win.viewport.height()), image)
                painter.end()
            try:
                os.remove(scratch)
            except OSError:
                pass
        chrome.save(out)
        print("%-40s %d x %d" % (os.path.basename(out), chrome.width(),
                                 chrome.height()))

    def go():
        if which == "start":
            # the examples as the recent files, not whatever tests left
            from datum.core import fileformat
            page = win.start_page
            page._clear_recent()
            here = os.path.join(ROOT, "examples")
            for relative, kind in (
                    ("excavator/Excavator.adat", fileformat.ASSEMBLY),
                    ("railing/Stair Railing.pdat", fileformat.PART),
                    ("plywood-tote/Tote Nest.cdat", fileformat.CAM),
                    ("drawings/Side Panel.ddat", fileformat.DRAWING),
                    ("weld-cart/Welding Cart.icasm", fileformat.ASSEMBLY),
                    ("weld-cart/Bottle Tray.icpart", fileformat.PART),
                    ("weld-cart/MIG Welder.icpart", fileformat.PART),
                    ("weld-cart/Cart Plates.iccam", fileformat.CAM)):
                page.remember(os.path.join(here, relative), kind)
            page.refresh()
            win.show_start_page()
            settle(900)
        elif which == "extrude":
            from datum.core.document import Document
            from datum.core.features import SketchFeature
            from datum.core.sketch import Sketch, SketchPlane
            part = Document()
            drawn = SketchFeature(name="Two Regions")
            drawn.sketch = Sketch(SketchPlane((0, 0, 0), (0, 0, 1),
                                              (1, 0, 0), "XY Plane"),
                                  "Two Regions")
            drawn.sketch.add_rectangle((0.0, 0.0), (60.0, 40.0))
            drawn.sketch.add_circle((95.0, 20.0), 14.0)
            part.add_feature(drawn)
            part.rebuild()
            path = os.path.join(tempfile.mkdtemp(), "Part1.icpart")
            part.save(path)
            win.open_path(path)
            settle(800)
            win.viewport.set_view("iso")
            settle(300)
            win.viewport.fit_all()
            settle(300)
            from datum.core.features import ExtrudeFeature
            win.new_feature(ExtrudeFeature)
            settle(800)
            win.viewport.fit_all()
            settle(500)
            win.raise_()
            win.activateWindow()
            settle(500)
        else:
            win.open_assembly(os.path.join(SAMPLES, "Excavator.adat"))
            settle(1400)
            win.assembly_ui.browser.expandAll()
            win.viewport.set_view("iso")
            settle(450)
            win.viewport.fit_all()
            settle(450)
        shot()
        app.quit()

    QtCore.QTimer.singleShot(1500, go)
    # never left waiting on something that did not come up
    QtCore.QTimer.singleShot(180000, app.quit)
    sys.exit(app.exec())


PICTURES = [
    ("01_start_page.png", "start", {}),
    ("16_profile_picker.png", "extrude", {}),
    ("17_scheme_midnight_navy_dark.png", "assembly", {"theme": "midnight"}),
    ("18_scheme_olive_moss_light.png", "assembly",
     {"theme": "olive_light"}),
    ("19_language_german.png", "assembly", {"language": "de"}),
]


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for name, which, settings in PICTURES:
        config = tempfile.mkdtemp(prefix="ic_shot_")
        with open(os.path.join(config, "preferences.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(settings, handle)
        env = dict(os.environ, DATUM_CONFIG_DIR=config)
        subprocess.run([sys.executable, os.path.abspath(__file__), "--one",
                        which, os.path.join(out, name)], env=env,
                       timeout=600)


if __name__ == "__main__":
    main()
