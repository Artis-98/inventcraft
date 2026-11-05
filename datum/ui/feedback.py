"""The Suggest button: a suggestion or a problem, sent straight to IITEG.

It lands on IITEG's own board, read by the people building InventCraft,
not in a public tracker. Offline it waits in a small queue beside the
preferences and goes the next time the application starts with a
connection. Nothing is sent but what is typed, the version and the
operating system.
"""
from __future__ import annotations

import json
import os
import platform
import threading
import urllib.request
from typing import Dict, List

from PySide6 import QtCore, QtWidgets

from .. import __version__
from ..core import prefs

ENDPOINT = "https://api.iiteg.com/datum-feedback.php"
QUEUE = "feedback-queue.json"


def _queue_path() -> str:
    return prefs.config_path(QUEUE)


def _read_queue() -> List[Dict[str, str]]:
    try:
        with open(_queue_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_queue(items: List[Dict[str, str]]) -> None:
    try:
        os.makedirs(os.path.dirname(_queue_path()), exist_ok=True)
        with open(_queue_path(), "w", encoding="utf-8") as handle:
            json.dump(items, handle)
    except OSError:
        pass


def send(message: Dict[str, str], timeout: float = 15.0) -> bool:
    """One message to the server; True when it took it."""
    body = json.dumps(message).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "InventCraft/%s" % __version__})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return 200 <= reply.status < 300
    except Exception:
        return False


def flush_queue() -> None:
    """Whatever waited while offline, sent now, in the background."""
    waiting = _read_queue()
    if not waiting:
        return

    def run():
        left = [m for m in waiting if not send(m)]
        _write_queue(left)
    threading.Thread(target=run, daemon=True).start()


def message(kind: str, text: str, email: str = "") -> Dict[str, str]:
    return {"kind": kind, "text": text, "email": email,
            "version": __version__,
            "os": "%s %s" % (platform.system(), platform.release())}


class FeedbackDialog(QtWidgets.QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Suggest or Report a Problem")
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Goes straight to the people building InventCraft. Say what "
            "you would like, or what went wrong and what you were doing.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        kinds = QtWidgets.QHBoxLayout()
        self.suggestion = QtWidgets.QRadioButton("Suggestion")
        self.problem = QtWidgets.QRadioButton("Problem")
        self.suggestion.setChecked(True)
        kinds.addWidget(self.suggestion)
        kinds.addWidget(self.problem)
        kinds.addStretch(1)
        layout.addLayout(kinds)

        self.text = QtWidgets.QPlainTextEdit()
        self.text.setPlaceholderText("Your suggestion or problem")
        layout.addWidget(self.text, 1)

        self.email = QtWidgets.QLineEdit()
        self.email.setPlaceholderText("Email, only if you would like a reply")
        layout.addWidget(self.email)

        note = QtWidgets.QLabel("Sent with the version (%s) and the "
                                "operating system, nothing else." % __version__)
        note.setProperty("hint", True)
        layout.addWidget(note)

        buttons = QtWidgets.QDialogButtonBox()
        self.send_button = buttons.addButton(
            "Send", QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._send)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(480, 360)

    def _send(self) -> None:
        text = self.text.toPlainText().strip()
        if not text:
            self.text.setFocus()
            return
        item = message("problem" if self.problem.isChecked() else "suggestion",
                       text[:4000], self.email.text().strip())
        self.send_button.setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            sent = send(item)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if not sent:
            _write_queue(_read_queue() + [item])
            QtWidgets.QMessageBox.information(
                self, "Kept for later",
                "There is no connection right now. It will be sent the "
                "next time InventCraft starts online.")
        else:
            QtWidgets.QMessageBox.information(self, "Thank you",
                                              "Sent. Thank you!")
        self.accept()
