import requests

from promptwriter.config import LOCAL_SERVER_ROOT_URL


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
