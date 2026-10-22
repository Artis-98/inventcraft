"""Colour palette and application stylesheet."""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6 import QtGui

from ..core import prefs as user_prefs


def _linear(hex_colour: str):
    """An sRGB colour as the linear light the 3D view wants it in."""
    out = []
    for i in (1, 3, 5):
        c = int(hex_colour[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045
                   else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(round(v, 4) for v in out)


def _screen(hex_colour: str) -> str:
    """The value that shows as this colour once the 3D view has had it.

    The view takes a colour as linear light and brightens it on the way to
    the screen, so a mid green typed in comes out pastel and dark ink comes
    out grey.  On a dark backdrop that is what DATUM was tuned with; on the
    light one the sketch has to read as ink, so its colours are written as
    the screen should show them and stored as what the view wants.
    """
    return "#%02x%02x%02x" % tuple(
        int(round(v * 255)) for v in _linear(hex_colour))


# InventCraft's own scheme: white chrome, dark text, and the beaver's amber
# for whatever is picked, checked or in focus.  The 3D view is a white to
# cool grey wash, as Inventor's light one, so a sketch is drawn in dark
# ink and a part keeps its black edges.
LIGHT = {
    "window": "#f4f4f2",
    "ribbon": "#fbfbfa",
    "ribbon_tab": "#ececea",
    "ribbon_tab_active": "#fbfbfa",
    "panel": "#f8f8f6",
    "panel_alt": "#ebebe8",
    "border": "#d6d6d1",
    "border_light": "#bebeb8",
    "text": "#20242a",
    "text_dim": "#646b73",
    "text_bright": "#000000",
    "text_disabled": "#a4a9af",
    "field_disabled": "#ececea",
    "button_disabled": "#efefec",
    "hover_overlay": "rgba(0, 0, 0, 0.07)",
    "tree_hidden": "#a0a6ad",
    "tree_faint": "#8f969d",
    "accent": "#d5a129",
    "accent_dark": "#c48f1b",
    "accent_soft": "#f5e5bc",
    "on_accent": "#1c1a14",
    "error": "#c8303e",
    "warn": "#b06f12",
    "ok": "#2c8a3c",
    "sketch_line": _screen("#1c2229"),
    "sketch_free": _screen("#6a4fd8"),
    "sketch_construction": _screen("#7c8691"),
    "sketch_ground": _screen("#23944f"),
    "sketch_dim": _screen("#157a53"),
    "sketch_selected": _screen("#d08a00"),
    "sketch_hover": _screen("#14a058"),
    "sketch_picked": _screen("#1f6fd1"),
    "sketch_drag": _screen("#d08a00"),
    "sketch_magnet": _screen("#14a058"),
    "sketch_fixed": _screen("#2f8a3a"),
    "sketch_preview": _screen("#6f7c8a"),
    "sketch_reference": _screen("#7a8591"),
    "sketch_reference_dim": _screen("#5f6b78"),
    "axis_label": _screen("#3a434d"),
    "cube_box": "#cfd5dc",
    "cube_text": "#000000",
    "cube_axis_label": _screen("#2b333d"),
    "wordmark": "#20242a",
    "origin_mark": _screen("#2b333d"),
    "bg_top": _linear("#f8f9fa"),
    "bg_bottom": _linear("#c4ccd5"),
    "material": (0.700, 0.704, 0.708),
    "material_edge": (0.0, 0.0, 0.0),
    "highlight": _linear("#e8a020"),
    "preselect": (0.050, 0.350, 1.000),
    "paper_selected": "#5b6b7d",
}

# The dark scheme DATUM shipped until 0.3.0, kept as it was.
DARK = {
    "window": "#1e2124",
    "ribbon": "#2a2e32",
    "ribbon_tab": "#212528",
    "ribbon_tab_active": "#2a2e32",
    "panel": "#24282c",
    "panel_alt": "#2e3338",
    "border": "#3a4046",
    "border_light": "#4b535b",
    "text": "#dfe3e8",
    "text_dim": "#98a1aa",
    "text_bright": "#ffffff",
    "text_disabled": "#5b636c",
    "field_disabled": "#24272b",
    "button_disabled": "#262a2e",
    "hover_overlay": "rgba(255, 255, 255, 0.10)",
    "tree_hidden": "#5d656e",
    "tree_faint": "#666e78",
    "accent": "#c2ccd8",
    "accent_dark": "#9aa7b6",
    "accent_soft": "#3d4854",
    "on_accent": "#171a20",
    "error": "#e05561",
    "warn": "#e0a355",
    "ok": "#69c26b",
    "sketch_line": "#e8ecef",
    "sketch_free": "#9a8cf2",
    "sketch_construction": "#8a93a0",
    "sketch_ground": "#67d08a",
    "sketch_dim": "#78c8a0",
    "sketch_selected": "#ffcf4d",
    "sketch_hover": "#4ee08a",
    "sketch_picked": "#2f7fd6",
    "sketch_drag": "#ffcf4d",
    "sketch_magnet": "#4ee08a",
    "sketch_fixed": "#67b96a",
    "sketch_preview": "#aebbc9",
    "sketch_reference": "#7f8894",
    "sketch_reference_dim": "#95a0ad",
    "axis_label": "#c8d0da",
    "cube_box": "#3a434f",
    "cube_text": "#ffffff",
    "cube_axis_label": "#ffff00",
    "wordmark": "#d5dee8",
    "origin_mark": "#e8ecef",
    "bg_top": (0.0545, 0.0648, 0.0844),
    "bg_bottom": (0.0130, 0.0152, 0.0194),
    "material": (0.835, 0.839, 0.843),
    "material_edge": (0.0, 0.0, 0.0),
    "highlight": (1.000, 0.812, 0.302),
    "preselect": (0.050, 0.350, 1.000),
    "paper_selected": "#5b6b7d",
}

THEMES = {"light": LIGHT, "dark": DARK}

# The tones the toolbar icons are drawn in: an outline, an accent and a
# solid, a clear step apart so a 16 pixel icon does not turn to a smudge.
ICON_TONES = {
    "light": ("#2b3540", "#b9820f", "#7a8693"),
    "dark": ("#d5dee8", "#93a6bb", "#67737f"),
}

_current = "light"


class C:
    """Named colours - one place to retune the whole application.

    Filled from the scheme in use; ``set_theme`` swaps them all at once.
    """


for _name, _value in LIGHT.items():
    setattr(C, _name, _value)


def current_theme() -> str:
    return _current


def set_theme(name: str) -> None:
    """Use a colour scheme: every named colour taken from it."""
    global _current
    _current = name if name in THEMES else "light"
    for key, value in THEMES[_current].items():
        setattr(C, key, value)


FONT_STACK = '"Segoe UI", "Inter", system-ui, sans-serif'
MONO_STACK = '"Cascadia Mono", "Consolas", monospace'
# The wordmark wants a heavy grotesque with flat sides, not the interface
# font at a heavier weight - Segoe UI has no black cut, so it falls back to
# whichever of these is installed before settling for bolding the UI face.
WORDMARK_STACK = ('"Archivo Black", "Inter", "Segoe UI Variable Display",'
                  ' "Segoe UI Semibold", "Arial Black", sans-serif')


def qcolor(hex_or_tuple) -> QtGui.QColor:
    if isinstance(hex_or_tuple, str):
        return QtGui.QColor(hex_or_tuple)
    r, g, b = hex_or_tuple
    return QtGui.QColor(int(r * 255), int(g * 255), int(b * 255))


STYLESHEET = """
* {{
    font-family: {font};
    font-size: 12px;
}}

QWidget {{
    background: {window};
    color: {text};
}}

QMainWindow::separator {{
    background: {border};
    width: 1px;
    height: 1px;
}}

/* ---------------------------------------------------------------- ribbon */

#RibbonBar {{
    background: {ribbon};
    border-bottom: 1px solid {border};
}}

QToolButton#WindowButton, QToolButton#WindowClose {{
    border: none;
    border-radius: 0px;
    background: transparent;
}}
QToolButton#WindowButton:hover {{
    background: {hover_overlay};
}}
QToolButton#WindowClose:hover {{
    background: #c42b1c;
}}

#RibbonQat {{
    background: {window};
    border-bottom: 1px solid {border};
}}

#RibbonTabStrip {{
    background: {ribbon_tab};
    border-bottom: 1px solid {border};
}}

#RibbonTabButton {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 6px 16px 5px 16px;
    color: {text_dim};
    font-size: 12px;
}}
#RibbonTabButton:hover {{
    color: {text};
    background: {panel_alt};
}}
#RibbonTabButton:checked {{
    color: {text_bright};
    background: {ribbon};
    border-bottom: 2px solid {accent};
    font-weight: 600;
}}

#RibbonPanel {{
    background: transparent;
    border-right: 1px solid {border};
}}

#QuickButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
}}
#QuickButton:hover {{
    background: {panel_alt};
    border: 1px solid {border_light};
}}
#QuickButton:pressed {{
    background: {accent_soft};
}}
#QuickButton:checked {{
    background: {accent_soft};
    border: 1px solid {accent};
}}

#RibbonPanelTitle {{
    color: {text_dim};
    font-size: 10px;
    padding-top: 1px;
}}

#RibbonButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 4px 6px;
    color: {text};
    text-align: center;
}}
#RibbonButton:hover {{
    background: {panel_alt};
    border: 1px solid {border_light};
}}
#RibbonButton:pressed, #RibbonButton:checked {{
    background: {accent_soft};
    border: 1px solid {accent};
}}
#RibbonButton:disabled {{
    color: {text_disabled};
}}

#RibbonSmallButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 2px 8px 2px 4px;
    color: {text};
    text-align: left;
}}
#RibbonSmallButton:hover {{
    background: {panel_alt};
    border: 1px solid {border_light};
}}
#RibbonSmallButton:pressed, #RibbonSmallButton:checked {{
    background: {accent_soft};
    border: 1px solid {accent};
}}
#RibbonSmallButton:disabled {{
    color: {text_disabled};
}}

/* ----------------------------------------------------------- dock panels */

QDockWidget {{
    color: {text_dim};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {panel_alt};
    padding: 5px 8px;
    border-bottom: 1px solid {border};
    font-size: 11px;
    font-weight: 600;
    color: {text};
}}

QTreeWidget, QTreeView, QListWidget, QTableWidget {{
    background: {panel};
    alternate-background-color: {panel_alt};
    border: none;
    outline: none;
    selection-background-color: {accent_soft};
}}
QTreeWidget::item, QListWidget::item {{
    padding: 3px 2px;
    border: none;
}}
QTreeWidget::item:hover, QListWidget::item:hover {{
    background: {panel_alt};
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {accent_soft};
    color: {text_bright};
}}
QHeaderView::section {{
    background: {panel_alt};
    color: {text_dim};
    padding: 4px 6px;
    border: none;
    border-right: 1px solid {border};
    border-bottom: 1px solid {border};
}}
QTableWidget {{
    gridline-color: {border};
}}
QTableWidget::item:selected {{
    background: {accent_soft};
}}

/* --------------------------------------------------------------- inputs */

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {ribbon_tab};
    border: 1px solid {border};
    border-radius: 3px;
    padding: 4px 6px;
    color: {text};
    selection-background-color: {accent};
    /* the accent is light now, so highlighted text has to go dark */
    selection-color: {on_accent};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus {{
    border: 1px solid {accent};
}}
QLineEdit[invalid="true"] {{
    border: 1px solid {error};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {text_disabled};
    background: {field_disabled};
}}

QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background: {panel_alt};
    border: 1px solid {border_light};
    selection-background-color: {accent_soft};
    outline: none;
}}

QPushButton {{
    background: {panel_alt};
    border: 1px solid {border_light};
    border-radius: 3px;
    padding: 5px 14px;
    color: {text};
    min-width: 68px;
}}
QPushButton:hover {{
    background: {border};
    border-color: {accent};
}}
QPushButton:pressed {{
    background: {accent_soft};
}}
QPushButton:disabled {{
    color: {text_disabled};
    background: {button_disabled};
}}
QPushButton[primary="true"] {{
    background: {accent_dark};
    border-color: {accent};
    color: {on_accent};
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{
    background: {accent};
}}

QCheckBox, QRadioButton {{
    spacing: 6px;
    padding: 2px 0;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {border_light};
    background: {ribbon_tab};
    border-radius: 2px;
}}
QRadioButton::indicator {{
    border-radius: 7px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}

QGroupBox {{
    border: 1px solid {border};
    border-radius: 3px;
    margin-top: 9px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {text_dim};
    font-size: 11px;
}}

QLabel[hint="true"] {{
    color: {text_dim};
    font-size: 11px;
}}
QLabel[error="true"] {{
    color: {error};
}}

/* -------------------------------------------------------------- various */

QToolTip {{
    background: {panel_alt};
    color: {text};
    border: 1px solid {border_light};
    padding: 4px 6px;
}}

QStatusBar {{
    background: {ribbon_tab};
    border-top: 1px solid {border};
    color: {text_dim};
}}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {border_light};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
}}
QScrollBar::handle:horizontal {{
    background: {border_light};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{
    background: {panel_alt};
    border: 1px solid {border_light};
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 24px 5px 10px;
    border-radius: 2px;
}}
QMenu::item:selected {{ background: {accent_soft}; }}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 4px 6px;
}}

QSplitter::handle {{ background: {border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QProgressBar {{
    border: 1px solid {border};
    border-radius: 2px;
    background: {ribbon_tab};
    text-align: center;
    height: 6px;
}}
QProgressBar::chunk {{ background: {accent}; }}
"""


def stylesheet() -> str:
    return browser_mode_css() + STYLESHEET.format(
        font=FONT_STACK,
        window=C.window,
        ribbon=C.ribbon,
        ribbon_tab=C.ribbon_tab,
        panel=C.panel,
        panel_alt=C.panel_alt,
        border=C.border,
        border_light=C.border_light,
        text=C.text,
        text_dim=C.text_dim,
        text_bright=C.text_bright,
        accent=C.accent,
        accent_dark=C.accent_dark,
        accent_soft=C.accent_soft,
        on_accent=C.on_accent,
        error=C.error,
        text_disabled=C.text_disabled,
        field_disabled=C.field_disabled,
        button_disabled=C.button_disabled,
        hover_overlay=C.hover_overlay,
    )


def browser_mode_css() -> str:
    return BROWSER_MODE_CSS % {
        "panel": C.panel, "border": C.border, "dim": C.text_dim,
        "text": C.text, "accent": C.accent}


BROWSER_MODE_CSS = """
#BrowserModeBar { background: %(panel)s;
                  border-bottom: 1px solid %(border)s; }
#BrowserModeTab { color: %(dim)s; background: transparent; border: none;
                  border-bottom: 2px solid transparent;
                  padding: 3px 10px 4px 10px; font-size: 11px; }
#BrowserModeTab:hover { color: %(text)s; }
#BrowserModeTab:checked { color: %(text)s;
                          border-bottom: 2px solid %(accent)s; }
""" % {"panel": C.panel, "border": C.border, "dim": C.text_dim,
       "text": C.text, "accent": C.accent}


# --------------------------------------------------------------- overrides
#
# The palette above is what DATUM ships with.  A user may repaint a few of
# it from Preferences - the viewport background and the sketch line
# colours - and those are theirs, not the document's, so they live in the
# preferences file and are laid over the palette at startup.

def shipped(key: str) -> Any:
    """The colour the scheme in use came with, whatever it is set to now."""
    return THEMES[_current].get(key)


def as_hex(value: Any) -> str:
    """A palette entry as "#rrggbb", whether it is stored that way or not.

    The viewport wants its background as floats and everything else wants
    a string, which is an implementation detail no colour picker should
    have to know about.
    """
    if isinstance(value, tuple):
        return "#%02x%02x%02x" % tuple(
            max(0, min(255, int(round(c * 255.0)))) for c in value[:3])
    return str(value)


def _as_stored(key: str, text: str) -> Any:
    if isinstance(shipped(key), tuple):
        text = text.lstrip("#")
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return text


def apply_colours(mapping: Optional[Dict[str, str]] = None) -> None:
    """Lay the user's colours over the palette, or take them off again."""
    chosen = (user_prefs.prefs().colours_for(_current) if mapping is None
              else mapping)
    for key, shipped_value in THEMES[_current].items():
        text = chosen.get(key)
        try:
            setattr(C, key, _as_stored(key, text) if text else shipped_value)
        except (ValueError, IndexError):
            setattr(C, key, shipped_value)
