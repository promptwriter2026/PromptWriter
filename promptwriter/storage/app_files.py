import json
import shutil

from promptwriter.config import (
    APP_DIR,
    BOOTSTRAP_PROMPT_PATH,
    CONFIG_PATH,
    DATA_DIR,
    DEFAULT_CONFIG,
    DEFAULT_JSON_FILES,
    SYSTEM_PROMPTS_DIR,
    VISION_BOOTSTRAP_PROMPT_PATH,
    VISION_SYSTEM_PROMPTS_DIR,
)
from promptwriter.storage.history_db import initialize_history_database


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


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
