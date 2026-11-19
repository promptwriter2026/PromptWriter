import requests

from promptwriter.storage.config_store import (
    get_comfyui_base_url,
    get_forge_base_url,
)


VRAM_CLEANUP_TIMEOUT = 1.5
VRAM_PREFLIGHT_THRESHOLD = 75.0
COMFYUI_BACKEND_NAME = "ComfyUI"
FORGE_BACKEND_NAME = "Forge Neo"


def _normalized_base_url(base_url):
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("A backend URL is required to free VRAM.")
    return base_url.strip().rstrip("/")


def free_comfyui_vram(base_url, timeout=VRAM_CLEANUP_TIMEOUT):
    response = requests.post(
        f"{_normalized_base_url(base_url)}/free",
        json={"unload_models": True, "free_memory": True},
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def free_forge_vram(base_url, timeout=VRAM_CLEANUP_TIMEOUT):
    response = requests.post(
        f"{_normalized_base_url(base_url)}/sdapi/v1/unload-checkpoint",
        json={},
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def free_external_vram(
    comfyui_url, forge_url, timeout=VRAM_CLEANUP_TIMEOUT
):
    """Ask ComfyUI and Forge Neo to release VRAM, skipping unavailable backends."""
    freed = []
    for name, base_url, free_func in (
        (COMFYUI_BACKEND_NAME, comfyui_url, free_comfyui_vram),
        (FORGE_BACKEND_NAME, forge_url, free_forge_vram),
    ):
        if not isinstance(base_url, str) or not base_url.strip():
            continue
        try:
            free_func(base_url, timeout=timeout)
        except (requests.exceptions.RequestException, ValueError):
            continue
        freed.append(name)
    return freed


def free_external_vram_from_config(timeout=VRAM_CLEANUP_TIMEOUT):
    return free_external_vram(
        get_comfyui_base_url(), get_forge_base_url(), timeout=timeout
    )


def should_prompt_vram_unload(memory, loaded_models):
    """Prompt only when VRAM is high and LM Studio has no loaded model."""
    if not isinstance(memory, dict):
        return False
    percent = memory.get("percent")
    if not isinstance(percent, (int, float)) or isinstance(percent, bool):
        return False
    if percent <= VRAM_PREFLIGHT_THRESHOLD:
        return False
    if not isinstance(loaded_models, (list, tuple)):
        return False
    return len(loaded_models) == 0
