"""The Versions window: check in, history, branches.

The open document's history, newest first, on the branch it is on or on
every branch.  Check In keeps the file as saved, with a note of why.
Restore, New Branch, switching branch and Merge put another version in
the file's place, so the document is opened again from it afterwards.
"""
from __future__ import annotations

import os

from PySide6 import QtCore, QtWidgets

from ..core import history


class VersionsDialog(QtWidgets.QDialog):
    def __init__(self, host, path: str) -> None:
        super().__init__(host)
        self.host = host
        self.path = path
        self.setWindowTitle("Versions - %s" % os.path.basename(path))
        self.resize(680, 460)
        layout = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Branch", self))
        self.branch = QtWidgets.QComboBox(self)
        self.branch.activated.connect(self._switch)
        top.addWidget(self.branch, 1)
        self.every = QtWidgets.QCheckBox("Every branch", self)
        self.every.toggled.connect(self.refresh)
        top.addWidget(self.every)
        layout.addLayout(top)

        self.table = QtWidgets.QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["Version", "Branch", "When", "Who", "Why"])
        self.table.horizontalHeader().setSectionResizeMode(
            4, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        check = QtWidgets.QHBoxLayout()
        self.message = QtWidgets.QLineEdit(self)
        self.message.setPlaceholderText("What changed")
        check.addWidget(self.message, 1)
        self.check_in_button = QtWidgets.QPushButton("Check In", self)
        self.check_in_button.clicked.connect(self.check_in)
        check.addWidget(self.check_in_button)
        layout.addLayout(check)

        row = QtWidgets.QHBoxLayout()
        for label, slot, tip in (
                ("Restore", self.restore,
                 "Put the picked version back; it comes back as the newest"),
                ("New Branch...", self.new_branch,
                 "A branch from the picked version, to try something"),
                ("Merge into main", self.merge,
                 "main takes this branch's latest as its next version")):
            button = QtWidgets.QPushButton(label, self)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        self.state = QtWidgets.QLabel("", self)
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.refresh()

    # -- what is shown -------------------------------------------------------

    def refresh(self) -> None:
        h = history.load(self.path)
        self.branch.blockSignals(True)
        self.branch.clear()
        names = sorted(h.branches) or [history.MAIN]
        for name in names:
            self.branch.addItem(name)
        self.branch.setCurrentText(h.current)
        self.branch.blockSignals(False)
        rows = h.all() if self.every.isChecked() else h.line()
        self.table.setRowCount(len(rows))
        head = h.head()
        for i, v in enumerate(rows):
            mark = " *" if head is not None and v.id == head.id else ""
            for col, text in enumerate((str(v.id) + mark, v.branch, v.when,
                                        v.author, v.message)):
                item = QtWidgets.QTableWidgetItem(text)
                item.setData(QtCore.Qt.UserRole, v.id)
                self.table.setItem(i, col, item)
        if not h.versions:
            self.state.setText("No versions yet. Check In keeps this file "
                               "as it is saved now.")
        elif history.changed(self.path, h):
            self.state.setText("The file has changes since version %d."
                               % head.id)
        else:
            self.state.setText("The file is version %d, on %s."
                               % (head.id, h.current))

    def picked(self) -> int:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return int(item.data(QtCore.Qt.UserRole)) if item else 0

    # -- doing --------------------------------------------------------------

    def _fail(self, exc) -> None:
        self.state.setText(str(exc)[:1].upper() + str(exc)[1:] + ".")

    def check_in(self) -> None:
        if not self.host.save_versioned(self.path):
            return
        try:
            v = history.check_in(self.path, self.message.text().strip())
        except history.HistoryError as exc:
            self._fail(exc)
            return
        self.message.clear()
        self.refresh()
        self.host.status_message.setText("Checked in as version %d." % v.id)

    def _changes_kept(self) -> bool:
        """The file's unsaved or unchecked work is not lost silently."""
        if not self.host.save_versioned(self.path):
            return False
        if history.load(self.path).versions and history.changed(self.path):
            answer = QtWidgets.QMessageBox.question(
                self, "Versions",
                "The file has changes that are not checked in. Check them "
                "in first?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                | QtWidgets.QMessageBox.Cancel)
            if answer == QtWidgets.QMessageBox.Cancel:
                return False
            if answer == QtWidgets.QMessageBox.Yes:
                history.check_in(self.path, "Before switching")
            return True
        return True

    def _after(self, text: str) -> None:
        self.host.reload_from_disk(self.path)
        self.refresh()
        self.host.status_message.setText(text)

    def restore(self) -> None:
        vid = self.picked()
        if not vid or not self._changes_kept():
            return
        try:
            v = history.restore(self.path, vid, force=True)
        except history.HistoryError as exc:
            self._fail(exc)
            return
        self._after("Version %d restored, as version %d." % (vid, v.id))

    def new_branch(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Branch", "Name of the branch:")
        if not ok or not name.strip() or not self._changes_kept():
            return
        try:
            history.new_branch(self.path, name.strip(), self.picked())
        except history.HistoryError as exc:
            self._fail(exc)
            return
        self._after("On branch %s." % name.strip())

    def _switch(self, _index=None) -> None:
        name = self.branch.currentText()
        if name == history.load(self.path).current:
            return
        if not self._changes_kept():
            self.refresh()
            return
        try:
            history.switch(self.path, name, force=True)
        except history.HistoryError as exc:
            self._fail(exc)
            self.refresh()
            return
        self._after("On branch %s." % name)

    def merge(self) -> None:
        h = history.load(self.path)
        if h.current == history.MAIN:
            self.state.setText("This is main: switch to the branch to merge "
                               "first.")
            return
        if not self._changes_kept():
            return
        branch = h.current
        try:
            v = history.merge(self.path, branch, history.MAIN)
        except history.HistoryError as exc:
            self._fail(exc)
            return
        self._after("%s merged into main as version %d." % (branch, v.id))
