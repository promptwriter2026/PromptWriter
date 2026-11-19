import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from promptwriter.config import LOCAL_ENGINE
from promptwriter.services import llm_client, lm_studio_api, model_catalog
from promptwriter.services.prompt_builder import (
    VISION_DEFAULT_USER_PROMPT,
    assemble_image_request,
    assemble_text_request,
)
from promptwriter.utils.text import strip_think_tags


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.content = json.dumps(payload).encode("utf-8") if payload is not None else b""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


def chat_response(content, reasoning_content=None):
    message = {"role": "assistant", "content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    return FakeResponse({"choices": [{"message": message}]})


class PromptAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.prompt_path = Path(self.temp_dir.name) / "Model.txt"
        self.prompt_path.write_text("SYSTEM RULES", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_text_assembly_separates_system_and_user(self):
        parts = assemble_text_request(
            self.prompt_path, "None", [], "50mm lens", "a cat in space"
        )
        self.assertIn("SYSTEM RULES", parts["system"])
        self.assertIn("50mm lens", parts["system"])
        self.assertNotIn("a cat in space", parts["system"])
        self.assertEqual(parts["user"], "User's rough idea:\na cat in space")

    def test_vision_assembly_separates_system_and_user(self):
        parts = assemble_image_request(self.prompt_path, "None", [], "make it cinematic")
        self.assertEqual(parts["system"], "SYSTEM RULES")
        self.assertEqual(
            parts["user"], "Additional context and instructions:\nmake it cinematic"
        )

    def test_vision_assembly_defaults_user_prompt_when_context_empty(self):
        parts = assemble_image_request(self.prompt_path, "None", [], "")
        self.assertEqual(parts["user"], VISION_DEFAULT_USER_PROMPT)


class PayloadTests(unittest.TestCase):
    def _capture(self, engine, response, **kwargs):
        with patch.object(
            llm_client.requests, "post", return_value=response
        ) as post:
            result = llm_client.request_generated_prompt(
                engine, "key", "model", **kwargs
            )
        return result, post

    def test_local_text_payload_uses_system_and_user_roles(self):
        _, post = self._capture(
            LOCAL_ENGINE,
            chat_response("a prompt"),
            request_text={"system": "SYS", "user": "USER"},
            temperature=0.9,
            cache_prompt=True,
            base_url="http://127.0.0.1:1234",
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(
            payload["messages"],
            [
                {"role": "system", "content": "SYS"},
                {"role": "user", "content": "USER"},
            ],
        )
        self.assertEqual(payload["cache_prompt"], True)
        self.assertEqual(payload["max_tokens"], 2048)
        self.assertEqual(payload["top_p"], 0.95)
        self.assertNotIn("min_p", payload)
        self.assertNotIn("repeat_penalty", payload)
        self.assertEqual(
            post.call_args.args[0], "http://127.0.0.1:1234/v1/chat/completions"
        )

    def test_local_vision_payload_keeps_image_in_user_message(self):
        _, post = self._capture(
            LOCAL_ENGINE,
            chat_response("a prompt"),
            request_text={"system": "SYS", "user": "Describe this"},
            image_base64="abc123",
            cache_prompt=False,
            base_url="http://127.0.0.1:1234",
        )
        messages = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(messages[0], {"role": "system", "content": "SYS"})
        self.assertEqual(messages[1]["role"], "user")
        content = messages[1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "Describe this"})
        self.assertEqual(
            content[1],
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64,abc123"},
            },
        )
        self.assertEqual(post.call_args.kwargs["json"]["top_p"], 0.2)

    def test_groq_never_receives_local_only_fields(self):
        _, post = self._capture(
            "Groq",
            chat_response("a prompt"),
            request_text={"system": "SYS", "user": "USER"},
            cache_prompt=True,
            min_p=0.05,
            repeat_penalty=1.1,
        )
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("cache_prompt", payload)
        self.assertNotIn("min_p", payload)
        self.assertNotIn("repeat_penalty", payload)
        self.assertEqual(payload["max_tokens"], 6500)
        self.assertEqual(payload["top_p"], 0.95)

    def test_local_only_fields_are_included_when_explicitly_provided(self):
        _, post = self._capture(
            LOCAL_ENGINE,
            chat_response("a prompt"),
            request_text={"system": "SYS", "user": "USER"},
            cache_prompt=False,
            min_p=0.05,
            repeat_penalty=1.1,
            top_p=0.5,
            max_tokens=512,
            base_url="http://127.0.0.1:1234",
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["cache_prompt"], False)
        self.assertEqual(payload["min_p"], 0.05)
        self.assertEqual(payload["repeat_penalty"], 1.1)
        self.assertEqual(payload["top_p"], 0.5)
        self.assertEqual(payload["max_tokens"], 512)

    def test_gemini_uses_system_instruction(self):
        response = FakeResponse(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "a prompt"}]}}
                ]
            }
        )
        _, post = self._capture(
            "Gemini",
            response,
            request_text={"system": "SYS", "user": "USER"},
            image_base64="abc123",
            temperature=0.4,
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(
            payload["system_instruction"], {"parts": [{"text": "SYS"}]}
        )
        self.assertEqual(payload["contents"][0]["parts"][0], {"text": "USER"})
        self.assertEqual(
            payload["contents"][0]["parts"][1],
            {"inline_data": {"mime_type": "image/jpeg", "data": "abc123"}},
        )
        self.assertEqual(payload["generationConfig"], {"temperature": 0.4})
        self.assertNotIn("messages", payload)

    def test_plain_string_request_text_still_works(self):
        _, post = self._capture(
            LOCAL_ENGINE,
            chat_response("a prompt"),
            request_text="legacy request",
            base_url="http://127.0.0.1:1234",
        )
        messages = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(messages, [{"role": "user", "content": "legacy request"}])


class ReasoningCleanupTests(unittest.TestCase):
    def test_strip_think_tag_variants(self):
        cases = {
            "<think>reasoning</think>final": "final",
            "<THINK>reasoning</THINK>final": "final",
            "<thinking>reasoning</thinking>final": "final",
            "<Thinking>reasoning</Thinking>final": "final",
            "<|think|>reasoning<|/think|>final": "final",
            "<think>a</think> <think>b</think>final": "final",
            "<think>unfinished reasoning": "",
            "final<think>unfinished reasoning": "final",
            "<|think|>unfinished reasoning": "",
            "final prompt": "final prompt",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(strip_think_tags(raw), expected)

    def test_client_strips_reasoning_before_returning(self):
        response = chat_response("<think>reasoning</think>final prompt")
        with patch.object(llm_client.requests, "post", return_value=response):
            result = llm_client.request_generated_prompt(
                LOCAL_ENGINE,
                "key",
                "model",
                "USER",
                base_url="http://127.0.0.1:1234",
            )
        self.assertEqual(result, "final prompt")

    def test_unclosed_reasoning_reports_clear_error(self):
        response = chat_response("<think>I am still thinking")
        with patch.object(llm_client.requests, "post", return_value=response):
            with self.assertRaisesRegex(ValueError, "only reasoning text"):
                llm_client.request_generated_prompt(
                    LOCAL_ENGINE,
                    "key",
                    "model",
                    "USER",
                    base_url="http://127.0.0.1:1234",
                )

    def test_empty_content_with_reasoning_content_reports_budget_error(self):
        for content in ("", None, "   "):
            response = chat_response(content, reasoning_content="deep thoughts")
            with self.subTest(content=content):
                with patch.object(
                    llm_client.requests, "post", return_value=response
                ):
                    with self.assertRaisesRegex(
                        ValueError, "Increase max_tokens"
                    ):
                        llm_client.request_generated_prompt(
                            LOCAL_ENGINE,
                            "key",
                            "model",
                            "USER",
                            base_url="http://127.0.0.1:1234",
                        )

    def test_reasoning_content_is_ignored_when_content_present(self):
        response = chat_response(
            "final prompt", reasoning_content="hidden reasoning"
        )
        with patch.object(llm_client.requests, "post", return_value=response):
            result = llm_client.request_generated_prompt(
                LOCAL_ENGINE,
                "key",
                "model",
                "USER",
                base_url="http://127.0.0.1:1234",
            )
        self.assertEqual(result, "final prompt")


class ProviderErrorMessageTests(unittest.TestCase):
    def test_empty_choices_reports_active_engine(self):
        for engine in (LOCAL_ENGINE, "Groq"):
            response = FakeResponse({"choices": []})
            with self.subTest(engine=engine):
                with patch.object(
                    llm_client.requests, "post", return_value=response
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        re.escape(
                            f"{engine} returned no chat completion choices"
                        ),
                    ):
                        llm_client.request_generated_prompt(
                            engine,
                            "key",
                            "model",
                            "USER",
                            base_url="http://127.0.0.1:1234",
                        )

    def test_numeric_output_is_rejected(self):
        response = chat_response("42")
        with patch.object(llm_client.requests, "post", return_value=response):
            with self.assertRaisesRegex(ValueError, "numeric content"):
                llm_client.request_generated_prompt(
                    LOCAL_ENGINE,
                    "key",
                    "model",
                    "USER",
                    base_url="http://127.0.0.1:1234",
                )


class LmStudioApiTests(unittest.TestCase):
    def test_load_model_posts_native_payload(self):
        with patch.object(
            lm_studio_api.requests, "post", return_value=FakeResponse({"id": "x"})
        ) as post:
            result = lm_studio_api.load_model(
                "model@q4", context_length=8192, base_url="http://host:1234"
            )
        self.assertEqual(result, {"id": "x"})
        self.assertEqual(
            post.call_args.args[0], "http://host:1234/api/v1/models/load"
        )
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"model_key": "model@q4", "context_length": 8192},
        )

    def test_load_model_omits_context_length_when_not_given(self):
        with patch.object(
            lm_studio_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            lm_studio_api.load_model("model", base_url="http://host:1234")
        self.assertEqual(post.call_args.kwargs["json"], {"model_key": "model"})

    def test_load_model_requires_model_key(self):
        for model_key in ("", "   ", None):
            with self.subTest(model_key=model_key):
                with self.assertRaises(ValueError):
                    lm_studio_api.load_model(model_key)

    def test_load_model_raises_on_http_error(self):
        with patch.object(
            lm_studio_api.requests,
            "post",
            return_value=FakeResponse({"error": "bad"}, status_code=400),
        ):
            with self.assertRaises(requests.exceptions.HTTPError):
                lm_studio_api.load_model("model", base_url="http://host:1234")


class BaseUrlConfigTests(unittest.TestCase):
    def test_default_base_url(self):
        from promptwriter.storage import config_store

        with patch.object(config_store, "load_config", return_value={}):
            self.assertEqual(
                config_store.get_lm_studio_base_url(), "http://127.0.0.1:1234"
            )

    def test_custom_base_url_is_normalized(self):
        from promptwriter.storage import config_store

        config = {"lm_studio_base_url": " http://192.168.1.5:5555/v1/ "}
        with patch.object(config_store, "load_config", return_value=config):
            self.assertEqual(
                config_store.get_lm_studio_base_url(), "http://192.168.1.5:5555"
            )

    def test_model_catalog_listing_uses_configured_base_url(self):
        response = FakeResponse({"data": [{"id": "local-model"}]})
        with patch.object(model_catalog.requests, "get", return_value=response) as get:
            models, fallback = model_catalog.fetch_provider_models(
                LOCAL_ENGINE, "", base_url="http://host:9999"
            )
        self.assertEqual(models, ["local-model"])
        self.assertIsNone(fallback)
        self.assertEqual(get.call_args.args[0], "http://host:9999/v1/models")


GROQ_MODELS_RESPONSE = {
    "data": [
        {
            "id": "qwen/qwen3.8-27b",
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        },
        {
            "id": "whisper-large-v3",
            "input_modalities": ["audio"],
            "output_modalities": ["transcription"],
        },
        {
            "id": "canopylabs/orpheus-v1-english",
            "input_modalities": ["text"],
            "output_modalities": ["speech"],
        },
        {
            "id": "openai/gpt-oss-20b",
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        {
            "id": "meta-llama/llama-prompt-guard-2-22m",
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        {
            "id": "allam-2-7b",
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        {
            "id": "openai/gpt-oss-safeguard-20b",
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        {
            "id": "openai/gpt-oss-120b",
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
    ]
}

EXPECTED_GROQ_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "allam-2-7b",
    "openai/gpt-oss-120b",
]


class GroqModelFetchTests(unittest.TestCase):
    def test_filter_keeps_chat_and_vision_models(self):
        self.assertEqual(
            model_catalog.filter_groq_models(GROQ_MODELS_RESPONSE["data"]),
            EXPECTED_GROQ_MODELS,
        )

    def test_filter_excludes_non_chat_modalities_without_blacklist_terms(self):
        model_data = [
            {
                "id": "vendor/audio-model",
                "input_modalities": ["audio"],
                "output_modalities": ["transcription"],
            },
            {
                "id": "vendor/speech-model",
                "input_modalities": ["text"],
                "output_modalities": ["speech"],
            },
            {
                "id": "vendor/chat-model",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
        ]
        self.assertEqual(
            model_catalog.filter_groq_models(model_data), ["vendor/chat-model"]
        )

    def test_filter_keeps_models_without_modality_fields_and_dedupes(self):
        model_data = [
            {"id": "legacy-model"},
            {"id": "legacy-model"},
            {"id": "new-model", "input_modalities": ["text"]},
            "not-a-dict",
            {"id": 123},
        ]
        self.assertEqual(
            model_catalog.filter_groq_models(model_data),
            ["legacy-model", "new-model"],
        )

    def test_fetch_provider_models_returns_filtered_groq_models(self):
        response = FakeResponse(GROQ_MODELS_RESPONSE)
        with patch.object(model_catalog.requests, "get", return_value=response) as get:
            models, fallback = model_catalog.fetch_provider_models(
                "Groq", "secret-key"
            )
        self.assertEqual(models, EXPECTED_GROQ_MODELS)
        self.assertIsNone(fallback)
        self.assertEqual(get.call_args.args[0], "https://api.groq.com/openai/v1/models")
        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"], "Bearer secret-key"
        )
        self.assertNotIn("secret-key", get.call_args.args[0])

    def test_fetch_provider_models_raises_when_groq_returns_only_non_chat(self):
        response = FakeResponse(
            {
                "data": [
                    {
                        "id": "whisper-large-v3",
                        "input_modalities": ["audio"],
                        "output_modalities": ["transcription"],
                    }
                ]
            }
        )
        with patch.object(model_catalog.requests, "get", return_value=response):
            with self.assertRaisesRegex(
                ValueError, "Groq returned no available models"
            ):
                model_catalog.fetch_provider_models("Groq", "secret-key")


if __name__ == "__main__":
    unittest.main()
