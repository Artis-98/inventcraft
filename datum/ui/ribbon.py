"""Inventor-style ribbon: a tab strip over panels of command buttons."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from . import icons
from .theme import C


class _Squeezable:
    """A ribbon button that drops its caption when there is no room for it.

    On a scaled up display the ribbon is wider than the window, the layout
    squeezes the buttons, and Qt cut their captions down to "C...nt" and
    "Di...on", which says nothing.  A button too narrow for its words now
    shows only its icon, and hovering it says what it is.
    """

    def squeezed(self) -> bool:
        """Whether the caption would have to be cut short to fit."""
        if self.toolButtonStyle() == QtCore.Qt.ToolButtonIconOnly:
            return False
        return self.width() + 1 < QtWidgets.QToolButton.sizeHint(self).width()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if not self.squeezed():
            QtWidgets.QToolButton.paintEvent(self, event)
            return
        painter = QtWidgets.QStylePainter(self)
        option = QtWidgets.QStyleOptionToolButton()
        self.initStyleOption(option)
        option.toolButtonStyle = QtCore.Qt.ToolButtonIconOnly
        option.text = ""
        painter.drawComplexControl(QtWidgets.QStyle.CC_ToolButton, option)

    def event(self, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.ToolTip and self.squeezed():
            name = " ".join(self.text().split())
            tip = self.toolTip()
            text = name if not tip or tip == name else (
                tip if name.lower() in tip.lower() else "%s - %s" % (name, tip))
            QtWidgets.QToolTip.showText(event.globalPos(), text, self)
            return True
        return QtWidgets.QToolButton.event(self, event)


class RibbonButton(_Squeezable, QtWidgets.QToolButton):
    """Large button: icon on top, caption underneath."""

    def __init__(self, name: str, text: str, tip: str = "",
                 checkable: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("RibbonButton")
        self.setIcon(icons.icon(name, 26))
        self.setIconSize(QtCore.QSize(26, 26))
        self.setText(text)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
        self.setToolTip(tip or text)
        self.setCheckable(checkable)
        self.setAutoRaise(False)
        self.setMinimumWidth(54)
        self.setMaximumWidth(88)
        self.setFixedHeight(68)
        self.setStyleSheet("font-size: 11px;")
        self.setCursor(QtCore.Qt.PointingHandCursor)


class RibbonSmallButton(_Squeezable, QtWidgets.QToolButton):
    """Compact button: icon beside caption, stacked three per column."""

    def __init__(self, name: str, text: str, tip: str = "",
                 checkable: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("RibbonSmallButton")
        self.setIcon(icons.icon(name, 17))
        self.setIconSize(QtCore.QSize(17, 17))
        self.setText(" " + text)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.setToolTip(tip or text)
        self.setCheckable(checkable)
        self.setFixedHeight(20)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setSizePolicy(QtWidgets.QSizePolicy.Minimum,
                           QtWidgets.QSizePolicy.Fixed)

    def set_compact(self, on: bool) -> None:
        """Icon only, packed tight, or icon and caption."""
        self.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly if on
                                else QtCore.Qt.ToolButtonTextBesideIcon)
        self.setMaximumWidth(26 if on else 16777215)


class SplitMenuEntry(QtWidgets.QWidget):
    """One row of a split button's menu: the name over what it does.

    A plain menu action is a single line, and these variants only make sense
    as a pair - "Rectangle" tells you nothing without "Three Point Center"
    underneath it.
    """

    def __init__(self, icon_name: str, title: str, subtitle: str,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SplitEntry")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 14, 4)
        layout.setSpacing(9)

        badge = QtWidgets.QLabel()
        badge.setPixmap(icons.pixmap(icon_name, 20, self.devicePixelRatioF()))
        badge.setFixedWidth(22)
        layout.addWidget(badge)

        text = QtWidgets.QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        head = QtWidgets.QLabel(title)
        head.setStyleSheet("font-weight: 600; color: %s;" % C.text)
        sub = QtWidgets.QLabel(subtitle)
        sub.setStyleSheet("color: %s; font-size: 11px;" % C.text_dim)
        text.addWidget(head)
        text.addWidget(sub)
        layout.addLayout(text, 1)


class RibbonSplitButton(RibbonButton):
    """A big button with a list of variants under an arrow.

    Inventor puts the rectangle, slot and polygon tools behind one button
    like this.  The button keeps showing whichever variant you used last, so
    the common case stays one click and the rest are one click plus a pick.
    """

    chosen = QtCore.Signal(str)

    def __init__(self, options, tip: str = "", parent=None) -> None:
        """``options`` is a list of (key, icon name, title, subtitle)."""
        first = options[0]
        super().__init__(first[1], first[2], tip, True, parent)
        self.options = list(options)
        self.current = first[0]

        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(
            "QMenu { padding: 4px; }"
            " #SplitEntry { background: transparent; }")
        for key, icon_name, title, subtitle in options:
            action = QtWidgets.QWidgetAction(menu)
            entry = SplitMenuEntry(icon_name, title, subtitle, menu)
            action.setDefaultWidget(entry)
            action.triggered.connect(lambda _=False, k=key: self._pick(k))
            menu.addAction(action)
        self.setMenu(menu)
        self.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        # room for the arrow without squeezing the caption
        self.setMaximumWidth(100)
        self.set_current(first[0])
        self.clicked.connect(lambda _=False: self.chosen.emit(self.current))

    @property
    def keys(self):
        return [option[0] for option in self.options]

    def _pick(self, key: str) -> None:
        self.set_current(key)
        self.chosen.emit(key)

    def set_current(self, key: str) -> None:
        for option_key, icon_name, title, subtitle in self.options:
            if option_key != key:
                continue
            self.current = key
            self.setIcon(icons.icon(icon_name, 26))
            # the caption is the variant, because "Rectangle" alone does not
            # say which of the four is armed
            self.setText(title + chr(10) + subtitle)
            self.setToolTip("%s - %s" % (title, subtitle))
            return


class RibbonPanel(QtWidgets.QWidget):
    """A titled group of commands inside a ribbon tab."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("RibbonPanel")
        # Qt does not paint a stylesheet background or border on a plain
        # QWidget subclass unless it is told to, so the separator the
        # theme has always asked for was quietly doing nothing.
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.title = title

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 1)
        outer.setSpacing(1)

        self.body = QtWidgets.QHBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(2)
        outer.addLayout(self.body, 1)

        label = QtWidgets.QLabel(title)
        label.setObjectName("RibbonPanelTitle")
        label.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)
        outer.addWidget(label)

        self._column: Optional[QtWidgets.QVBoxLayout] = None
        self._column_count = 0
        self.compact = False

    def small_buttons(self) -> List["RibbonSmallButton"]:
        return self.findChildren(RibbonSmallButton)

    def set_compact(self, on: bool) -> None:
        """The whole group with captions, or the whole group as icons.

        All of a group one way or the other: some buttons worded and their
        neighbours bare looked broken, and bare buttons spread out at the
        width the words needed looked lost.  So the group goes over as one,
        and its icons pack into a tight grid.
        """
        if on == self.compact:
            return
        self.compact = on
        buttons = self.small_buttons()
        for button in buttons:
            button.set_compact(on)
        # Qt would only work the new sizes out on its next pass, and the
        # tab asks straight away whether it fits yet
        for column in {id(b.parentWidget()): b.parentWidget()
                       for b in buttons}.values():
            if column.layout() is not None:
                column.layout().invalidate()
            column.updateGeometry()
        self.body.invalidate()
        self.layout().invalidate()
        self.updateGeometry()

    def add_big(self, name: str, text: str, tip: str = "",
                checkable: bool = False) -> RibbonButton:
        self._column = None
        btn = RibbonButton(name, text, tip, checkable, self)
        self.body.addWidget(btn, 0, QtCore.Qt.AlignTop)
        return btn

    def add_split(self, options, tip: str = "") -> "RibbonSplitButton":
        """A big button whose arrow opens a list of variants."""
        self._column = None
        btn = RibbonSplitButton(options, tip, self)
        self.body.addWidget(btn, 0, QtCore.Qt.AlignTop)
        return btn

    def add_small(self, name: str, text: str, tip: str = "",
                  checkable: bool = False) -> RibbonSmallButton:
        if self._column is None or self._column_count >= 3:
            self._column = QtWidgets.QVBoxLayout()
            self._column.setContentsMargins(0, 0, 0, 0)
            self._column.setSpacing(1)
            self._column.setAlignment(QtCore.Qt.AlignTop)
            holder = QtWidgets.QWidget(self)
            holder.setLayout(self._column)
            holder.setFixedHeight(68)
            self.body.addWidget(holder, 0, QtCore.Qt.AlignTop)
            self._column_count = 0
        btn = RibbonSmallButton(name, text, tip, checkable, self)
        self._column.addWidget(btn)
        self._column_count += 1
        return btn

    def add_widget(self, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        self._column = None
        self.body.addWidget(widget, 0, QtCore.Qt.AlignVCenter)
        return widget

    def add_separator(self) -> None:
        self._column = None
        line = QtWidgets.QFrame(self)
        line.setFrameShape(QtWidgets.QFrame.VLine)
        line.setStyleSheet("color: %s;" % C.border)
        line.setFixedWidth(1)
        self.body.addWidget(line)


class RibbonTab(QtWidgets.QWidget):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(2, 0, 2, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        self.panels: List[RibbonPanel] = []
        self._fitting = False

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.fit()

    def _needed(self) -> int:
        margins = self._layout.contentsMargins()
        return (sum(panel.sizeHint().width() for panel in self.panels)
                + margins.left() + margins.right())

    def fit(self) -> None:
        """Fold groups down to icons, most buttons first, until all fit.

        On a scaled up display, or a narrow window, the ribbon is wider
        than the room it has.  The group with the most small buttons saves
        the most by going to icons, so it goes first, then the next, until
        the whole ribbon fits; a wider window puts the words back.
        """
        if self._fitting or not self.panels:
            return
        self._fitting = True
        try:
            room = self.width()
            for panel in self.panels:
                panel.set_compact(False)
            order = sorted((p for p in self.panels if p.small_buttons()),
                           key=lambda p: -len(p.small_buttons()))
            for panel in order:
                if self._needed() <= room:
                    break
                panel.set_compact(True)
        finally:
            self._fitting = False

    def add_panel(self, title: str) -> RibbonPanel:
        panel = RibbonPanel(title, self)
        self._layout.insertWidget(self._layout.count() - 1, panel)
        self.panels.append(panel)
        return panel

    def add_panel_right(self, title: str) -> RibbonPanel:
        """A panel past the stretch, so it sits at the far right.

        For the one button that is not a modelling command: the way back
        out of an in-place edit belongs at the end of the ribbon, away
        from the tools, which is where every CAD package puts it.
        """
        panel = RibbonPanel(title, self)
        self._layout.addWidget(panel)
        self.panels.append(panel)
        return panel


class Ribbon(QtWidgets.QWidget):
    """The whole ribbon: tab strip plus the stacked tab pages."""

    tab_changed = QtCore.Signal(str)
    # the window buttons at the right of the title row
    minimise_requested = QtCore.Signal()
    maximise_requested = QtCore.Signal()
    close_requested = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("RibbonBar")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Row 1: the quick access toolbar, on its own line above the tabs,
        # which is where Inventor puts it.
        self.qat_bar = QtWidgets.QWidget(self)
        self.qat_bar.setObjectName("RibbonQat")
        # tall enough for the material pickers that sit on it; at 26 the
        # combo boxes were cut off half way up
        self.qat_bar.setFixedHeight(32)
        qat_layout = QtWidgets.QHBoxLayout(self.qat_bar)
        qat_layout.setContentsMargins(7, 2, 0, 2)
        qat_layout.setSpacing(2)

        # This row is the window's title bar too, as in Inventor: the mark
        # first, the program and the document in the middle, and the
        # window buttons at the right end.
        self.logo = QtWidgets.QLabel(self.qat_bar)
        self.logo.setPixmap(icons.brand_pixmap(
            20, self.devicePixelRatioF()))
        self.logo.setFixedSize(22, 22)
        self.logo.setAlignment(QtCore.Qt.AlignCenter)
        qat_layout.addWidget(self.logo)
        qat_layout.addSpacing(4)

        self.quick_access = QtWidgets.QHBoxLayout()
        self.quick_access.setContentsMargins(0, 0, 0, 0)
        self.quick_access.setSpacing(1)
        qat_layout.addLayout(self.quick_access)
        qat_layout.addSpacing(14)

        # Material and appearance sit up here rather than in a panel,
        # because what a part is made of is a property of the part and not
        # a command you run.  Next to the quick access icons rather than
        # out on the right, so they are near the rest of the controls
        # instead of marooned beside the file name.
        self.material_slot = QtWidgets.QHBoxLayout()
        self.material_slot.setContentsMargins(0, 0, 0, 0)
        self.material_slot.setSpacing(0)
        qat_layout.addLayout(self.material_slot)

        # where "editing X in place" and its way back appear, which is
        # only ever while that is true
        self.banner_slot = QtWidgets.QHBoxLayout()
        self.banner_slot.setContentsMargins(0, 0, 0, 0)
        self.banner_slot.setSpacing(6)
        qat_layout.addLayout(self.banner_slot)

        qat_layout.addStretch(1)

        # "DATUM  Part1.pdat", in the very centre of the row whatever sits
        # either side of it, so it is laid over the row rather than in it;
        # clicks go through it to the row, which drags the window
        self.document_label = QtWidgets.QLabel("", self.qat_bar)
        self.document_label.setObjectName("WindowTitle")
        self.document_label.setAlignment(QtCore.Qt.AlignCenter)
        self.document_label.setStyleSheet(
            "color: %s; font-size: 12px;" % C.text_dim)
        self.document_label.setAttribute(
            QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.qat_bar.installEventFilter(self)

        self.window_buttons = QtWidgets.QWidget(self.qat_bar)
        buttons = QtWidgets.QHBoxLayout(self.window_buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(0)
        self.minimise_button = self._window_button("min", "Minimise")
        self.maximise_button = self._window_button("max", "Maximise")
        self.close_button = self._window_button("close", "Close")
        self.close_button.setObjectName("WindowClose")
        self.minimise_button.clicked.connect(self.minimise_requested)
        self.maximise_button.clicked.connect(self.maximise_requested)
        self.close_button.clicked.connect(self.close_requested)
        for button in (self.minimise_button, self.maximise_button,
                       self.close_button):
            buttons.addWidget(button)
        qat_layout.addWidget(self.window_buttons)
        self.window_buttons.setVisible(False)

        root.addWidget(self.qat_bar)

        # Row 2: the File button and the tab strip.
        self.strip = QtWidgets.QWidget(self)
        self.strip.setObjectName("RibbonTabStrip")
        self.strip.setFixedHeight(27)
        strip_layout = QtWidgets.QHBoxLayout(self.strip)
        strip_layout.setContentsMargins(6, 0, 8, 0)
        strip_layout.setSpacing(1)
        self._strip_layout = strip_layout

        # File behaves like Inventor's: a coloured button holding the document
        # commands, rather than a ribbon tab of its own.
        self.file_button = QtWidgets.QToolButton(self.strip)
        self.file_button.setObjectName("FileButton")
        self.file_button.setText("File")
        self.file_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.file_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.file_button.setStyleSheet(
            "#FileButton { background: %s; color: %s; font-weight: 600;"
            " padding: 6px 15px 5px 15px; border: none; }"
            "#FileButton:hover { background: %s; }"
            "#FileButton::menu-indicator { image: none; width: 0; }"
            % (C.accent_dark, C.on_accent, C.accent))
        strip_layout.addWidget(self.file_button)
        strip_layout.addSpacing(4)
        strip_layout.addStretch(1)

        self.status_hint = QtWidgets.QLabel("")
        self.status_hint.setStyleSheet(
            "color: %s; font-size: 11px;" % C.text_dim)
        strip_layout.addWidget(self.status_hint)

        root.addWidget(self.strip)

        self.stack = QtWidgets.QStackedWidget(self)
        self.stack.setFixedHeight(90)
        root.addWidget(self.stack)

        self._tabs: Dict[str, RibbonTab] = {}
        self._buttons: Dict[str, QtWidgets.QToolButton] = {}
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)

    # -- construction -------------------------------------------------------

    def add_tab(self, title: str, contextual: bool = False) -> RibbonTab:
        tab = RibbonTab(title, self)
        self._tabs[title] = tab
        self.stack.addWidget(tab)

        btn = QtWidgets.QToolButton(self.strip)
        btn.setObjectName("RibbonTabButton")
        btn.setText(title)
        btn.setCheckable(True)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        if contextual:
            btn.setStyleSheet("#RibbonTabButton:checked { border-bottom: 2px "
                              "solid %s; } #RibbonTabButton { color: %s; }"
                              % (C.warn, C.warn))
            btn.setVisible(False)
        btn.clicked.connect(lambda _=False, t=title: self.show_tab(t))
        self._group.addButton(btn)
        # insert before the stretch + hint
        self._strip_layout.insertWidget(self._strip_layout.count() - 2, btn)
        self._buttons[title] = btn

        if len(self._tabs) == 1:
            btn.setChecked(True)
        return tab

    # -- behaviour ----------------------------------------------------------

    def show_tab(self, title: str) -> None:
        tab = self._tabs.get(title)
        if tab is None:
            return
        self._buttons[title].setVisible(True)
        self._buttons[title].setChecked(True)
        self.stack.setCurrentWidget(tab)
        self.tab_changed.emit(title)

    def set_pages_enabled(self, enabled: bool) -> None:
        """Grey the tabs, leaving File and the quick access icons alive.

        On the home page there is no document for Extrude to act on, but
        there is still every reason to want Open, or Check for Updates.
        Disabling the whole ribbon took those away with the rest.
        """
        # the tab buttons, not the strip that holds them: File lives on
        # that strip, and a disabled parent takes its children with it
        self.stack.setEnabled(enabled)
        for button in self._buttons.values():
            button.setEnabled(enabled)

    def set_tab_visible(self, title: str, visible: bool) -> None:
        btn = self._buttons.get(title)
        if btn is not None:
            btn.setVisible(visible)

    def tab(self, title: str) -> Optional[RibbonTab]:
        return self._tabs.get(title)

    def current_tab(self) -> str:
        widget = self.stack.currentWidget()
        return getattr(widget, "title", "")

    def set_hint(self, text: str) -> None:
        self.status_hint.setText(text)

    def set_file_menu(self, menu: QtWidgets.QMenu) -> None:
        self.file_button.setMenu(menu)

    def add_quick_action(self, icon_name: str, tip: str) -> QtWidgets.QToolButton:
        """Small always-visible button beside File, like Inventor's QAT."""
        btn = QtWidgets.QToolButton(self.qat_bar)
        btn.setObjectName("QuickButton")
        btn.setIcon(icons.icon(icon_name, 16))
        btn.setIconSize(QtCore.QSize(16, 16))
        btn.setToolTip(tip)
        btn.setAutoRaise(True)
        btn.setFixedSize(24, 22)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.quick_access.addWidget(btn)
        return btn

    def add_quick_separator(self) -> None:
        line = QtWidgets.QFrame(self.qat_bar)
        line.setFrameShape(QtWidgets.QFrame.VLine)
        line.setFixedWidth(1)
        line.setStyleSheet("color: %s; margin: 3px 5px;" % C.border_light)
        self.quick_access.addWidget(line)

    def _window_button(self, kind: str, tip: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton(self.window_buttons)
        button.setObjectName("WindowButton")
        button.setIcon(icons.window_icon(kind))
        button.setIconSize(QtCore.QSize(12, 12))
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setFixedSize(46, 32)
        return button

    def show_window_buttons(self, on: bool) -> None:
        """The title row's own minimise, maximise and close, when it is
        the window's title bar."""
        self.window_buttons.setVisible(on)
        self.qat_bar.layout().setContentsMargins(7, 0 if on else 2,
                                                 0 if on else 8,
                                                 0 if on else 2)
        self._place_title()

    def set_maximised(self, maximised: bool) -> None:
        self.maximise_button.setIcon(
            icons.window_icon("restore" if maximised else "max"))
        self.maximise_button.setToolTip(
            "Restore Down" if maximised else "Maximise")

    def eventFilter(self, obj, event) -> bool:
        if obj is self.qat_bar and event.type() in (
                QtCore.QEvent.Resize, QtCore.QEvent.LayoutRequest):
            # after the row has laid itself out, so the pickers are where
            # they are going to be
            QtCore.QTimer.singleShot(0, self._place_title)
        return super().eventFilter(obj, event)

    def _place_title(self) -> None:
        """The title in the middle of the row, or of the room there is.

        In the very centre when nothing is in the way; on a narrow window,
        where the material pickers reach the middle, centred in the gap
        between them and the window buttons, shortened if it must be.
        """
        bar = self.qat_bar
        label = self.document_label
        text = getattr(self, "_title_text", label.text())
        metrics = label.fontMetrics()
        want = metrics.horizontalAdvance(text) + 12
        left_end = 0
        for child in bar.findChildren(QtWidgets.QWidget,
                                      options=QtCore.Qt.FindDirectChildrenOnly):
            if child in (label, self.window_buttons) or not child.isVisible():
                continue
            left_end = max(left_end, child.geometry().right() + 1)
        right_start = (self.window_buttons.x() if self.window_buttons.isVisible()
                       else bar.width())
        gap_left, gap_right = left_end + 16, right_start - 16
        x = (bar.width() - want) // 2
        if x < gap_left or x + want > gap_right:
            x = max(gap_left, (gap_left + gap_right - want) // 2)
        width = max(0, min(want, gap_right - x))
        label.setText(metrics.elidedText(text, QtCore.Qt.ElideMiddle,
                                         max(0, width - 12)))
        label.setGeometry(x, 0, width, bar.height())

    def set_document_label(self, text: str) -> None:
        self._title_text = "InventCraft  %s" % text if text else "InventCraft"
        self.document_label.setText(self._title_text)
        self._place_title()

