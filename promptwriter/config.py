from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
SYSTEM_PROMPTS_DIR = APP_DIR / "system_prompts"
VISION_SYSTEM_PROMPTS_DIR = APP_DIR / "system_prompts_vision"
CONFIG_PATH = APP_DIR / "config.json"
ROUGH_IDEA_CACHE_PATH = APP_DIR / "rough_idea_cache.txt"
CAMERAS_PATH = DATA_DIR / "cameras.json"
LORA_PROFILES_PATH = DATA_DIR / "lora_profiles.json"
MODEL_PROFILES_PATH = DATA_DIR / "model_profiles.json"
HISTORY_DB_PATH = DATA_DIR / "history.db"
BOOTSTRAP_PROMPT_PATH = APP_DIR / "defaults" / "Flux-2-Klein.txt"
VISION_BOOTSTRAP_PROMPT_PATH = APP_DIR / "defaults" / "Vision-Default.txt"


DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
LOCAL_ENGINE = "Local (LM Studio)"
LLM_ENGINES = ("Gemini", "Groq", LOCAL_ENGINE)
DEFAULT_LM_STUDIO_BASE_URL = "http://127.0.0.1:1234"
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
    "lm_studio_base_url": DEFAULT_LM_STUDIO_BASE_URL,
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
    MODEL_PROFILES_PATH: {},
}


def model_cache_key(engine):
    normalized_engine = (
        engine.lower().replace(" (", "_").replace(")", "").replace(" ", "_")
    )
    return f"cached_models_{normalized_engine}"
