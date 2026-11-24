import requests

from promptwriter.config import (
    GEMINI_EXCLUDED_MODEL_TERMS,
    GROQ_EXCLUDED_MODEL_TERMS,
)
from promptwriter.storage.config_store import get_lm_studio_base_url


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
        output_modalities = item.get("output_modalities")
        if isinstance(output_modalities, list) and output_modalities:
            if "text" not in {str(mode).lower() for mode in output_modalities}:
                continue
        input_modalities = item.get("input_modalities")
        if isinstance(input_modalities, list) and input_modalities:
            supported_inputs = {str(mode).lower() for mode in input_modalities}
            if "text" not in supported_inputs and "image" not in supported_inputs:
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


def fetch_provider_models(engine, api_key, base_url=None):
    """Return (models, fallback_message); raises on provider errors."""
    if engine == "Gemini":
        from google import genai

        client = genai.Client(api_key=api_key)
        models = filter_gemini_models(client.models.list())
        if not models:
            return (
                [],
                "No standard text-generation Gemini models were returned.",
            )
        return sorted(set(model for model in models if model)), None

    if engine == "Groq":
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
        if not models:
            raise ValueError(f"{engine} returned no available models.")
        return models, None

    response = requests.get(
        f"{(base_url or get_lm_studio_base_url()).rstrip('/')}/v1/models",
        timeout=5,
    )
    response.raise_for_status()
    response_data = response.json()
    if not isinstance(response_data, dict):
        raise ValueError("LM Studio returned an invalid models response.")
    model_data = response_data.get("data")
    if not isinstance(model_data, list):
        raise ValueError("LM Studio returned an invalid models response.")
    models = filter_local_models(model_data)
    if not models:
        raise ValueError("LM Studio returned no available models.")
    return models, None
