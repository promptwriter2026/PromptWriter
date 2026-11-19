import json

from promptwriter.config import LOCAL_ENGINE, MODEL_PROFILES_PATH
from promptwriter.storage.app_files import read_json, write_json

PROFILE_MODES = ("text", "vision")
LOCAL_ONLY_FIELDS = ("min_p", "repeat_penalty", "context_length")
PROFILE_FIELDS = (
    "temperature",
    "top_p",
    "min_p",
    "repeat_penalty",
    "max_tokens",
    "context_length",
    "disable_thinking",
)
CONTEXT_LENGTH_CHOICES = (None, 4096, 8192, 16384, 32768)
DEFAULT_MAX_TOKENS = {"Groq": 6500, LOCAL_ENGINE: 2048}


def default_profile(engine, mode):
    if mode not in PROFILE_MODES:
        raise ValueError(f"Unsupported profile mode: {mode}")
    return {
        "temperature": 0.1 if mode == "vision" else 0.7,
        "top_p": 0.2 if mode == "vision" else 0.95,
        "min_p": None,
        "repeat_penalty": None,
        "max_tokens": DEFAULT_MAX_TOKENS.get(engine),
        "context_length": None,
        "disable_thinking": False,
    }


def _number(value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def merge_profile(saved, engine, mode):
    profile = default_profile(engine, mode)
    if not isinstance(saved, dict):
        return profile

    temperature = _number(saved.get("temperature"), 0.0, 2.0)
    if temperature is not None:
        profile["temperature"] = temperature
    top_p = _number(saved.get("top_p"), 0.0, 1.0)
    if top_p is not None:
        profile["top_p"] = top_p
    min_p = _number(saved.get("min_p"), 0.0, 1.0)
    if min_p is not None:
        profile["min_p"] = min_p
    repeat_penalty = _number(saved.get("repeat_penalty"), 0.0, 3.0)
    if repeat_penalty is not None and repeat_penalty > 0:
        profile["repeat_penalty"] = repeat_penalty
    max_tokens = _positive_int(saved.get("max_tokens"))
    if max_tokens is not None:
        profile["max_tokens"] = max_tokens
    context_length = _positive_int(saved.get("context_length"))
    if context_length is not None:
        profile["context_length"] = context_length
    if isinstance(saved.get("disable_thinking"), bool):
        profile["disable_thinking"] = saved["disable_thinking"]
    return profile


def _validate_key(engine, model_id, mode):
    if not isinstance(engine, str) or not engine.strip():
        raise ValueError("An engine is required for a model profile.")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("A model is required for a model profile.")
    if mode not in PROFILE_MODES:
        raise ValueError(f"Unsupported profile mode: {mode}")
    return engine.strip(), model_id.strip()


def load_profiles():
    try:
        profiles = read_json(MODEL_PROFILES_PATH, {})
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return profiles if isinstance(profiles, dict) else {}


def save_profiles(profiles):
    write_json(MODEL_PROFILES_PATH, profiles)


def get_saved_profile(engine, model_id, mode):
    engine, model_id = _validate_key(engine, model_id, mode)[:2]
    engine_profiles = load_profiles().get(engine)
    if not isinstance(engine_profiles, dict):
        return None
    model_profiles = engine_profiles.get(model_id)
    if not isinstance(model_profiles, dict):
        return None
    saved = model_profiles.get(mode)
    return saved if isinstance(saved, dict) else None


def get_profile(engine, model_id, mode):
    return merge_profile(get_saved_profile(engine, model_id, mode), engine, mode)


def save_profile(engine, model_id, mode, values):
    engine, model_id = _validate_key(engine, model_id, mode)[:2]
    profile = merge_profile(values, engine, mode)
    profiles = load_profiles()
    engine_profiles = profiles.setdefault(engine, {})
    if not isinstance(engine_profiles, dict):
        engine_profiles = {}
        profiles[engine] = engine_profiles
    model_profiles = engine_profiles.setdefault(model_id, {})
    if not isinstance(model_profiles, dict):
        model_profiles = {}
        engine_profiles[model_id] = model_profiles
    model_profiles[mode] = profile
    save_profiles(profiles)
    return profile


def delete_profile(engine, model_id, mode):
    engine, model_id = _validate_key(engine, model_id, mode)[:2]
    profiles = load_profiles()
    engine_profiles = profiles.get(engine)
    if not isinstance(engine_profiles, dict):
        return False
    model_profiles = engine_profiles.get(model_id)
    if not isinstance(model_profiles, dict) or mode not in model_profiles:
        return False
    del model_profiles[mode]
    if not model_profiles:
        del engine_profiles[model_id]
    if not engine_profiles:
        del profiles[engine]
    save_profiles(profiles)
    return True


def list_profiles():
    entries = []
    for engine, engine_profiles in load_profiles().items():
        if not isinstance(engine, str) or not isinstance(engine_profiles, dict):
            continue
        for model_id, model_profiles in engine_profiles.items():
            if not isinstance(model_id, str) or not isinstance(model_profiles, dict):
                continue
            for mode, saved in model_profiles.items():
                if mode not in PROFILE_MODES or not isinstance(saved, dict):
                    continue
                entries.append(
                    {
                        "engine": engine,
                        "model_id": model_id,
                        "mode": mode,
                        "profile": merge_profile(saved, engine, mode),
                    }
                )
    return sorted(
        entries,
        key=lambda entry: (entry["engine"], entry["model_id"], entry["mode"]),
    )


def profile_request_kwargs(engine, profile):
    kwargs = {
        "temperature": profile.get("temperature"),
        "top_p": profile.get("top_p"),
        "max_tokens": profile.get("max_tokens"),
    }
    if engine == LOCAL_ENGINE:
        kwargs["min_p"] = profile.get("min_p")
        kwargs["repeat_penalty"] = profile.get("repeat_penalty")
        kwargs["disable_thinking"] = bool(profile.get("disable_thinking"))
    return kwargs


def profile_context_length(engine, profile):
    """Return the explicit Local context length, or None for Auto/cloud."""
    if engine != LOCAL_ENGINE:
        return None
    context_length = profile.get("context_length")
    if isinstance(context_length, int) and context_length > 0:
        return context_length
    return None


def format_profile_summary(engine, profile, has_saved, temperature=None):
    if not has_saved:
        return "Default profile"
    temperature = (
        profile.get("temperature") if temperature is None else temperature
    )
    parts = [f"Temp: {float(temperature):.2f}"]
    if engine == LOCAL_ENGINE:
        context_length = profile.get("context_length")
        parts.append(
            "Ctx: Auto" if context_length is None else f"Ctx: {context_length}"
        )
    max_tokens = profile.get("max_tokens")
    if max_tokens is not None:
        parts.append(f"Max: {max_tokens}")
    top_p = profile.get("top_p")
    if top_p is not None:
        parts.append(f"Top-P: {top_p:g}")
    if engine == LOCAL_ENGINE:
        min_p = profile.get("min_p")
        if min_p is not None:
            parts.append(f"Min-P: {min_p:g}")
        repeat_penalty = profile.get("repeat_penalty")
        if repeat_penalty is not None:
            parts.append(f"Repeat: {repeat_penalty:g}")
        if profile.get("disable_thinking"):
            parts.append("No-Think")
    return " · ".join(parts)
