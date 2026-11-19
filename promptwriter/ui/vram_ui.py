import time
import tkinter

import customtkinter as ctk
import requests

from promptwriter.services.lm_studio_api import get_lm_studio_loaded_models
from promptwriter.services.vram_cleanup_api import (
    PREFLIGHT_CANCEL,
    PREFLIGHT_LOAD_ANYWAY,
    PREFLIGHT_UNLOAD,
    VRAM_PREFLIGHT_THRESHOLD,
    free_external_vram_from_config,
    preflight_flags,
    should_prompt_vram_unload,
)
from promptwriter.services.vram_monitor import (
    VRAM_COLOR_NEUTRAL,
    VRAM_ERROR_LABEL,
    format_vram_usage,
    get_gpu_memory_usage,
    shutdown_nvml,
    vram_usage_color,
)


VRAM_POLL_INTERVAL_MS = 2000
LM_STUDIO_PREFLIGHT_TIMEOUT = 2
VRAM_RELEASE_WAIT_SECONDS = 1.0


class VRAMMixin:
    def _build_vram_indicator(self):
        self._vram_after_id = None
        self.vram_label = ctk.CTkLabel(
            self,
            text=VRAM_ERROR_LABEL,
            text_color=VRAM_COLOR_NEUTRAL,
            font=ctk.CTkFont(size=12),
        )
        self.vram_label.place(relx=1.0, x=-22, y=21, anchor="e")
        self.bind("<Configure>", self._position_vram_label, add="+")
        self.after_idle(self._position_vram_label)
        self._add_tooltip(
            self.vram_label,
            "Live GPU 0 VRAM usage, refreshed every 2 seconds.",
        )

    def _position_vram_label(self, event=None):
        if not hasattr(self, "vram_label"):
            return
        try:
            segmented_button = self.tabs._segmented_button
            segmented_button.update_idletasks()
            center_y = (
                self.tabs.winfo_y()
                + segmented_button.winfo_y()
                + segmented_button.winfo_height() / 2
            )
            self.vram_label.place_configure(
                relx=1.0, x=-22, y=center_y, anchor="e"
            )
        except (AttributeError, tkinter.TclError):
            pass

    def _start_vram_polling(self):
        self._poll_vram_usage()

    def _poll_vram_usage(self):
        self._vram_after_id = None
        if getattr(self, "_closing", False):
            return
        memory = get_gpu_memory_usage()
        self._update_vram_label(memory)
        try:
            self._vram_after_id = self.after(
                VRAM_POLL_INTERVAL_MS, self._poll_vram_usage
            )
        except tkinter.TclError:
            self._vram_after_id = None

    def _update_vram_label(self, memory):
        if not hasattr(self, "vram_label"):
            return
        color = (
            vram_usage_color(memory["percent"])
            if memory
            else VRAM_COLOR_NEUTRAL
        )
        try:
            self.vram_label.configure(
                text=format_vram_usage(memory), text_color=color
            )
        except (KeyError, TypeError, ValueError, tkinter.TclError):
            pass

    def _stop_vram_polling(self):
        if self._vram_after_id is not None:
            try:
                self.after_cancel(self._vram_after_id)
            except tkinter.TclError:
                pass
            self._vram_after_id = None
        shutdown_nvml()

    def _local_generation_preflight(self):
        """Return (proceed, free_external_vram) for a Local generation click."""
        action = self._preflight_local_vram()
        if action is None:
            return True, False
        return preflight_flags(action)

    def _preflight_local_vram(self):
        """Ask about external VRAM when needed; return the chosen action or None."""
        memory = get_gpu_memory_usage()
        if not memory:
            return None
        if memory["percent"] <= VRAM_PREFLIGHT_THRESHOLD:
            return None
        try:
            loaded_models = get_lm_studio_loaded_models(
                timeout=LM_STUDIO_PREFLIGHT_TIMEOUT
            )
        except (requests.exceptions.RequestException, ValueError):
            return None
        if not should_prompt_vram_unload(memory, loaded_models):
            return None
        return self._ask_vram_preflight(memory)

    def _ask_vram_preflight(self, memory):
        result = {"action": PREFLIGHT_CANCEL}
        dialog = ctk.CTkToplevel(self)
        dialog.title("High VRAM Usage Detected")
        dialog.resizable(False, False)
        dialog.transient(self)

        def choose(action):
            result["action"] = action
            try:
                dialog.grab_release()
            except tkinter.TclError:
                pass
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", lambda: choose(PREFLIGHT_CANCEL))
        dialog.bind("<Escape>", lambda event: choose(PREFLIGHT_CANCEL))

        content = ctk.CTkFrame(dialog, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=16)
        ctk.CTkLabel(
            content,
            text=(
                f"VRAM is currently at {memory['percent']:.0f}% "
                f"({memory['used_gb']:.1f} / "
                f"{memory['total_gb']:.1f} GB), and no local LLM "
                "is loaded yet.\n\n"
                "Unload ComfyUI / Forge Neo models before generating?"
            ),
            justify="left",
            anchor="w",
            wraplength=430,
        ).pack(fill="x")
        ctk.CTkLabel(
            content,
            text="Load Anyway proceeds without unloading external VRAM.",
            justify="left",
            anchor="w",
            wraplength=430,
            text_color="gray",
            font=ctk.CTkFont(size=11),
        ).pack(fill="x", pady=(8, 0))

        buttons = ctk.CTkFrame(content, fg_color="transparent")
        buttons.pack(fill="x", pady=(18, 0))
        buttons.grid_columnconfigure((0, 1, 2), weight=1)
        unload_button = ctk.CTkButton(
            buttons,
            text="Unload & Load",
            width=130,
            command=lambda: choose(PREFLIGHT_UNLOAD),
        )
        unload_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        ctk.CTkButton(
            buttons,
            text="Load Anyway",
            width=130,
            fg_color="gray30",
            hover_color="gray20",
            command=lambda: choose(PREFLIGHT_LOAD_ANYWAY),
        ).grid(row=0, column=1, padx=6, sticky="ew")
        ctk.CTkButton(
            buttons,
            text="Cancel",
            width=90,
            fg_color="gray30",
            hover_color="gray20",
            command=lambda: choose(PREFLIGHT_CANCEL),
        ).grid(row=0, column=2, padx=(6, 0), sticky="ew")

        dialog.update_idletasks()
        x = self.winfo_rootx() + (
            self.winfo_width() - dialog.winfo_reqwidth()
        ) // 2
        y = self.winfo_rooty() + (
            self.winfo_height() - dialog.winfo_reqheight()
        ) // 3
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        dialog.lift()
        dialog.focus_force()
        try:
            dialog.grab_set()
        except tkinter.TclError:
            pass
        unload_button.focus_set()
        dialog.wait_window()
        return result["action"]

    def _set_generation_status(self, context, text, color="gray"):
        label = (
            self.image_status_label if context == "image" else self.status_label
        )
        try:
            label.configure(text=text, text_color=color)
        except tkinter.TclError:
            pass

    def _free_external_vram_in_worker(self, context):
        self._schedule_ui(
            0,
            self._set_generation_status,
            context,
            "Unloading ComfyUI / Forge Neo VRAM...",
            "gray",
        )
        try:
            freed = free_external_vram_from_config()
        except (OSError, ValueError):
            freed = []
        if freed:
            time.sleep(VRAM_RELEASE_WAIT_SECONDS)
        self._schedule_ui(
            0, self._set_generation_status, context, "Generating...", "gray"
        )
        return freed
