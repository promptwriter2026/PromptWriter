import sqlite3
import tkinter
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from promptwriter.storage.history_db import (
    bulk_delete_generations,
    count_generations_for_delete,
    delete_generation,
    fetch_favorite_prompts,
    fetch_generation,
    fetch_recent_generations,
    toggle_favorite,
)
from promptwriter.ui.tooltip import ToolTip
from promptwriter.utils.text import format_history_timestamp, history_idea_snippet


HISTORY_SEARCH_DEBOUNCE_MS = 200
BULK_DELETE_AGE_CHOICES = (
    ("All entries", None),
    ("Older than 30 days", 30),
    ("Older than 90 days", 90),
    ("Older than 1 year", 365),
)


class BulkDeleteHistoryDialog(ctk.CTkToplevel):
    def __init__(self, parent, count_callback, delete_callback):
        super().__init__(parent)
        self.title("Bulk Delete History")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._tooltips = []
        self._count_callback = count_callback
        self._delete_callback = delete_callback

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, padx=18, pady=(16, 8), sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body,
            text="Delete multiple history entries. Favorites are kept unless included.",
            anchor="w",
            justify="left",
            wraplength=360,
        ).grid(row=0, column=0, pady=(0, 10), sticky="w")

        self.include_favorites_var = tkinter.BooleanVar(self, value=False)
        self.include_favorites_checkbox = ctk.CTkCheckBox(
            body,
            text="Include favorites",
            variable=self.include_favorites_var,
            command=self._refresh_count,
        )
        self.include_favorites_checkbox.grid(row=1, column=0, pady=4, sticky="w")
        self._add_tooltip(
            self.include_favorites_checkbox,
            "Also delete entries marked as favorites.",
        )

        ctk.CTkLabel(body, text="Only delete entries older than").grid(
            row=2, column=0, pady=(10, 2), sticky="w"
        )
        self.age_menu = ctk.CTkOptionMenu(
            body,
            values=[label for label, _days in BULK_DELETE_AGE_CHOICES],
            command=lambda _value: self._refresh_count(),
        )
        self.age_menu.set(BULK_DELETE_AGE_CHOICES[0][0])
        self.age_menu.grid(row=3, column=0, pady=2, sticky="ew")
        self._add_tooltip(
            self.age_menu,
            "Optionally limit deletion to entries older than the chosen age.",
        )

        self.count_label = ctk.CTkLabel(body, text="", anchor="w")
        self.count_label.grid(row=4, column=0, pady=(12, 2), sticky="w")
        self.error_label = ctk.CTkLabel(
            body,
            text="",
            text_color="red",
            anchor="w",
            justify="left",
            wraplength=360,
        )
        self.error_label.grid(row=5, column=0, pady=(0, 4), sticky="w")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=1, column=0, padx=18, pady=(0, 16), sticky="ew")
        buttons.grid_columnconfigure((0, 1), weight=1)
        self.cancel_button = ctk.CTkButton(
            buttons, text="Cancel", command=self.destroy
        )
        self.cancel_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.delete_button = ctk.CTkButton(
            buttons,
            text="Delete",
            fg_color="#8B2E2E",
            hover_color="#6E2323",
            command=self._confirm_delete,
        )
        self.delete_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")
        self._add_tooltip(self.cancel_button, "Close without deleting anything.")
        self._add_tooltip(
            self.delete_button,
            "Delete the matching history entries after confirmation.",
        )

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        width = max(420, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        parent.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.lift()
        self._refresh_count()

    def _add_tooltip(self, widget, text):
        self._tooltips.append(ToolTip(widget, text))

    def _older_than(self):
        days = dict(BULK_DELETE_AGE_CHOICES).get(self.age_menu.get())
        if days is None:
            return None
        return datetime.now().astimezone() - timedelta(days=days)

    def _read_count(self):
        try:
            return self._count_callback(
                bool(self.include_favorites_var.get()), self._older_than()
            )
        except sqlite3.Error as error:
            self.error_label.configure(text=f"Could not count entries: {error}")
            return None

    def _refresh_count(self):
        count = self._read_count()
        if count is None:
            self.count_label.configure(text="", text_color="gray")
            self.delete_button.configure(state="disabled")
            return
        self.error_label.configure(text="")
        if count == 0:
            self.count_label.configure(
                text="No entries match these options.", text_color="gray"
            )
            self.delete_button.configure(state="disabled")
            return
        noun = "entry" if count == 1 else "entries"
        self.count_label.configure(
            text=f"{count} {noun} will be deleted.",
            text_color=ctk.ThemeManager.theme["CTkLabel"]["text_color"],
        )
        self.delete_button.configure(state="normal")

    def _confirm_delete(self):
        count = self._read_count()
        if not count:
            self._refresh_count()
            return
        noun = "entry" if count == 1 else "entries"
        if not messagebox.askyesno(
            "Bulk Delete History",
            f"Permanently delete {count} history {noun}?\n\nThis cannot be undone.",
            parent=self,
        ):
            return
        try:
            self._delete_callback(
                bool(self.include_favorites_var.get()), self._older_than()
            )
        except sqlite3.Error as error:
            self.error_label.configure(text=f"Could not delete entries: {error}")
            self._refresh_count()
            return
        self.destroy()


class HistoryTabMixin:
    def _build_history_tab(self):
        tab = self.history_tab
        self._history_selected_font = ctk.CTkFont(weight="bold")
        self._history_row_font = ctk.CTkFont()
        self._history_rows = []
        self._history_empty_label = None
        self._history_search_after_id = None
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=2)
        tab.grid_rowconfigure(1, weight=1)

        filters = ctk.CTkFrame(tab, fg_color="transparent")
        filters.grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 0), sticky="ew"
        )
        filters.grid_columnconfigure(0, weight=1)
        self.history_search_entry = ctk.CTkEntry(
            filters, placeholder_text="Search prompts and rough ideas..."
        )
        self.history_search_entry.grid(
            row=0, column=0, padx=(0, 8), pady=4, sticky="ew"
        )
        self._add_tooltip(
            self.history_search_entry,
            "Type to filter your past prompts by keywords.",
        )
        self.history_search_entry.bind("<KeyRelease>", self._on_history_search)
        self.favorites_only_switch = ctk.CTkSwitch(
            filters,
            text="Show Favorites Only",
            command=self._refresh_history,
            onvalue=1,
            offvalue=0,
        )
        self.favorites_only_switch.grid(
            row=0, column=1, padx=8, pady=4, sticky="w"
        )
        self._add_tooltip(
            self.favorites_only_switch,
            "Show only your favorited prompts.",
        )
        self.export_favorites_button = ctk.CTkButton(
            filters, text="Export Favorites", command=self._export_favorites
        )
        self.export_favorites_button.grid(
            row=0, column=2, padx=(8, 0), pady=4
        )
        self._add_tooltip(
            self.export_favorites_button,
            "Save your favorite prompts to a text file.",
        )

        self.history_list = ctk.CTkScrollableFrame(tab, label_text="Past generations")
        self.history_list.grid(
            row=1, column=0, padx=(12, 6), pady=12, sticky="nsew"
        )
        self._add_tooltip(
            self.history_list,
            "Select a past generation to review its prompt and original idea.",
        )
        self.history_content_tabs = ctk.CTkTabview(tab)
        self.history_content_tabs.grid(
            row=1, column=1, padx=(6, 12), pady=12, sticky="nsew"
        )
        self.history_generated_tab = self.history_content_tabs.add(
            "Generated Prompts"
        )
        self.history_original_tab = self.history_content_tabs.add("Original Idea")
        self.history_generated_tab.grid_columnconfigure(0, weight=1)
        self.history_generated_tab.grid_rowconfigure(0, weight=1)
        self.history_original_tab.grid_columnconfigure(0, weight=1)
        self.history_original_tab.grid_rowconfigure(0, weight=1)
        self.history_generated_text = ctk.CTkTextbox(
            self.history_generated_tab, wrap="word"
        )
        self.history_generated_text.grid(
            row=0, column=0, padx=8, pady=8, sticky="nsew"
        )
        self.history_original_text = ctk.CTkTextbox(
            self.history_original_tab, wrap="word"
        )
        self.history_original_text.grid(
            row=0, column=0, padx=8, pady=8, sticky="nsew"
        )
        self.load_history_button = ctk.CTkButton(
            self.history_original_tab,
            text="Load back to Generator",
            command=self._load_history_prompt,
        )
        self.load_history_button.grid(
            row=1, column=0, padx=8, pady=(0, 8), sticky="e"
        )
        self._add_tooltip(
            self.load_history_button,
            "Load this entry's original idea back into the Generator.",
        )
        self._add_tooltip(
            self.history_generated_text, "The selected generated prompt."
        )
        self._add_tooltip(
            self.history_original_text, "The selected entry's original idea."
        )
        for textbox in (self.history_generated_text, self.history_original_text):
            textbox._textbox.bind(
                "<Button-3>", self._show_text_context_menu
            )
            textbox._textbox.bind("<<SelectAll>>", self._select_all_text)

        list_actions = ctk.CTkFrame(tab, fg_color="transparent")
        list_actions.grid(
            row=2, column=0, padx=(12, 6), pady=(0, 12), sticky="w"
        )
        self.toggle_favorite_button = ctk.CTkButton(
            list_actions,
            text="Toggle Favorite (★)",
            width=150,
            height=26,
            command=self._toggle_history_favorite,
        )
        self.toggle_favorite_button.pack(side="left")
        self._add_tooltip(
            self.toggle_favorite_button,
            "Add or remove the selected prompt from favorites.",
        )

        prompt_actions = ctk.CTkFrame(tab, fg_color="transparent")
        prompt_actions.grid(
            row=2, column=1, padx=(6, 12), pady=(0, 12), sticky="e"
        )
        self.copy_history_button = ctk.CTkButton(
            prompt_actions,
            text="Copy Prompt",
            width=120,
            height=26,
            command=self._copy_history_prompt,
        )
        self.copy_history_button.pack(side="left", padx=(0, 6))
        self._add_tooltip(
            self.copy_history_button,
            "Copy the selected generated prompt to your clipboard.",
        )
        self.delete_history_button = ctk.CTkButton(
            prompt_actions,
            text="Delete Selected",
            width=130,
            height=26,
            fg_color="#8B2E2E",
            hover_color="#6E2323",
            command=self._delete_history_entry,
        )
        self.delete_history_button.pack(side="left")
        self._add_tooltip(
            self.delete_history_button,
            "Permanently delete the selected history entry.",
        )
        self.bulk_delete_history_button = ctk.CTkButton(
            prompt_actions,
            text="Bulk Delete...",
            width=112,
            height=26,
            fg_color="#8B2E2E",
            hover_color="#6E2323",
            command=self._open_bulk_delete_history,
        )
        self.bulk_delete_history_button.pack(side="left", padx=(6, 0))
        self._add_tooltip(
            self.bulk_delete_history_button,
            "Delete many entries at once, keeping favorites unless included.",
        )
        self.history_status_label = ctk.CTkLabel(tab, text="")
        self.history_status_label.grid(
            row=3, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="e"
        )

    def _on_history_search(self, _event=None):
        if self._history_search_after_id is not None:
            try:
                self.after_cancel(self._history_search_after_id)
            except tkinter.TclError:
                pass
        self._history_search_after_id = self.after(
            HISTORY_SEARCH_DEBOUNCE_MS, self._run_scheduled_history_refresh
        )

    def _run_scheduled_history_refresh(self):
        self._history_search_after_id = None
        self._refresh_history()

    def _refresh_history(self):
        if self._history_search_after_id is not None:
            try:
                self.after_cancel(self._history_search_after_id)
            except tkinter.TclError:
                pass
            self._history_search_after_id = None
        search_text = self.history_search_entry.get().strip()
        favorites_only = bool(self.favorites_only_switch.get())
        try:
            rows = fetch_recent_generations(search_text, favorites_only)
        except sqlite3.Error as error:
            self.history_records = []
            self._hide_history_rows(0)
            self._show_history_empty("No matching history entries.")
            self.history_status_label.configure(
                text=f"Could not load history: {error}", text_color="red"
            )
            return

        self.history_records = [
            {
                "id": row[0],
                "timestamp": row[1],
                "rough_idea": row[2] or "",
                "is_favorite": bool(row[3]),
            }
            for row in rows
        ]
        for index, item in enumerate(self.history_records):
            self._update_history_row(self._acquire_history_row(index), item)
        self._hide_history_rows(len(self.history_records))
        self._show_history_empty(
            "No matching history entries." if not self.history_records else None
        )

    def _acquire_history_row(self, index):
        while len(self._history_rows) <= index:
            row = {
                "id": None,
                "text": None,
                "rough_idea": None,
                "selected": None,
                "visible": False,
            }
            button = ctk.CTkButton(
                self.history_list,
                text="",
                anchor="w",
                command=lambda row=row: self._select_history(row["id"]),
            )
            row["button"] = button
            row["tooltip"] = self._add_tooltip(button, "")
            self._history_rows.append(row)
        return self._history_rows[index]

    def _update_history_row(self, row, item):
        favorite_prefix = "★ " if item["is_favorite"] else ""
        text = (
            f'{favorite_prefix}{format_history_timestamp(item["timestamp"])}'
            f' - {history_idea_snippet(item["rough_idea"])}'
        )[:90]
        if row["text"] != text:
            row["button"].configure(text=text)
            row["text"] = text
        if row["rough_idea"] != item["rough_idea"]:
            row["tooltip"].text = item["rough_idea"]
            row["rough_idea"] = item["rough_idea"]
        row["id"] = item["id"]
        if not row["visible"]:
            row["button"].pack(fill="x", padx=6, pady=4)
            row["visible"] = True
        self._apply_history_row_selection(
            row, item["id"] == self.history_selection_id
        )

    def _hide_history_rows(self, start_index):
        for row in self._history_rows[start_index:]:
            if row["visible"]:
                row["button"].pack_forget()
                row["visible"] = False
            row["id"] = None
            self._apply_history_row_selection(row, False)

    def _apply_history_row_selection(self, row, selected):
        if row["selected"] == selected:
            return
        row["selected"] = selected
        button = row["button"]
        if selected:
            button.configure(
                fg_color=("#2F86D8", "#1F6AA5"),
                hover_color=("#1F6FB8", "#17567F"),
                text_color="#FFFFFF",
                border_width=2,
                border_color="#FFC857",
                font=self._history_selected_font,
            )
            return
        theme = ctk.ThemeManager.theme["CTkButton"]
        button.configure(
            fg_color=theme["fg_color"],
            hover_color=theme["hover_color"],
            text_color=theme["text_color"],
            border_width=0,
            font=self._history_row_font,
        )

    def _apply_history_selection_styles(self):
        for row in self._history_rows:
            self._apply_history_row_selection(
                row,
                row["id"] is not None and row["id"] == self.history_selection_id,
            )

    def _show_history_empty(self, message):
        if self._history_empty_label is None:
            if message is None:
                return
            self._history_empty_label = ctk.CTkLabel(
                self.history_list, text=message
            )
        if message is None:
            self._history_empty_label.pack_forget()
            return
        self._history_empty_label.configure(text=message)
        if not self._history_empty_label.winfo_manager():
            self._history_empty_label.pack(fill="x", padx=6, pady=8)

    def _select_history(self, generation_id):
        try:
            row = fetch_generation(generation_id)
        except sqlite3.Error as error:
            self.history_status_label.configure(
                text=f"Could not load history entry: {error}", text_color="red"
            )
            return
        if row is None:
            self.history_status_label.configure(
                text="This history entry no longer exists.", text_color="red"
            )
            self._refresh_history()
            return

        self.history_selection = dict(
            zip(
                (
                    "id",
                    "timestamp",
                    "source_tab",
                    "rough_idea",
                    "generated_prompt",
                    "engine",
                    "model",
                    "is_favorite",
                    "image_path",
                    "settings_json",
                ),
                row,
            )
        )
        self.history_selection["is_favorite"] = bool(
            self.history_selection["is_favorite"]
        )
        self.history_selection_id = generation_id
        self._set_history_text(
            self.history_generated_text,
            self.history_selection["generated_prompt"] or "",
        )
        self._set_history_text(
            self.history_original_text,
            self.history_selection["rough_idea"] or "",
        )
        self.history_content_tabs.set("Generated Prompts")
        self.history_status_label.configure(text="", text_color="gray")
        self._apply_history_selection_styles()

    @staticmethod
    def _set_history_text(textbox, value):
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", value)

    def _toggle_history_favorite(self):
        if not self.history_selection_id or not self.history_selection:
            self.history_status_label.configure(
                text="Select a history entry first.", text_color="red"
            )
            return

        try:
            toggle_favorite(self.history_selection_id)
        except sqlite3.Error as error:
            self.history_status_label.configure(
                text=f"Could not update favorite: {error}", text_color="red"
            )
            return

        self.history_selection["is_favorite"] = not self.history_selection[
            "is_favorite"
        ]
        self.history_status_label.configure(
            text=(
                "Added to favorites."
                if self.history_selection["is_favorite"]
                else "Removed from favorites."
            ),
            text_color="green",
        )
        self._refresh_history()

    def _export_favorites(self):
        try:
            favorites = fetch_favorite_prompts()
        except sqlite3.Error as error:
            self.history_status_label.configure(
                text=f"Could not read history: {error}", text_color="red"
            )
            return

        if not favorites:
            self.history_status_label.configure(
                text="There are no favorite prompts to export.", text_color="red"
            )
            return

        export_path = filedialog.asksaveasfilename(
            title="Export favorite prompts",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not export_path:
            return
        try:
            Path(export_path).write_text(
                "\n\n---\n\n".join(favorites), encoding="utf-8"
            )
        except OSError as error:
            self.history_status_label.configure(
                text=f"Could not export favorites: {error}", text_color="red"
            )
            return
        self.history_status_label.configure(
            text=f"Exported {len(favorites)} favorite prompt(s).",
            text_color="green",
        )

    def _load_history_prompt(self):
        if not isinstance(self.history_selection, dict):
            return

        user_idea = self.history_selection.get("rough_idea", "")
        if not isinstance(user_idea, str):
            self.status_label.configure(
                text="Error: This history entry does not contain a valid rough idea.",
                text_color="red",
            )
            return

        self.rough_idea_text.delete("1.0", "end")
        self.rough_idea_text.insert("1.0", user_idea)
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")
        self.tabs.set("Generator")
        self.rough_idea_text.focus_set()

    def _copy_history_prompt(self):
        prompt = ""
        if isinstance(self.history_selection, dict):
            prompt = self.history_selection.get("generated_prompt") or ""
        self._copy_text(
            prompt,
            button=self.copy_history_button,
            status_label=self.history_status_label,
        )

    def _delete_history_entry(self):
        if not self.history_selection_id:
            self.history_status_label.configure(
                text="Select a history entry first.", text_color="red"
            )
            return
        if not messagebox.askyesno(
            "Delete History Entry",
            "Permanently delete the selected history entry?",
            parent=self,
        ):
            return

        try:
            deleted = delete_generation(self.history_selection_id)
        except sqlite3.Error as error:
            self.history_status_label.configure(
                text=f"Could not delete history entry: {error}", text_color="red"
            )
            return

        self._clear_history_selection()
        self._refresh_history()
        if deleted:
            self.history_status_label.configure(
                text="Deleted the selected history entry.", text_color="green"
            )
        else:
            self.history_status_label.configure(
                text="This history entry no longer exists.", text_color="red"
            )

    def _open_bulk_delete_history(self):
        existing = getattr(self, "_bulk_delete_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        self._bulk_delete_dialog = BulkDeleteHistoryDialog(
            self,
            count_callback=count_generations_for_delete,
            delete_callback=self._delete_history_entries,
        )

    def _delete_history_entries(self, include_favorites, older_than):
        deleted = bulk_delete_generations(include_favorites, older_than)
        if (
            self.history_selection_id
            and fetch_generation(self.history_selection_id) is None
        ):
            self._clear_history_selection()
        self._refresh_history()
        noun = "entry" if deleted == 1 else "entries"
        self.history_status_label.configure(
            text=f"Deleted {deleted} history {noun}.", text_color="green"
        )
        return deleted

    def _clear_history_selection(self):
        self.history_selection = None
        self.history_selection_id = None
        self._set_history_text(self.history_generated_text, "")
        self._set_history_text(self.history_original_text, "")
