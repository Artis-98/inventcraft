"""The window's title bar drawn by InventCraft, on Windows.

The system title bar is taken away and the quick access row stands in for
it, as Inventor's does.  Windows still does the work: the window keeps its
resizing frame and caption styles, so dragging, snapping to the edges of
the screen, double clicking to maximise and the shadow all stay Windows'
own.  Only two messages are answered here: how big the frame is (none),
and what each point of the window is (an edge, the caption, or inside).

The second question is asked of whichever window is under the pointer,
and that is not always the main one.  The 3D view is a native window, and
Qt makes the widgets around it native too, so the title row can sit on a
child window of its own.  A child answers "inside" to everything, the
main window is never asked, and the bar cannot be dragged.  So every child
of the main window is filtered as well: where the main window would say
caption or edge, the child says "transparent", which hands the question
on to the window behind it.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Optional

# what WM_NCHITTEST answers mean
HT_TRANSPARENT = -1
HT_CLIENT = 1
HT_CAPTION = 2
HT_LEFT = 10
HT_RIGHT = 11
HT_TOP = 12
HT_TOPLEFT = 13
HT_TOPRIGHT = 14
HT_BOTTOM = 15
HT_BOTTOMLEFT = 16
HT_BOTTOMRIGHT = 17

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084

if sys.platform == "win32":
    from ctypes import wintypes

    class _NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3),
                    ("lppos", ctypes.c_void_p)]

    class _MARGINS(ctypes.Structure):
        _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                    ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

    _user32 = ctypes.windll.user32


def take_over(hwnd: int) -> None:
    """Have Windows ask again how big the frame is, now that it is none.

    The shadow is kept by letting the frame reach one pixel into the
    window; with no frame at all Windows draws none.
    """
    if sys.platform != "win32":
        return
    try:
        dwm = ctypes.windll.dwmapi
        margins = _MARGINS(0, 0, 1, 0)
        dwm.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd),
                                         ctypes.byref(margins))
    except Exception:
        pass
    # SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
    _user32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0,
                         0x0020 | 0x0002 | 0x0001 | 0x0004)


def _frame_thickness(hwnd: int) -> int:
    """The resizing frame, as Windows hangs it off a maximised window."""
    try:
        dpi = _user32.GetDpiForWindow(wintypes.HWND(hwnd))
        metric = _user32.GetSystemMetricsForDpi
        # SM_CXSIZEFRAME and SM_CXPADDEDBORDER
        return metric(32, dpi) + metric(92, dpi)
    except Exception:
        return _user32.GetSystemMetrics(32) + _user32.GetSystemMetrics(92)


def handle(window, message) -> Optional[int]:
    """Answer the two frame messages for a window; None for everything else."""
    if sys.platform != "win32":
        return None
    try:
        msg = wintypes.MSG.from_address(int(message))
    except Exception:
        return None
    if msg.message == WM_NCCALCSIZE and msg.wParam:
        # Windows works the frame out as usual, which keeps the invisible
        # borders on the left, right and bottom that the window is resized
        # by; then the top is put back where it was, which is the caption
        # gone and the window running to its top edge.
        params = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
        top = params.rgrc[0].top
        _default(msg)
        params.rgrc[0].top = top
        if window.isMaximized():
            # maximised, the frame hangs off the top of the screen too
            params.rgrc[0].top += _frame_thickness(int(msg.hWnd))
        return 0
    if msg.message == WM_NCHITTEST:
        from PySide6 import QtGui
        point = QtGui.QCursor.pos()
        inside = window.mapFromGlobal(point)
        if not window.rect().contains(inside):
            return None          # the real borders: Windows' own business
        return window.title_hit(point)
    return None


def child_hit(window, message) -> Optional[int]:
    """Answer WM_NCHITTEST for a native child of the main window.

    Transparent where the main window would take the point as its caption
    or an edge, so Windows asks the main window; None everywhere else,
    which leaves the child to answer as it always has.
    """
    if sys.platform != "win32":
        return None
    try:
        msg = wintypes.MSG.from_address(int(message))
    except Exception:
        return None
    if msg.message != WM_NCHITTEST:
        return None
    top = int(window.winId())
    hwnd = int(msg.hWnd or 0)
    if not hwnd or hwnd == top or not _user32.IsChild(
            wintypes.HWND(top), wintypes.HWND(hwnd)):
        return None
    from PySide6 import QtGui
    if window.title_hit(QtGui.QCursor.pos()) == HT_CLIENT:
        return None
    return HT_TRANSPARENT


def install_child_filter(window):
    """Filter the main window's native children as described above.

    Returns the filter, which the caller keeps: Qt holds no reference to
    it, and one that is collected stops filtering without a word.
    """
    if sys.platform != "win32":
        return None
    from PySide6 import QtCore, QtWidgets

    class _ChildHits(QtCore.QAbstractNativeEventFilter):
        def nativeEventFilter(self, event_type, message):
            try:
                answer = child_hit(window, message)
            except Exception:                       # noqa: BLE001
                # a window already gone (tests make and drop several):
                # nothing to say, and nothing to raise inside Qt's loop
                answer = None
            if answer is None:
                return False, 0
            return True, answer

    hits = _ChildHits()
    QtWidgets.QApplication.instance().installNativeEventFilter(hits)
    return hits


def _default(msg) -> int:
    """What Windows itself would answer to a message."""
    proc = _user32.DefWindowProcW
    proc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                     wintypes.LPARAM]
    proc.restype = ctypes.c_ssize_t
    return proc(msg.hWnd, msg.message, msg.wParam, msg.lParam)
