import tkinter
from tkinter import messagebox

import customtkinter as ctk

from promptwriter.config import LOCAL_ENGINE
from promptwriter.storage.profile_store import (
    CONTEXT_LENGTH_CHOICES,
    PRESENCE_PENALTY_MAX,
    TEMPERATURE_MAX,
    supports_presence_penalty,
)
from promptwriter.ui.tooltip import ToolTip


class ModelProfileDialog(ctk.CTkToplevel):
    def __init__(self, parent, engine, model_name, profile, on_save, on_reset):
        super().__init__(parent)
        self.title(f"Model Profile: {model_name}")
        self._tooltips = []
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._engine = engine
        self._on_save = on_save
        self._on_reset = on_reset
        self._local = engine == LOCAL_ENGINE
        self._supports_presence = supports_presence_penalty(engine)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, padx=18, pady=(16, 8), sticky="nsew")
        body.grid_columnconfigure(1, weight=1)

        self._entry_target = None
        self._entry_menu = tkinter.Menu(self, tearoff=0)
        self._entry_menu.add_command(
            label="Cut", command=lambda: self._entry_event("<<Cut>>")
        )
        self._entry_menu.add_command(
            label="Copy", command=lambda: self._entry_event("<<Copy>>")
        )
        self._entry_menu.add_command(
            label="Paste", command=lambda: self._entry_event("<<Paste>>")
        )
        self._entry_menu.add_command(
            label="Select All", command=self._select_all_entry_text
        )

        self.fields = {}
        self._add_entry(
            body, 0, "temperature", "Temperature", self._format(profile, "temperature", "{:.2f}")
        )
        self._add_entry(
            body, 1, "top_p", "Top-P", self._format(profile, "top_p", "{:g}")
        )
        self._add_entry(
            body,
            2,
            "presence_penalty",
            "Presence Penalty",
            self._format(profile, "presence_penalty", "{:.2f}"),
            supported_only=True,
        )
        self._add_entry(
            body, 3, "min_p", "Min-P", self._format(profile, "min_p", "{:g}"), local_only=True
        )
        self._add_entry(
            body,
            4,
            "repeat_penalty",
            "Repeat Penalty",
            self._format(profile, "repeat_penalty", "{:g}"),
            local_only=True,
        )
        self._add_entry(
            body,
            5,
            "max_tokens",
            "Max Tokens",
            self._format(profile, "max_tokens", "{}"),
        )

        context_length = profile.get("context_length")
        self.context_menu = ctk.CTkComboBox(
            body,
            values=["Auto", *[str(value) for value in CONTEXT_LENGTH_CHOICES[1:]]],
            state="readonly" if self._local else "disabled",
        )
        self.context_menu.set("Auto" if context_length is None else str(context_length))
        context_label = self._add_label(body, 6, "Context Length", local_only=True)
        self.context_menu.grid(row=6, column=1, padx=(10, 0), pady=5, sticky="ew")
        self._add_tooltip(
            self.context_menu,
            "Local only: context window size used when loading the model.",
        )

        self.disable_thinking_var = tkinter.BooleanVar(
            self, value=bool(profile.get("disable_thinking"))
        )
        self.disable_thinking_checkbox = ctk.CTkCheckBox(
            body,
            text="Disable Thinking",
            variable=self.disable_thinking_var,
            state="normal" if self._local else "disabled",
        )
        thinking_label = self._add_label(body, 7, "Thinking", local_only=True)
        self.disable_thinking_checkbox.grid(
            row=7, column=1, padx=(10, 0), pady=6, sticky="w"
        )
        self._add_tooltip(
            self.disable_thinking_checkbox,
            "Local only: ask the model to skip reasoning tokens.",
        )
        if not self._local:
            context_label.grid_remove()
            self.context_menu.grid_remove()
            thinking_label.grid_remove()
            self.disable_thinking_checkbox.grid_remove()
        else:
            self.context_menu.lift()
            self.disable_thinking_checkbox.lift()

        if not self._local:
            hint = ctk.CTkLabel(
                body,
                text=(
                    "Min-P, Repeat Penalty, Context Length, and Disable Thinking "
                    "apply to Local (LM Studio) only."
                ),
                text_color="gray",
                wraplength=330,
                justify="left",
            )
            hint.grid(row=8, column=0, columnspan=2, pady=(8, 0), sticky="w")

        self.error_label = ctk.CTkLabel(body, text="", text_color="red")
        self.error_label.grid(
            row=9, column=0, columnspan=2, pady=(8, 0), sticky="w"
        )

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=1, column=0, padx=18, pady=(0, 16), sticky="ew")
        buttons.grid_columnconfigure((0, 1, 2), weight=1)
        self.reset_button = ctk.CTkButton(
            buttons, text="Reset to Default", command=self._reset
        )
        self.reset_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.cancel_button = ctk.CTkButton(
            buttons, text="Cancel", command=self.destroy
        )
        self.cancel_button.grid(row=0, column=1, padx=6, sticky="ew")
        self.save_button = ctk.CTkButton(
            buttons, text="Save Profile", command=self._save
        )
        self.save_button.grid(row=0, column=2, padx=(6, 0), sticky="ew")
        self._add_tooltip(
            self.reset_button, "Restore this model to the engine defaults."
        )
        self._add_tooltip(
            self.cancel_button, "Close without saving changes."
        )
        self._add_tooltip(
            self.save_button, "Save these sampling settings for this model."
        )

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        width = max(460, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        parent.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.lift()

    def _add_tooltip(self, widget, text):
        tooltip = ToolTip(widget, text)
        self._tooltips.append(tooltip)
        return tooltip

    def _show_entry_context_menu(self, event):
        self._entry_target = event.widget
        self._entry_menu.tk_popup(event.x_root, event.y_root)
        self._entry_menu.grab_release()
        return "break"

    def _entry_event(self, virtual_event):
        if self._entry_target is None:
            return
        self._entry_target.focus_set()
        self._entry_target.event_generate(virtual_event)

    def _select_all_entry_text(self):
        if self._entry_target is None:
            return
        self._entry_target.focus_set()
        self._entry_target.selection_range(0, "end")
        self._entry_target.icursor("end")

    @staticmethod
    def _format(profile, field, template):
        value = profile.get(field)
        return "" if value is None else template.format(value)

    def _add_label(self, parent, row, text, local_only=False):
        label = ctk.CTkLabel(
            parent,
            text=f"{text} (Local)" if local_only else text,
            text_color="gray" if local_only and not self._local else None,
        )
        label.grid(row=row, column=0, pady=5, sticky="w")
        return label

    def _add_entry(
        self,
        parent,
        row,
        field,
        label,
        value,
        local_only=False,
        supported_only=False,
    ):
        label_widget = self._add_label(parent, row, label, local_only=local_only)
        entry = ctk.CTkEntry(parent)
        entry.insert(0, value)
        unsupported = supported_only and not self._supports_presence
        if (local_only and not self._local) or unsupported:
            entry.configure(state="disabled")
        entry.grid(row=row, column=1, padx=(10, 0), pady=5, sticky="ew")
        entry._entry.bind("<Button-3>", self._show_entry_context_menu)
        tooltip_text = {
            "temperature": "Controls randomness from 0.00 to 1.00; higher values produce more varied prompts.",
            "top_p": "Nucleus sampling; lower values keep only the most likely tokens.",
            "presence_penalty": "Groq / Local only: 0.00 to 2.00; sent only when above 0.00.",
            "min_p": "Local only: drops tokens below this fraction of the top token.",
            "repeat_penalty": "Local only: penalizes repeated tokens; higher values reduce repetition.",
            "max_tokens": "Maximum number of tokens the model may generate.",
        }.get(field)
        if tooltip_text:
            self._add_tooltip(entry, tooltip_text)
        if (local_only and not self._local) or unsupported:
            label_widget.grid_remove()
            entry.grid_remove()
        self.fields[field] = entry
        return entry

    @staticmethod
    def _parse_float(entry, label, minimum, maximum):
        text = entry.get().strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError as error:
            raise ValueError(f"{label} must be a number.") from error
        if not minimum <= value <= maximum:
            raise ValueError(f"{label} must be between {minimum} and {maximum}.")
        return value

    def _read_values(self):
        values = {
            "temperature": self._parse_float(
                self.fields["temperature"],
                "Temperature",
                0.0,
                TEMPERATURE_MAX,
            ),
            "top_p": self._parse_float(
                self.fields["top_p"], "Top-P", 0.0, 1.0
            ),
            "presence_penalty": 0.0,
            "min_p": None,
            "repeat_penalty": None,
            "max_tokens": None,
            "context_length": None,
            "disable_thinking": False,
        }
        if self._supports_presence:
            values["presence_penalty"] = self._parse_float(
                self.fields["presence_penalty"],
                "Presence Penalty",
                0.0,
                PRESENCE_PENALTY_MAX,
            )
        max_tokens_text = self.fields["max_tokens"].get().strip()
        if max_tokens_text:
            try:
                max_tokens = int(max_tokens_text)
            except ValueError as error:
                raise ValueError("Max Tokens must be a whole number.") from error
            if max_tokens <= 0:
                raise ValueError("Max Tokens must be greater than zero.")
            values["max_tokens"] = max_tokens

        if self._local:
            values["min_p"] = self._parse_float(
                self.fields["min_p"], "Min-P", 0.0, 1.0
            )
            repeat_penalty = self._parse_float(
                self.fields["repeat_penalty"], "Repeat Penalty", 0.0, 3.0
            )
            if repeat_penalty is not None and repeat_penalty <= 0:
                raise ValueError("Repeat Penalty must be greater than zero.")
            values["repeat_penalty"] = repeat_penalty
            context_choice = self.context_menu.get()
            if context_choice != "Auto":
                values["context_length"] = int(context_choice)
            values["disable_thinking"] = self.disable_thinking_var.get()
        return values

    def _save(self):
        try:
            values = self._read_values()
            self._on_save(values)
        except (OSError, ValueError) as error:
            self.error_label.configure(text=str(error))
            return
        self.destroy()

    def _reset(self):
        if not messagebox.askyesno(
            "Reset Profile",
            "Reset this model profile to the engine defaults?",
            parent=self,
        ):
            return
        try:
            self._on_reset()
        except OSError as error:
            self.error_label.configure(text=str(error))
            return
        self.destroy()
