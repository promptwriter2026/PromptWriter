import json
import sqlite3
import threading
import time
import tkinter
from tkinter import messagebox

import customtkinter as ctk
import requests

from promptwriter.config import (
    LLM_ENGINES,
    LOCAL_ENGINE,
    MODEL_PLACEHOLDER,
    ROUGH_IDEA_CACHE_PATH,
    SYSTEM_PROMPTS_DIR,
)
from promptwriter.services.llm_client import request_generated_prompt
from promptwriter.services.lm_studio_api import ensure_model_loaded
from promptwriter.services.lora import (
    enforce_lora_trigger_prefix,
    find_lora_profile,
    lora_profile_value,
)
from promptwriter.services.prompt_builder import assemble_text_request
from promptwriter.storage.config_store import load_config
from promptwriter.storage.history_db import insert_generation
from promptwriter.storage.profile_store import (
    profile_context_length,
    profile_request_kwargs,
)
from promptwriter.utils.text import (
    format_as_single_line_prompts,
    is_numeric_result,
)


class GeneratorTabMixin:
    def _build_generator_tab(self):
        tab = self.generator_tab
        tab.grid_columnconfigure(0, weight=1, uniform="generator_columns")
        tab.grid_columnconfigure(1, weight=1, uniform="generator_columns")
        tab.grid_rowconfigure(6, weight=0)
        tab.grid_rowconfigure(9, weight=2, minsize=80)

        ctk.CTkLabel(tab, text="LLM engine").grid(
            row=0, column=0, padx=12, pady=(10, 4), sticky="w"
        )
        self.engine_menu = ctk.CTkOptionMenu(
            tab, values=LLM_ENGINES, command=self._on_generator_engine_selected
        )
        self.engine_menu.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")
        self._add_tooltip(
            self.engine_menu, "Select the API provider (e.g., Groq or Gemini)."
        )

        ctk.CTkLabel(tab, text="Selected API model").grid(
            row=0, column=1, padx=12, pady=(10, 4), sticky="w"
        )
        api_model_frame = ctk.CTkFrame(tab, fg_color="transparent")
        api_model_frame.grid(
            row=1, column=1, padx=12, pady=(0, 8), sticky="ew"
        )
        api_model_frame.grid_columnconfigure(0, weight=1)
        self.api_model_menu = ctk.CTkComboBox(
            api_model_frame,
            values=[MODEL_PLACEHOLDER],
            state="readonly",
            command=self._on_api_model_changed,
        )
        self.api_model_menu.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self._add_tooltip(
            self.api_model_menu, "Select the API model used to generate prompts."
        )
        self.generator_fetch_button = ctk.CTkButton(
            api_model_frame,
            text="Fetch",
            width=64,
            command=lambda: self._fetch_available_models("generator"),
        )
        self.generator_fetch_button.grid(row=0, column=1, sticky="e")
        self._add_tooltip(
            self.generator_fetch_button, "Fetch available models from the API provider."
        )
        self.generator_profile_button = ctk.CTkButton(
            api_model_frame,
            text="⚙",
            width=34,
            command=lambda: self._open_profile_dialog("text"),
        )
        self.generator_profile_button.grid(row=0, column=2, padx=(6, 0), sticky="e")
        self._add_tooltip(
            self.generator_profile_button,
            "Edit sampling settings for the selected model.",
        )

        ctk.CTkLabel(tab, text="System prompt").grid(
            row=2, column=0, padx=12, pady=(4, 2), sticky="w"
        )
        self.model_menu = ctk.CTkOptionMenu(
            tab, values=[""]
        )
        self.model_menu.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="ew")
        self._add_tooltip(
            self.model_menu,
            "Choose the system prompt that defines how generated prompts are written.",
        )

        ctk.CTkLabel(tab, text="Camera / lens").grid(
            row=2, column=1, padx=12, pady=(4, 2), sticky="w"
        )
        self.camera_menu = ctk.CTkOptionMenu(tab, values=["None / Auto"])
        self.camera_menu.grid(row=3, column=1, padx=12, pady=(0, 8), sticky="ew")
        self._add_tooltip(
            self.camera_menu,
            "Select a camera setup to inject professional photography keywords into your prompt.",
        )

        ctk.CTkLabel(tab, text="Character / LoRA").grid(
            row=4, column=0, padx=12, pady=(4, 2), sticky="w"
        )
        self.lora_menu = ctk.CTkOptionMenu(
            tab, values=["None"], variable=self.generator_lora_var
        )
        self.lora_menu.grid(row=5, column=0, padx=12, pady=(0, 8), sticky="ew")
        self._add_tooltip(
            self.lora_menu,
            "Apply a character profile and its trigger words to the generation.",
        )
        generator_temperature_frame = ctk.CTkFrame(tab, fg_color="transparent")
        generator_temperature_frame.grid(
            row=6, column=0, padx=12, pady=(0, 8), sticky="ew"
        )
        generator_temperature_frame.grid_columnconfigure(1, weight=1)
        self.generator_temperature_frame = generator_temperature_frame
        self._generator_controls_minheight = 0
        self._generator_controls_sync_active = False
        self._generator_controls_sync_pending = False
        self._generator_controls_wrap_width = None
        self._generator_controls_wrap_job = None
        self._status_wrap_job = None
        self._status_wrap_width = None
        self._status_wrap_busy = False
        self.generator_temp_label = ctk.CTkLabel(
            generator_temperature_frame, text="Temp: 0.70", height=20
        )
        self.generator_temp_label.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.generator_temp_slider = ctk.CTkSlider(
            generator_temperature_frame,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            variable=self.generator_temp_var,
            command=self._update_generator_temp_label,
        )
        self.generator_temp_slider.grid(row=0, column=1, sticky="ew")
        self._add_tooltip(
            self.generator_temp_slider,
            "Adjust text prompt variety from 0.00 to 1.00; saved values above 1.00 are capped.",
        )
        self.generator_profile_label = ctk.CTkLabel(
            generator_temperature_frame,
            text="Default profile",
            text_color="gray",
            anchor="w",
            justify="left",
            height=18,
            font=ctk.CTkFont(size=11),
        )
        self.generator_profile_label.grid(
            row=1, column=0, columnspan=2, pady=(2, 0), sticky="ew"
        )
        self._add_tooltip(
            self.generator_profile_label,
            "Profile settings for the selected engine and model.",
        )
        self.generator_auto_unload_checkbox = ctk.CTkCheckBox(
            generator_temperature_frame,
            text="Auto-Unload Model from VRAM",
            variable=self.auto_unload_var,
        )
        self.generator_auto_unload_checkbox.grid(
            row=2, column=0, padx=(0, 8), pady=(4, 0), sticky="w"
        )
        self._add_tooltip(
            self.generator_auto_unload_checkbox,
            "Automatically unload the Local model from VRAM after each generation.",
        )
        self.generator_clear_vram_button = ctk.CTkButton(
            generator_temperature_frame,
            text="Unload Model",
            width=120,
            height=24,
            command=self._clear_lm_studio_vram,
        )
        self.generator_clear_vram_button.grid(
            row=2, column=1, padx=(8, 0), pady=(4, 0), sticky="w"
        )
        self._add_tooltip(
            self.generator_clear_vram_button,
            "Unload the Local model from LM Studio and free VRAM now.",
        )
        self.generator_lm_studio_status_label = ctk.CTkLabel(
            generator_temperature_frame,
            text="LM Studio Status: [Checking...]",
            anchor="w",
            justify="left",
            height=18,
            wraplength=320,
        )
        self.generator_lm_studio_status_label.grid(
            row=4, column=0, columnspan=2, pady=(4, 0), sticky="ew"
        )
        self._add_tooltip(
            self.generator_lm_studio_status_label,
            "Shows which model is currently loaded in LM Studio.",
        )
        generator_temperature_frame.bind(
            "<Configure>", self._update_generator_controls_layout
        )

        rough_idea_header = ctk.CTkFrame(tab, fg_color="transparent")
        rough_idea_header.grid(
            row=4, column=1, padx=12, pady=(4, 4), sticky="ew"
        )
        ctk.CTkLabel(rough_idea_header, text="Rough idea").pack(
            side="left", anchor="w"
        )
        self.clear_rough_idea_button = ctk.CTkButton(
            rough_idea_header,
            text="Clear",
            width=60,
            height=26,
            command=self._clear_rough_idea,
        )
        self.clear_rough_idea_button.pack(side="right")
        self._add_tooltip(
            self.clear_rough_idea_button, "Instantly clear the rough idea text."
        )

        self.rough_idea_text = ctk.CTkTextbox(tab, height=96, wrap="word")
        self.rough_idea_text.grid(
            row=5, column=1, rowspan=2, padx=12, pady=(0, 8), sticky="nsew"
        )
        self._add_tooltip(
            self.rough_idea_text,
            "Type your basic idea or scene description here.",
        )

        self.generate_button = ctk.CTkButton(
            tab, text="Generate Prompt", command=self._generate_prompt
        )
        self.generate_button.grid(
            row=7, column=0, padx=12, pady=(0, 6), sticky="w"
        )
        self._add_tooltip(
            self.generate_button, "Send the data to the LLM to create your prompt."
        )
        generation_status_frame = ctk.CTkFrame(tab, fg_color="transparent")
        generation_status_frame.grid(
            row=7, column=1, padx=12, pady=(0, 6), sticky="ew"
        )
        generation_status_frame.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(
            generation_status_frame,
            text="Ready",
            text_color="gray",
            wraplength=400,
            justify="right",
        )
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.status_label.bind("<Configure>", self._update_status_wraplength)
        self.quota_label = ctk.CTkLabel(
            generation_status_frame, text="Quota: N/A", text_color="gray"
        )
        self.quota_label.grid(row=0, column=2, padx=(8, 0), sticky="e")
        self.time_label = ctk.CTkLabel(
            generation_status_frame, text="Time: --", text_color="gray"
        )
        self.time_label.grid(row=0, column=1, padx=(8, 0), sticky="e")

        output_header = ctk.CTkFrame(tab, fg_color="transparent")
        output_header.grid(
            row=8, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="ew"
        )
        output_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(output_header, text="Generated prompt").grid(
            row=0, column=0, sticky="w"
        )
        self.generator_single_line_checkbox = ctk.CTkCheckBox(
            output_header,
            text="Enforce Single-Line Prompts",
            variable=self.force_single_line_var,
        )
        self.generator_single_line_checkbox.grid(row=0, column=1, sticky="e")
        self._add_tooltip(
            self.generator_single_line_checkbox,
            "Collapse multi-line output into clean single-line prompts.",
        )
        self.output_text = ctk.CTkTextbox(tab, wrap="word")
        self.output_text.grid(
            row=9, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="nsew"
        )
        self._add_tooltip(
            self.output_text, "The final generated prompt will appear here."
        )
        self.output_text.configure(state="disabled")
        self.text_context_menu = tkinter.Menu(self, tearoff=0)
        self.text_context_menu.add_command(
            label="Cut", command=lambda: self._generate_text_event("<<Cut>>")
        )
        self.text_context_menu.add_command(
            label="Copy", command=lambda: self._generate_text_event("<<Copy>>")
        )
        self.text_context_menu.add_command(
            label="Paste", command=lambda: self._generate_text_event("<<Paste>>")
        )
        self.text_context_menu.add_command(
            label="Select All",
            command=lambda: self._generate_text_event("<<SelectAll>>"),
        )
        self.rough_idea_text._textbox.bind(
            "<Button-3>", self._show_text_context_menu
        )
        self.output_text._textbox.bind("<Button-3>", self._show_text_context_menu)
        self.rough_idea_text._textbox.bind(
            "<<SelectAll>>", self._select_all_text
        )
        self.output_text._textbox.bind("<<SelectAll>>", self._select_all_text)

        self.copy_button = ctk.CTkButton(
            tab, text="Copy to Clipboard", command=self._copy_output
        )
        self.copy_button.grid(
            row=10, column=0, columnspan=2, padx=12, pady=(0, 6)
        )
        self._add_tooltip(
            self.copy_button, "Copy the final generated prompt to your clipboard."
        )

    def _load_rough_idea(self):
        try:
            rough_idea = ROUGH_IDEA_CACHE_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as error:
            messagebox.showerror(
                "Could Not Load Rough Idea",
                f"Could not load the saved rough idea: {error}",
                parent=self,
            )
            return
        self.rough_idea_text.insert("1.0", rough_idea)

    def _save_rough_idea(self):
        rough_idea = self.rough_idea_text.get("1.0", "end-1c")
        try:
            ROUGH_IDEA_CACHE_PATH.write_text(rough_idea, encoding="utf-8")
        except OSError as error:
            messagebox.showerror(
                "Could Not Save Rough Idea",
                f"Could not save the rough idea: {error}",
                parent=self,
            )
            return False
        return True

    def _update_generator_temp_label(self, value=None):
        temperature = (
            self.generator_temp_var.get() if value is None else float(value)
        )
        self.generator_temp_label.configure(text=f"Temp: {temperature:.2f}")
        self._update_profile_summary("text")

    _WRAP_DEBOUNCE_MS = 30
    _WRAP_HYSTERESIS_PX = 8

    def _update_status_wraplength(self, event):
        width = int(event.width)
        previous_width = self._status_wrap_width
        if previous_width is not None:
            if abs(width - previous_width) < self._WRAP_HYSTERESIS_PX:
                return
        self._status_wrap_width = width
        if self._status_wrap_job is not None:
            try:
                self.after_cancel(self._status_wrap_job)
            except (tkinter.TclError, ValueError):
                pass
        # A timer (not after_idle) keeps applying the new wraplength out of the
        # Tk event/idle dispatch chain, so a configure cannot re-enter itself.
        self._status_wrap_job = self.after(
            self._WRAP_DEBOUNCE_MS,
            self._apply_status_wraplength,
            max(200, width - 24),
        )

    def _apply_status_wraplength(self, wraplength):
        self._status_wrap_job = None
        if self._status_wrap_busy:
            return
        self._status_wrap_busy = True
        try:
            if self.status_label.cget("wraplength") != wraplength:
                self.status_label.configure(wraplength=wraplength)
        except tkinter.TclError:
            pass
        finally:
            self._status_wrap_busy = False

    def _update_generator_controls_layout(self, event):
        wraplength = max(180, event.width - 24)
        previous_width = self._generator_controls_wrap_width
        if previous_width is None or abs(wraplength - previous_width) >= (
            self._WRAP_HYSTERESIS_PX
        ):
            self._generator_controls_wrap_width = wraplength
            if self._generator_controls_wrap_job is not None:
                try:
                    self.after_cancel(self._generator_controls_wrap_job)
                except (tkinter.TclError, ValueError):
                    pass
            self._generator_controls_wrap_job = self.after(
                self._WRAP_DEBOUNCE_MS,
                self._apply_generator_controls_wraplength,
                wraplength,
            )
        self._schedule_generator_controls_sync()

    def _apply_generator_controls_wraplength(self, wraplength):
        self._generator_controls_wrap_job = None
        try:
            for label in (
                self.generator_lm_studio_status_label,
                self.generator_profile_label,
            ):
                if label.cget("wraplength") != wraplength:
                    label.configure(wraplength=wraplength)
        except tkinter.TclError:
            pass

    def _schedule_generator_controls_sync(self):
        if self._generator_controls_sync_pending:
            return
        self._generator_controls_sync_pending = True
        self.after(
            self._WRAP_DEBOUNCE_MS * 2, self._sync_generator_controls_height
        )

    def _sync_generator_controls_height(self):
        self._generator_controls_sync_pending = False
        if self._generator_controls_sync_active:
            return
        self._generator_controls_sync_active = True
        try:
            frame = self.generator_temperature_frame
            # No update_idletasks() here: pumping idle callbacks from a layout
            # handler can re-enter the wrap callbacks that scheduled it.
            pady = frame.grid_info().get("pady", 0)
            if isinstance(pady, (tuple, list)):
                padding = sum(int(value) for value in pady)
            else:
                padding = sum(int(part) for part in str(pady).split())
            required_height = frame.winfo_reqheight() + padding
            if required_height != self._generator_controls_minheight:
                self._generator_controls_minheight = required_height
                self.generator_tab.grid_rowconfigure(6, minsize=required_height)
        except (tkinter.TclError, ValueError):
            pass
        finally:
            self._generator_controls_sync_active = False

    def _generate_prompt(self):
        if self.generate_button.cget("state") == "disabled":
            return

        user_idea = self.rough_idea_text.get("1.0", "end").strip()
        if not user_idea:
            self.status_label.configure(
                text="Enter a rough idea before generating.", text_color="red"
            )
            return

        try:
            request_parts = assemble_text_request(
                SYSTEM_PROMPTS_DIR / f"{self.model_menu.get()}.txt",
                self.lora_menu.get(),
                self.lora_profiles,
                self.camera_menu.get(),
                user_idea,
            )
            config_data = load_config()
            engine = self.engine_menu.get()
            if engine not in LLM_ENGINES:
                raise ValueError("Choose a valid LLM engine.")
            if engine == LOCAL_ENGINE:
                api_key = "local-key"
            else:
                api_key = config_data.get(
                    "gemini_api_key" if engine == "Gemini" else "groq_api_key", ""
                )
                if not isinstance(api_key, str):
                    raise ValueError(f"The saved {engine} API key must be text.")
                api_key = api_key.strip()
                if not api_key:
                    raise ValueError(
                        f"API Key missing: add and save your {engine} API key in Settings."
                    )
            api_model = self.api_model_menu.get()
            if not isinstance(api_model, str) or not api_model.strip():
                raise ValueError(f"Select an available {engine} API model.")
            api_model = api_model.strip()
            if api_model == MODEL_PLACEHOLDER:
                raise ValueError(f"Fetch and select an available {engine} API model.")
            generation_settings = {
                "target_model": self.model_menu.get(),
                "camera_lens": self.camera_menu.get(),
                "character_lora": self.lora_menu.get(),
                "llm_engine": engine,
                "api_model": api_model,
                "auto_unload": self.auto_unload_var.get(),
            }
            generation_settings.update(
                profile_request_kwargs(engine, self.generator_profile)
            )
            generation_settings["context_length"] = profile_context_length(
                engine, self.generator_profile
            )
            generation_settings["temperature"] = self.generator_temp_var.get()
            force_single_line = self.force_single_line_var.get()
            generation_settings["force_single_line"] = force_single_line
            selected_profile = find_lora_profile(
                generation_settings["character_lora"], self.lora_profiles
            )
            generation_settings["trigger_words"] = (
                lora_profile_value(selected_profile, "trigger_word")
                if selected_profile
                else ""
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.status_label.configure(text=f"Error: {error}", text_color="red")
            return

        free_external_vram_first = False
        if engine == LOCAL_ENGINE:
            proceed, free_external_vram_first = (
                self._local_generation_preflight()
            )
            if not proceed:
                return
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")
        self.generate_button.configure(state="disabled")
        self.status_label.configure(
            text=(
                "Unloading ComfyUI / Forge Neo VRAM..."
                if free_external_vram_first
                else "Generating..."
            ),
            text_color="gray",
        )
        self.time_label.configure(text="Generating...", text_color="gray")
        self._update_quota_label(self.quota_label, engine, None)
        threading.Thread(
            target=self._generation_worker,
            args=(
                engine,
                api_key,
                api_model,
                request_parts,
                user_idea,
                generation_settings,
                force_single_line,
                free_external_vram_first,
            ),
            daemon=True,
        ).start()

    def _generation_worker(
        self,
        engine,
        api_key,
        api_model,
        request_parts,
        user_idea,
        generation_settings,
        force_single_line,
        free_external_vram_first=False,
    ):
        start_time = None
        elapsed = None
        try:
            if engine == LOCAL_ENGINE and free_external_vram_first:
                self._free_external_vram_in_worker("generator")
            if engine == LOCAL_ENGINE:
                ensure_model_loaded(
                    api_model,
                    context_length=generation_settings.get("context_length"),
                )
            start_time = time.time()
            generated_prompt, quota, total_used = request_generated_prompt(
                engine,
                api_key,
                api_model,
                request_parts,
                include_quota=True,
                temperature=generation_settings["temperature"],
                top_p=generation_settings.get("top_p"),
                min_p=generation_settings.get("min_p"),
                repeat_penalty=generation_settings.get("repeat_penalty"),
                max_tokens=generation_settings.get("max_tokens"),
                disable_thinking=generation_settings.get(
                    "disable_thinking", False
                ),
            )
            elapsed = time.time() - start_time
            if engine == LOCAL_ENGINE and generation_settings["auto_unload"]:
                self._auto_unload_lm_studio_model()
            generated_prompt = enforce_lora_trigger_prefix(
                generated_prompt, generation_settings.get("trigger_words", "")
            )
            if not generated_prompt or is_numeric_result(generated_prompt):
                raise ValueError("The generation result was not prompt text.")
        except requests.exceptions.RequestException as error:
            if start_time is not None:
                elapsed = time.time() - start_time
            self.after(
                0,
                self.handle_generation_error,
                f"{engine} generation failed: {error}",
                "generator",
                elapsed,
                engine,
            )
            return
        except Exception as error:
            if start_time is not None:
                elapsed = time.time() - start_time
            self.after(
                0,
                self.handle_generation_error,
                f"{engine} generation failed: {error}",
                "generator",
                elapsed,
                engine,
            )
            return

        self.after(
            0,
            self._on_generation_success,
            generated_prompt,
            engine,
            quota,
            total_used,
            elapsed,
            user_idea,
            generation_settings,
            api_model,
            force_single_line,
        )

    def _on_generation_success(
        self,
        generated_prompt,
        engine,
        quota,
        total_used,
        elapsed,
        user_idea,
        generation_settings,
        api_model,
        force_single_line,
    ):
        if not isinstance(generated_prompt, str):
            self._on_generation_error(
                "LLM", "The generation result was not prompt text.", elapsed
            )
            return
        if force_single_line:
            generated_prompt = format_as_single_line_prompts(generated_prompt)
        if is_numeric_result(generated_prompt):
            self._on_generation_error(
                "LLM", "The generation result was not prompt text.", elapsed
            )
            return
        if not generated_prompt:
            self._on_generation_error(
                "LLM", "The generation result was empty.", elapsed
            )
            return
        history_error = None
        try:
            insert_generation(
                user_idea,
                generated_prompt,
                generation_settings,
                source_tab="generator",
                engine=engine,
                model=api_model,
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            history_error = f"Generated, but could not save history: {error}"
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", generated_prompt)
        self.time_label.configure(text=f"Time: {elapsed:.1f}s")
        self.output_text.configure(state="disabled")
        self.generate_button.configure(state="normal")
        self._update_quota_label(
            self.quota_label, engine, quota, total_used
        )
        if history_error:
            self.status_label.configure(text=history_error, text_color="red")
        else:
            self.status_label.configure(text="Ready", text_color="gray")
        self._refresh_history()

    def _on_generation_error(self, engine, error_message, elapsed=None):
        self.handle_generation_error(
            f"{engine} generation failed: {error_message}",
            "generator",
            elapsed,
            engine,
        )

    def _copy_output(self):
        self._copy_text(self.output_text.get("1.0", "end").strip())

    def _clear_rough_idea(self):
        self.rough_idea_text.delete("1.0", "end")
