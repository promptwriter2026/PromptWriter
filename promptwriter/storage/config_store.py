import json

from promptwriter.config import (
    CONFIG_PATH,
    DEFAULT_CONFIG,
    DEFAULT_LM_STUDIO_BASE_URL,
)
from promptwriter.storage.app_files import read_json, write_json


def load_config():
    return read_json(CONFIG_PATH, DEFAULT_CONFIG)


def save_config(config_data):
    write_json(CONFIG_PATH, config_data)


def get_lm_studio_base_url(config_data=None):
    if config_data is None:
        try:
            config_data = load_config()
        except (OSError, ValueError, json.JSONDecodeError):
            config_data = {}
    base_url = (
        config_data.get("lm_studio_base_url")
        if isinstance(config_data, dict)
        else None
    )
    if not isinstance(base_url, str) or not base_url.strip():
        return DEFAULT_LM_STUDIO_BASE_URL
    base_url = base_url.strip().rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3].rstrip("/")
    return base_url or DEFAULT_LM_STUDIO_BASE_URL
