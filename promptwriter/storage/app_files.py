import json
import shutil

from promptwriter.config import (
    APP_DIR,
    BASELINE_PROMPTS,
    BASELINE_PROMPTS_DIR,
    CONFIG_PATH,
    DATA_DIR,
    DEFAULT_CONFIG,
    DEFAULT_JSON_FILES,
    SYSTEM_PROMPTS_DIR,
    VISION_SYSTEM_PROMPTS_DIR,
)
from promptwriter.storage.history_db import initialize_history_database


LEGACY_BOOTSTRAP_PROMPTS = {
    SYSTEM_PROMPTS_DIR: ("Flux-2-Klein.txt",),
    VISION_SYSTEM_PROMPTS_DIR: ("Vision-Default.txt",),
}


def _ensure_baseline_prompts():
    for directory, names in BASELINE_PROMPTS.items():
        legacy_names = LEGACY_BOOTSTRAP_PROMPTS.get(directory, ())
        existing = list(directory.glob("*.txt"))
        if any(path.name not in legacy_names for path in existing):
            continue
        for path in existing:
            path.unlink(missing_ok=True)
        for name in names:
            source = BASELINE_PROMPTS_DIR / name
            if not source.is_file():
                raise FileNotFoundError(
                    f"Default system prompt is missing: {source}"
                )
            shutil.copyfile(source, directory / name)


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

    _ensure_baseline_prompts()


def read_json(path, default_value):
    with path.open("r", encoding="utf-8") as data_file:
        value = json.load(data_file)
    if not isinstance(value, type(default_value)):
        raise ValueError(f"Expected {type(default_value).__name__} in {path.name}")
    return value


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
