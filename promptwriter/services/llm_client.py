import re
from urllib.parse import quote

import requests

from promptwriter.config import LOCAL_ENGINE
from promptwriter.storage.config_store import get_lm_studio_base_url
from promptwriter.utils.text import strip_think_tags

DEFAULT_TEXT_TOP_P = 0.95
DEFAULT_VISION_TOP_P = 0.2
DEFAULT_GROQ_MAX_TOKENS = 6500
DEFAULT_LOCAL_MAX_TOKENS = 2048
MAX_PRESENCE_PENALTY = 2.0


def _presence_penalty_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    penalty = float(value)
    if not 0.0 < penalty <= MAX_PRESENCE_PENALTY:
        return None
    return penalty


def _split_request_text(request_text, system_prompt):
    if isinstance(request_text, dict):
        system = request_text.get("system", system_prompt)
        user_text = request_text.get("user", "")
    else:
        system = system_prompt
        user_text = request_text
    if not isinstance(system, str):
        system = ""
    if not isinstance(user_text, str):
        raise ValueError("The user prompt must be text.")
    return system.strip(), user_text.strip()


def _build_user_content(user_text, image_base64):
    if not image_base64:
        return user_text
    return [
        {"type": "text", "text": user_text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
        },
    ]


def _build_chat_messages(system_prompt, user_text, image_base64):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append(
        {"role": "user", "content": _build_user_content(user_text, image_base64)}
    )
    return messages


def request_generated_prompt(
    engine,
    api_key,
    api_model,
    request_text,
    image_base64=None,
    include_quota=False,
    temperature=0.7,
    system_prompt=None,
    top_p=None,
    presence_penalty=None,
    min_p=None,
    repeat_penalty=None,
    max_tokens=None,
    disable_thinking=False,
    base_url=None,
):
    system_text, user_text = _split_request_text(request_text, system_prompt)
    default_top_p = DEFAULT_VISION_TOP_P if image_base64 else DEFAULT_TEXT_TOP_P

    if engine == "Gemini":
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(api_model, safe='')}:generateContent"
        )
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        parts = [{"text": user_text}]
        if image_base64:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": image_base64,
                    }
                }
            )
        generation_config = {"temperature": float(temperature)}
        if top_p is not None:
            generation_config["topP"] = float(top_p)
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = int(max_tokens)
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": generation_config,
        }
        if system_text:
            payload["system_instruction"] = {"parts": [{"text": system_text}]}
    elif engine == "Groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": api_model,
            "messages": _build_chat_messages(
                system_text, user_text, image_base64
            ),
            "temperature": float(temperature),
            "top_p": float(default_top_p if top_p is None else top_p),
            "max_tokens": int(
                DEFAULT_GROQ_MAX_TOKENS if max_tokens is None else max_tokens
            ),
        }
        presence = _presence_penalty_value(presence_penalty)
        if presence is not None:
            payload["presence_penalty"] = presence
    elif engine == LOCAL_ENGINE:
        lm_base_url = (base_url or get_lm_studio_base_url()).rstrip("/")
        url = f"{lm_base_url}/v1/chat/completions"
        headers = {
            "Authorization": "Bearer local-key",
            "Content-Type": "application/json",
        }
        payload = {
            "model": api_model,
            "messages": _build_chat_messages(
                system_text, user_text, image_base64
            ),
            "temperature": float(temperature),
            "top_p": float(default_top_p if top_p is None else top_p),
            "max_tokens": int(
                DEFAULT_LOCAL_MAX_TOKENS if max_tokens is None else max_tokens
            ),
        }
        presence = _presence_penalty_value(presence_penalty)
        if presence is not None:
            payload["presence_penalty"] = presence
        if disable_thinking:
            # LM Studio rejects "off"; "none" is its supported disable value.
            payload["reasoning_effort"] = "none"
        if min_p is not None:
            payload["min_p"] = float(min_p)
        if repeat_penalty is not None:
            payload["repeat_penalty"] = float(repeat_penalty)
    else:
        raise ValueError(f"Unsupported LLM engine: {engine}")

    timeout = 300 if engine == LOCAL_ENGINE else 60
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    quota = None
    if engine == "Groq":
        quota = (
            response.headers.get("x-ratelimit-remaining-tokens"),
            response.headers.get("x-ratelimit-limit-tokens"),
        )
    response_data = response.json()
    if not isinstance(response_data, dict):
        raise ValueError(f"{engine} returned an invalid response.")
    usage = response_data.get("usage", {})
    total_used = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0

    if engine == "Gemini":
        candidates = response_data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Gemini returned no generated candidates.")
        content = candidates[0].get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        generated_text = "\n".join(
            part["text"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ).strip()
        if not generated_text:
            raise ValueError("Gemini returned an empty response.")
    else:
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError(f"{engine} returned no chat completion choices.")
        message = choices[0].get("message", {})
        if not isinstance(message, dict):
            raise ValueError(f"{engine} returned an invalid chat message.")
        content = message.get("content")
        reasoning_content = message.get("reasoning_content")
        if content is None:
            content = ""
        if isinstance(content, list):
            content = "\n".join(
                part["text"]
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        if not isinstance(content, str):
            raise ValueError(f"{engine} returned a response without text content.")
        generated_text = content.strip()
        if not generated_text:
            if isinstance(reasoning_content, str) and reasoning_content.strip():
                raise ValueError(
                    f"{engine} used its entire output budget on reasoning and "
                    "returned no final answer. Increase max_tokens or disable the "
                    "model's thinking mode."
                )
            raise ValueError(f"{engine} returned an empty response.")

    generated_text = strip_think_tags(generated_text)
    if not generated_text:
        raise ValueError(
            f"{engine} returned only reasoning text without a final answer."
        )
    if re.fullmatch(
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
        generated_text,
    ):
        raise ValueError(
            f"{engine} returned numeric content instead of a generated prompt: "
            f"{generated_text}"
        )
    if include_quota:
        return generated_text, quota, total_used
    return generated_text
