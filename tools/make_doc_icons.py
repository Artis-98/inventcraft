"""Write the Windows file icons for the four kinds of document.

    python tools/make_doc_icons.py

Each comes from its SVG in datum/ui/assets/icons (doc_part, doc_assembly,
doc_cam, doc_drawing), drawn in the light scheme's tones, into
datum/ui/assets/filetypes/<kind>.ico at every size Explorer asks for.  The
installer points each file type's DefaultIcon at them, so a .icpart, an
.icasm, an .iccam and an .icdraw each show their own picture.
"""

from __future__ import annotations

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6 import QtCore, QtGui, QtWidgets          # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
OUT = os.path.join(ROOT, "datum", "ui", "assets", "filetypes")
KINDS = ("part", "assembly", "cam", "drawing")


def png_bytes(name: str, size: int) -> bytes:
    from datum.ui import icons

    pixmap = icons.pixmap(name, size, 1.0)
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def write_ico(name: str, path: str) -> str:
    images = [(size, png_bytes(name, size)) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    directory = b""
    offset = 6 + 16 * len(images)
    for size, data in images:
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                                 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as handle:
        handle.write(header + directory + b"".join(d for _, d in images))
    return path


def main() -> int:
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from datum.ui import icons
    icons.use_theme("light")
    os.makedirs(OUT, exist_ok=True)
    for kind in KINDS:
        print(write_ico("doc_" + kind, os.path.join(OUT, kind + ".ico")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
