import re
from urllib.parse import quote

import requests

from promptwriter.config import LOCAL_ENGINE, LOCAL_SERVER_URL


def request_generated_prompt(
    engine,
    api_key,
    api_model,
    request_text,
    image_base64=None,
    include_quota=False,
    temperature=0.7,
    cache_prompt=True,
):
    if engine == "Gemini":
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(api_model, safe='')}:generateContent"
        )
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        parts = [{"text": request_text}]
        if image_base64:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": image_base64,
                    }
                }
            )
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": float(temperature)},
        }
    elif engine == "Groq":
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        message_content = request_text
        if image_base64:
            message_content = [
                {"type": "text", "text": request_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    },
                },
            ]
        payload = {
            "model": api_model,
            "messages": [{"role": "user", "content": message_content}],
            "temperature": float(temperature),
            "top_p": 0.2 if image_base64 else 0.95,
            "max_tokens": 6500,
        }
    elif engine == LOCAL_ENGINE:
        url = f"{LOCAL_SERVER_URL}/chat/completions"
        headers = {
            "Authorization": "Bearer local-key",
            "Content-Type": "application/json",
        }
        message_content = request_text
        if image_base64:
            message_content = [
                {"type": "text", "text": request_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    },
                },
            ]
        payload = {
            "model": api_model,
            "messages": [{"role": "user", "content": message_content}],
            "temperature": float(temperature),
            "top_p": 0.2 if image_base64 else 0.95,
            "max_tokens": 2048,
        }
        payload["cache_prompt"] = cache_prompt
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
    else:
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError(f"{engine} returned no chat completion choices.")
        message = choices[0].get("message", {})
        generated_text = (
            message.get("content")
            if isinstance(message, dict)
            else None
        )
        if not isinstance(generated_text, str):
            raise ValueError("Groq returned a response without text content.")
        generated_text = generated_text.strip()

    if not generated_text:
        raise ValueError(f"{engine} returned an empty response.")
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
