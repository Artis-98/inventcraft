"""Every icon on one picture, as the app draws it now: drawn ones, files
dropped into datum/ui/assets/icons, and the borrowed ones still waiting.

    python tools/icon_sheet.py [out.png] [--theme dark]

Writes docs/icons/current-icons.png by default.  A file that replaced its
icon is marked with a green corner; one still borrowing with a grey name.
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    theme = "dark" if "--theme" in sys.argv and "dark" in sys.argv else ""
    out = args[0] if args else os.path.join(HERE, "docs", "icons",
                                            "current-icons.png")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from datum.ui import icons
    if theme:
        icons.use_theme(theme)
    names = sorted(set(icons.PAINTERS) | set(icons.BORROWED))
    folder = icons._ICON_DIR
    cols, cell, size = 10, 120, 48
    rows = (len(names) + cols - 1) // cols
    image = QtGui.QImage(cols * cell, rows * cell, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("#25292f" if theme else "#ffffff"))
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    font = painter.font()
    font.setPixelSize(11)
    painter.setFont(font)
    for i, name in enumerate(names):
        x, y = (i % cols) * cell, (i // cols) * cell
        painter.drawPixmap(x + (cell - size) // 2, y + 18,
                           icons.pixmap(name, size, 1.0))
        own = os.path.exists(os.path.join(folder, name + ".svg"))
        waiting = name in icons.BORROWED and not own
        painter.setPen(QtGui.QColor("#999999" if waiting else
                                    ("#dddddd" if theme else "#333333")))
        painter.drawText(QtCore.QRectF(x + 2, y + 74, cell - 4, 40),
                         QtCore.Qt.AlignHCenter | QtCore.Qt.TextWordWrap,
                         name.replace("_", "_​"))
        if own:
            painter.fillRect(QtCore.QRectF(x + cell - 12, y, 12, 12),
                             QtGui.QColor("#69c26b"))
        painter.setPen(QtGui.QColor("#e5e5e5" if not theme else "#3a3f46"))
        painter.drawRect(x, y, cell, cell)
    painter.end()
    image.save(out)
    print("%d icons -> %s" % (len(names), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
