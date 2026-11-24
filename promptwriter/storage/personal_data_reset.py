import copy
import json
import shutil
import sqlite3

from promptwriter.config import (
    BASELINE_PROMPTS,
    BASELINE_PROMPTS_DIR,
    CONFIG_PATH,
    DEFAULT_CONFIG,
    DEFAULT_JSON_FILES,
    ROUGH_IDEA_CACHE_PATH,
)
from promptwriter.storage import history_db
from promptwriter.storage.app_files import read_json, write_json

API_KEY_FIELDS = ("gemini_api_key", "groq_api_key")


def _load_existing_config():
    try:
        config = read_json(CONFIG_PATH, DEFAULT_CONFIG)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return config if isinstance(config, dict) else {}


def _restore_baseline_prompt(directory, name):
    source = BASELINE_PROMPTS_DIR / name
    target = directory / name
    if source.is_file() and source.resolve() != target.resolve():
        shutil.copyfile(source, target)
        return True
    return target.is_file()


def _reset_prompts():
    removed = 0
    restored = []
    errors = []
    for directory, baseline_names in BASELINE_PROMPTS.items():
        directory.mkdir(parents=True, exist_ok=True)
        for prompt_path in directory.glob("*.txt"):
            if prompt_path.name in baseline_names:
                continue
            try:
                prompt_path.unlink()
                removed += 1
            except OSError as error:
                errors.append(f"Could not delete {prompt_path.name}: {error}")
        for name in baseline_names:
            try:
                if _restore_baseline_prompt(directory, name):
                    restored.append(name)
            except OSError as error:
                errors.append(f"Could not restore {name}: {error}")
    return removed, restored, errors


def reset_personal_data(delete_api_keys=False):
    """Delete personal data and restore the shipped baseline prompts.

    Missing files or folders are treated as already reset; failures are
    collected in the returned ``errors`` list instead of raising.
    """
    existing = _load_existing_config()
    config = copy.deepcopy(DEFAULT_CONFIG)
    if not delete_api_keys:
        for field in API_KEY_FIELDS:
            value = existing.get(field)
            if isinstance(value, str):
                config[field] = value
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(CONFIG_PATH, config)

    for path, default_value in DEFAULT_JSON_FILES.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, copy.deepcopy(default_value))

    removed_prompts, restored_prompts, errors = _reset_prompts()

    history_deleted = 0
    try:
        history_deleted = history_db.clear_history()
    except (OSError, sqlite3.Error) as error:
        errors.append(f"Could not clear history: {error}")

    if ROUGH_IDEA_CACHE_PATH.exists():
        try:
            ROUGH_IDEA_CACHE_PATH.unlink()
        except OSError as error:
            errors.append(f"Could not delete rough idea cache: {error}")

    return {
        "api_keys_deleted": bool(delete_api_keys),
        "history_entries_deleted": history_deleted,
        "prompts_removed": removed_prompts,
        "baseline_prompts": restored_prompts,
        "errors": errors,
    }
