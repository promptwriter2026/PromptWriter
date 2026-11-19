import tkinter

from promptwriter.config import LOCAL_ENGINE


class TextActionsMixin:
    @staticmethod
    def _update_quota_label(label, engine, quota, total_used=None):
        if engine == LOCAL_ENGINE:
            used = total_used if total_used is not None else "--"
            label.configure(text=f"Local Tokens Used: {used}")
        elif engine == "Groq":
            if (
                isinstance(quota, tuple)
                and len(quota) == 2
                and all(isinstance(value, str) and value for value in quota)
            ):
                remaining, limit = quota
                quota_text = f"{remaining} / {limit}"
            else:
                quota_text = "N/A"
            used = total_used if total_used is not None else "--"
            label.configure(
                text=f"Groq Tokens Used: {used} | Quota: {quota_text}"
            )
        else:
            label.configure(text="Quota: N/A")

    def _copy_text(self, text, button=None, status_label=None):
        button = button or self.copy_button
        status_label = status_label or self.status_label
        if not text:
            status_label.configure(text="Nothing to copy", text_color="red")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except tkinter.TclError as error:
            status_label.configure(text=f"Clipboard error: {error}", text_color="red")
            return

        previous_after_id = self._copy_feedback_after_ids.get(button)
        if previous_after_id is not None:
            self.after_cancel(previous_after_id)
        button.configure(text="Copied!", fg_color="#2e8b57")
        self._copy_feedback_after_ids[button] = self.after(
            1500,
            lambda: self._reset_copy_button(button),
        )

    def _reset_copy_button(self, button=None):
        button = button or self.copy_button
        self._copy_feedback_after_ids.pop(button, None)
        button.configure(
            text="Copy to Clipboard", fg_color=("#3B8ED0", "#1F6AA5")
        )

    def _show_text_context_menu(self, event):
        self._context_text_widget = event.widget
        self.text_context_menu.tk_popup(event.x_root, event.y_root)
        self.text_context_menu.grab_release()
        return "break"

    def _generate_text_event(self, virtual_event):
        widget = getattr(self, "_context_text_widget", None)
        if widget is not None:
            widget.focus_set()
            widget.event_generate(virtual_event)

    @staticmethod
    def _select_all_text(event):
        widget = event.widget
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "end-1c")
        widget.see("insert")
        return "break"
