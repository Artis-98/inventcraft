"""The window in another language, simply.

Not a Qt translation of every string in the code, which would mean
wrapping thousands of them one by one, but a table of what is shown:
English text in, the language's text out, put on each button, label,
menu, tab and tooltip as it comes on screen. Whatever the table has not
got stays in English, so a language can be added to bit by bit and a
missing line never breaks anything.

The tables are ``assets/lang/<code>.json``:

    {"name": "Deutsch", "strings": {"Save": "Speichern", ...}}

A table entry matches the text as shown, or the text without its menu
accelerator (``&``), its shortcut (after a tab) and a trailing ``...``,
``:`` or ``…``, which are put back on the translation. A tooltip of
several paragraphs is looked up whole and then paragraph by paragraph.

Qt's own words (OK, Cancel, the file dialogs) come from Qt's translation
for the language when Qt ships one.

``DATUM_LANGUAGE`` overrides the preference, and ``DATUM_I18N_RECORD`` set
to a file name writes every text that was shown without a translation to
it at exit, which is how a table is filled in.
"""
from __future__ import annotations

import atexit
import json
import os
import re
from typing import Dict, Optional, Set

from PySide6 import QtCore, QtWidgets

ENGLISH = "en"
_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "assets", "lang")

_code = ENGLISH
_table: Dict[str, str] = {}
_reverse: Dict[str, str] = {}
_misses: Optional[Set[str]] = None
_filter = None
_qt_translator = None

# the end of a menu entry or a label that is not part of the words
_TAIL = re.compile(r"(\s*(?:\.\.\.|…|:)?\s*)$")


def languages() -> Dict[str, str]:
    """The languages there are tables for, code -> own name, English
    first."""
    found = {ENGLISH: "English"}
    try:
        names = sorted(os.listdir(_FOLDER))
    except OSError:
        names = []
    for name in names:
        if name.endswith(".json"):
            try:
                with open(os.path.join(_FOLDER, name), encoding="utf-8") as f:
                    found[name[:-5]] = str(json.load(f).get("name")
                                           or name[:-5])
            except (OSError, ValueError):
                pass
    return found


def current() -> str:
    return _code


def load(code: str) -> None:
    """Use this language's table from now on; English needs none."""
    global _code, _table, _reverse
    _code = code or ENGLISH
    _table, _reverse = {}, {}
    if _code == ENGLISH:
        return
    try:
        with open(os.path.join(_FOLDER, _code + ".json"),
                  encoding="utf-8") as f:
            strings = json.load(f).get("strings") or {}
    except (OSError, ValueError):
        strings = {}
    _table = {str(k): str(v) for k, v in strings.items() if v}
    _reverse = {v: k for k, v in _table.items()}


def _word(text: str) -> Optional[str]:
    """The table's entry for one piece of text, trying it as it is, then
    without the accelerator and the dots or colon at its end."""
    hit = _table.get(text)
    if hit is not None:
        return hit
    plain = text.replace("&&", "\0").replace("&", "").replace("\0", "&")
    tail = _TAIL.search(plain).group(1)
    core = plain[:len(plain) - len(tail)] if tail else plain
    lead = core[:len(core) - len(core.lstrip())]
    core = core.strip()
    if not core:
        return None
    hit = _table.get(core)
    if hit is None:
        return None
    return lead + hit + tail


def tr(text: str) -> str:
    """The text in the language in use, or as it is when there is no
    translation for it."""
    if not text or (not _table and _misses is None):
        return text
    if text in _reverse:
        return text
    words, tab, keys = text.partition("\t")
    hit = _word(words)
    if hit is None and "\n" in words:
        parts = words.split("\n")
        done = [(_word(p) if p.strip() else p) for p in parts]
        if any(d is not None for d in done):
            hit = "\n".join(d if d is not None else p
                            for d, p in zip(done, parts))
        for p, d in zip(parts, done):
            if d is None and p.strip():
                _missed(p)
    elif hit is None:
        _missed(words)
    return (hit if hit is not None else words) + tab + keys


def english(text: str) -> str:
    """What a translated text was in English: for code that reads a label
    back to decide something."""
    words, tab, keys = text.partition("\t")
    if words in _reverse:
        return _reverse[words] + tab + keys
    return text


def _missed(text: str) -> None:
    if _misses is not None and any(c.isalpha() for c in text) \
            and text not in _reverse:
        _misses.add(text.strip())


# ------------------------------------------------------------ the widgets


def _swap(obj, key: str, get, put) -> None:
    """Put the translation of what ``get`` returns, once: the translated
    text is remembered on the object, so seeing it again does nothing,
    while a new text set since is translated in turn."""
    try:
        text = get()
    except RuntimeError:
        return
    if not text or obj.property(key) == text:
        return
    new = tr(text)
    if new != text:
        put(new)
    obj.setProperty(key, new)


def apply(widget) -> None:
    """Translate one widget's own words: its text, title, placeholder,
    tabs or menu entries, as fits what it is."""
    if isinstance(widget, QtWidgets.QAbstractButton):
        _swap(widget, "_i18n_text", widget.text, widget.setText)
    elif isinstance(widget, QtWidgets.QLabel):
        _swap(widget, "_i18n_text", widget.text, widget.setText)
    elif isinstance(widget, QtWidgets.QGroupBox):
        _swap(widget, "_i18n_text", widget.title, widget.setTitle)
    elif isinstance(widget, QtWidgets.QLineEdit):
        _swap(widget, "_i18n_hint", widget.placeholderText,
              widget.setPlaceholderText)
    elif isinstance(widget, QtWidgets.QAbstractSpinBox):
        _swap(widget, "_i18n_special", widget.specialValueText,
              widget.setSpecialValueText)
    elif isinstance(widget, QtWidgets.QTabBar):
        for i in range(widget.count()):
            _swap(widget, "_i18n_tab%d" % i,
                  lambda i=i: widget.tabText(i),
                  lambda t, i=i: widget.setTabText(i, t))
    elif isinstance(widget, QtWidgets.QMenu):
        _swap(widget, "_i18n_text", widget.title, widget.setTitle)
        for action in widget.actions():
            _swap(action, "_i18n_text", action.text, action.setText)
    if isinstance(widget, QtWidgets.QTreeWidget):
        head = widget.headerItem()
        for i in range(head.columnCount()):
            text = head.text(i)
            new = tr(text)
            if new != text:
                head.setText(i, new)
    if isinstance(widget, QtWidgets.QComboBox):
        # only a list whose every entry carries its own data: the code
        # then reads the data, never the words, so they can change
        count = widget.count()
        if count and all(widget.itemData(i) is not None
                         for i in range(count)):
            for i in range(count):
                _swap(widget, "_i18n_item%d" % i,
                      lambda i=i: widget.itemText(i),
                      lambda t, i=i: widget.setItemText(i, t))
    if isinstance(widget, QtWidgets.QDockWidget):
        _swap(widget, "_i18n_title", widget.windowTitle,
              widget.setWindowTitle)
    if isinstance(widget, QtWidgets.QDialog):
        _swap(widget, "_i18n_title", widget.windowTitle,
              widget.setWindowTitle)


class _Translator(QtCore.QObject):
    """Every widget's words, as it comes on screen, and its tooltip as
    that is about to show."""

    SHOW = QtCore.QEvent.Show
    TIP = QtCore.QEvent.ToolTip

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == self.SHOW:
            if isinstance(obj, QtWidgets.QWidget):
                apply(obj)
        elif kind == self.TIP:
            if isinstance(obj, QtWidgets.QWidget):
                _swap(obj, "_i18n_tip", obj.toolTip, obj.setToolTip)
        return False


def translated_label(label: QtWidgets.QLabel) -> None:
    """A label whose text the code changes while it is on screen, the
    status bar's, translated each time it is set."""
    if not _table and _misses is None:
        return
    put = QtWidgets.QLabel.setText

    def set_text(text, label=label, put=put):
        put(label, tr(text))
    label.setText = set_text
    label.setText(label.text())


def install(app: Optional[QtWidgets.QApplication] = None,
            code: Optional[str] = None) -> None:
    """Start translating, in the language asked for, the preference's, or
    DATUM_LANGUAGE's; once per run, and nothing at all for English unless
    a record of the missing words is being kept."""
    global _filter, _misses, _qt_translator
    app = app or QtWidgets.QApplication.instance()
    if app is None or _filter is not None:
        return
    if code is None:
        code = os.environ.get("DATUM_LANGUAGE", "")
    if not code:
        try:
            from ..core import prefs
            code = prefs.prefs().language
        except Exception:
            code = ENGLISH
    record = os.environ.get("DATUM_I18N_RECORD", "")
    if record and _misses is None:
        _misses = set()
        atexit.register(_write_misses, record)
    load(code)
    if not _table and _misses is None:
        return
    if _code != ENGLISH:
        _qt_translator = QtCore.QTranslator(app)
        where = QtCore.QLibraryInfo.path(
            QtCore.QLibraryInfo.LibraryPath.TranslationsPath)
        if _qt_translator.load("qtbase_" + _code, where):
            app.installTranslator(_qt_translator)
    _filter = _Translator(app)
    app.installEventFilter(_filter)


def _write_misses(path: str) -> None:
    """This run's untranslated texts, beside the record file."""
    # one file a process, since test suites run side by side
    try:
        with open("%s.%d" % (path, os.getpid()), "w",
                  encoding="utf-8") as f:
            json.dump(sorted(_misses or set()), f, ensure_ascii=False,
                      indent=0)
    except OSError:
        pass
