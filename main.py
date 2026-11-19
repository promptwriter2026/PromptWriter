import base64
import io
import json
import os
import re
import shutil
import sqlite3
import tkinter
import threading
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from urllib.parse import quote

import customtkinter as ctk
import requests
from PIL import Image, ImageOps
from tkinterdnd2 import DND_FILES, TkinterDnD


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SYSTEM_PROMPTS_DIR = APP_DIR / "system_prompts"
VISION_SYSTEM_PROMPTS_DIR = APP_DIR / "system_prompts_vision"
CONFIG_PATH = APP_DIR / "config.json"
ROUGH_IDEA_CACHE_PATH = APP_DIR / "rough_idea_cache.txt"
CAMERAS_PATH = DATA_DIR / "cameras.json"
LORA_PROFILES_PATH = DATA_DIR / "lora_profiles.json"
HISTORY_DB_PATH = DATA_DIR / "history.db"
BOOTSTRAP_PROMPT_PATH = APP_DIR / "defaults" / "Flux-2-Klein.txt"
VISION_BOOTSTRAP_PROMPT_PATH = APP_DIR / "defaults" / "Vision-Default.txt"


def truncate_filename(filepath, max_length=40):
    filename = os.path.basename(filepath)
    if max_length <= 0:
        return ""
    if len(filename) <= max_length:
        return filename

    stem, extension = os.path.splitext(filename)
    available_stem_length = max_length - len(extension) - 3
    if available_stem_length <= 0:
        return f"...{filename[-max(0, max_length - 3):]}"
    prefix_length = (available_stem_length + 1) // 2
    suffix_length = available_stem_length - prefix_length
    suffix = stem[-suffix_length:] if suffix_length else ""
    return f"{stem[:prefix_length]}...{suffix}{extension}"


def format_as_single_line_prompts(text):
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = normalized_text.split("\n\n")
    cleaned_blocks = [
        " ".join(block.split())
        for block in blocks
        if block.strip()
    ]
    return "\n".join(cleaned_blocks)


DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
LOCAL_ENGINE = "Local (LM Studio)"
LLM_ENGINES = ("Gemini", "Groq", LOCAL_ENGINE)
LOCAL_SERVER_URL = "http://127.0.0.1:1234/v1"
LOCAL_SERVER_ROOT_URL = "http://127.0.0.1:1234"
GEMINI_FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-2.5-flash"]
GEMINI_EXCLUDED_MODEL_TERMS = (
    "preview",
    "-tts",
    "-image",
    "-audio",
    "-robotics",
    "-computer-use",
    "antigravity",
    "deep-research",
    "omni",
    "nano",
)
GROQ_EXCLUDED_MODEL_TERMS = (
    "guard",
    "safeguard",
    "whisper",
    "orpheus",
    "canopylabs",
)
DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "groq_api_key": "",
    "engine": "Gemini",
    "selected_api_model": DEFAULT_GEMINI_MODEL,
    "selected_api_models": {
        "Gemini": DEFAULT_GEMINI_MODEL,
        "Groq": "",
        LOCAL_ENGINE: "",
    },
    "generator_engine": "Gemini",
    "generator_model": DEFAULT_GEMINI_MODEL,
    "vision_engine": "Gemini",
    "vision_model": DEFAULT_GEMINI_MODEL,
    "available_models": {
        "Gemini": [DEFAULT_GEMINI_MODEL],
        "Groq": [],
        LOCAL_ENGINE: [],
    },
    "cached_models_gemini": [DEFAULT_GEMINI_MODEL],
    "cached_models_groq": [],
    "cached_models_local_lm_studio": [],
}
DEFAULT_JSON_FILES = {
    CAMERAS_PATH: [],
    LORA_PROFILES_PATH: [],
}


def model_cache_key(engine):
    normalized_engine = (
        engine.lower().replace(" (", "_").replace(")", "").replace(" ", "_")
    )
    return f"cached_models_{normalized_engine}"


def filter_gemini_models(models):
    filtered_models = set()
    for model in models:
        name = getattr(model, "name", model)
        if not isinstance(name, str):
            continue
        supported_actions = getattr(model, "supported_actions", None)
        if supported_actions and "generateContent" not in supported_actions:
            continue
        name = name.removeprefix("models/").strip()
        normalized_name = name.lower()
        if not normalized_name.startswith("gemini-"):
            continue
        if any(term in normalized_name for term in GEMINI_EXCLUDED_MODEL_TERMS):
            continue
        filtered_models.add(name)
    return sorted(filtered_models)


def filter_groq_models(model_data):
    filtered_models = []
    seen_models = set()
    for item in model_data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        normalized_id = model_id.lower()
        if any(term in normalized_id for term in GROQ_EXCLUDED_MODEL_TERMS):
            continue
        if model_id not in seen_models:
            filtered_models.append(model_id)
            seen_models.add(model_id)
    return filtered_models


def filter_local_models(model_data):
    models = []
    seen_models = set()
    for item in model_data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if model_id is None:
            continue
        model_name = str(model_id).strip()
        if model_name and model_name not in seen_models:
            models.append(str(model_name))
            seen_models.add(model_name)
    return models


def lora_profile_value(profile, key):
    legacy_keys = {
        "name": "Name",
        "trigger_word": "Trigger Word",
        "description": "Description",
    }
    value = profile.get(key, profile.get(legacy_keys[key], ""))
    return value.strip() if isinstance(value, str) else ""


def find_lora_profile(profile_name, profiles):
    return next(
        (
            item
            for item in profiles
            if isinstance(item, dict)
            and lora_profile_value(item, "name") == profile_name
        ),
        None,
    )


def build_lora_instructions(profile_name, profiles):
    if profile_name == "None":
        return ""
    profile = find_lora_profile(profile_name, profiles)
    if profile is None:
        raise ValueError(f"LoRA profile not found: {profile_name}")
    trigger_words = lora_profile_value(profile, "trigger_word")
    description = lora_profile_value(profile, "description")
    if not trigger_words or not description:
        raise ValueError(
            f"LoRA profile '{profile_name}' must include trigger words and a description."
        )
    return (
        "CHARACTER IDENTITY & STYLING RULES:\n"
        "1. CORE IDENTITY LOCK: You MUST replace the subject's core physical "
        "identity (ethnicity, age, facial features, base body type) with this "
        f"exact LoRA profile: {description}. If the user's input describes a "
        "different core identity (e.g., 'East Asian'), ignore the input and use "
        "the LoRA profile.\n"
        "2. DYNAMIC STYLING: Hair color, hairstyle, makeup, and clothing are "
        "mutable. If the user's input explicitly specifies a styling choice "
        "(e.g., 'pink hair', 'short bob', 'black hair'), apply that specific "
        "style to the character. If no hair/styling is mentioned in the input, "
        f"default to the traits in the LoRA profile: {description}.\n"
        f"3. TRIGGER: You MUST place the exact trigger words '{trigger_words}' "
        "at the VERY BEGINNING of your final prompt."
    )


def build_image_lora_instructions(profile_name, profiles):
    if profile_name == "None":
        return ""
    profile = find_lora_profile(profile_name, profiles)
    if profile is None:
        raise ValueError(f"LoRA profile not found: {profile_name}")
    trigger_words = lora_profile_value(profile, "trigger_word")
    description = lora_profile_value(profile, "description")
    if not trigger_words or not description:
        raise ValueError(
            f"LoRA profile '{profile_name}' must include trigger words and a description."
        )
    return (
        "CHARACTER REPLACEMENT RULE:\n"
        "The user wants to replace the main subject in the provided image with "
        "their custom character. When describing the person in the image, you "
        "MUST IGNORE their original physical appearance (age, gender, facial "
        "features, hair, body type) and REPLACE it completely with this profile: "
        f"{description}\n"
        "However, you MUST STRICTLY PRESERVE the original subject's exact pose, "
        "clothing, actions, and expression. Keep the entire background, "
        "environment, lighting, and camera style exactly as seen in the original "
        "image.\n"
        f"You MUST place the exact trigger words '{trigger_words}' at the VERY "
        "BEGINNING of your final generated prompt."
    )


def enforce_lora_trigger_prefix(generated_prompt, trigger_words):
    prompt = generated_prompt.strip()
    if trigger_words and not prompt.casefold().startswith(trigger_words.casefold()):
        return f"{trigger_words} {prompt}"
    return prompt


def optimize_image_for_api(image_path, max_edge=1024):
    with Image.open(image_path) as source_image:
        image = ImageOps.exif_transpose(source_image).convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="JPEG", quality=85, optimize=True)
    return base64.b64encode(image_buffer.getvalue()).decode("ascii")


def initialize_history_database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                source_tab TEXT,
                rough_idea TEXT,
                generated_prompt TEXT,
                engine TEXT,
                model TEXT,
                is_favorite INTEGER DEFAULT 0,
                image_path TEXT,
                settings_json TEXT
            )
            """
        )


def format_history_timestamp(timestamp):
    if not isinstance(timestamp, str) or not timestamp:
        return "Unknown date"
    try:
        return datetime.fromisoformat(timestamp).strftime("%m.%d. %H:%M")
    except ValueError:
        return timestamp[:16]


def history_idea_snippet(rough_idea, max_length=58):
    snippet = re.sub(r"\s+", " ", rough_idea or "").strip()
    snippet = re.sub(
        r"^Generate\s+\d+\s+prompts?\.\s*", "", snippet, flags=re.IGNORECASE
    )
    if re.match(r"^Each prompt\b", snippet, flags=re.IGNORECASE):
        topic_match = re.search(r"\bTopic\s*:\s*", snippet, flags=re.IGNORECASE)
        if topic_match:
            snippet = snippet[topic_match.end() :]
        else:
            snippet = re.sub(
                r"^Each prompt\b[^.!?\n]*[.!?]\s*",
                "",
                snippet,
                count=1,
                flags=re.IGNORECASE,
            )
    snippet = re.sub(r"^Topic\s*:\s*", "", snippet, flags=re.IGNORECASE).strip()
    if len(snippet) > max_length:
        return f"{snippet[: max_length - 3].rstrip()}..."
    return snippet


def get_lm_studio_loaded_models():
    response = requests.get(
        f"{LOCAL_SERVER_ROOT_URL}/api/v1/models", timeout=5
    )
    response.raise_for_status()
    response_data = response.json()
    if not isinstance(response_data, dict) or not isinstance(
        response_data.get("models"), list
    ):
        raise ValueError("LM Studio returned an invalid models response.")

    loaded_models = []
    for model in response_data["models"]:
        if not isinstance(model, dict):
            raise ValueError("LM Studio returned an invalid model entry.")
        instances = model.get("loaded_instances", [])
        if not isinstance(instances, list):
            raise ValueError("LM Studio returned invalid loaded model instances.")
        model_name = model.get("display_name") or model.get("key")
        if not isinstance(model_name, str) or not model_name:
            model_name = "Unknown model"
        for instance in instances:
            instance_id = instance.get("id") if isinstance(instance, dict) else None
            if not isinstance(instance_id, str) or not instance_id:
                raise ValueError("LM Studio returned an invalid loaded model instance.")
            loaded_models.append((model_name, instance_id))
    return loaded_models


def unload_lm_studio_models():
    loaded_models = get_lm_studio_loaded_models()
    for _, instance_id in loaded_models:
        response = requests.post(
            f"{LOCAL_SERVER_ROOT_URL}/api/v1/models/unload",
            json={"instance_id": instance_id},
            timeout=30,
        )
        response.raise_for_status()
    return loaded_models


def request_generated_prompt(
    engine,
    api_key,
    api_model,
    request_text,
    image_base64=None,
    include_quota=False,
    temperature=0.7,
    cache_prompt=True,
):
    if engine == "Gemini":
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(api_model, safe='')}:generateContent"
        )
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        parts = [{"text": request_text}]
        if image_base64:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": image_base64,
                    }
                }
            )
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": float(temperature)},
        }
    elif engine == "Groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        message_content = request_text
        if image_base64:
            message_content = [
                {"type": "text", "text": request_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    },
                },
            ]
        payload = {
            "model": api_model,
            "messages": [{"role": "user", "content": message_content}],
            "temperature": float(temperature),
            "top_p": 0.2 if image_base64 else 0.95,
            "max_tokens": 6500,
        }
    elif engine == LOCAL_ENGINE:
        url = f"{LOCAL_SERVER_URL}/chat/completions"
        headers = {
            "Authorization": "Bearer local-key",
            "Content-Type": "application/json",
        }
        message_content = request_text
        if image_base64:
            message_content = [
                {"type": "text", "text": request_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    },
                },
            ]
        payload = {
            "model": api_model,
            "messages": [{"role": "user", "content": message_content}],
            "temperature": float(temperature),
            "top_p": 0.2 if image_base64 else 0.95,
            "max_tokens": 2048,
        }
        payload["cache_prompt"] = cache_prompt
    else:
        raise ValueError(f"Unsupported LLM engine: {engine}")

    timeout = 300 if engine == LOCAL_ENGINE else 60
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    quota = None
    if engine == "Groq":
        quota = (
            response.headers.get("x-ratelimit-remaining-tokens"),
            response.headers.get("x-ratelimit-limit-tokens"),
        )
    response_data = response.json()
    if not isinstance(response_data, dict):
        raise ValueError(f"{engine} returned an invalid response.")
    usage = response_data.get("usage", {})
    total_used = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0

    if engine == "Gemini":
        candidates = response_data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Gemini returned no generated candidates.")
        content = candidates[0].get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        generated_text = "\n".join(
            part["text"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ).strip()
    else:
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError(f"{engine} returned no chat completion choices.")
        message = choices[0].get("message", {})
        generated_text = (
            message.get("content")
            if isinstance(message, dict)
            else None
        )
        if not isinstance(generated_text, str):
            raise ValueError("Groq returned a response without text content.")
        generated_text = generated_text.strip()

    if not generated_text:
        raise ValueError(f"{engine} returned an empty response.")
    if re.fullmatch(
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
        generated_text,
    ):
        raise ValueError(
            f"{engine} returned numeric content instead of a generated prompt: "
            f"{generated_text}"
        )
    if include_quota:
        return generated_text, quota, total_used
    return generated_text


def ensure_app_files():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SYSTEM_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    VISION_SYSTEM_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    (APP_DIR / "defaults").mkdir(parents=True, exist_ok=True)

    for path, default_value in DEFAULT_JSON_FILES.items():
        if not path.exists():
            path.write_text(json.dumps(default_value, indent=2), encoding="utf-8")

    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    initialize_history_database()

    if not any(SYSTEM_PROMPTS_DIR.glob("*.txt")):
        if BOOTSTRAP_PROMPT_PATH.exists():
            shutil.copyfile(
                BOOTSTRAP_PROMPT_PATH,
                SYSTEM_PROMPTS_DIR / BOOTSTRAP_PROMPT_PATH.name,
            )
        else:
            raise FileNotFoundError(
                f"Default system prompt is missing: {BOOTSTRAP_PROMPT_PATH}"
            )

    vision_default_path = VISION_SYSTEM_PROMPTS_DIR / "Vision-Default.txt"
    if not vision_default_path.exists():
        if VISION_BOOTSTRAP_PROMPT_PATH.exists():
            shutil.copyfile(VISION_BOOTSTRAP_PROMPT_PATH, vision_default_path)
        else:
            raise FileNotFoundError(
                f"Default vision system prompt is missing: "
                f"{VISION_BOOTSTRAP_PROMPT_PATH}"
            )


def read_json(path, default_value):
    with path.open("r", encoding="utf-8") as data_file:
        value = json.load(data_file)
    if not isinstance(value, type(default_value)):
        raise ValueError(f"Expected {type(default_value).__name__} in {path.name}")
    return value


class ToolTip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self._window = None
        for target in self._widget_tree(widget):
            target.bind("<Enter>", self._schedule_show, add="+")
            target.bind("<Leave>", self._hide, add="+")
            target.bind("<ButtonPress>", self._hide, add="+")
            target.bind("<Destroy>", self._on_destroy, add="+")

    @staticmethod
    def _widget_tree(widget):
        yield widget
        for child in widget.winfo_children():
            yield from ToolTip._widget_tree(child)

    def _schedule_show(self, _event=None):
        self._cancel_scheduled_show()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel_scheduled_show(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tkinter.TclError:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if not self.widget.winfo_exists() or self._window is not None:
            return

        pointer_x, pointer_y = self.widget.winfo_pointerxy()
        x = pointer_x + 15
        y = pointer_y + 15
        window = tkinter.Toplevel(self.widget.winfo_toplevel())
        window.wm_overrideredirect(True)
        window.configure(background="#2b2b2b")
        tkinter.Label(
            window,
            text=self.text,
            justify="left",
            background="#2b2b2b",
            foreground="#f2f2f2",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=5,
        ).pack()
        window.update_idletasks()

        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = min(x, screen_width - window.winfo_reqwidth() - 4)
        y = min(y, screen_height - window.winfo_reqheight() - 4)
        window.geometry(f"+{max(0, x)}+{max(0, y)}")
        self._window = window

    def _hide(self, _event=None):
        self._cancel_scheduled_show()
        window = self._window
        self._window = None
        if window is not None:
            try:
                window.destroy()
            except tkinter.TclError:
                pass

    def _on_destroy(self, event):
        if event.widget is self.widget:
            self._hide()


class PromptGeneratorApp(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        ensure_app_files()

        self.title("PromptWriter")
        self.geometry("1000x760")
        self.minsize(780, 600)

        self.config_data = read_json(CONFIG_PATH, DEFAULT_CONFIG)
        self.cameras = read_json(CAMERAS_PATH, [])
        self.lora_profiles = read_json(LORA_PROFILES_PATH, [])
        self.model_names = self._get_model_names()
        self.history_selection = None
        self.history_selection_id = None
        self.history_records = []
        self._copy_feedback_after_ids = {}
        self.tooltips = []
        self._history_row_tooltips = []
        self.generator_temp_var = tkinter.DoubleVar(master=self, value=0.7)
        self.vision_temp_var = tkinter.DoubleVar(master=self, value=0.1)
        self.auto_unload_var = tkinter.BooleanVar(master=self, value=False)
        self.generator_cache_var = tkinter.BooleanVar(master=self, value=True)
        self.vision_cache_var = tkinter.BooleanVar(master=self, value=True)
        self.force_single_line_var = tkinter.BooleanVar(master=self, value=True)
        self._lm_studio_unload_lock = threading.Lock()
        self._lm_studio_status_check_in_progress = False
        self.saved_generator_api_model = None
        self.saved_generator_api_engine = None
        self.saved_vision_api_model = None
        self.saved_vision_api_engine = None
        self.generator_lora_var = tkinter.StringVar(master=self, value="None")
        self.vision_lora_var = tkinter.StringVar(master=self, value="None")

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self._build_layout()
        self._load_rough_idea()
        self._refresh_generator_options()
        self._load_settings()
        self.load_ui_state()
        self._refresh_history()
        self._on_generator_engine_selected(self.engine_menu.get())
        self._on_image_engine_selected(self.image_engine_menu.get())
        self.after(200, self._refresh_lm_studio_status)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _add_tooltip(self, widget, text):
        tooltip = ToolTip(widget, text)
        self.tooltips.append(tooltip)
        return tooltip

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        self.generator_tab = self.tabs.add("Generator")
        self.image_prompt_tab = self.tabs.add("Image to Prompt")
        self.settings_tab = self.tabs.add("Settings")
        self.history_tab = self.tabs.add("History")

        self._build_generator_tab()
        self._build_image_prompt_tab()
        self._build_settings_tab()
        self._build_history_tab()

    def _build_generator_tab(self):
        tab = self.generator_tab
        tab.grid_columnconfigure((0, 1), weight=1)
        tab.grid_rowconfigure(6, weight=1)
        tab.grid_rowconfigure(9, weight=2)

        ctk.CTkLabel(tab, text="LLM engine").grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w"
        )
        self.engine_menu = ctk.CTkOptionMenu(
            tab, values=LLM_ENGINES, command=self._on_generator_engine_selected
        )
        self.engine_menu.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        self._add_tooltip(
            self.engine_menu, "Select the API provider (e.g., Groq or Gemini)."
        )

        ctk.CTkLabel(tab, text="Selected API model").grid(
            row=0, column=1, padx=12, pady=(12, 4), sticky="w"
        )
        api_model_frame = ctk.CTkFrame(tab, fg_color="transparent")
        api_model_frame.grid(
            row=1, column=1, padx=12, pady=(0, 12), sticky="ew"
        )
        api_model_frame.grid_columnconfigure(0, weight=1)
        self.api_model_menu = ctk.CTkComboBox(
            api_model_frame,
            values=["Fetch models first"],
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

        ctk.CTkLabel(tab, text="Target model").grid(
            row=2, column=0, padx=12, pady=(4, 4), sticky="w"
        )
        self.model_menu = ctk.CTkOptionMenu(
            tab, values=[""]
        )
        self.model_menu.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        self._add_tooltip(
            self.model_menu,
            "Select the image generator you are writing this prompt for.",
        )

        ctk.CTkLabel(tab, text="Camera / lens").grid(
            row=2, column=1, padx=12, pady=(4, 4), sticky="w"
        )
        self.camera_menu = ctk.CTkOptionMenu(tab, values=["None / Auto"])
        self.camera_menu.grid(row=3, column=1, padx=12, pady=(0, 12), sticky="ew")
        self._add_tooltip(
            self.camera_menu,
            "Select a camera setup to inject professional photography keywords into your prompt.",
        )

        ctk.CTkLabel(tab, text="Character / LoRA").grid(
            row=4, column=0, padx=12, pady=(4, 4), sticky="w"
        )
        self.lora_menu = ctk.CTkOptionMenu(
            tab, values=["None"], variable=self.generator_lora_var
        )
        self.lora_menu.grid(row=5, column=0, padx=12, pady=(0, 12), sticky="ew")
        self._add_tooltip(
            self.lora_menu,
            "Apply a character profile and its trigger words to the generation.",
        )
        generator_temperature_frame = ctk.CTkFrame(tab, fg_color="transparent")
        generator_temperature_frame.grid(
            row=6, column=0, padx=12, pady=(0, 12), sticky="ew"
        )
        generator_temperature_frame.grid_columnconfigure(1, weight=1)
        self.generator_temp_label = ctk.CTkLabel(
            generator_temperature_frame, text="Temp: 0.70"
        )
        self.generator_temp_label.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.generator_temp_slider = ctk.CTkSlider(
            generator_temperature_frame,
            from_=0.0,
            to=1.5,
            number_of_steps=150,
            variable=self.generator_temp_var,
            command=self._update_generator_temp_label,
        )
        self.generator_temp_slider.grid(row=0, column=1, sticky="ew")
        self._add_tooltip(
            self.generator_temp_slider,
            "Adjust how varied or predictable text prompt generation is.",
        )
        self.generator_cache_checkbox = ctk.CTkCheckBox(
            generator_temperature_frame,
            text="Enable Local Prompt Caching",
            variable=self.generator_cache_var,
        )
        self.generator_cache_checkbox.grid(
            row=1, column=0, columnspan=2, pady=(8, 0), sticky="w"
        )
        self._add_tooltip(
            self.generator_cache_checkbox,
            "Enable prompt caching when using the Local API to speed up repeated requests.",
        )
        self.generator_auto_unload_checkbox = ctk.CTkCheckBox(
            generator_temperature_frame,
            text="Auto-Unload Model from VRAM",
            variable=self.auto_unload_var,
        )
        self.generator_auto_unload_checkbox.grid(
            row=2, column=0, padx=(0, 8), pady=(8, 0), sticky="w"
        )
        self.generator_single_line_checkbox = ctk.CTkCheckBox(
            generator_temperature_frame,
            text="Enforce Single-Line Prompts",
            variable=self.force_single_line_var,
        )
        self.generator_single_line_checkbox.grid(
            row=3, column=0, columnspan=2, pady=(8, 0), sticky="w"
        )
        self.generator_clear_vram_button = ctk.CTkButton(
            generator_temperature_frame,
            text="Clear VRAM / Unload Model",
            width=210,
            command=self._clear_lm_studio_vram,
        )
        self.generator_clear_vram_button.grid(
            row=2, column=1, pady=(8, 0), sticky="ew"
        )
        self.generator_lm_studio_status_label = ctk.CTkLabel(
            generator_temperature_frame,
            text="LM Studio Status: [Checking...]",
            anchor="w",
        )
        self.generator_lm_studio_status_label.grid(
            row=4, column=0, columnspan=2, pady=(4, 0), sticky="ew"
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

        self.rough_idea_text = ctk.CTkTextbox(tab, height=120, wrap="word")
        self.rough_idea_text.grid(
            row=5, column=1, rowspan=2, padx=12, pady=(0, 12), sticky="nsew"
        )
        self._add_tooltip(
            self.rough_idea_text,
            "Type your basic idea or scene description here.",
        )

        self.generate_button = ctk.CTkButton(
            tab, text="Generate Prompt", command=self._generate_prompt
        )
        self.generate_button.grid(
            row=7, column=0, padx=12, pady=(0, 8), sticky="w"
        )
        self._add_tooltip(
            self.generate_button, "Send the data to the LLM to create your prompt."
        )
        generation_status_frame = ctk.CTkFrame(tab, fg_color="transparent")
        generation_status_frame.grid(
            row=7, column=1, padx=12, pady=(0, 8), sticky="ew"
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

        ctk.CTkLabel(tab, text="Generated prompt").grid(
            row=8, column=0, columnspan=2, padx=12, pady=(4, 4), sticky="w"
        )
        self.output_text = ctk.CTkTextbox(tab, wrap="word")
        self.output_text.grid(
            row=9, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="nsew"
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
            row=10, column=0, columnspan=2, padx=12, pady=(0, 12)
        )
        self._add_tooltip(
            self.copy_button, "Copy the final generated prompt to your clipboard."
        )

    def _build_image_prompt_tab(self):
        tab = self.image_prompt_tab
        tab.grid_columnconfigure((0, 1), weight=1)
        tab.grid_rowconfigure(5, weight=1)
        tab.grid_rowconfigure(9, weight=1)

        ctk.CTkLabel(tab, text="LLM engine").grid(
            row=0, column=0, padx=12, pady=(12, 4), sticky="w"
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
            row=0, column=1, padx=12, pady=(12, 4), sticky="w"
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
            row=4, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew"
        )
        image_hardware_frame.grid_columnconfigure(1, weight=1)
        self.image_auto_unload_checkbox = ctk.CTkCheckBox(
            image_hardware_frame,
            text="Auto-Unload Model from VRAM",
            variable=self.auto_unload_var,
        )
        self.image_auto_unload_checkbox.grid(
            row=1, column=0, padx=(0, 8), sticky="w"
        )
        self.image_single_line_checkbox = ctk.CTkCheckBox(
            image_hardware_frame,
            text="Enforce Single-Line Prompts",
            variable=self.force_single_line_var,
        )
        self.image_single_line_checkbox.grid(
            row=0, column=0, columnspan=2, pady=(0, 8), sticky="w"
        )
        self.image_clear_vram_button = ctk.CTkButton(
            image_hardware_frame,
            text="Clear VRAM / Unload Model",
            width=210,
            command=self._clear_lm_studio_vram,
        )
        self.image_clear_vram_button.grid(row=1, column=1, sticky="w")
        self.image_lm_studio_status_label = ctk.CTkLabel(
            image_hardware_frame,
            text="LM Studio Status: [Checking...]",
            anchor="w",
        )
        self.image_lm_studio_status_label.grid(
            row=2, column=0, columnspan=2, pady=(4, 0), sticky="ew"
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
        self.image_context_text = ctk.CTkTextbox(context_frame, wrap="word")
        self.image_context_text.grid(row=1, column=0, sticky="nsew")
        self._add_tooltip(
            self.image_context_text,
            "Type your basic idea or scene description here.",
        )

        image_actions = ctk.CTkFrame(tab, fg_color="transparent")
        image_actions.grid(
            row=6, column=0, columnspan=2, padx=12, pady=8, sticky="ew"
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
        self.vision_cache_checkbox = ctk.CTkCheckBox(
            image_actions,
            text="Enable Local Prompt Caching",
            variable=self.vision_cache_var,
        )
        self.vision_cache_checkbox.grid(
            row=1, column=0, columnspan=4, pady=(8, 0), sticky="w"
        )
        self._add_tooltip(
            self.vision_cache_checkbox,
            "Enable prompt caching when using the Local API to speed up repeated requests.",
        )
        image_status_frame = ctk.CTkFrame(tab, fg_color="transparent")
        image_status_frame.grid(
            row=7, column=0, columnspan=2, padx=12, pady=(0, 4), sticky="ew"
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

        ctk.CTkLabel(tab, text="Output Prompt").grid(
            row=8, column=0, columnspan=2, padx=12, pady=(4, 4), sticky="w"
        )
        self.image_output_text = ctk.CTkTextbox(tab, wrap="word")
        self.image_output_text.grid(
            row=9, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="nsew"
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
            row=10, column=0, columnspan=2, padx=12, pady=(0, 12)
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

        self.save_settings_button = ctk.CTkButton(
            tab, text="Save Settings", command=self._save_settings
        )
        self.save_settings_button.grid(
            row=3, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.save_settings_button, "Save your API keys and configuration."
        )
        self.settings_status = ctk.CTkLabel(tab, text="")
        self.settings_status.grid(
            row=13, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="e"
        )

        ctk.CTkLabel(tab, text="Add a camera / lens").grid(
            row=7, column=0, padx=12, pady=(12, 4), sticky="w"
        )
        self.camera_entry = ctk.CTkEntry(tab, placeholder_text="Camera and lens")
        self.camera_entry.grid(
            row=8, column=0, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.camera_entry,
            "Add a new camera and lens combination to your local database.",
        )
        self.add_camera_button = ctk.CTkButton(
            tab, text="Add Camera", command=self._add_camera
        )
        self.add_camera_button.grid(
            row=8, column=1, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.add_camera_button,
            "Add a new camera and lens combination to your local database.",
        )

        ctk.CTkLabel(tab, text="Text System Prompts").grid(
            row=9, column=0, padx=12, pady=(12, 4), sticky="w"
        )
        self.prompt_name_menu = ctk.CTkComboBox(
            tab,
            values=self._get_model_names(),
            command=self.load_selected_text_prompt,
        )
        self.prompt_name_menu.grid(
            row=10, column=0, padx=12, pady=(0, 8), sticky="new"
        )
        self._add_tooltip(
            self.prompt_name_menu,
            "Select, edit, or save your system prompt templates.",
        )
        self.prompt_editor = ctk.CTkTextbox(tab, wrap="word")
        self.prompt_editor.grid(
            row=11, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="nsew"
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
        tab.grid_rowconfigure(11, weight=1)

        prompt_actions = ctk.CTkFrame(tab, fg_color="transparent")
        prompt_actions.grid(
            row=12, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew"
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
            row=14, column=0, padx=12, pady=(12, 4), sticky="w"
        )
        self.vision_prompt_name_menu = ctk.CTkComboBox(
            tab,
            values=self._get_model_names(VISION_SYSTEM_PROMPTS_DIR),
            command=self.load_selected_vision_prompt,
        )
        self.vision_prompt_name_menu.grid(
            row=15, column=0, padx=12, pady=(0, 8), sticky="new"
        )
        self._add_tooltip(
            self.vision_prompt_name_menu,
            "Select, edit, or save your vision system prompt templates.",
        )
        self.vision_prompt_editor = ctk.CTkTextbox(tab, wrap="word")
        self.vision_prompt_editor.grid(
            row=16, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="nsew"
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
        tab.grid_rowconfigure(16, weight=1)

        vision_prompt_actions = ctk.CTkFrame(tab, fg_color="transparent")
        vision_prompt_actions.grid(
            row=17, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="ew"
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
            row=19, column=0, columnspan=2, padx=12, pady=(16, 4), sticky="w"
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
        self.lora_name_menu.grid(
            row=20, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew"
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
            row=21, column=0, padx=12, pady=(4, 4), sticky="w"
        )
        self.lora_trigger_entry = ctk.CTkEntry(
            tab, placeholder_text="Exact trigger words"
        )
        self.lora_trigger_entry.grid(
            row=22, column=0, padx=12, pady=(0, 8), sticky="ew"
        )
        self._add_tooltip(
            self.lora_trigger_entry,
            "Manage your character profiles to override default AI generation styles.",
        )
        ctk.CTkLabel(tab, text="Character Profile / Description").grid(
            row=21, column=1, padx=12, pady=(4, 4), sticky="w"
        )
        self.lora_description_text = ctk.CTkTextbox(tab, wrap="word", height=110)
        self.lora_description_text.grid(
            row=22, column=1, rowspan=2, padx=12, pady=(0, 8), sticky="nsew"
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
            row=23, column=0, padx=12, pady=(0, 8), sticky="ew"
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
            row=24, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="e"
        )

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
        if not self.available_models["Gemini"]:
            self.available_models["Gemini"] = [DEFAULT_GEMINI_MODEL]
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
        if generator_model == "Fetch models first":
            generator_model = ""
        vision_engine = self.image_engine_menu.get()
        vision_model = self.image_api_model_menu.get()
        if vision_model == "Fetch models first":
            vision_model = ""
        self.generator_selected_models[generator_engine] = generator_model
        self.vision_selected_models[vision_engine] = vision_model

        legacy_selected_models = {
            provider: self.generator_selected_models.get(provider, "")
            for provider in LLM_ENGINES
        }
        self.config_data = {
            "gemini_api_key": self.gemini_key_entry.get().strip(),
            "groq_api_key": self.groq_key_entry.get().strip(),
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
            CONFIG_PATH.write_text(
                json.dumps(self.config_data, indent=2), encoding="utf-8"
            )
        except OSError as error:
            self.settings_status.configure(
                text=f"Could not save settings: {error}", text_color="red"
            )
            return
        self.settings_status.configure(text="Settings saved", text_color="green")

    def _collect_ui_state(self):
        return {
            "generator": {
                "engine": self.engine_menu.get(),
                "api_model": self.api_model_menu.get(),
                "target_model": self.model_menu.get(),
                "camera": self.camera_menu.get(),
                "generator_lora": self.lora_menu.get(),
                "temperature": self.generator_temp_var.get(),
                "cache_prompt": self.generator_cache_var.get(),
            },
            "image_prompt": {
                "engine": self.image_engine_menu.get(),
                "api_model": self.image_api_model_menu.get(),
                "target_model": self.image_target_model_menu.get(),
                "vision_lora": self.image_lora_menu.get(),
                "temperature": self.vision_temp_var.get(),
                "cache_prompt": self.vision_cache_var.get(),
            },
        }

    def _update_generator_temp_label(self, value=None):
        temperature = (
            self.generator_temp_var.get() if value is None else float(value)
        )
        self.generator_temp_label.configure(text=f"Temp: {temperature:.2f}")

    def _update_vision_temp_label(self, value=None):
        temperature = self.vision_temp_var.get() if value is None else float(value)
        self.vision_temp_label.configure(text=f"Temp: {temperature:.2f}")

    def save_ui_state(self):
        config_data = dict(self.config_data)
        config_data["ui_state"] = self._collect_ui_state()
        try:
            CONFIG_PATH.write_text(
                json.dumps(config_data, indent=2), encoding="utf-8"
            )
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
                1.5,
            ),
            (
                image_state,
                self.vision_temp_var,
                self._update_vision_temp_label,
                1.0,
            ),
        ):
            temperature = state.get("temperature")
            if (
                isinstance(temperature, (int, float))
                and not isinstance(temperature, bool)
                and 0.0 <= temperature <= max_temperature
            ):
                variable.set(temperature)
                update_label()

        for state, variable in (
            (generator_state, self.generator_cache_var),
            (image_state, self.vision_cache_var),
        ):
            cache_prompt = state.get("cache_prompt")
            if isinstance(cache_prompt, bool):
                variable.set(cache_prompt)

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
        self._save_rough_idea()
        self.save_ui_state()
        self.destroy()

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

    def _set_api_model_options(self, context, engine):
        cached_models = self.available_models.get(engine, [])
        models = []
        if isinstance(cached_models, (list, tuple)):
            for model in cached_models:
                if model is None:
                    continue
                model_name = str(model).strip()
                if model_name and model_name not in models:
                    models.append(model_name)
        if context == "generator":
            menu = self.api_model_menu
            selected_models = self.generator_selected_models
            saved_model = self.saved_generator_api_model
            saved_engine = self.saved_generator_api_engine
        else:
            menu = self.image_api_model_menu
            selected_models = self.vision_selected_models
            saved_model = self.saved_vision_api_model
            saved_engine = self.saved_vision_api_engine

        selected_model = selected_models.get(engine, "")
        if not models:
            placeholder = selected_model or (
                DEFAULT_GEMINI_MODEL if engine == "Gemini" else "Fetch models first"
            )
            model_list = [str(placeholder)]
            menu.configure(values=model_list)
            menu.set(model_list[0])
            return
        model_list = [str(model) for model in models]
        menu.configure(values=model_list)
        menu.set(model_list[0])
        if saved_engine == engine:
            if saved_model in model_list:
                selected_model = saved_model
            if context == "generator":
                self.saved_generator_api_model = None
                self.saved_generator_api_engine = None
            else:
                self.saved_vision_api_model = None
                self.saved_vision_api_engine = None
        if selected_model not in model_list:
            selected_model = (
                DEFAULT_GEMINI_MODEL
                if engine == "Gemini" and DEFAULT_GEMINI_MODEL in model_list
                else model_list[0]
            )
        menu.set(selected_model)
        selected_models[engine] = selected_model

    def _on_engine_changed(self, engine):
        self._set_api_model_options("generator", engine)
        self._update_lm_studio_controls(
            engine,
            self.generator_auto_unload_checkbox,
            self.generator_clear_vram_button,
            self.generator_lm_studio_status_label,
        )
        self.after(200, self._refresh_lm_studio_status)

    def _on_generator_engine_selected(self, engine):
        self._on_engine_changed(engine)
        self.update_engine_color()

    def _on_image_engine_selected(self, engine):
        self._on_image_engine_changed(engine)
        self.update_engine_color()

    def _update_lm_studio_controls(
        self, engine, auto_unload_checkbox, clear_vram_button, status_label
    ):
        state = "normal" if engine == LOCAL_ENGINE else "disabled"
        auto_unload_checkbox.configure(state=state)
        clear_vram_button.configure(state=state)
        status_label.configure(state=state)

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

    def _on_api_model_changed(self, model):
        engine = self.engine_menu.get()
        if model and model != "Fetch models first":
            self.generator_selected_models[engine] = model

    def _on_image_engine_changed(self, engine):
        self._set_api_model_options("vision", engine)
        self._update_lm_studio_controls(
            engine,
            self.image_auto_unload_checkbox,
            self.image_clear_vram_button,
            self.image_lm_studio_status_label,
        )
        self.after(200, self._refresh_lm_studio_status)

    def _has_local_engine_selected(self):
        return (
            self.engine_menu.get() == LOCAL_ENGINE
            or self.image_engine_menu.get() == LOCAL_ENGINE
        )

    def _refresh_lm_studio_status(self):
        if not self._has_local_engine_selected():
            return
        if self._lm_studio_status_check_in_progress:
            return
        self._lm_studio_status_check_in_progress = True
        self.after(200, self._start_lm_studio_status_worker)

    def _start_lm_studio_status_worker(self):
        if not self._has_local_engine_selected():
            self._lm_studio_status_check_in_progress = False
            return
        threading.Thread(
            target=self._lm_studio_status_worker, daemon=True
        ).start()

    def _lm_studio_status_worker(self):
        try:
            loaded_models = get_lm_studio_loaded_models()
            model_names = list(dict.fromkeys(name for name, _ in loaded_models))
            status = ", ".join(model_names) if model_names else "Empty"
            color = "gray"
        except (requests.exceptions.RequestException, ValueError) as error:
            status = f"Unavailable: {error}"
            color = "red"
        self.after(0, self._finish_lm_studio_status_refresh, status, color)

    def _finish_lm_studio_status_refresh(self, status, color):
        status_text = f"LM Studio Status: {status}"
        self.generator_lm_studio_status_label.configure(
            text=status_text, text_color=color
        )
        self.image_lm_studio_status_label.configure(
            text=status_text, text_color=color
        )
        self._lm_studio_status_check_in_progress = False
        if self._has_local_engine_selected():
            self.after(4000, self._refresh_lm_studio_status)

    def _clear_lm_studio_vram(self):
        self.generator_clear_vram_button.configure(state="disabled")
        self.image_clear_vram_button.configure(state="disabled")
        self._set_lm_studio_status("Unloading...", "gray")
        threading.Thread(
            target=self._clear_lm_studio_vram_worker,
            daemon=True,
        ).start()

    def _clear_lm_studio_vram_worker(self):
        try:
            with self._lm_studio_unload_lock:
                unload_lm_studio_models()
            loaded_models = get_lm_studio_loaded_models()
            model_names = list(dict.fromkeys(name for name, _ in loaded_models))
            status = ", ".join(model_names) if model_names else "Empty"
            color = "gray"
        except (requests.exceptions.RequestException, ValueError) as error:
            status = f"Unload failed: {error}"
            color = "red"
        self.after(0, self._finish_lm_studio_unload, status, color)

    def _finish_lm_studio_unload(self, status, color):
        self._set_lm_studio_status(status, color)
        self._update_lm_studio_controls(
            self.engine_menu.get(),
            self.generator_auto_unload_checkbox,
            self.generator_clear_vram_button,
            self.generator_lm_studio_status_label,
        )
        self._update_lm_studio_controls(
            self.image_engine_menu.get(),
            self.image_auto_unload_checkbox,
            self.image_clear_vram_button,
            self.image_lm_studio_status_label,
        )

    def _set_lm_studio_status(self, status, color):
        status_text = f"LM Studio Status: {status}"
        self.generator_lm_studio_status_label.configure(
            text=status_text, text_color=color
        )
        self.image_lm_studio_status_label.configure(
            text=status_text, text_color=color
        )

    def _auto_unload_lm_studio_model(self):
        try:
            with self._lm_studio_unload_lock:
                unload_lm_studio_models()
            self.after(0, self._refresh_lm_studio_status)
        except (requests.exceptions.RequestException, ValueError) as error:
            self.after(
                0,
                self._set_lm_studio_status,
                f"Unload failed: {error}",
                "red",
            )

    def _on_image_api_model_changed(self, model):
        engine = self.image_engine_menu.get()
        if model and model != "Fetch models first":
            self.vision_selected_models[engine] = model

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

    def _assemble_image_request(self, additional_context):
        model_name = self.image_target_model_menu.get()
        prompt_path = VISION_SYSTEM_PROMPTS_DIR / f"{model_name}.txt"
        if not prompt_path.is_file():
            raise ValueError("Select a valid target model before generating.")
        instruction_parts = [prompt_path.read_text(encoding="utf-8").strip()]

        selected_lora = self.image_lora_menu.get()
        lora_instructions = build_image_lora_instructions(
            selected_lora, self.lora_profiles
        )
        if lora_instructions:
            instruction_parts.append(lora_instructions)
        if additional_context:
            instruction_parts.append(
                f"Additional context and instructions:\n{additional_context}"
            )
        return "\n\n".join(part for part in instruction_parts if part)

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
            config_data = read_json(CONFIG_PATH, DEFAULT_CONFIG)
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
            request_text = self._assemble_image_request(rough_idea)
            selected_lora = self.image_lora_menu.get()
            selected_profile = find_lora_profile(selected_lora, self.lora_profiles)
            trigger_words = (
                lora_profile_value(selected_profile, "trigger_word")
                if selected_profile
                else ""
            )
            image_path = self._selected_image_path
            temperature = self.vision_temp_var.get()
            cache_prompt = self.vision_cache_var.get()
            auto_unload = self.auto_unload_var.get()
            force_single_line = self.force_single_line_var.get()
            generation_settings = {
                "target_model": self.image_target_model_menu.get(),
                "character_lora": selected_lora,
                "temperature": temperature,
                "cache_prompt": cache_prompt,
                "auto_unload": auto_unload,
                "force_single_line": force_single_line,
            }
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
                request_text,
                image_path,
                trigger_words,
                temperature,
                cache_prompt,
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
        request_text,
        image_path,
        trigger_words,
        temperature,
        cache_prompt,
        auto_unload,
        rough_idea,
        generation_settings,
        force_single_line,
    ):
        start_time = None
        elapsed = None
        try:
            image_base64 = optimize_image_for_api(image_path)
            start_time = time.time()
            generated_prompt, quota, total_used = request_generated_prompt(
                engine,
                api_key,
                api_model,
                request_text,
                image_base64=image_base64,
                include_quota=True,
                temperature=temperature,
                cache_prompt=cache_prompt,
            )
            elapsed = time.time() - start_time
            if engine == LOCAL_ENGINE and auto_unload:
                self._auto_unload_lm_studio_model()
            generated_prompt = enforce_lora_trigger_prefix(
                generated_prompt, trigger_words
            )
            generated_prompt = re.sub(
                r"<think>.*?</think>", "", generated_prompt, flags=re.DOTALL
            ).strip()
            if not generated_prompt or self._is_numeric_result(generated_prompt):
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
        if self._is_numeric_result(generated_prompt):
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
            self._save_generation(
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

    def _fetch_available_models(self, context):
        if context == "generator":
            engine = self.engine_menu.get()
            status_label = self.status_label
        else:
            engine = self.image_engine_menu.get()
            status_label = self.image_status_label
        try:
            config_data = read_json(CONFIG_PATH, DEFAULT_CONFIG)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            status_label.configure(
                text=f"Could not read saved API settings: {error}",
                text_color="red",
            )
            return
        api_key = (
            ""
            if engine == LOCAL_ENGINE
            else config_data.get(
                "gemini_api_key" if engine == "Gemini" else "groq_api_key", ""
            )
        )
        if not isinstance(api_key, str):
            api_key = ""
        api_key = api_key.strip()
        if engine != LOCAL_ENGINE and not api_key:
            status_label.configure(
                text=f"Save your {engine} API key in Settings before fetching models.",
                text_color="red",
            )
            return
        self._set_fetch_buttons_state("disabled")
        status_label.configure(
            text=f"Fetching {engine} models...", text_color="gray"
        )
        threading.Thread(
            target=self._fetch_models_worker,
            args=(engine, api_key, context),
            daemon=True,
        ).start()

    def _fetch_models_worker(self, engine, api_key, context):
        try:
            if engine == "Gemini":
                from google import genai

                client = genai.Client(api_key=api_key)
                models = filter_gemini_models(client.models.list())
                if not models:
                    self.after(
                        0,
                        self._on_models_fetched,
                        engine,
                        GEMINI_FALLBACK_MODELS.copy(),
                        "No standard text-generation Gemini models were returned; showing fallback models.",
                        context,
                    )
                    return
            elif engine == "Groq":
                response = requests.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=30,
                )
                response.raise_for_status()
                response_data = response.json()
                model_data = response_data.get("data")
                if not isinstance(model_data, list):
                    raise ValueError("Groq returned an invalid models response.")
                models = filter_groq_models(model_data)
            else:
                try:
                    response = requests.get(
                        f"{LOCAL_SERVER_URL}/models",
                        timeout=5,
                    )
                    response.raise_for_status()
                    response_data = response.json()
                    if not isinstance(response_data, dict):
                        raise ValueError(
                            "LM Studio returned an invalid models response."
                        )
                    model_data = response_data.get("data")
                    if not isinstance(model_data, list):
                        raise ValueError(
                            "LM Studio returned an invalid models response."
                        )
                    models = filter_local_models(model_data)
                    if not models:
                        raise ValueError("LM Studio returned no available models.")
                except (
                    requests.exceptions.RequestException,
                    ValueError,
                    KeyError,
                ) as error:
                    print(f"Could not fetch Local models: {error}")
                    self.after(
                        0, self._on_models_error, engine, error, context
                    )
                    return
            if engine == "Gemini":
                models = sorted(set(model for model in models if model))
            if not models:
                raise ValueError(f"{engine} returned no available models.")
        except Exception as error:
            if engine == "Gemini":
                self.after(
                    0,
                    self._on_models_fetched,
                    engine,
                    GEMINI_FALLBACK_MODELS.copy(),
                    f"Could not fetch Gemini models: {error}. Showing fallback models.",
                    context,
                )
            else:
                if engine == LOCAL_ENGINE:
                    print(f"Could not fetch Local models: {error}")
                self.after(0, self._on_models_error, engine, error, context)
            return
        self.after(0, self._on_models_fetched, engine, models, None, context)

    def _on_models_fetched(
        self, engine, models, fallback_message=None, context="generator"
    ):
        model_list = []
        if isinstance(models, (list, tuple)):
            for model in models:
                if model is None:
                    continue
                model_name = str(model).strip()
                if model_name and model_name not in model_list:
                    model_list.append(str(model_name))
        if not model_list:
            self.available_models[engine] = []
            self._on_models_error(
                engine,
                fallback_message or f"No {engine} models were returned.",
                context,
            )
            return
        models = model_list
        self.available_models[engine] = models
        cache_error = None
        if fallback_message is None:
            try:
                config_data = read_json(CONFIG_PATH, DEFAULT_CONFIG)
                available_models = config_data.get("available_models", {})
                if not isinstance(available_models, dict):
                    available_models = {}
                available_models[engine] = models
                config_data["available_models"] = available_models
                config_data[model_cache_key(engine)] = models
                CONFIG_PATH.write_text(
                    json.dumps(config_data, indent=2), encoding="utf-8"
                )
                self.config_data = config_data
            except (OSError, ValueError, json.JSONDecodeError) as error:
                cache_error = error

        if self.engine_menu.get() == engine:
            self._set_api_model_options("generator", engine)
        if self.image_engine_menu.get() == engine:
            self._set_api_model_options("vision", engine)
        self._set_fetch_buttons_state("normal")
        status_label = (
            self.status_label if context == "generator" else self.image_status_label
        )
        status_label.configure(
            text=(
                fallback_message
                or (
                    f"Fetched {len(models)} {engine} models, but could not cache them: "
                    f"{cache_error}"
                    if cache_error
                    else f"Fetched and cached {len(models)} {engine} models."
                )
            ),
            text_color="red" if fallback_message or cache_error else "green",
        )

    def _on_models_error(self, engine, error, context):
        self._set_fetch_buttons_state("normal")
        for selected_engine, menu in (
            (self.engine_menu.get(), self.api_model_menu),
            (self.image_engine_menu.get(), self.image_api_model_menu),
        ):
            if selected_engine == engine:
                model_list = ["Fetch models first"]
                menu.configure(values=model_list)
                menu.set(model_list[0])
        status_label = (
            self.status_label if context == "generator" else self.image_status_label
        )
        status_label.configure(
            text=f"Could not fetch {engine} models: {error}", text_color="red"
        )

    def _set_fetch_buttons_state(self, state):
        self.generator_fetch_button.configure(state=state)
        self.image_fetch_button.configure(state=state)

    def _update_status_wraplength(self, event):
        wraplength = max(200, event.width - 24)
        if self.status_label.cget("wraplength") != wraplength:
            self.status_label.configure(wraplength=wraplength)

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
        search_pattern = f"%{search_text}%"
        try:
            with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
                rows = connection.execute(
                    """
                    WITH recent AS (
                        SELECT id, timestamp, rough_idea, generated_prompt,
                               is_favorite
                        FROM generations
                        ORDER BY id DESC
                        LIMIT 50
                    )
                    SELECT id, timestamp, rough_idea, is_favorite
                    FROM recent
                    WHERE (? = '' OR rough_idea LIKE ? COLLATE NOCASE
                           OR generated_prompt LIKE ? COLLATE NOCASE)
                      AND (? = 0 OR is_favorite = 1)
                    ORDER BY id DESC
                    """,
                    (
                        search_text,
                        search_pattern,
                        search_pattern,
                        int(favorites_only),
                    ),
                ).fetchall()
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
            with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
                row = connection.execute(
                    """
                    SELECT id, timestamp, source_tab, rough_idea,
                           generated_prompt, engine, model, is_favorite,
                           image_path, settings_json
                    FROM generations
                    WHERE id = ?
                    """,
                    (generation_id,),
                ).fetchone()
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
            with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
                connection.execute(
                    """
                    UPDATE generations
                    SET is_favorite = CASE WHEN is_favorite = 1 THEN 0 ELSE 1 END
                    WHERE id = ?
                    """,
                    (self.history_selection_id,),
                )
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
            with closing(sqlite3.connect(HISTORY_DB_PATH)) as connection, connection:
                favorites = [
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT generated_prompt
                        FROM generations
                        WHERE is_favorite = 1
                        ORDER BY id DESC
                        """
                    )
                    if isinstance(row[0], str) and row[0].strip()
                ]
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

    def _copy_output(self):
        self._copy_text(self.output_text.get("1.0", "end").strip())

    def _clear_rough_idea(self):
        self.rough_idea_text.delete("1.0", "end")

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

    def _assemble_request(self, user_idea):
        model_name = self.model_menu.get()
        prompt_path = SYSTEM_PROMPTS_DIR / f"{model_name}.txt"
        if not prompt_path.is_file():
            raise ValueError("Select a valid target model before generating.")

        instruction_parts = [prompt_path.read_text(encoding="utf-8").strip()]
        selected_lora = self.lora_menu.get()
        lora_instructions = build_lora_instructions(
            selected_lora, self.lora_profiles
        )
        if lora_instructions:
            instruction_parts.append(lora_instructions)

        selected_camera = self.camera_menu.get()
        if selected_camera != "None / Auto":
            instruction_parts.append(
                f"The image is shot on {selected_camera}. "
                "Include relevant photography terms."
            )
        instruction_parts.append(f"User's rough idea:\n{user_idea}")
        return "\n\n".join(part for part in instruction_parts if part)

    def _generate_prompt(self):
        if self.generate_button.cget("state") == "disabled":
            return

        user_idea = self.rough_idea_text.get("1.0", "end").strip()
        if not user_idea:
            self.status_label.configure(
                text="Enter a rough idea before generating.", text_color="red"
            )
            return

        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")

        try:
            request_text = self._assemble_request(user_idea)
            config_data = read_json(CONFIG_PATH, DEFAULT_CONFIG)
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
            if api_model == "Fetch models first":
                raise ValueError(f"Fetch and select an available {engine} API model.")
            generation_settings = {
                "target_model": self.model_menu.get(),
                "camera_lens": self.camera_menu.get(),
                "character_lora": self.lora_menu.get(),
                "llm_engine": engine,
                "api_model": api_model,
                "temperature": self.generator_temp_var.get(),
                "cache_prompt": self.generator_cache_var.get(),
                "auto_unload": self.auto_unload_var.get(),
            }
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

        self.generate_button.configure(state="disabled")
        self.status_label.configure(text="Generating...", text_color="gray")
        self.time_label.configure(text="Generating...", text_color="gray")
        self._update_quota_label(self.quota_label, engine, None)
        threading.Thread(
            target=self._generation_worker,
            args=(
                engine,
                api_key,
                api_model,
                request_text,
                user_idea,
                generation_settings,
                force_single_line,
            ),
            daemon=True,
        ).start()

    def _generation_worker(
        self,
        engine,
        api_key,
        api_model,
        request_text,
        user_idea,
        generation_settings,
        force_single_line,
    ):
        start_time = None
        elapsed = None
        try:
            start_time = time.time()
            generated_prompt, quota, total_used = request_generated_prompt(
                engine,
                api_key,
                api_model,
                request_text,
                include_quota=True,
                temperature=generation_settings["temperature"],
                cache_prompt=generation_settings["cache_prompt"],
            )
            elapsed = time.time() - start_time
            if engine == LOCAL_ENGINE and generation_settings["auto_unload"]:
                self._auto_unload_lm_studio_model()
            generated_prompt = enforce_lora_trigger_prefix(
                generated_prompt, generation_settings.get("trigger_words", "")
            )
            generated_prompt = re.sub(
                r"<think>.*?</think>", "", generated_prompt, flags=re.DOTALL
            ).strip()
            if not generated_prompt or self._is_numeric_result(generated_prompt):
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

    def _save_generation(
        self,
        user_idea,
        generated_prompt,
        generation_settings,
        source_tab="generator",
        engine=None,
        model=None,
        image_path=None,
    ):
        if not isinstance(generated_prompt, str):
            raise ValueError("Cannot save a generated prompt that is not text.")
        if source_tab not in ("generator", "image_to_prompt"):
            raise ValueError(f"Unsupported history source tab: {source_tab}")
        with closing(
            sqlite3.connect(HISTORY_DB_PATH, timeout=10)
        ) as connection, connection:
            connection.execute(
                """
                INSERT INTO generations (
                    timestamp, source_tab, rough_idea, generated_prompt,
                    engine, model, is_favorite, image_path, settings_json
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    datetime.now()
                    .astimezone()
                    .isoformat(timespec="seconds"),
                    source_tab,
                    user_idea,
                    generated_prompt,
                    engine or generation_settings.get("llm_engine", ""),
                    model or generation_settings.get("api_model", ""),
                    image_path,
                    json.dumps(generation_settings, ensure_ascii=False),
                ),
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
        if self._is_numeric_result(generated_prompt):
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
            self._save_generation(
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

    @staticmethod
    def _is_numeric_result(value):
        return bool(
            isinstance(value, str)
            and re.fullmatch(
                r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
                value.strip(),
            )
        )

    def _on_generation_error(self, engine, error_message, elapsed=None):
        self.handle_generation_error(
            f"{engine} generation failed: {error_message}",
            "generator",
            elapsed,
            engine,
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


if __name__ == "__main__":
    ensure_app_files()
    app = PromptGeneratorApp()
    app.mainloop()
