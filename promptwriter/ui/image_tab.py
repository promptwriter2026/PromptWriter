import json
import sqlite3
import threading
import time
import tkinter
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import requests
from PIL import Image, ImageOps
from tkinterdnd2 import DND_FILES

from promptwriter.config import (
    LLM_ENGINES,
    LOCAL_ENGINE,
    VISION_SYSTEM_PROMPTS_DIR,
)
from promptwriter.services.image_tools import optimize_image_for_api
from promptwriter.services.llm_client import request_generated_prompt
from promptwriter.services.lm_studio_api import ensure_model_loaded
from promptwriter.services.lora import (
    enforce_lora_trigger_prefix,
    find_lora_profile,
    lora_profile_value,
)
from promptwriter.services.prompt_builder import assemble_image_request
from promptwriter.storage.config_store import load_config
from promptwriter.storage.history_db import insert_generation
from promptwriter.storage.profile_store import profile_request_kwargs
from promptwriter.utils.text import (
    format_as_single_line_prompts,
    is_numeric_result,
    truncate_filename,
)


class ImagePromptTabMixin:
    def _build_image_prompt_tab(self):
        tab = self.image_prompt_tab
        tab.grid_columnconfigure(0, weight=1, uniform="image_columns")
        tab.grid_columnconfigure(1, weight=1, uniform="image_columns")
        tab.grid_rowconfigure(5, weight=1)
        tab.grid_rowconfigure(9, weight=2, minsize=80)

        ctk.CTkLabel(tab, text="LLM engine").grid(
            row=0, column=0, padx=12, pady=(10, 4), sticky="w"
        )
        self.image_engine_menu = ctk.CTkOptionMenu(
            tab, values=LLM_ENGINES, command=self._on_image_engine_selected
        )
        self.image_engine_menu.grid(
            row=1, column=0, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.image_engine_menu,
            "Select the API provider (e.g., Groq or Gemini).",
        )

        ctk.CTkLabel(tab, text="Selected API model").grid(
            row=0, column=1, padx=12, pady=(10, 4), sticky="w"
        )
        image_api_model_frame = ctk.CTkFrame(tab, fg_color="transparent")
        image_api_model_frame.grid(
            row=1, column=1, padx=12, pady=(0, 8), sticky="ew"
        )
        image_api_model_frame.grid_columnconfigure(0, weight=1)
        self.image_api_model_menu = ctk.CTkComboBox(
            image_api_model_frame,
            values=["Fetch models first"],
            state="readonly",
            command=self._on_image_api_model_changed,
        )
        self.image_api_model_menu.grid(
            row=0, column=0, padx=(0, 6), sticky="ew"
        )
        self._add_tooltip(
            self.image_api_model_menu,
            "Select the API model used to analyze images.",
        )
        self.image_fetch_button = ctk.CTkButton(
            image_api_model_frame,
            text="Fetch",
            width=64,
            command=lambda: self._fetch_available_models("vision"),
        )
        self.image_fetch_button.grid(row=0, column=1, sticky="e")
        self._add_tooltip(
            self.image_fetch_button, "Fetch available models from the API provider."
        )
        self.image_profile_button = ctk.CTkButton(
            image_api_model_frame,
            text="⚙",
            width=34,
            command=lambda: self._open_profile_dialog("vision"),
        )
        self.image_profile_button.grid(row=0, column=2, padx=(6, 0), sticky="e")
        self._add_tooltip(
            self.image_profile_button,
            "Edit sampling settings for the selected model.",
        )

        ctk.CTkLabel(tab, text="Target model").grid(
            row=2, column=0, padx=12, pady=(4, 4), sticky="w"
        )
        self.image_target_model_menu = ctk.CTkOptionMenu(
            tab, values=[""]
        )
        self.image_target_model_menu.grid(
            row=3, column=0, padx=12, pady=(0, 12), sticky="ew"
        )
        self._add_tooltip(
            self.image_target_model_menu,
            "Select the image generator you are writing this prompt for.",
        )

        ctk.CTkLabel(tab, text="Character / LoRA").grid(
            row=2, column=1, padx=12, pady=(4, 4), sticky="w"
        )
        self.image_lora_menu = ctk.CTkOptionMenu(
            tab, values=["None"], variable=self.vision_lora_var
        )
        self.image_lora_menu.grid(
            row=3, column=1, padx=12, pady=(0, 12), sticky="ew"
        )
        self._add_tooltip(
            self.image_lora_menu,
            "Apply a character profile and its trigger words to the generation.",
        )

        image_hardware_frame = ctk.CTkFrame(tab, fg_color="transparent")
        image_hardware_frame.grid(
            row=4, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="ew"
        )
        image_hardware_frame.grid_columnconfigure(1, weight=1)
        self.image_hardware_frame = image_hardware_frame
        self.image_auto_unload_checkbox = ctk.CTkCheckBox(
            image_hardware_frame,
            text="Auto-Unload Model from VRAM",
            variable=self.auto_unload_var,
        )
        self.image_auto_unload_checkbox.grid(
            row=0, column=0, padx=(0, 8), sticky="w"
        )
        self.image_clear_vram_button = ctk.CTkButton(
            image_hardware_frame,
            text="Unload Model",
            width=120,
            command=self._clear_lm_studio_vram,
        )
        self.image_clear_vram_button.grid(row=0, column=1, sticky="w")
        self.image_lm_studio_status_label = ctk.CTkLabel(
            image_hardware_frame,
            text="LM Studio Status: [Checking...]",
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self.image_lm_studio_status_label.grid(
            row=1, column=0, columnspan=2, pady=(2, 0), sticky="ew"
        )
        image_hardware_frame.bind(
            "<Configure>", self._update_image_lm_status_wraplength
        )

        image_frame = ctk.CTkFrame(tab)
        image_frame.grid(row=5, column=0, padx=12, pady=4, sticky="nsew")
        image_frame.grid_rowconfigure(0, weight=1)
        image_frame.grid_columnconfigure(0, weight=1)
        self.image_preview_label = ctk.CTkLabel(
            image_frame, text="Select an image to preview", wraplength=360
        )
        self.image_preview_label.grid(row=0, column=0, sticky="nsew")
        self.image_preview_frame = image_frame
        for drop_target in (image_frame, self.image_preview_label):
            drop_target.drop_target_register(DND_FILES)
            drop_target.dnd_bind("<<Drop>>", self._handle_image_drop)
        image_frame.bind("<Configure>", self._update_image_preview)

        context_frame = ctk.CTkFrame(tab, fg_color="transparent")
        context_frame.grid(row=5, column=1, padx=12, pady=4, sticky="nsew")
        context_frame.grid_columnconfigure(0, weight=1)
        context_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            context_frame, text="Additional Context / Instructions"
        ).grid(row=0, column=0, pady=(0, 4), sticky="w")
        self.image_context_text = ctk.CTkTextbox(
            context_frame, height=96, wrap="word"
        )
        self.image_context_text.grid(row=1, column=0, sticky="nsew")
        self._add_tooltip(
            self.image_context_text,
            "Type your basic idea or scene description here.",
        )

        image_actions = ctk.CTkFrame(tab, fg_color="transparent")
        image_actions.grid(
            row=6, column=0, columnspan=2, padx=12, pady=4, sticky="ew"
        )
        image_actions.grid_columnconfigure(0, weight=1)
        image_actions.grid_columnconfigure(1, weight=1)
        image_actions.grid_columnconfigure(2, weight=1)
        self.select_image_button = ctk.CTkButton(
            image_actions, text="Select Image", command=self._select_image
        )
        self.select_image_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self._add_tooltip(
            self.select_image_button,
            "Load a reference image for the vision model to analyze.",
        )
        self.generate_image_prompt_button = ctk.CTkButton(
            image_actions,
            text="Generate Prompt from Image",
            command=self._generate_image_prompt,
        )
        self.generate_image_prompt_button.grid(
            row=0, column=1, padx=(6, 0), sticky="ew"
        )
        self._add_tooltip(
            self.generate_image_prompt_button,
            "Send the data to the LLM to create your prompt.",
        )
        self.vision_temp_label = ctk.CTkLabel(
            image_actions, text="Temp: 0.10"
        )
        self.vision_temp_label.grid(row=0, column=2, padx=(12, 4), sticky="w")
        self.vision_temp_slider = ctk.CTkSlider(
            image_actions,
            from_=0.0,
            to=1.0,
            number_of_steps=100,
            variable=self.vision_temp_var,
            command=self._update_vision_temp_label,
        )
        self.vision_temp_slider.grid(
            row=0, column=3, padx=(4, 0), sticky="ew"
        )
        self._add_tooltip(
            self.vision_temp_slider,
            "Adjust how varied or predictable image analysis responses are.",
        )
        image_actions.grid_columnconfigure(3, weight=2)
        self.vision_profile_label = ctk.CTkLabel(
            image_actions,
            text="Default profile",
            text_color="gray",
            anchor="w",
            height=18,
            font=ctk.CTkFont(size=11),
        )
        self.vision_profile_label.grid(
            row=1, column=0, columnspan=4, pady=(6, 0), sticky="ew"
        )
        self._add_tooltip(
            self.vision_profile_label,
            "Profile settings for the selected engine and model.",
        )
        image_status_frame = ctk.CTkFrame(tab, fg_color="transparent")
        image_status_frame.grid(
            row=7, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="ew"
        )
        image_status_frame.grid_columnconfigure(0, weight=1)
        self.image_status_label = ctk.CTkLabel(
            image_status_frame,
            text="Ready",
            text_color="gray",
            wraplength=700,
            justify="left",
        )
        self.image_status_label.grid(row=0, column=0, sticky="ew")
        self.image_status_label.bind(
            "<Configure>", self._update_image_status_wraplength
        )
        self.image_quota_label = ctk.CTkLabel(
            image_status_frame, text="Quota: N/A", text_color="gray"
        )
        self.image_quota_label.grid(row=0, column=2, padx=(8, 0), sticky="e")
        self.image_time_label = ctk.CTkLabel(
            image_status_frame, text="Time: --", text_color="gray"
        )
        self.image_time_label.grid(row=0, column=1, padx=(8, 0), sticky="e")

        output_header = ctk.CTkFrame(tab, fg_color="transparent")
        output_header.grid(
            row=8, column=0, columnspan=2, padx=12, pady=(0, 2), sticky="ew"
        )
        output_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(output_header, text="Output Prompt").grid(
            row=0, column=0, sticky="w"
        )
        self.image_single_line_checkbox = ctk.CTkCheckBox(
            output_header,
            text="Enforce Single-Line Prompts",
            variable=self.force_single_line_var,
        )
        self.image_single_line_checkbox.grid(row=0, column=1, sticky="e")
        self.image_output_text = ctk.CTkTextbox(tab, wrap="word")
        self.image_output_text.grid(
            row=9, column=0, columnspan=2, padx=12, pady=(0, 6), sticky="nsew"
        )
        self._add_tooltip(
            self.image_output_text, "The final generated prompt will appear here."
        )
        self.image_output_text.configure(state="disabled")
        self.copy_image_output_button = ctk.CTkButton(
            tab,
            text="Copy to Clipboard",
            command=self._copy_image_output,
        )
        self.copy_image_output_button.grid(
            row=10, column=0, columnspan=2, padx=12, pady=(0, 6)
        )
        self._add_tooltip(
            self.copy_image_output_button,
            "Copy the final generated prompt to your clipboard.",
        )
        self.image_output_text._textbox.bind(
            "<Button-3>", self._show_text_context_menu
        )
        self.image_output_text._textbox.bind(
            "<<SelectAll>>", self._select_all_text
        )
        self.image_context_text._textbox.bind(
            "<Button-3>", self._show_text_context_menu
        )
        self.image_context_text._textbox.bind(
            "<<SelectAll>>", self._select_all_text
        )
        self._selected_image_path = None
        self._selected_image = None
        self.current_preview_image = None

    def _update_vision_temp_label(self, value=None):
        temperature = self.vision_temp_var.get() if value is None else float(value)
        self.vision_temp_label.configure(text=f"Temp: {temperature:.2f}")
        self._update_profile_summary("vision")

    def _select_image(self):
        image_path = filedialog.askopenfilename(
            title="Select an image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not image_path:
            return
        self._load_image_path(image_path)

    def _handle_image_drop(self, event):
        try:
            try:
                dropped_paths = self.tk.splitlist(event.data)
            except tkinter.TclError as error:
                self.image_status_label.configure(
                    text=f"Could not read dropped file path: {error}",
                    text_color="red",
                )
                return "copy"

            if not dropped_paths:
                self.image_status_label.configure(
                    text="Drop an image file to load it.", text_color="red"
                )
                return "copy"

            image_path = dropped_paths[0].strip()
            if image_path.startswith("{") and image_path.endswith("}"):
                image_path = image_path[1:-1]
            if Path(image_path).suffix.lower() not in {
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
            }:
                self.image_status_label.configure(
                    text="Dropped file must be a JPG, JPEG, PNG, or WEBP image.",
                    text_color="red",
                )
                return "copy"

            self._load_image_path(image_path)
        except Exception as error:
            self.image_status_label.configure(
                text=f"Could not load dropped image: {error}", text_color="red"
            )
        return "copy"

    def _load_image_path(self, image_path):
        try:
            with Image.open(image_path) as image:
                self._selected_image = ImageOps.exif_transpose(image).convert("RGB")
        except (OSError, Image.UnidentifiedImageError) as error:
            self._selected_image_path = None
            self._selected_image = None
            self.current_preview_image = None
            self.image_preview_label.configure(
                image=None, text="Select an image to preview"
            )
            error_message = str(error).replace(
                image_path, truncate_filename(image_path)
            )
            self.image_status_label.configure(
                text=f"Could not open {truncate_filename(image_path)}: {error_message}",
                text_color="red",
            )
            return

        self._selected_image_path = image_path
        self.image_status_label.configure(
            text=truncate_filename(image_path), text_color="gray"
        )
        self._update_image_preview()

    def _update_image_preview(self, event=None):
        if self._selected_image is None:
            return
        width = self.image_preview_frame.winfo_width()
        height = self.image_preview_frame.winfo_height()
        if event is not None:
            width = min(width, event.width)
            height = min(height, event.height)
        if width <= 24 or height <= 24:
            return
        width = max(1, width - 24)
        height = max(1, height - 24)
        scale = min(
            width / self._selected_image.width,
            height / self._selected_image.height,
        )
        preview_size = (
            max(1, round(self._selected_image.width * scale)),
            max(1, round(self._selected_image.height * scale)),
        )
        preview = self._selected_image.resize(preview_size, Image.Resampling.LANCZOS)
        self.current_preview_image = ctk.CTkImage(
            light_image=preview,
            dark_image=preview,
            size=preview_size,
        )
        self.image_preview_label.configure(image=self.current_preview_image, text="")

    def _update_image_status_wraplength(self, event):
        wraplength = max(200, event.width - 24)
        if self.image_status_label.cget("wraplength") != wraplength:
            self.image_status_label.configure(wraplength=wraplength)

    def _update_image_lm_status_wraplength(self, event):
        wraplength = max(300, event.width - 24)
        if self.image_lm_studio_status_label.cget("wraplength") != wraplength:
            self.image_lm_studio_status_label.configure(wraplength=wraplength)

    def _generate_image_prompt(self):
        if self.generate_image_prompt_button.cget("state") == "disabled":
            return
        if not self._selected_image_path:
            self.image_status_label.configure(
                text="Select an image before generating.", text_color="red"
            )
            return

        engine = self.image_engine_menu.get()
        api_model = self.image_api_model_menu.get().strip()
        try:
            config_data = load_config()
            if engine not in LLM_ENGINES:
                raise ValueError("Choose a valid LLM engine.")
            if engine == LOCAL_ENGINE:
                api_key = "local-key"
            else:
                api_key = config_data.get(
                    "gemini_api_key" if engine == "Gemini" else "groq_api_key", ""
                )
                if not isinstance(api_key, str) or not api_key.strip():
                    raise ValueError(
                        f"API Key missing: add and save your {engine} API key in Settings."
                    )
            if not api_model or api_model == "Fetch models first":
                raise ValueError(f"Select an available {engine} API model.")
            rough_idea = self.image_context_text.get("1.0", "end").strip()
            request_parts = assemble_image_request(
                VISION_SYSTEM_PROMPTS_DIR
                / f"{self.image_target_model_menu.get()}.txt",
                self.image_lora_menu.get(),
                self.lora_profiles,
                rough_idea,
            )
            selected_lora = self.image_lora_menu.get()
            selected_profile = find_lora_profile(selected_lora, self.lora_profiles)
            trigger_words = (
                lora_profile_value(selected_profile, "trigger_word")
                if selected_profile
                else ""
            )
            image_path = self._selected_image_path
            auto_unload = self.auto_unload_var.get()
            force_single_line = self.force_single_line_var.get()
            generation_settings = {
                "target_model": self.image_target_model_menu.get(),
                "character_lora": selected_lora,
                "auto_unload": auto_unload,
                "force_single_line": force_single_line,
            }
            generation_settings.update(
                profile_request_kwargs(engine, self.vision_profile)
            )
            temperature = self.vision_temp_var.get()
            generation_settings["temperature"] = temperature
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.image_status_label.configure(
                text=f"Error: {error}", text_color="red"
            )
            return

        self.image_output_text.configure(state="normal")
        self.image_output_text.delete("1.0", "end")
        self.image_output_text.configure(state="disabled")
        self.generate_image_prompt_button.configure(state="disabled")
        self.image_status_label.configure(text="Generating...", text_color="gray")
        self.image_time_label.configure(text="Generating...", text_color="gray")
        self._update_quota_label(self.image_quota_label, engine, None)
        threading.Thread(
            target=self._image_generation_worker,
            args=(
                engine,
                api_key.strip(),
                api_model,
                request_parts,
                image_path,
                trigger_words,
                temperature,
                auto_unload,
                rough_idea,
                generation_settings,
                force_single_line,
            ),
            daemon=True,
        ).start()

    def _image_generation_worker(
        self,
        engine,
        api_key,
        api_model,
        request_parts,
        image_path,
        trigger_words,
        temperature,
        auto_unload,
        rough_idea,
        generation_settings,
        force_single_line,
    ):
        start_time = None
        elapsed = None
        try:
            if (
                engine == LOCAL_ENGINE
                and generation_settings.get("context_length") is not None
            ):
                ensure_model_loaded(
                    api_model,
                    context_length=generation_settings["context_length"],
                )
            image_base64 = optimize_image_for_api(image_path)
            start_time = time.time()
            generated_prompt, quota, total_used = request_generated_prompt(
                engine,
                api_key,
                api_model,
                request_parts,
                image_base64=image_base64,
                include_quota=True,
                temperature=temperature,
                top_p=generation_settings.get("top_p"),
                min_p=generation_settings.get("min_p"),
                repeat_penalty=generation_settings.get("repeat_penalty"),
                max_tokens=generation_settings.get("max_tokens"),
                disable_thinking=generation_settings.get(
                    "disable_thinking", False
                ),
            )
            elapsed = time.time() - start_time
            if engine == LOCAL_ENGINE and auto_unload:
                self._auto_unload_lm_studio_model()
            generated_prompt = enforce_lora_trigger_prefix(
                generated_prompt, trigger_words
            )
            if not generated_prompt or is_numeric_result(generated_prompt):
                raise ValueError("The generation result was not prompt text.")
        except requests.exceptions.RequestException as error:
            if start_time is not None:
                elapsed = time.time() - start_time
            self.after(
                0,
                self.handle_generation_error,
                f"{engine} image prompt generation failed: {error}",
                "image",
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
                f"{engine} image prompt generation failed: {error}",
                "image",
                elapsed,
                engine,
            )
            return
        self.after(
            0,
            self._on_image_generation_success,
            generated_prompt,
            engine,
            quota,
            total_used,
            elapsed,
            rough_idea,
            generation_settings,
            api_model,
            image_path,
            force_single_line,
        )

    def _on_image_generation_success(
        self,
        generated_prompt,
        engine,
        quota,
        total_used,
        elapsed,
        rough_idea,
        generation_settings,
        api_model,
        image_path,
        force_single_line,
    ):
        if not isinstance(generated_prompt, str):
            self._on_image_generation_error(
                "LLM", "The generation result was not prompt text.", elapsed
            )
            return
        if force_single_line:
            generated_prompt = format_as_single_line_prompts(generated_prompt)
        if is_numeric_result(generated_prompt):
            self._on_image_generation_error(
                "LLM", "The generation result was not prompt text.", elapsed
            )
            return
        if not generated_prompt:
            self._on_image_generation_error(
                "LLM", "The generation result was empty.", elapsed
            )
            return
        history_error = None
        try:
            insert_generation(
                rough_idea,
                generated_prompt,
                generation_settings,
                source_tab="image_to_prompt",
                engine=engine,
                model=api_model,
                image_path=image_path,
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            history_error = f"Generated, but could not save history: {error}"
        self.image_output_text.configure(state="normal")
        self.image_output_text.delete("1.0", "end")
        self.image_output_text.insert("1.0", generated_prompt)
        self.image_time_label.configure(text=f"Time: {elapsed:.1f}s")
        self.image_output_text.configure(state="disabled")
        self.generate_image_prompt_button.configure(state="normal")
        self._update_quota_label(
            self.image_quota_label, engine, quota, total_used
        )
        self.image_status_label.configure(
            text=history_error or "Ready",
            text_color="red" if history_error else "gray",
        )
        self._refresh_history()

    def _on_image_generation_error(self, engine, error_message, elapsed=None):
        self.handle_generation_error(
            f"{engine} image prompt generation failed: {error_message}",
            "image",
            elapsed,
            engine,
        )

    def _copy_image_output(self):
        self._copy_text(
            self.image_output_text.get("1.0", "end").strip(),
            button=self.copy_image_output_button,
            status_label=self.image_status_label,
        )
