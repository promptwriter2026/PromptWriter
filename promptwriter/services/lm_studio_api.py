import requests

from promptwriter.storage.config_store import get_lm_studio_base_url


def _base_url(base_url=None):
    return (base_url or get_lm_studio_base_url()).rstrip("/")


def get_lm_studio_loaded_models(base_url=None, timeout=5):
    response = requests.get(
        f"{_base_url(base_url)}/api/v1/models", timeout=timeout
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


def _unload_model_instances(instances, base_url=None):
    for instance in instances:
        instance_id = instance.get("id") if isinstance(instance, dict) else None
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("LM Studio returned an invalid loaded model instance.")
        response = requests.post(
            f"{_base_url(base_url)}/api/v1/models/unload",
            json={"instance_id": instance_id},
            timeout=30,
        )
        response.raise_for_status()


def ensure_model_loaded(model_key, context_length=None, base_url=None):
    """Free other loaded models, then prepare the target model.

    Other models' instances are always unloaded. The target is loaded or
    reloaded only when an explicit context length is required; with Auto the
    target is reused if present or left for JIT loading.

    Returns True when a target load request was sent.
    """
    if not isinstance(model_key, str) or not model_key.strip():
        raise ValueError("A model key is required to check an LM Studio model.")
    model_key = model_key.strip()

    response = requests.get(f"{_base_url(base_url)}/api/v1/models", timeout=5)
    response.raise_for_status()
    response_data = response.json()
    if not isinstance(response_data, dict) or not isinstance(
        response_data.get("models"), list
    ):
        raise ValueError("LM Studio returned an invalid models response.")

    model = None
    for entry in response_data["models"]:
        if not isinstance(entry, dict):
            continue
        if model_key in {entry.get("key"), entry.get("display_name")}:
            model = entry
            break
    if model is None:
        raise ValueError(f"LM Studio does not list the model '{model_key}'.")

    instances = model.get("loaded_instances")
    if not isinstance(instances, list):
        raise ValueError("LM Studio returned invalid loaded model instances.")
    load_key = model.get("key") or model_key

    for entry in response_data["models"]:
        if entry is model or not isinstance(entry, dict):
            continue
        other_instances = entry.get("loaded_instances", [])
        if not isinstance(other_instances, list):
            raise ValueError("LM Studio returned invalid loaded model instances.")
        if other_instances:
            _unload_model_instances(other_instances, base_url=base_url)

    if not instances:
        if context_length is None:
            return False
        load_model(load_key, context_length=context_length, base_url=base_url)
        return True

    if context_length is None:
        return False

    requested_context_length = int(context_length)
    for instance in instances:
        config = instance.get("config") if isinstance(instance, dict) else None
        active_context_length = (
            config.get("context_length") if isinstance(config, dict) else None
        )
        if active_context_length == requested_context_length:
            return False

    _unload_model_instances(instances, base_url=base_url)
    load_model(
        load_key,
        context_length=requested_context_length,
        base_url=base_url,
    )
    return True


def load_model(model_key, context_length=None, base_url=None, timeout=120):
    if not isinstance(model_key, str) or not model_key.strip():
        raise ValueError("A model key is required to load an LM Studio model.")

    payload = {"model": model_key.strip()}
    if context_length is not None:
        payload["context_length"] = int(context_length)

    response = requests.post(
        f"{_base_url(base_url)}/api/v1/models/load",
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    response_data = response.json()
    if not isinstance(response_data, dict):
        raise ValueError("LM Studio returned an invalid model load response.")
    return response_data


def unload_lm_studio_models(base_url=None):
    loaded_models = get_lm_studio_loaded_models(base_url=base_url)
    for _, instance_id in loaded_models:
        response = requests.post(
            f"{_base_url(base_url)}/api/v1/models/unload",
            json={"instance_id": instance_id},
            timeout=30,
        )
        response.raise_for_status()
    return loaded_models
