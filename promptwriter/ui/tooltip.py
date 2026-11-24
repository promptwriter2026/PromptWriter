import ctypes
import ctypes.wintypes
import sys
import tkinter
import weakref

_MONITOR_DEFAULTTONEAREST = 2
_EDGE_MARGIN = 4
_CURSOR_OFFSET = 15

_SHOWN_TOOLTIPS = weakref.WeakSet()
_BOUND_TOPLEVELS = weakref.WeakSet()


def _hide_shown_tooltips(_event=None):
    for tooltip in list(_SHOWN_TOOLTIPS):
        tooltip._hide()


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
    ]


def monitor_work_area(x, y):
    """Return (left, top, right, bottom) of the monitor nearest a point."""
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [
            ctypes.wintypes.POINT,
            ctypes.wintypes.DWORD,
        ]
        user32.MonitorFromPoint.restype = ctypes.wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(_MonitorInfo),
        ]
        user32.GetMonitorInfoW.restype = ctypes.wintypes.BOOL
        monitor = user32.MonitorFromPoint(
            ctypes.wintypes.POINT(int(x), int(y)), _MONITOR_DEFAULTTONEAREST
        )
        if not monitor:
            return None
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(_MonitorInfo)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        return (work.left, work.top, work.right, work.bottom)
    except (AttributeError, OSError, ValueError):
        return None


def clamp_tooltip_position(x, y, width, height, work_area, margin=_EDGE_MARGIN):
    left, top, right, bottom = work_area
    min_x = left + margin
    max_x = right - width - margin
    min_y = top + margin
    max_y = bottom - height - margin
    x = min(max(x, min_x), max_x) if max_x >= min_x else min_x
    y = min(max(y, min_y), max_y) if max_y >= min_y else min_y
    return int(x), int(y)


class ToolTip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self._window = None
        for target in self._widget_tree(widget):
            target.bind("<Enter>", self._schedule_show, add="+")
            target.bind("<Leave>", self._hide, add="+")
            target.bind("<ButtonPress>", self._hide, add="+")
            target.bind("<FocusOut>", self._hide, add="+")
            target.bind("<Unmap>", self._hide, add="+")
            target.bind("<Destroy>", self._on_destroy, add="+")
        toplevel = widget.winfo_toplevel()
        if toplevel not in _BOUND_TOPLEVELS:
            _BOUND_TOPLEVELS.add(toplevel)
            toplevel.bind("<FocusOut>", _hide_shown_tooltips, add="+")
            toplevel.bind("<Unmap>", _hide_shown_tooltips, add="+")

    @staticmethod
    def _widget_tree(widget):
        yield widget
        for child in widget.winfo_children():
            yield from ToolTip._widget_tree(child)

    def _schedule_show(self, _event=None):
        self._cancel_scheduled_show()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel_scheduled_show(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tkinter.TclError:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._window is not None:
            return
        try:
            if not self.widget.winfo_exists() or not self.widget.winfo_ismapped():
                return
            pointer_x, pointer_y = self.widget.winfo_pointerxy()
            widget_x = self.widget.winfo_rootx()
            widget_y = self.widget.winfo_rooty()
        except tkinter.TclError:
            return

        window = tkinter.Toplevel(self.widget.winfo_toplevel())
        window.wm_overrideredirect(True)
        window.configure(background="#2b2b2b")
        tkinter.Label(
            window,
            text=self.text,
            justify="left",
            background="#2b2b2b",
            foreground="#f2f2f2",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=5,
        ).pack()
        window.update_idletasks()

        width = window.winfo_reqwidth()
        height = window.winfo_reqheight()
        work_area = monitor_work_area(pointer_x, pointer_y) or monitor_work_area(
            widget_x, widget_y
        )
        if work_area is not None:
            _, _, right, bottom = work_area
            x = pointer_x + _CURSOR_OFFSET
            y = pointer_y + _CURSOR_OFFSET
            if x + width > right - _EDGE_MARGIN:
                x = pointer_x - width - _CURSOR_OFFSET
            if y + height > bottom - _EDGE_MARGIN:
                y = pointer_y - height - _CURSOR_OFFSET
            x, y = clamp_tooltip_position(x, y, width, height, work_area)
        else:
            x = min(
                pointer_x + _CURSOR_OFFSET,
                self.widget.winfo_screenwidth() - width - _EDGE_MARGIN,
            )
            y = min(
                pointer_y + _CURSOR_OFFSET,
                self.widget.winfo_screenheight() - height - _EDGE_MARGIN,
            )
            x = max(_EDGE_MARGIN, x)
            y = max(_EDGE_MARGIN, y)

        window.geometry(f"+{x}+{y}")
        self._window = window
        _SHOWN_TOOLTIPS.add(self)

    def _hide(self, _event=None):
        if self._window is not None:
            _SHOWN_TOOLTIPS.discard(self)
        if self._after_id is None and self._window is None:
            return
        self._cancel_scheduled_show()
        window = self._window
        self._window = None
        if window is not None:
            try:
                window.destroy()
            except tkinter.TclError:
                pass

    def _on_destroy(self, event):
        if event.widget is self.widget:
            self._hide()
