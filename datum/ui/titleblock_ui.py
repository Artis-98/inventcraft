"""Editing a drawing's title block and border in place, as Inventor does.

A title block is one definition the drawing holds by name; every sheet that
uses it shows it. Double-clicking it on a sheet opens it here, and what is
changed is the definition, so every sheet follows.

Text in a title block can hold properties among its words, the way
Inventor's Format Text does: ``<Model.PartNumber>`` is replaced by the
part number of the first model on the sheet, ``<Sheet.Number>`` by the
sheet's number, and so on, wherever they stand in the text.
"""
from __future__ import annotations

import copy
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import drawing as dwg

# What Inventor's Format Text offers under Type, and what each holds
PROPERTY_GROUPS = (
    ("Properties - Model", [
        ("Part Number", "Model.PartNumber"), ("Name", "Model.Name"),
        ("Description", "Model.Description"), ("Designer", "Model.Designer"),
        ("Material", "Model.Material"), ("Vendor", "Model.Vendor"),
        ("Stock Number", "Model.StockNumber"),
        ("Revision", "Model.Revision"), ("Units", "Model.Units"),
    ]),
    ("Physical Properties - Model", [
        ("Mass", "Model.Mass"), ("Volume", "Model.Volume"),
        ("Area", "Model.Area"),
    ]),
    ("Properties - Drawing", [
        ("Title", "Drawing.Title"), ("Author", "Drawing.Author"),
        ("Company", "Drawing.Company"), ("Revision", "Drawing.Revision"),
        ("Date", "Drawing.Date"), ("File Name", "Drawing.FileName"),
    ]),
    ("Sheet Properties", [
        ("Sheet Name", "Sheet.Name"), ("Sheet Number", "Sheet.Number"),
        ("Number of Sheets", "Sheet.Count"), ("Sheet Size", "Sheet.Size"),
        ("Scale", "Sheet.Scale"), ("Standard", "Sheet.Standard"),
    ]),
)


class _Preview(QtWidgets.QWidget):
    """The block drawn to fit, its picked text lit."""

    clicked = QtCore.Signal(int)

    def __init__(self, dialog: "TitleBlockDialog") -> None:
        super().__init__(dialog)
        self.dialog = dialog
        self.setMinimumSize(520, 170)

    def _frame(self):
        block = self.dialog.block
        w, h = max(block.width, 1.0), max(block.height, 1.0)
        scale = min((self.width() - 20) / w, (self.height() - 20) / h)
        ox = (self.width() - w * scale) / 2
        oy = (self.height() + h * scale) / 2
        return scale, ox, oy

    def _to_widget(self, x, y):
        scale, ox, oy = self._frame()
        return QtCore.QPointF(ox + x * scale, oy - y * scale)

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("white"))
        block = self.dialog.block
        scale, _ox, _oy = self._frame()
        p.setPen(QtGui.QPen(QtGui.QColor("black"), 1.2))
        for x1, y1, x2, y2 in [line[:4] for line in block.lines]:
            p.drawLine(self._to_widget(x1, y1), self._to_widget(x2, y2))
        for i, item in enumerate(block.fields):
            font = QtGui.QFont("Arial")
            font.setPixelSize(max(6, int(item.height * scale)))
            font.setBold(item.bold)
            p.setFont(font)
            lit = i == self.dialog.current_row()
            p.setPen(QtGui.QColor("#d97706" if lit else "black"))
            text = item.text if item.kind != dwg.PROMPTED else (
                item.value or item.text)
            if item.kind == dwg.PROPERTY:
                text = "<%s>" % item.text
            at = self._to_widget(item.x, item.y)
            width = QtGui.QFontMetricsF(font).horizontalAdvance(text)
            if item.align in ("centre", "center"):
                at.setX(at.x() - width / 2)
            elif item.align == "right":
                at.setX(at.x() - width)
            p.drawText(at, text)
        p.end()

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        best, gap = None, 30.0
        for i, item in enumerate(self.dialog.block.fields):
            at = self._to_widget(item.x, item.y)
            d = abs(at.x() - pos.x()) + abs(at.y() - pos.y())
            if d < gap:
                best, gap = i, d
        if best is not None:
            self.clicked.emit(best)


class TitleBlockDialog(QtWidgets.QDialog):
    """The title block's size, lines and text, and the properties its text
    shows."""

    def __init__(self, parent, doc: dwg.DrawingDocument, name: str) -> None:
        super().__init__(parent)
        self.doc = doc
        self.name = name
        self.block = copy.deepcopy(doc.title_blocks[name])
        self.setWindowTitle("Edit Title Block - %s" % name)
        root = QtWidgets.QVBoxLayout(self)

        size = QtWidgets.QHBoxLayout()
        self.width_box = self._spin(self.block.width)
        self.height_box = self._spin(self.block.height)
        size.addWidget(QtWidgets.QLabel("Width"))
        size.addWidget(self.width_box)
        size.addWidget(QtWidgets.QLabel("Height"))
        size.addWidget(self.height_box)
        size.addStretch(1)
        root.addLayout(size)

        self.preview = _Preview(self)
        self.preview.clicked.connect(lambda row: self.table.selectRow(row))
        root.addWidget(self.preview, 1)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Text", "X", "Y", "Height", "Bold", "Align"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._table_changed)
        self.table.itemSelectionChanged.connect(self.preview.update)
        root.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add Text")
        add.clicked.connect(self._add_text)
        remove = QtWidgets.QPushButton("Delete Text")
        remove.clicked.connect(self._remove_text)
        row.addWidget(add)
        row.addWidget(remove)
        row.addSpacing(16)
        # Inventor's Format Text: Type, Property, and the button that puts
        # it into the text where the cursor is
        self.group = QtWidgets.QComboBox()
        for title, _items in PROPERTY_GROUPS:
            self.group.addItem(title)
        self.prop = QtWidgets.QComboBox()
        self.group.currentIndexChanged.connect(self._fill_props)
        self._fill_props(0)
        insert = QtWidgets.QPushButton("Add Property")
        insert.setToolTip("Put the property into the picked text, where it "
                          "is filled in from the model or the sheet")
        insert.clicked.connect(self._insert_property)
        row.addWidget(QtWidgets.QLabel("Type"))
        row.addWidget(self.group)
        row.addWidget(QtWidgets.QLabel("Property"))
        row.addWidget(self.prop)
        row.addWidget(insert)
        row.addStretch(1)
        root.addLayout(row)

        lines_row = QtWidgets.QHBoxLayout()
        lines_row.addWidget(QtWidgets.QLabel(
            "Lines (x1 y1 x2 y2 per line, millimetres from bottom left):"))
        root.addLayout(lines_row)
        self.lines = QtWidgets.QPlainTextEdit()
        self.lines.setPlainText("\n".join(
            " ".join("%g" % v for v in line[:4]) for line in self.block.lines))
        self.lines.setMaximumHeight(110)
        self.lines.textChanged.connect(self._lines_changed)
        root.addWidget(self.lines)

        note = QtWidgets.QLabel("Every sheet using this title block "
                                "changes with it.")
        note.setProperty("hint", True)
        root.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._loading = False
        self._fill_table()
        self.resize(820, 640)

    def _spin(self, value: float) -> QtWidgets.QDoubleSpinBox:
        box = QtWidgets.QDoubleSpinBox()
        box.setRange(1.0, 2000.0)
        box.setDecimals(1)
        box.setSuffix(" mm")
        box.setValue(value)
        box.valueChanged.connect(self._size_changed)
        return box

    def _size_changed(self, _v) -> None:
        self.block.width = self.width_box.value()
        self.block.height = self.height_box.value()
        self.preview.update()

    def current_row(self) -> int:
        rows = self.table.selectionModel().selectedRows() \
            if self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def _fill_props(self, index: int) -> None:
        self.prop.clear()
        for label, key in PROPERTY_GROUPS[max(0, index)][1]:
            self.prop.addItem(label, key)

    @staticmethod
    def _shown(item: dwg.TextField) -> str:
        # a field that is a property and nothing else reads as one in the
        # text, so all text is edited the one way
        if item.kind == dwg.PROPERTY:
            return "<%s>" % item.text
        return item.text

    def _fill_table(self) -> None:
        self._loading = True
        self.table.setRowCount(0)
        for item in self.block.fields:
            r = self.table.rowCount()
            self.table.insertRow(r)
            values = [self._shown(item), "%g" % item.x, "%g" % item.y,
                      "%g" % item.height]
            for c, v in enumerate(values):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(v))
            bold = QtWidgets.QTableWidgetItem()
            bold.setFlags(bold.flags() | QtCore.Qt.ItemIsUserCheckable)
            bold.setCheckState(QtCore.Qt.Checked if item.bold
                               else QtCore.Qt.Unchecked)
            self.table.setItem(r, 4, bold)
            self.table.setItem(r, 5, QtWidgets.QTableWidgetItem(item.align))
        self._loading = False
        self.preview.update()

    def _table_changed(self, cell) -> None:
        if self._loading:
            return
        r, c = cell.row(), cell.column()
        if not 0 <= r < len(self.block.fields):
            return
        item = self.block.fields[r]
        text = cell.text()
        try:
            if c == 0:
                kind, value = _parse_text(text)
                item.kind = kind if item.kind != dwg.PROMPTED else item.kind
                item.text = value
            elif c == 1:
                item.x = float(text)
            elif c == 2:
                item.y = float(text)
            elif c == 3:
                item.height = max(0.5, float(text))
            elif c == 4:
                item.bold = cell.checkState() == QtCore.Qt.Checked
            elif c == 5:
                item.align = text if text in ("left", "centre", "right") \
                    else "left"
        except ValueError:
            pass
        self.preview.update()

    def _add_text(self) -> None:
        self.block.fields.append(dwg.TextField(
            "text%d" % (len(self.block.fields) + 1), dwg.STATIC, "Text",
            x=2.0, y=2.0, height=2.5))
        self._fill_table()
        self.table.selectRow(len(self.block.fields) - 1)

    def _remove_text(self) -> None:
        r = self.current_row()
        if 0 <= r < len(self.block.fields):
            del self.block.fields[r]
            self._fill_table()

    def _insert_property(self) -> None:
        r = self.current_row()
        if r < 0:
            self._add_text()
            r = len(self.block.fields) - 1
            self.block.fields[r].text = ""
        item = self.block.fields[r]
        token = "<%s>" % self.prop.currentData()
        joined = self._shown(item)
        joined = token if joined in ("", "Text") else joined + " " + token
        kind, value = _parse_text(joined)
        item.kind, item.text = kind, value
        self._fill_table()
        self.table.selectRow(r)

    def _lines_changed(self) -> None:
        lines: List[List[float]] = []
        for raw in self.lines.toPlainText().splitlines():
            parts = raw.replace(",", " ").split()
            if len(parts) >= 4:
                try:
                    lines.append([float(v) for v in parts[:4]])
                except ValueError:
                    continue
        self.block.lines = lines
        self.preview.update()

    def apply(self) -> None:
        """Into the drawing: every sheet using the block follows."""
        self.doc.title_blocks[self.name] = self.block


def _parse_text(text: str):
    """A field's text as typed: ``<Key>`` alone is a property field, any
    other text is static, with properties standing among its words."""
    stripped = text.strip()
    if (stripped.startswith("<") and stripped.endswith(">")
            and stripped.count("<") == 1
            and _known(stripped[1:-1])):
        return dwg.PROPERTY, stripped[1:-1]
    return dwg.STATIC, text


def _known(key: str) -> bool:
    return key.split(".", 1)[0] in ("Model", "Drawing", "Sheet")


class BorderDialog(QtWidgets.QDialog):
    """Inventor's default border: margins, and zones up the edges."""

    def __init__(self, parent, doc: dwg.DrawingDocument, name: str) -> None:
        super().__init__(parent)
        self.doc, self.name = doc, name
        border = doc.borders[name]
        self.setWindowTitle("Edit Border - %s" % name)
        form = QtWidgets.QFormLayout(self)

        def spin(value, low=0.0, high=100.0):
            box = QtWidgets.QDoubleSpinBox()
            box.setRange(low, high)
            box.setDecimals(1)
            box.setSuffix(" mm")
            box.setValue(value)
            return box

        self.margin = spin(border.margin)
        self.left = spin(border.left_margin)
        self.zones = QtWidgets.QCheckBox("Zones with letters and numbers")
        self.zones.setChecked(border.zones)
        self.zone_size = spin(border.zone_size, 1.0, 30.0)
        form.addRow("Margin", self.margin)
        form.addRow("Left margin", self.left)
        form.addRow("", self.zones)
        form.addRow("Zone band", self.zone_size)
        note = QtWidgets.QLabel("Every sheet using this border changes "
                                "with it.")
        note.setProperty("hint", True)
        form.addRow(note)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self) -> None:
        border = self.doc.borders[self.name]
        border.margin = self.margin.value()
        border.left_margin = self.left.value()
        border.zones = self.zones.isChecked()
        border.zone_size = self.zone_size.value()


def block_rect(doc: dwg.DrawingDocument, sheet: dwg.Sheet
               ) -> Optional[tuple]:
    """Where the sheet's title block sits, in sheet millimetres."""
    block = doc.title_blocks.get(sheet.title_block)
    if block is None:
        return None
    width, height = sheet.extent()
    border = doc.borders.get(sheet.border)
    x1, y0 = ((border.frame(width, height)[2], border.frame(width, height)[1])
              if border else (width - 10.0, 10.0))
    return (x1 - block.width, y0, x1, y0 + block.height)
