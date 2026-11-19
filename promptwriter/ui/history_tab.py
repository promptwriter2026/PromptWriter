import sqlite3
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from promptwriter.storage.history_db import (
    fetch_favorite_prompts,
    fetch_generation,
    fetch_recent_generations,
    toggle_favorite,
)
from promptwriter.utils.text import format_history_timestamp, history_idea_snippet


class HistoryTabMixin:
    def _build_history_tab(self):
        tab = self.history_tab
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
        self.history_search_entry.bind(
            "<KeyRelease>", lambda _event: self._refresh_history()
        )
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

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)
        self.copy_history_button = ctk.CTkButton(
            actions, text="Copy History Prompt", command=self._copy_history_prompt
        )
        self.copy_history_button.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self._add_tooltip(
            self.copy_history_button, "Copy the selected history prompt."
        )
        self.toggle_favorite_button = ctk.CTkButton(
            actions,
            text="Toggle Favorite (★)",
            command=self._toggle_history_favorite,
        )
        self.toggle_favorite_button.grid(row=0, column=1, padx=(4, 0), sticky="ew")
        self._add_tooltip(
            self.toggle_favorite_button,
            "Add or remove the selected prompt from favorites.",
        )
        self.history_status_label = ctk.CTkLabel(tab, text="")
        self.history_status_label.grid(
            row=3, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="e"
        )

    def _refresh_history(self):
        for tooltip in self._history_row_tooltips:
            tooltip._hide()
            if tooltip in self.tooltips:
                self.tooltips.remove(tooltip)
        self._history_row_tooltips.clear()
        for widget in self.history_list.winfo_children():
            widget.destroy()
        search_text = self.history_search_entry.get().strip()
        favorites_only = bool(self.favorites_only_switch.get())
        try:
            rows = fetch_recent_generations(search_text, favorites_only)
        except sqlite3.Error as error:
            self.history_records = []
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
        for item in self.history_records:
            favorite_prefix = "★ " if item["is_favorite"] else ""
            label = (
                f'{favorite_prefix}{format_history_timestamp(item["timestamp"])}'
                f' - {history_idea_snippet(item["rough_idea"])}'
            )
            button_options = {}
            if item["id"] == self.history_selection_id:
                button_options = {
                    "fg_color": ("#DCEBFA", "#1F538D"),
                    "text_color": ("#101820", "#FFFFFF"),
                }
            history_button = ctk.CTkButton(
                self.history_list,
                text=label[:90],
                anchor="w",
                command=lambda generation_id=item["id"]: self._select_history(
                    generation_id
                ),
                **button_options,
            )
            history_button.pack(fill="x", padx=6, pady=4)
            tooltip = self._add_tooltip(
                history_button, item["rough_idea"]
            )
            self._history_row_tooltips.append(tooltip)
        if not self.history_records:
            ctk.CTkLabel(
                self.history_list, text="No matching history entries."
            ).pack(fill="x", padx=6, pady=8)

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
        self._refresh_history()

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
        if self.history_selection:
            self._copy_text(self.history_selection.get("generated_prompt", ""))
