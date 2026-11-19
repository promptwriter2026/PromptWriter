import tkinter


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
            target.bind("<Destroy>", self._on_destroy, add="+")

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
        if not self.widget.winfo_exists() or self._window is not None:
            return

        pointer_x, pointer_y = self.widget.winfo_pointerxy()
        x = pointer_x + 15
        y = pointer_y + 15
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

        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = min(x, screen_width - window.winfo_reqwidth() - 4)
        y = min(y, screen_height - window.winfo_reqheight() - 4)
        window.geometry(f"+{max(0, x)}+{max(0, y)}")
        self._window = window

    def _hide(self, _event=None):
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
