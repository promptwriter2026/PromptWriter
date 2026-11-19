from promptwriter.config import CONFIG_PATH, DEFAULT_CONFIG
from promptwriter.storage.app_files import read_json, write_json


def load_config():
    return read_json(CONFIG_PATH, DEFAULT_CONFIG)


def save_config(config_data):
    write_json(CONFIG_PATH, config_data)
