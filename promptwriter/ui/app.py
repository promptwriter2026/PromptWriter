import ctypes
import sys
import threading
import tkinter
from tkinter import messagebox

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD

from promptwriter.config import (
    APP_ICON_PATH,
    CAMERAS_PATH,
    LORA_PROFILES_PATH,
    SYSTEM_PROMPTS_DIR,
    VISION_SYSTEM_PROMPTS_DIR,
)
from promptwriter.services.lora import lora_profile_value
from promptwriter.storage.app_files import ensure_app_files, read_json
from promptwriter.storage.config_store import load_config, save_config
from promptwriter.storage.profile_store import TEMPERATURE_MAX
from promptwriter.ui.generator_tab import GeneratorTabMixin
from promptwriter.ui.help_tab import HelpTabMixin
from promptwriter.ui.history_tab import HistoryTabMixin
from promptwriter.ui.image_tab import ImagePromptTabMixin
from promptwriter.ui.lm_studio_panel import LMStudioMixin
from promptwriter.ui.model_selector import ModelSelectorMixin
from promptwriter.ui.profile_ui import ProfileMixin
from promptwriter.ui.settings_tab import SettingsTabMixin
from promptwriter.ui.text_actions import TextActionsMixin
from promptwriter.ui.tooltip import ToolTip
from promptwriter.ui.vram_ui import VRAMMixin


def _set_windows_app_user_model_id():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "PromptWriter.Desktop"
        )
    except (AttributeError, OSError):
        pass


class PromptGeneratorApp(
    GeneratorTabMixin,
    ImagePromptTabMixin,
    SettingsTabMixin,
    HistoryTabMixin,
    HelpTabMixin,
    ModelSelectorMixin,
    ProfileMixin,
    LMStudioMixin,
    VRAMMixin,
    TextActionsMixin,
    ctk.CTk,
    TkinterDnD.DnDWrapper,
):
    def __init__(self):
        _set_windows_app_user_model_id()
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        ensure_app_files()

        self.title("PWLP — Prompt Writer for Lazy People")
        self._apply_window_icon()
        self.geometry("1000x760")
        self.minsize(780, 600)

        self.config_data = load_config()
        self.cameras = read_json(CAMERAS_PATH, [])
        self.lora_profiles = read_json(LORA_PROFILES_PATH, [])
        self.model_names = self._get_model_names()
        self.history_selection = None
        self.history_selection_id = None
        self.history_records = []
        self._copy_feedback_after_ids = {}
        self._copy_button_defaults = {}
        self._copy_status_defaults = {}
        self.tooltips = []
        self.generator_temp_var = tkinter.DoubleVar(master=self, value=0.7)
        self.vision_temp_var = tkinter.DoubleVar(master=self, value=0.1)
        self.auto_unload_var = tkinter.BooleanVar(master=self, value=False)
        self.force_single_line_var = tkinter.BooleanVar(master=self, value=True)
        self.generator_profile = {}
        self.vision_profile = {}
        self.generator_profile_saved = False
        self.vision_profile_saved = False
        self._profiles_sync_enabled = False
        self._lm_studio_unload_lock = threading.Lock()
        self._lm_studio_status_check_in_progress = False
        self._closing = False
        self.saved_generator_api_model = None
        self.saved_generator_api_engine = None
        self.saved_vision_api_model = None
        self.saved_vision_api_engine = None
        self.generator_lora_var = tkinter.StringVar(master=self, value="None")
        self.vision_lora_var = tkinter.StringVar(master=self, value="None")

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self._build_layout()
        self._build_vram_indicator()
        self._load_rough_idea()
        self._refresh_generator_options()
        self._load_settings()
        self.load_ui_state()
        self._refresh_history()
        self._on_engine_changed(self.engine_menu.get())
        self._on_image_engine_changed(self.image_engine_menu.get())
        self.update_engine_color()
        self._profiles_sync_enabled = True
        self._refresh_profile("text", sync_temperature=False)
        self._refresh_profile("vision", sync_temperature=False)
        self.after(200, self._refresh_lm_studio_status)
        self._start_vram_polling()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _add_tooltip(self, widget, text):
        tooltip = ToolTip(widget, text)
        self.tooltips.append(tooltip)
        return tooltip

    def _apply_window_icon(self):
        if not APP_ICON_PATH.is_file():
            return
        try:
            self.iconbitmap(str(APP_ICON_PATH))
            self.iconbitmap(default=str(APP_ICON_PATH))
        except tkinter.TclError:
            pass

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=0, column=0, padx=20, pady=12, sticky="nsew")

        self.generator_tab = self.tabs.add("Generator")
        self.image_prompt_tab = self.tabs.add("Image to Prompt")
        self.settings_tab = self.tabs.add("Settings")
        self.history_tab = self.tabs.add("History")
        self.help_tab = self.tabs.add("Help")

        self._build_generator_tab()
        self._build_image_prompt_tab()
        self._build_settings_tab()
        self._build_history_tab()
        self._build_help_tab()

    def _get_model_names(self, directory=SYSTEM_PROMPTS_DIR):
        return sorted(path.stem for path in directory.glob("*.txt"))

    def _refresh_prompt_name_options(self):
        text_prompt_names = self._get_model_names()
        self.prompt_name_menu.configure(
            values=text_prompt_names or ["No text prompts found"]
        )
        vision_prompt_names = self._get_model_names(VISION_SYSTEM_PROMPTS_DIR)
        self.vision_prompt_name_menu.configure(
            values=vision_prompt_names or ["No vision prompts found"]
        )

    def _refresh_generator_options(self):
        self.model_names = self._get_model_names()
        current_model = self.model_menu.get()
        model_values = self.model_names or ["No system prompts found"]
        self.model_menu.configure(values=model_values)
        self.model_menu.set(
            current_model if current_model in model_values else model_values[0]
        )
        vision_model_names = self._get_model_names(VISION_SYSTEM_PROMPTS_DIR)
        vision_model_values = vision_model_names or ["No vision prompts found"]
        current_vision_model = self.image_target_model_menu.get()
        self.image_target_model_menu.configure(values=vision_model_values)
        self.image_target_model_menu.set(
            current_vision_model
            if current_vision_model in vision_model_values
            else vision_model_values[0]
        )

        camera_values = ["None / Auto", *self.cameras]
        current_camera = self.camera_menu.get()
        self.camera_menu.configure(values=camera_values)
        self.camera_menu.set(
            current_camera if current_camera in camera_values else camera_values[0]
        )

        self._refresh_lora_options()

    def _refresh_lora_options(self, preferred_selection=None):
        lora_values = [
            "None",
            *[
                lora_profile_value(profile, "name")
                for profile in self.lora_profiles
                if isinstance(profile, dict) and lora_profile_value(profile, "name")
            ],
        ]
        if hasattr(self, "lora_name_menu"):
            profile_names = lora_values[1:]
            self.lora_name_menu.configure(
                values=profile_names or ["No saved profiles"]
            )

        for menu in (self.lora_menu, self.image_lora_menu):
            previous = (
                preferred_selection
                if preferred_selection is not None
                else menu.get()
            )
            selected = previous if previous in lora_values else "None"
            menu.configure(values=lora_values)
            menu.set(selected)
        if hasattr(self, "lora_name_menu"):
            selected_profile = (
                preferred_selection
                if preferred_selection in lora_values[1:]
                else self.lora_name_menu.get()
            )
            if selected_profile in lora_values[1:]:
                self.lora_name_menu.set(selected_profile)
            else:
                self.lora_name_menu.set("")

    def _collect_ui_state(self):
        return {
            "force_single_line": bool(self.force_single_line_var.get()),
            "generator": {
                "engine": self.engine_menu.get(),
                "api_model": self.api_model_menu.get(),
                "target_model": self.model_menu.get(),
                "camera": self.camera_menu.get(),
                "generator_lora": self.lora_menu.get(),
                "temperature": self.generator_temp_var.get(),
            },
            "image_prompt": {
                "engine": self.image_engine_menu.get(),
                "api_model": self.image_api_model_menu.get(),
                "target_model": self.image_target_model_menu.get(),
                "vision_lora": self.image_lora_menu.get(),
                "temperature": self.vision_temp_var.get(),
            },
        }

    def save_ui_state(self):
        config_data = dict(self.config_data)
        config_data["ui_state"] = self._collect_ui_state()
        try:
            save_config(config_data)
        except OSError as error:
            messagebox.showerror(
                "Could Not Save UI State",
                f"Could not save UI selections: {error}",
                parent=self,
            )
            return False
        self.config_data = config_data
        return True

    def load_ui_state(self):
        ui_state = self.config_data.get("ui_state", {})
        if not isinstance(ui_state, dict):
            return
        generator_state = ui_state.get("generator", {})
        image_state = ui_state.get("image_prompt", {})
        if not isinstance(generator_state, dict):
            generator_state = {}
        if not isinstance(image_state, dict):
            image_state = {}

        if isinstance(ui_state.get("force_single_line"), bool):
            self.force_single_line_var.set(ui_state["force_single_line"])

        for key, menu in (
            ("engine", self.engine_menu),
            ("target_model", self.model_menu),
            ("camera", self.camera_menu),
        ):
            value = generator_state.get(key)
            if isinstance(value, str) and value in menu.cget("values"):
                menu.set(value)
        generator_lora = generator_state.get(
            "generator_lora", generator_state.get("lora")
        )
        if (
            isinstance(generator_lora, str)
            and generator_lora in self.lora_menu.cget("values")
        ):
            self.lora_menu.set(generator_lora)

        for key, menu in (
            ("engine", self.image_engine_menu),
            ("target_model", self.image_target_model_menu),
        ):
            value = image_state.get(key)
            if isinstance(value, str) and value in menu.cget("values"):
                menu.set(value)
        vision_lora = image_state.get("vision_lora", image_state.get("lora"))
        if (
            isinstance(vision_lora, str)
            and vision_lora in self.image_lora_menu.cget("values")
        ):
            self.image_lora_menu.set(vision_lora)

        for state, variable, update_label, max_temperature in (
            (
                generator_state,
                self.generator_temp_var,
                self._update_generator_temp_label,
                TEMPERATURE_MAX,
            ),
            (
                image_state,
                self.vision_temp_var,
                self._update_vision_temp_label,
                1.0,
            ),
        ):
            temperature = state.get("temperature")
            if isinstance(temperature, (int, float)) and not isinstance(
                temperature, bool
            ):
                variable.set(min(max(float(temperature), 0.0), max_temperature))
                update_label()

        generator_engine = self.engine_menu.get()
        image_engine = self.image_engine_menu.get()
        generator_api_model = generator_state.get("api_model")
        if isinstance(generator_api_model, str) and generator_api_model:
            self.saved_generator_api_model = generator_api_model
            self.saved_generator_api_engine = generator_engine
            self.generator_selected_models[generator_engine] = generator_api_model
        vision_api_model = image_state.get("api_model")
        if isinstance(vision_api_model, str) and vision_api_model:
            self.saved_vision_api_model = vision_api_model
            self.saved_vision_api_engine = image_engine
            self.vision_selected_models[image_engine] = vision_api_model

        self._on_engine_changed(generator_engine)
        self._on_image_engine_changed(image_engine)

    def on_closing(self):
        self._closing = True
        self._stop_vram_polling()
        self._save_rough_idea()
        self.save_ui_state()
        self.destroy()

    def update_engine_color(self):
        for engine_menu in (self.engine_menu, self.image_engine_menu):
            choice = engine_menu.get()
            if "Local" in choice:
                fg_color = "#275435"
                button_color = "#1e4028"
            else:
                fg_color = "#7a2d2d"
                button_color = "#5e2222"
            engine_menu.configure(
                fg_color=fg_color,
                button_color=button_color,
                text_color="#ffffff",
            )

    def handle_generation_error(self, error_msg, context, elapsed=None, engine=None):
        if context == "image":
            output_text = self.image_output_text
            timer_label = self.image_time_label
            status_label = self.image_status_label
            self.generate_image_prompt_button.configure(state="normal")
            self.select_image_button.configure(state="normal")
            self._update_quota_label(self.image_quota_label, engine, None)
        else:
            output_text = self.output_text
            timer_label = self.time_label
            status_label = self.status_label
            self.generate_button.configure(state="normal")
            self._update_quota_label(self.quota_label, engine, None)

        output_text.configure(state="normal")
        output_text.delete("1.0", "end")
        output_text.insert("1.0", f"Error: {error_msg}")
        output_text.configure(state="disabled")
        timer_label.configure(
            text=f"Time: {elapsed:.1f}s" if elapsed is not None else "Time: --"
        )
        status_label.configure(text="Generation failed", text_color="red")
