import json
import re
import tkinter
from tkinter import messagebox

import customtkinter as ctk

from promptwriter.config import (
    CAMERAS_PATH,
    DEFAULT_COMFYUI_BASE_URL,
    DEFAULT_FORGE_BASE_URL,
    DEFAULT_LM_STUDIO_BASE_URL,
    LLM_ENGINES,
    LORA_PROFILES_PATH,
    MODEL_PLACEHOLDER,
    SYSTEM_PROMPTS_DIR,
    VISION_SYSTEM_PROMPTS_DIR,
    model_cache_key,
)
from promptwriter.services.lora import lora_profile_value
from promptwriter.storage.app_files import read_json
from promptwriter.storage.config_store import load_config, save_config
from promptwriter.storage.personal_data_reset import reset_personal_data
from promptwriter.storage.profile_store import delete_profile, list_profiles


class SettingsTabMixin:
    def _build_settings_tab(self):
        tab = ctk.CTkScrollableFrame(self.settings_tab)
        tab.grid(row=0, column=0, sticky="nsew")
        self.settings_tab.grid_columnconfigure(0, weight=1)
        self.settings_tab.grid_rowconfigure(0, weight=1)
        self.settings_content = tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(tab, text="Gemini API key").grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w"
        )
        self.gemini_key_entry = ctk.CTkEntry(tab, show="*")
        self.gemini_key_entry.grid(
            row=1, column=0, padx=12, pady=(0, 12), sticky="ew"
        )
        self._add_tooltip(
            self.gemini_key_entry,
            "Enter your API key. This is saved locally in your config file.",
        )

        ctk.CTkLabel(tab, text="Groq API key").grid(
            row=0, column=1, padx=12, pady=(12, 4), sticky="w"
        )
        self.groq_key_entry = ctk.CTkEntry(tab, show="*")
        self.groq_key_entry.grid(
            row=1, column=1, padx=12, pady=(0, 12), sticky="ew"
        )
        self._add_tooltip(
            self.groq_key_entry,
            "Enter your API key. This is saved locally in your config file.",
        )

        ctk.CTkLabel(tab, text="LM Studio base URL (Local)").grid(
            row=2, column=0, columnspan=2, padx=12, pady=(4, 4), sticky="w"
        )
        self.lm_studio_url_entry = ctk.CTkEntry(tab)
        self.lm_studio_url_entry.grid(
            row=3, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.lm_studio_url_entry,
            "Address of the LM Studio server, for example http://127.0.0.1:1234.",
        )

        ctk.CTkLabel(tab, text="ComfyUI base URL (VRAM unload)").grid(
            row=4, column=0, padx=12, pady=(0, 4), sticky="w"
        )
        self.comfyui_url_entry = ctk.CTkEntry(tab)
        self.comfyui_url_entry.grid(
            row=5, column=0, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.comfyui_url_entry,
            "Address of the ComfyUI server, for example http://127.0.0.1:8188.",
        )
        ctk.CTkLabel(tab, text="Forge Neo base URL (VRAM unload)").grid(
            row=4, column=1, padx=12, pady=(0, 4), sticky="w"
        )
        self.forge_url_entry = ctk.CTkEntry(tab)
        self.forge_url_entry.grid(
            row=5, column=1, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.forge_url_entry,
            "Address of the Forge Neo server, for example http://127.0.0.1:7860.",
        )

        self.save_settings_button = ctk.CTkButton(
            tab, text="Save Settings", command=self._save_settings
        )
        self.save_settings_button.grid(
            row=6, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew"
        )
        self._add_tooltip(
            self.save_settings_button, "Save your API keys and configuration."
        )
        ctk.CTkLabel(tab, text="Saved model profiles").grid(
            row=7, column=0, columnspan=2, padx=12, pady=(0, 4), sticky="w"
        )
        profiles_frame = ctk.CTkFrame(tab, fg_color="transparent")
        profiles_frame.grid(
            row=8, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew"
        )
        profiles_frame.grid_columnconfigure(0, weight=1)
        self.saved_profiles_count = ctk.CTkLabel(
            profiles_frame, text="Saved profiles: 0", anchor="w"
        )
        self.saved_profiles_count.grid(
            row=0, column=0, columnspan=2, pady=(0, 4), sticky="w"
        )
        self.saved_profile_menu = ctk.CTkComboBox(
            profiles_frame, values=["No saved profiles"], state="readonly"
        )
        self.saved_profile_menu.grid(row=1, column=0, padx=(0, 6), sticky="ew")
        self._add_tooltip(
            self.saved_profile_menu,
            "Profiles saved per engine, model, and tab.",
        )
        self.delete_saved_profile_button = ctk.CTkButton(
            profiles_frame,
            text="Delete",
            width=80,
            command=self._delete_saved_profile,
        )
        self.delete_saved_profile_button.grid(row=1, column=1, sticky="e")
        self._add_tooltip(
            self.delete_saved_profile_button,
            "Delete the selected saved model profile.",
        )
        self.saved_profiles_status = ctk.CTkLabel(
            profiles_frame, text="", anchor="w"
        )
        self.saved_profiles_status.grid(
            row=2, column=0, columnspan=2, pady=(4, 0), sticky="w"
        )
        self.settings_status = ctk.CTkLabel(tab, text="")
        self.settings_status.grid(
            row=15, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="e"
        )
        self._refresh_saved_profiles()

        ctk.CTkLabel(tab, text="Add a camera / lens").grid(
            row=9, column=0, padx=12, pady=(12, 4), sticky="w"
        )
        self.camera_entry = ctk.CTkEntry(tab, placeholder_text="Camera and lens")
        self.camera_entry.grid(
            row=10, column=0, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.camera_entry,
            "Add a new camera and lens combination to your local database.",
        )
        self.add_camera_button = ctk.CTkButton(
            tab, text="Add Camera", command=self._add_camera
        )
        self.add_camera_button.grid(
            row=10, column=1, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.add_camera_button,
            "Add a new camera and lens combination to your local database.",
        )

        ctk.CTkLabel(tab, text="Text System Prompts").grid(
            row=11, column=0, padx=12, pady=(12, 4), sticky="w"
        )
        self.prompt_name_menu = ctk.CTkComboBox(
            tab,
            values=self._get_model_names(),
            command=self.load_selected_text_prompt,
        )
        self.prompt_name_menu.grid(
            row=12, column=0, padx=12, pady=(0, 8), sticky="new"
        )
        self._add_tooltip(
            self.prompt_name_menu,
            "Select, edit, or save your system prompt templates.",
        )
        self.prompt_editor = ctk.CTkTextbox(tab, wrap="word")
        self.prompt_editor.grid(
            row=13, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="nsew"
        )
        self._add_tooltip(
            self.prompt_editor,
            "Select, edit, or save your system prompt templates.",
        )
        self.prompt_editor._textbox.bind(
            "<Button-3>", self._show_text_context_menu
        )
        self.prompt_editor._textbox.bind(
            "<<SelectAll>>", self._select_all_text
        )
        tab.grid_rowconfigure(13, weight=1)

        prompt_actions = ctk.CTkFrame(tab, fg_color="transparent")
        prompt_actions.grid(
            row=14, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew"
        )
        prompt_actions.grid_columnconfigure((0, 1, 2), weight=1)
        self.delete_prompt_button = ctk.CTkButton(
            prompt_actions,
            text="Delete Prompt",
            command=self.delete_text_prompt,
        )
        self.delete_prompt_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self._add_tooltip(
            self.delete_prompt_button,
            "Delete the selected system prompt template.",
        )
        self.save_prompt_button = ctk.CTkButton(
            prompt_actions,
            text="Save / Create Prompt",
            command=lambda: self._save_prompt("text"),
        )
        self.save_prompt_button.grid(row=0, column=1, padx=6, sticky="ew")
        self._add_tooltip(
            self.save_prompt_button,
            "Select, edit, or save your system prompt templates.",
        )

        ctk.CTkLabel(tab, text="Vision System Prompts").grid(
            row=16, column=0, padx=12, pady=(12, 4), sticky="w"
        )
        self.vision_prompt_name_menu = ctk.CTkComboBox(
            tab,
            values=self._get_model_names(VISION_SYSTEM_PROMPTS_DIR),
            command=self.load_selected_vision_prompt,
        )
        self.vision_prompt_name_menu.grid(
            row=17, column=0, padx=12, pady=(0, 8), sticky="new"
        )
        self._add_tooltip(
            self.vision_prompt_name_menu,
            "Select, edit, or save your vision system prompt templates.",
        )
        self.vision_prompt_editor = ctk.CTkTextbox(tab, wrap="word")
        self.vision_prompt_editor.grid(
            row=18, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="nsew"
        )
        self._add_tooltip(
            self.vision_prompt_editor,
            "Edit the instructions used to analyze images.",
        )
        self.vision_prompt_editor._textbox.bind(
            "<Button-3>", self._show_text_context_menu
        )
        self.vision_prompt_editor._textbox.bind(
            "<<SelectAll>>", self._select_all_text
        )
        tab.grid_rowconfigure(18, weight=1)

        vision_prompt_actions = ctk.CTkFrame(tab, fg_color="transparent")
        vision_prompt_actions.grid(
            row=19, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew"
        )
        vision_prompt_actions.grid_columnconfigure((0, 1, 2), weight=1)
        self.delete_vision_prompt_button = ctk.CTkButton(
            vision_prompt_actions,
            text="Delete Prompt",
            command=self.delete_vision_prompt,
        )
        self.delete_vision_prompt_button.grid(
            row=0, column=0, padx=(0, 6), sticky="ew"
        )
        self._add_tooltip(
            self.delete_vision_prompt_button,
            "Delete the selected vision system prompt template.",
        )
        self.save_vision_prompt_button = ctk.CTkButton(
            vision_prompt_actions,
            text="Save / Create Prompt",
            command=lambda: self._save_prompt("vision"),
        )
        self.save_vision_prompt_button.grid(
            row=0, column=1, padx=6, sticky="ew"
        )
        self._add_tooltip(
            self.save_vision_prompt_button,
            "Select, edit, or save your vision system prompt templates.",
        )

        ctk.CTkLabel(tab, text="Character / LoRA Management").grid(
            row=21, column=0, columnspan=2, padx=12, pady=(16, 4), sticky="w"
        )
        self.lora_name_menu = ctk.CTkComboBox(
            tab,
            values=[
                profile.get("name", profile.get("Name", ""))
                for profile in self.lora_profiles
                if profile.get("name", profile.get("Name", ""))
            ],
            command=self._load_lora_profile,
        )
        self.lora_name_menu.set("")
        self.lora_name_menu.grid(
            row=22, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.lora_name_menu,
            "Manage your character profiles to override default AI generation styles.",
        )
        self.lora_name_menu.bind(
            "<<ComboboxSelected>>",
            lambda event: self._load_lora_profile(self.lora_name_menu.get()),
        )
        ctk.CTkLabel(tab, text="Trigger Words").grid(
            row=23, column=0, padx=12, pady=(4, 4), sticky="w"
        )
        self.lora_trigger_entry = ctk.CTkEntry(
            tab, placeholder_text="Exact trigger words"
        )
        self.lora_trigger_entry.grid(
            row=24, column=0, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.lora_trigger_entry,
            "Manage your character profiles to override default AI generation styles.",
        )
        ctk.CTkLabel(tab, text="Character Profile / Description").grid(
            row=23, column=1, padx=12, pady=(4, 4), sticky="w"
        )
        self.lora_description_text = ctk.CTkTextbox(tab, wrap="word", height=110)
        self.lora_description_text.grid(
            row=24, column=1, rowspan=2, padx=12, pady=(0, 8), sticky="nsew"
        )
        self._add_tooltip(
            self.lora_description_text,
            "Manage your character profiles to override default AI generation styles.",
        )
        self.lora_description_text._textbox.bind(
            "<Button-3>", self._show_text_context_menu
        )
        self.lora_description_text._textbox.bind(
            "<<SelectAll>>", self._select_all_text
        )
        lora_actions = ctk.CTkFrame(tab, fg_color="transparent")
        lora_actions.grid(
            row=25, column=0, padx=12, pady=(0, 8), sticky="ew"
        )
        lora_actions.grid_columnconfigure((0, 1), weight=1)
        self.save_lora_button = ctk.CTkButton(
            lora_actions, text="Save LoRA", command=self._save_lora_profile
        )
        self.save_lora_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self._add_tooltip(
            self.save_lora_button,
            "Manage your character profiles to override default AI generation styles.",
        )
        self.delete_lora_button = ctk.CTkButton(
            lora_actions, text="Delete LoRA", command=self._delete_lora_profile
        )
        self.delete_lora_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")
        self._add_tooltip(
            self.delete_lora_button,
            "Manage your character profiles to override default AI generation styles.",
        )
        self.lora_status = ctk.CTkLabel(tab, text="")
        self.lora_status.grid(
            row=26, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="e"
        )

        ctk.CTkLabel(tab, text="Reset / Delete All Personal Data").grid(
            row=27, column=0, columnspan=2, padx=12, pady=(16, 4), sticky="w"
        )
        self.reset_delete_keys_var = tkinter.BooleanVar(master=self, value=False)
        self.reset_delete_keys_checkbox = ctk.CTkCheckBox(
            tab,
            text="Also delete saved API keys",
            variable=self.reset_delete_keys_var,
        )
        self.reset_delete_keys_checkbox.grid(
            row=28, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w"
        )
        self._add_tooltip(
            self.reset_delete_keys_checkbox,
            "When checked, the reset also removes the saved Gemini and Groq API keys.",
        )
        self.reset_personal_data_button = ctk.CTkButton(
            tab,
            text="Reset / Delete All Personal Data",
            fg_color="#7a2d2d",
            hover_color="#5e2222",
            command=self._confirm_reset_personal_data,
        )
        self.reset_personal_data_button.grid(
            row=29, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew"
        )
        self._add_tooltip(
            self.reset_personal_data_button,
            "Delete local settings, profiles, custom prompts, history, and caches. "
            "The 3 baseline system prompts are kept.",
        )

    def _load_lora_profile(self, profile_name):
        profile = next(
            (
                item
                for item in self.lora_profiles
                if isinstance(item, dict)
                and lora_profile_value(item, "name") == profile_name
            ),
            None,
        )
        self.lora_trigger_entry.delete(0, "end")
        self.lora_description_text.delete("1.0", "end")
        if profile is None:
            return
        self.lora_trigger_entry.insert(
            0, lora_profile_value(profile, "trigger_word")
        )
        self.lora_description_text.insert(
            "1.0", lora_profile_value(profile, "description")
        )

    def _save_lora_profile(self):
        profile = {
            "name": self.lora_name_menu.get().strip(),
            "trigger_word": self.lora_trigger_entry.get().strip(),
            "description": self.lora_description_text.get("1.0", "end").strip(),
        }
        if not all(profile.values()):
            self.lora_status.configure(
                text="Enter a name, trigger words, and profile description.",
                text_color="red",
            )
            return
        if not messagebox.askyesno(
            "Confirm Save", "Are you sure you want to save this LoRA profile?"
        ):
            return

        existing_index = next(
            (
                index
                for index, existing in enumerate(self.lora_profiles)
                if isinstance(existing, dict)
                and lora_profile_value(existing, "name") == profile["name"]
            ),
            None,
        )
        updated_profiles = list(self.lora_profiles)
        if existing_index is None:
            updated_profiles.append(profile)
        else:
            updated_profiles[existing_index] = profile
        try:
            LORA_PROFILES_PATH.write_text(
                json.dumps(updated_profiles, indent=2), encoding="utf-8"
            )
        except OSError as error:
            self.lora_status.configure(
                text=f"Could not save LoRA profile: {error}", text_color="red"
            )
            return

        self.lora_profiles = updated_profiles
        self._refresh_lora_options(profile["name"])
        self.lora_status.configure(
            text=f"Saved LoRA profile '{profile['name']}'.", text_color="green"
        )

    def _delete_lora_profile(self):
        profile_name = self.lora_name_menu.get().strip()
        if not profile_name:
            self.lora_status.configure(
                text="Select a LoRA profile to delete.", text_color="red"
            )
            return
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete the LoRA profile '{profile_name}'?",
        ):
            return
        updated_profiles = [
            profile
            for profile in self.lora_profiles
            if not (
                isinstance(profile, dict)
                and lora_profile_value(profile, "name") == profile_name
            )
        ]
        if len(updated_profiles) == len(self.lora_profiles):
            self.lora_status.configure(
                text=f"LoRA profile not found: {profile_name}", text_color="red"
            )
            return
        try:
            LORA_PROFILES_PATH.write_text(
                json.dumps(updated_profiles, indent=2), encoding="utf-8"
            )
        except OSError as error:
            self.lora_status.configure(
                text=f"Could not delete LoRA profile: {error}", text_color="red"
            )
            return

        self.lora_profiles = updated_profiles
        self.lora_name_menu.set("")
        self.lora_trigger_entry.delete(0, "end")
        self.lora_description_text.delete("1.0", "end")
        self._refresh_lora_options()
        self.lora_status.configure(
            text=f"Deleted LoRA profile '{profile_name}'.", text_color="green"
        )

    def _load_settings(self):
        self.gemini_key_entry.insert(0, self.config_data.get("gemini_api_key", ""))
        self.groq_key_entry.insert(0, self.config_data.get("groq_api_key", ""))
        base_url = self.config_data.get(
            "lm_studio_base_url", DEFAULT_LM_STUDIO_BASE_URL
        )
        if not isinstance(base_url, str) or not base_url.strip():
            base_url = DEFAULT_LM_STUDIO_BASE_URL
        self.lm_studio_url_entry.insert(0, base_url.strip())
        comfyui_url = self.config_data.get(
            "comfyui_base_url", DEFAULT_COMFYUI_BASE_URL
        )
        if not isinstance(comfyui_url, str) or not comfyui_url.strip():
            comfyui_url = DEFAULT_COMFYUI_BASE_URL
        self.comfyui_url_entry.insert(0, comfyui_url.strip())
        forge_url = self.config_data.get("forge_base_url", DEFAULT_FORGE_BASE_URL)
        if not isinstance(forge_url, str) or not forge_url.strip():
            forge_url = DEFAULT_FORGE_BASE_URL
        self.forge_url_entry.insert(0, forge_url.strip())
        self._refresh_saved_profiles()
        legacy_engine = self.config_data.get("engine", "Gemini")
        if legacy_engine not in LLM_ENGINES:
            legacy_engine = "Gemini"
        saved_available_models = self.config_data.get("available_models", {})
        if not isinstance(saved_available_models, dict):
            saved_available_models = {}
        self.available_models = {}
        for provider in LLM_ENGINES:
            models = self.config_data.get(model_cache_key(provider))
            if not isinstance(models, list):
                models = saved_available_models.get(provider, [])
            self.available_models[provider] = (
                [model for model in models if isinstance(model, str)]
                if isinstance(models, list)
                else []
            )
        selected_models = self.config_data.get("selected_api_models", {})
        if not isinstance(selected_models, dict):
            selected_models = {}
        legacy_selected_model = self.config_data.get("selected_api_model", "")

        generator_engine = self.config_data.get("generator_engine", legacy_engine)
        if generator_engine not in LLM_ENGINES:
            generator_engine = legacy_engine
        vision_engine = self.config_data.get("vision_engine", legacy_engine)
        if vision_engine not in LLM_ENGINES:
            vision_engine = legacy_engine

        self.generator_selected_models = {
            provider: (
                selected_models.get(provider, "")
                if isinstance(selected_models.get(provider, ""), str)
                else ""
            )
            for provider in LLM_ENGINES
        }
        self.vision_selected_models = self.generator_selected_models.copy()
        generator_model = self.config_data.get(
            "generator_model",
            self.generator_selected_models.get(generator_engine)
            or (legacy_selected_model if generator_engine == legacy_engine else ""),
        )
        vision_model = self.config_data.get(
            "vision_model",
            self.vision_selected_models.get(vision_engine)
            or (legacy_selected_model if vision_engine == legacy_engine else ""),
        )
        self.generator_selected_models[generator_engine] = (
            generator_model if isinstance(generator_model, str) else ""
        )
        self.vision_selected_models[vision_engine] = (
            vision_model if isinstance(vision_model, str) else ""
        )

        self.engine_menu.set(generator_engine)
        self.image_engine_menu.set(vision_engine)
        self._set_api_model_options("generator", generator_engine)
        self._set_api_model_options("vision", vision_engine)

    def _save_settings(self):
        generator_engine = self.engine_menu.get()
        generator_model = self.api_model_menu.get()
        if generator_model == MODEL_PLACEHOLDER:
            generator_model = ""
        vision_engine = self.image_engine_menu.get()
        vision_model = self.image_api_model_menu.get()
        if vision_model == MODEL_PLACEHOLDER:
            vision_model = ""
        self.generator_selected_models[generator_engine] = generator_model
        self.vision_selected_models[vision_engine] = vision_model

        legacy_selected_models = {
            provider: self.generator_selected_models.get(provider, "")
            for provider in LLM_ENGINES
        }
        base_url = self.lm_studio_url_entry.get().strip()
        if not base_url:
            base_url = DEFAULT_LM_STUDIO_BASE_URL
        comfyui_url = (
            self.comfyui_url_entry.get().strip() or DEFAULT_COMFYUI_BASE_URL
        )
        forge_url = self.forge_url_entry.get().strip() or DEFAULT_FORGE_BASE_URL
        self.config_data = {
            "gemini_api_key": self.gemini_key_entry.get().strip(),
            "groq_api_key": self.groq_key_entry.get().strip(),
            "lm_studio_base_url": base_url,
            "comfyui_base_url": comfyui_url,
            "forge_base_url": forge_url,
            "engine": generator_engine,
            "selected_api_model": generator_model,
            "selected_api_models": legacy_selected_models,
            "generator_engine": generator_engine,
            "generator_model": generator_model,
            "vision_engine": vision_engine,
            "vision_model": vision_model,
            "ui_state": self._collect_ui_state(),
            "available_models": {
                provider: models
                for provider, models in self.available_models.items()
            },
            **{
                model_cache_key(engine): models
                for engine, models in self.available_models.items()
            },
        }
        try:
            save_config(self.config_data)
        except OSError as error:
            self.settings_status.configure(
                text=f"Could not save settings: {error}", text_color="red"
            )
            return
        self.settings_status.configure(text="Settings saved", text_color="green")
        self.after(200, self._refresh_lm_studio_status)

    def _refresh_saved_profiles(self):
        entries = list_profiles()
        self._saved_profile_entries = entries
        self.saved_profiles_count.configure(
            text=f"Saved profiles: {len(entries)}"
        )
        labels = [
            (
                f"{entry['engine']} · {entry['model_id']} · "
                f"{'Image' if entry['mode'] == 'vision' else 'Text'}"
            )
            for entry in entries
        ]
        self.saved_profile_menu.configure(
            values=labels or ["No saved profiles"]
        )
        current = self.saved_profile_menu.get()
        fallback = labels[0] if labels else "No saved profiles"
        self.saved_profile_menu.set(current if current in labels else fallback)
        self.delete_saved_profile_button.configure(
            state="normal" if entries else "disabled"
        )

    def _delete_saved_profile(self):
        labels = list(self.saved_profile_menu.cget("values"))
        selection = self.saved_profile_menu.get()
        if selection not in labels or not self._saved_profile_entries:
            self.saved_profiles_status.configure(
                text="Select a saved profile to delete.", text_color="red"
            )
            return
        entry = self._saved_profile_entries[labels.index(selection)]
        mode_label = "Image to Prompt" if entry["mode"] == "vision" else "Generator"
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete the {mode_label} profile for '{entry['model_id']}'?",
            parent=self,
        ):
            return
        try:
            delete_profile(entry["engine"], entry["model_id"], entry["mode"])
        except (OSError, ValueError) as error:
            self.saved_profiles_status.configure(
                text=f"Could not delete profile: {error}", text_color="red"
            )
            return
        self._refresh_saved_profiles()
        self._refresh_profile(entry["mode"], sync_temperature=True)
        self.saved_profiles_status.configure(
            text="Profile deleted.", text_color="green"
        )

    def _confirm_reset_personal_data(self):
        delete_keys = bool(self.reset_delete_keys_var.get())
        lines = [
            "This permanently deletes:",
            "- Saved settings, model profiles, and last-used model selections",
            "- LoRA profiles and camera / lens entries",
            "- Custom system prompt .txt files (the 3 baseline prompts are kept)",
            "- All history entries",
            "- The saved rough idea and other session state",
            "- Cached / fetched model lists",
            (
                "- Saved Gemini and Groq API keys"
                if delete_keys
                else "- Saved API keys will be KEPT because the checkbox is off"
            ),
            "",
            "This cannot be undone. Continue?",
        ]
        if not messagebox.askyesno(
            "Delete All Personal Data",
            "\n".join(lines),
            icon="warning",
            parent=self,
        ):
            return
        try:
            summary = reset_personal_data(delete_api_keys=delete_keys)
        except OSError as error:
            self.settings_status.configure(
                text=f"Could not reset personal data: {error}", text_color="red"
            )
            return
        self._apply_personal_data_reset()
        if summary["errors"]:
            self.settings_status.configure(
                text=f"Reset finished with errors: {summary['errors'][0]}",
                text_color="red",
            )
            return
        self.settings_status.configure(
            text="All personal data deleted.", text_color="green"
        )

    def _apply_personal_data_reset(self):
        self.config_data = load_config()
        self.cameras = read_json(CAMERAS_PATH, [])
        self.lora_profiles = read_json(LORA_PROFILES_PATH, [])
        for entry in (
            self.gemini_key_entry,
            self.groq_key_entry,
            self.lm_studio_url_entry,
            self.comfyui_url_entry,
            self.forge_url_entry,
        ):
            entry.delete(0, "end")
        self._load_settings()

        self.prompt_name_menu.set("")
        self.vision_prompt_name_menu.set("")
        self.prompt_editor.delete("1.0", "end")
        self.vision_prompt_editor.delete("1.0", "end")
        self.lora_name_menu.set("")
        self.lora_trigger_entry.delete(0, "end")
        self.lora_description_text.delete("1.0", "end")
        self.lora_status.configure(text="")
        self.saved_profiles_status.configure(text="")
        self.rough_idea_text.delete("1.0", "end")
        self.auto_unload_var.set(False)
        self.force_single_line_var.set(True)

        self._refresh_prompt_name_options()
        self._refresh_generator_options()
        self._on_engine_changed(self.engine_menu.get(), sync_profile=True)
        self._on_image_engine_changed(
            self.image_engine_menu.get(), sync_profile=True
        )

        self.history_search_entry.delete(0, "end")
        self.favorites_only_switch.deselect()
        self._refresh_history()
        self._clear_history_selection()
        self.history_status_label.configure(text="")

        self.reset_delete_keys_var.set(False)

    def _add_camera(self):
        camera = self.camera_entry.get().strip()
        if not camera:
            self.settings_status.configure(
                text="Enter a camera / lens first", text_color="red"
            )
            return
        if camera not in self.cameras:
            self.cameras.append(camera)
            CAMERAS_PATH.write_text(json.dumps(self.cameras, indent=2), encoding="utf-8")
        self.camera_entry.delete(0, "end")
        self._refresh_generator_options()
        self.settings_status.configure(text="Camera added", text_color="green")

    def _load_prompt(self, prompt_type):
        if prompt_type == "vision":
            prompt_directory = VISION_SYSTEM_PROMPTS_DIR
            prompt_name_menu = self.vision_prompt_name_menu
            prompt_editor = self.vision_prompt_editor
        else:
            prompt_directory = SYSTEM_PROMPTS_DIR
            prompt_name_menu = self.prompt_name_menu
            prompt_editor = self.prompt_editor

        model_name = prompt_name_menu.get().strip()
        if not model_name:
            self.settings_status.configure(
                text="Select a system prompt to load", text_color="red"
            )
            return
        prompt_path = prompt_directory / f"{model_name}.txt"
        if not prompt_path.is_file():
            self.settings_status.configure(
                text=f"System prompt not found: {model_name}.txt", text_color="red"
            )
            return
        try:
            instructions = prompt_path.read_text(encoding="utf-8")
        except OSError as error:
            self.settings_status.configure(
                text=f"Could not load system prompt: {error}", text_color="red"
            )
            return
        prompt_editor.delete("1.0", "end")
        prompt_editor.insert("1.0", instructions)
        self.settings_status.configure(
            text=f"Loaded {model_name}.txt", text_color="green"
        )

    def load_selected_text_prompt(self, _prompt_name=None):
        self._load_prompt("text")

    def load_selected_vision_prompt(self, _prompt_name=None):
        self._load_prompt("vision")

    def delete_text_prompt(self):
        self._delete_prompt("text")

    def delete_vision_prompt(self):
        self._delete_prompt("vision")

    def _delete_prompt(self, prompt_type):
        if prompt_type == "vision":
            prompt_directory = VISION_SYSTEM_PROMPTS_DIR
            prompt_name_menu = self.vision_prompt_name_menu
            prompt_editor = self.vision_prompt_editor
        else:
            prompt_directory = SYSTEM_PROMPTS_DIR
            prompt_name_menu = self.prompt_name_menu
            prompt_editor = self.prompt_editor

        model_name = prompt_name_menu.get().strip()
        if not model_name:
            self.settings_status.configure(
                text="Select a system prompt to delete", text_color="red"
            )
            return
        prompt_path = prompt_directory / f"{model_name}.txt"
        if not prompt_path.is_file():
            self.settings_status.configure(
                text=f"System prompt not found: {model_name}.txt", text_color="red"
            )
            return
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete the system prompt '{model_name}'?",
        ):
            return
        try:
            prompt_path.unlink()
        except OSError as error:
            self.settings_status.configure(
                text=f"Could not delete system prompt: {error}", text_color="red"
            )
            return

        self._refresh_prompt_name_options()
        self._refresh_generator_options()
        prompt_name_menu.set("")
        prompt_editor.delete("1.0", "end")
        self.settings_status.configure(
            text=f"Deleted {model_name}.txt", text_color="green"
        )

    def _save_prompt(self, prompt_type):
        if prompt_type == "vision":
            prompt_directory = VISION_SYSTEM_PROMPTS_DIR
            prompt_name_menu = self.vision_prompt_name_menu
            prompt_editor = self.vision_prompt_editor
        else:
            prompt_directory = SYSTEM_PROMPTS_DIR
            prompt_name_menu = self.prompt_name_menu
            prompt_editor = self.prompt_editor

        model_name = prompt_name_menu.get().strip()
        instructions = prompt_editor.get("1.0", "end").strip()
        if not model_name or not instructions:
            self.settings_status.configure(
                text="Enter a model name and system prompt", text_color="red"
            )
            return
        if model_name in (".", "..") or not re.fullmatch(
            r"[\w .-]+", model_name, flags=re.UNICODE
        ):
            self.settings_status.configure(
                text="Use letters, numbers, spaces, dots, underscores, or hyphens",
                text_color="red",
            )
            return
        if not messagebox.askyesno(
            "Confirm Save", "Are you sure you want to save this system prompt?"
        ):
            return

        prompt_path = prompt_directory / f"{model_name}.txt"
        try:
            prompt_path.write_text(instructions + "\n", encoding="utf-8")
        except OSError as error:
            self.settings_status.configure(
                text=f"Could not save system prompt: {error}", text_color="red"
            )
            return
        self._refresh_prompt_name_options()
        self._refresh_generator_options()
        target_model_menu = (
            self.image_target_model_menu
            if prompt_type == "vision"
            else self.model_menu
        )
        target_model_menu.set(model_name)
        self.settings_status.configure(text="System prompt saved", text_color="green")
