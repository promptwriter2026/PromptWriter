import tkinter
from tkinter import messagebox

import customtkinter as ctk

from promptwriter.config import LOCAL_ENGINE
from promptwriter.storage.profile_store import CONTEXT_LENGTH_CHOICES


class ModelProfileDialog(ctk.CTkToplevel):
    def __init__(self, parent, engine, model_name, profile, on_save, on_reset):
        super().__init__(parent)
        self.title(f"Model Profile: {model_name}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._engine = engine
        self._on_save = on_save
        self._on_reset = on_reset
        self._local = engine == LOCAL_ENGINE

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, padx=18, pady=(16, 8), sticky="nsew")
        body.grid_columnconfigure(1, weight=1)

        self.fields = {}
        self._add_entry(
            body, 0, "temperature", "Temperature", self._format(profile, "temperature", "{:.2f}")
        )
        self._add_entry(
            body, 1, "top_p", "Top-P", self._format(profile, "top_p", "{:g}")
        )
        self._add_entry(
            body, 2, "min_p", "Min-P", self._format(profile, "min_p", "{:g}"), local_only=True
        )
        self._add_entry(
            body,
            3,
            "repeat_penalty",
            "Repeat Penalty",
            self._format(profile, "repeat_penalty", "{:g}"),
            local_only=True,
        )
        self._add_entry(
            body,
            4,
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
        context_label = self._add_label(body, 5, "Context Length", local_only=True)
        self.context_menu.grid(row=5, column=1, padx=(10, 0), pady=5, sticky="ew")

        self.disable_thinking_var = tkinter.BooleanVar(
            self, value=bool(profile.get("disable_thinking"))
        )
        self.disable_thinking_checkbox = ctk.CTkCheckBox(
            body,
            text="Disable Thinking",
            variable=self.disable_thinking_var,
            state="normal" if self._local else "disabled",
        )
        thinking_label = self._add_label(body, 6, "Thinking", local_only=True)
        self.disable_thinking_checkbox.grid(
            row=6, column=1, padx=(10, 0), pady=6, sticky="w"
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
            hint.grid(row=7, column=0, columnspan=2, pady=(8, 0), sticky="w")

        self.error_label = ctk.CTkLabel(body, text="", text_color="red")
        self.error_label.grid(
            row=8, column=0, columnspan=2, pady=(8, 0), sticky="w"
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

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        width = max(460, self.winfo_reqwidth())
        height = self.winfo_reqheight()
        parent.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.lift()

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

    def _add_entry(self, parent, row, field, label, value, local_only=False):
        label_widget = self._add_label(parent, row, label, local_only=local_only)
        entry = ctk.CTkEntry(parent)
        entry.insert(0, value)
        if local_only and not self._local:
            entry.configure(state="disabled")
        entry.grid(row=row, column=1, padx=(10, 0), pady=5, sticky="ew")
        if local_only and not self._local:
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
                self.fields["temperature"], "Temperature", 0.0, 2.0
            ),
            "top_p": self._parse_float(
                self.fields["top_p"], "Top-P", 0.0, 1.0
            ),
            "min_p": None,
            "repeat_penalty": None,
            "max_tokens": None,
            "context_length": None,
            "disable_thinking": False,
        }
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
