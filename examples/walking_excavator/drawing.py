"""A shop drawing of the boom weldment: views, a parts list, balloons
and weld symbols, all made through the same core the Drawing window uses.

    .venv/Scripts/python.exe -m examples.walking_excavator.drawing

Writes examples/walking-excavator/drawings/Boom Weldment.icdraw and its
PDF and PNG.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6 import QtWidgets

from datum.core import fileformat, views, kernel
from datum.core.assembly import AssemblyDocument
from datum.core.drawing import (BASE, PROJECTED, BALLOON, LINEAR, WELD, NOTE, DrawingDocument,
                                Annotation, View, PartsList, WITH_HIDDEN, three_view_layout)
from .common import OUT

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from datum.ui import drawingexport  # noqa: E402

DEST = OUT / 'drawings'
MODEL = OUT / 'subassemblies' / 'Boom.icasm'


def reference(path, base_dir):
    return fileformat.ComponentRef(path=fileformat.relative_path(str(path), str(base_dir)),
                                   name=os.path.basename(path),
                                   label=os.path.splitext(os.path.basename(path))[0])


import math


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    doc = DrawingDocument()
    doc.standard = 'ISO'
    doc.properties.update({'Title': 'BOOM WELDMENT', 'PartNumber': 'WX-2100', 'Company': 'IITEG',
                           'Author': 'IITEG', 'Revision': 'B', 'Material': 'S355 plate',
                           'Description': 'Walking excavator boom, welded'})
    doc.path = str(DEST / 'Boom Weldment.icdraw')
    sheet = doc.add_sheet('A2')
    ass = AssemblyDocument.load(str(MODEL))
    ass.rebuild()
    x0, y0, z0, x1, y1, z1 = kernel.bounding_box(ass.shape)
    border = doc.borders[sheet.border].frame(*sheet.extent())
    block = doc.title_blocks[sheet.title_block]
    # laid out by hand for a long weldment: the side view across the top,
    # the plan under it, the end view beside it, the iso bottom middle;
    # the parts list top right and the title block bottom right
    scale = 0.1
    base = View(kind=BASE, orientation='front', scale=scale, x=205.0, y=300.0,
                display=WITH_HIDDEN, name='Side')
    base.ref = reference(MODEL, DEST)
    doc.add_view(sheet, base)
    top = doc.add_view(sheet, View(kind=PROJECTED, parent=base.id, name='Plan', x=205.0, y=150.0))
    end = doc.add_view(sheet, View(kind=PROJECTED, parent=base.id, name='End', x=392.0, y=300.0))
    iso = doc.add_view(sheet, View(kind=PROJECTED, parent=base.id, name='Iso', display='shaded',
                                   scale=1 / 15.0, x=478.0, y=160.0))
    generator = views.Generator()
    generator.rebuild(doc)
    # the parts list in the top right corner, as a weldment's list sits
    table = doc.add_parts_list(sheet, PartsList(view=base.id, corner='top-right',
                                                x=border[2] - 6, y=border[3] - 6,
                                                columns=['item', 'qty', 'part_number', 'material'],
                                                widths={'part_number': 62.0}))
    generator.rebuild(doc, force=True)
    # the balloons go on the isometric, where a part is easiest to find:
    # two tidy columns either side of it, each part to the column on its
    # side, in the order the parts sit top to bottom so no leaders cross
    targets = generator.balloon_targets(doc, sheet, iso)
    ib = iso.projection.box
    icx = (ib[0] + ib[2]) / 2
    unique = {}
    for path, middle, corners in targets:
        unique.setdefault(path, (middle, corners))
    lx, rx_ = ib[0] - 14.0, ib[2] + 14.0
    left, right = [], []
    for path, (middle, corners) in unique.items():
        side = lx if middle[0] < icx else rx_
        # the leader lands on the corner facing its column, and the column
        # is ordered by where the leaders land, so none of them cross
        at = views.nearest_corner((path, middle, corners), (side, middle[1]))
        (left if side == lx else right).append((path, at))
    for column, x in ((left, lx), (right, rx_)):
        column.sort(key=lambda pa: -pa[1][1])
        n = len(column)
        top_y, bottom_y = ib[3] + 6.0, ib[1] - 6.0
        for k, (path, at) in enumerate(column):
            y = top_y - (top_y - bottom_y) * (k + 0.5) / n
            doc.add_annotation(sheet, Annotation(kind=BALLOON, view=iso.id, points=[list(at)],
                                                 offset=[x - at[0], y - at[1]], component=path))
    seen = unique
    from examples.walking_excavator import motion as M
    from examples.walking_excavator.beam import Beam
    BL = M.BOOM_LENGTH
    bx = base.projection.box
    # the boom's own outline, to put each weld arrow on its real seam
    beam = Beam(None, 'Boom', [dict(label='foot', c=(0, 0), rb=110, bore=60.3, length=300),
                               dict(label='tip', c=(BL, 0), rb=95, bore=55.3, fork=True,
                                    hole=55.3, ring=25)],
                [(M.BOOM_KNEE[0], 520)], [(1350, 90)], 300, 14, 12, 40, 'boom')

    def v(X, Z):
        return [bx[0] + (X - x0) * scale, bx[1] + (Z - z0) * scale]

    def on(line, X):
        for (ax, az), (bx_, bz) in zip(line, line[1:]):
            if min(ax, bx_) <= X <= max(ax, bx_):
                t = (X - ax) / ((bx_ - ax) or 1.0)
                return v(X, az + t * (bz - az))
        raise ValueError(X)

    def weld(at, off, text):
        doc.add_annotation(sheet, Annotation(kind=WELD, view=base.id, points=[at],
                                             offset=list(off), text=text))
    dx, dz = M.DIPPER_RAM_BASE[0], M.DIPPER_RAM_BASE[2]
    rx, rz = M.BOOM_RAM_ROD[0], M.BOOM_RAM_ROD[2]
    weld(on(beam.top, 650), (-14, 22), 'fillet|a6||')            # top cap to webs
    weld(on(beam.bottom, 1900), (6, -12), 'fillet|a6||')        # bottom cap to webs
    weld(on(beam.top, dx - 210), (-16, 20), 'fillet|a8||')       # dipper ram lugs
    weld(on(beam.bottom, rx + 135), (14, -16), 'fillet|a8||')    # lift ram lugs
    c = (math.cos(math.radians(235)), math.sin(math.radians(235)))
    weld(v(110 * c[0], 110 * c[1]), (-8, -24), 'fillet|a8||all_around')       # foot boss
    c = (math.cos(math.radians(-60)), math.sin(math.radians(-60)))
    weld(v(BL + 95 * c[0], 95 * c[1]), (8, -26), 'fillet|a8||all_around')     # tip boss
    weld(on(beam.top, BL - 300), (10, 14), 'fillet|a5||all_around')       # closure plate

    def dim(view, p1, p2, axis, line):
        """A linear dimension along ``axis`` whose line runs at ``line``."""
        off = [0.0, line - p1[1]] if axis == 'x' else [line - p1[0], 0.0]
        doc.add_annotation(sheet, Annotation(kind=LINEAR, view=view.id, points=[p1, p2],
                                             offset=off, axis=axis))
    foot, tip = v(0, 0), v(BL, 0)
    # along the boom, from the foot pin: knee, ram lug pins, pin to pin
    dim(base, [bx[0], bx[3]], [bx[2], bx[3]], 'x', bx[3] + 30)
    dim(base, foot, v(M.BOOM_KNEE[0], 520), 'x', bx[3] + 19)
    dim(base, foot, v(dx, dz), 'x', bx[3] + 8)
    dim(base, foot, v(rx, rz), 'x', bx[1] - 12)
    dim(base, foot, tip, 'x', bx[1] - 24)
    # heights off the pin line
    dim(base, foot, v(dx, dz), 'y', bx[0] - 10)
    dim(base, foot, v(M.BOOM_KNEE[0], 520), 'y', bx[0] - 20)
    # the pin bores
    from datum.core.drawing import DIAMETER
    for X, r, ang in ((0.0, 60.3, 45.0), (BL, 55.3, 135.0)):
        a = math.radians(ang)
        doc.add_annotation(sheet, Annotation(kind=DIAMETER, view=base.id,
                                             points=[v(X, 0), v(X + r * math.cos(a), r * math.sin(a))],
                                             offset=[14 * math.cos(a), 14 * math.sin(a)]))
    if top.projection is not None:
        tb = top.projection.box
        dim(top, [tb[2], tb[1]], [tb[2], tb[3]], 'y', tb[2] + 12)
        px = lambda X: tb[0] + (X - x0) * scale
        dim(top, [px(0), tb[1]], [px(BL - 300), tb[1]], 'x', tb[1] - 12)
    if end.projection is not None:
        eb = end.projection.box
        dim(end, [eb[0], eb[1]], [eb[2], eb[1]], 'x', eb[1] - 12)
        dim(end, [eb[0], eb[1]], [eb[0], eb[3]], 'y', eb[0] - 10)
    for view in sheet.views:
        view.scale_visible = True
    generator.rebuild(doc, force=True)
    doc.save(doc.path)
    pdf = drawingexport.to_pdf(doc, str(DEST / 'Boom Weldment.pdf'))
    png = drawingexport.to_image(doc, sheet, str(DEST / 'Boom Weldment.png'), dpi=110.0)
    print('views:', [(v.name, v.error or 'ok') for v in sheet.views])
    print('parts list rows:', len(table.rows), table.error)
    print('balloons:', len(seen))
    print('saved', doc.path, pdf, png)


if __name__ == '__main__':
    main()
