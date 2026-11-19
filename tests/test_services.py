import inspect
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from promptwriter.config import LOCAL_ENGINE
from promptwriter.services import (
    llm_client,
    lm_studio_api,
    model_catalog,
    vram_cleanup_api,
    vram_monitor,
)
from promptwriter.storage import profile_store
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
        self.assertNotIn("cache_prompt", payload)
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
        self.assertNotIn("reasoning_effort", post.call_args.kwargs["json"])

    def test_groq_never_receives_local_only_fields(self):
        _, post = self._capture(
            "Groq",
            chat_response("a prompt"),
            request_text={"system": "SYS", "user": "USER"},
            min_p=0.05,
            repeat_penalty=1.1,
            disable_thinking=True,
        )
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("cache_prompt", payload)
        self.assertNotIn("min_p", payload)
        self.assertNotIn("repeat_penalty", payload)
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["messages"][1]["content"], "USER")
        self.assertEqual(payload["max_tokens"], 6500)
        self.assertEqual(payload["top_p"], 0.95)

    def test_local_only_fields_are_included_when_explicitly_provided(self):
        _, post = self._capture(
            LOCAL_ENGINE,
            chat_response("a prompt"),
            request_text={"system": "SYS", "user": "USER"},
            min_p=0.05,
            repeat_penalty=1.1,
            top_p=0.5,
            max_tokens=512,
            disable_thinking=True,
            base_url="http://127.0.0.1:1234",
        )
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("cache_prompt", payload)
        self.assertEqual(payload["min_p"], 0.05)
        self.assertEqual(payload["repeat_penalty"], 1.1)
        self.assertEqual(payload["top_p"], 0.5)
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["messages"][1]["content"], "USER")

    def test_local_payload_omits_reasoning_effort_when_thinking_enabled(self):
        _, post = self._capture(
            LOCAL_ENGINE,
            chat_response("a prompt"),
            request_text={"system": "SYS", "user": "USER"},
            disable_thinking=False,
            base_url="http://127.0.0.1:1234",
        )
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["messages"][1]["content"], "USER")

    def test_disable_thinking_sets_reasoning_effort_for_vision(self):
        _, post = self._capture(
            LOCAL_ENGINE,
            chat_response("a prompt"),
            request_text={"system": "SYS", "user": "Describe this"},
            image_base64="abc123",
            disable_thinking=True,
            base_url="http://127.0.0.1:1234",
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["reasoning_effort"], "none")
        content = payload["messages"][1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "Describe this"})
        self.assertEqual(content[1]["type"], "image_url")

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

    def test_strip_gemma_channel_thought_blocks(self):
        cases = {
            "<|channel>thought\nreasoning<channel|>final": "final",
            "<|CHANNEL>thought reasoning<CHANNEL|>final": "final",
            "<|channel>thought<channel|>A<|channel>thought\nB<channel|>": "A",
            "final<|channel>thought unclosed": "final",
            "<|channel>thought unclosed": "",
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
            {"model": "model@q4", "context_length": 8192},
        )

    def test_load_model_omits_context_length_when_not_given(self):
        with patch.object(
            lm_studio_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            lm_studio_api.load_model("model", base_url="http://host:1234")
        self.assertEqual(post.call_args.kwargs["json"], {"model": "model"})

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


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "model_profiles.json"
        self.path.write_text("{}", encoding="utf-8")
        self.path_patch = patch.object(
            profile_store, "MODEL_PROFILES_PATH", self.path
        )
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_engine_and_mode_defaults(self):
        gemini_text = profile_store.default_profile("Gemini", "text")
        self.assertEqual(gemini_text["temperature"], 0.7)
        self.assertEqual(gemini_text["top_p"], 0.95)
        self.assertIsNone(gemini_text["max_tokens"])
        vision_local = profile_store.default_profile(LOCAL_ENGINE, "vision")
        self.assertEqual(vision_local["temperature"], 0.1)
        self.assertEqual(vision_local["top_p"], 0.2)
        self.assertEqual(vision_local["max_tokens"], 2048)
        self.assertEqual(
            profile_store.default_profile("Groq", "text")["max_tokens"], 6500
        )
        self.assertFalse(vision_local["disable_thinking"])

    def test_save_get_keeps_mode_and_model_profiles_separate(self):
        saved = profile_store.save_profile(
            "Gemini",
            "gemini-test",
            "text",
            {"temperature": 0.3, "top_p": 0.9, "max_tokens": 1234},
        )
        self.assertEqual(saved["temperature"], 0.3)
        self.assertEqual(saved["top_p"], 0.9)
        self.assertEqual(saved["max_tokens"], 1234)
        self.assertEqual(
            profile_store.get_profile("Gemini", "gemini-test", "text")["temperature"],
            0.3,
        )
        self.assertEqual(
            profile_store.get_saved_profile("Gemini", "gemini-test", "text")[
                "top_p"
            ],
            0.9,
        )
        self.assertIsNone(
            profile_store.get_saved_profile("Gemini", "gemini-test", "vision")
        )

        profile_store.save_profile(
            "Gemini", "gemini-test", "vision", {"temperature": 0.2}
        )
        self.assertEqual(
            profile_store.get_profile("Gemini", "gemini-test", "vision")[
                "temperature"
            ],
            0.2,
        )
        self.assertEqual(
            profile_store.get_profile("Gemini", "gemini-test", "vision")["top_p"],
            0.2,
        )
        entries = profile_store.list_profiles()
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            {entry["mode"] for entry in entries}, {"text", "vision"}
        )

    def test_partial_profile_falls_back_to_defaults(self):
        profile_store.save_profile(
            "Groq", "qwen-test", "text", {"temperature": 1.1}
        )
        profile = profile_store.get_profile("Groq", "qwen-test", "text")
        self.assertEqual(profile["temperature"], 1.1)
        self.assertEqual(profile["top_p"], 0.95)
        self.assertEqual(profile["max_tokens"], 6500)

    def test_delete_profile_and_list(self):
        profile_store.save_profile(
            LOCAL_ENGINE, "model-a", "text", {"context_length": 8192}
        )
        self.assertEqual(len(profile_store.list_profiles()), 1)
        self.assertTrue(
            profile_store.delete_profile(LOCAL_ENGINE, "model-a", "text")
        )
        self.assertEqual(profile_store.list_profiles(), [])
        self.assertFalse(
            profile_store.delete_profile(LOCAL_ENGINE, "model-a", "text")
        )

    def test_profile_summary(self):
        default = profile_store.default_profile(LOCAL_ENGINE, "text")
        self.assertEqual(
            profile_store.format_profile_summary(
                LOCAL_ENGINE, default, False
            ),
            "Default profile",
        )
        saved = dict(default)
        saved.update(
            {
                "context_length": 8192,
                "max_tokens": 2048,
                "top_p": 0.95,
                "min_p": 0.05,
            }
        )
        summary = profile_store.format_profile_summary(
            LOCAL_ENGINE, saved, True, temperature=0.55
        )
        self.assertIn("Temp: 0.55", summary)
        self.assertIn("Ctx: 8192", summary)
        self.assertIn("Max: 2048", summary)
        self.assertIn("Top-P: 0.95", summary)
        self.assertIn("Min-P: 0.05", summary)
        self.assertTrue(summary.endswith("Think: On"))
        saved["disable_thinking"] = True
        summary = profile_store.format_profile_summary(
            LOCAL_ENGINE, saved, True, temperature=0.55
        )
        self.assertTrue(summary.endswith("Think: Off"))


class ProfileInjectionTests(unittest.TestCase):
    def _profile(self, engine, mode, **overrides):
        profile = profile_store.default_profile(engine, mode)
        profile.update(overrides)
        return profile

    def test_cache_prompt_is_removed_from_client_signature(self):
        signature = inspect.signature(llm_client.request_generated_prompt)
        self.assertNotIn("cache_prompt", signature.parameters)

    def test_local_profile_injects_all_sampling_fields(self):
        profile = self._profile(
            LOCAL_ENGINE,
            "text",
            temperature=0.8,
            top_p=0.5,
            min_p=0.05,
            repeat_penalty=1.1,
            max_tokens=1024,
            disable_thinking=True,
        )
        kwargs = profile_store.profile_request_kwargs(LOCAL_ENGINE, profile)
        with patch.object(
            llm_client.requests, "post", return_value=chat_response("a prompt")
        ) as post:
            llm_client.request_generated_prompt(
                LOCAL_ENGINE,
                "key",
                "local-model",
                "USER",
                base_url="http://127.0.0.1:1234",
                **kwargs,
            )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0.8)
        self.assertEqual(payload["top_p"], 0.5)
        self.assertEqual(payload["min_p"], 0.05)
        self.assertEqual(payload["repeat_penalty"], 1.1)
        self.assertEqual(payload["max_tokens"], 1024)
        self.assertNotIn("cache_prompt", payload)
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["messages"][-1]["content"], "USER")

    def test_groq_profile_omits_local_only_fields(self):
        profile = self._profile(
            "Groq",
            "text",
            temperature=0.6,
            top_p=0.7,
            max_tokens=700,
            min_p=0.05,
            repeat_penalty=1.2,
            disable_thinking=True,
        )
        kwargs = profile_store.profile_request_kwargs("Groq", profile)
        self.assertEqual(set(kwargs), {"temperature", "top_p", "max_tokens"})
        with patch.object(
            llm_client.requests, "post", return_value=chat_response("a prompt")
        ) as post:
            llm_client.request_generated_prompt(
                "Groq", "key", "groq-model", "USER", **kwargs
            )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0.6)
        self.assertEqual(payload["top_p"], 0.7)
        self.assertEqual(payload["max_tokens"], 700)
        self.assertNotIn("min_p", payload)
        self.assertNotIn("repeat_penalty", payload)
        self.assertNotIn("cache_prompt", payload)
        self.assertEqual(payload["messages"][-1]["content"], "USER")

    def test_profile_context_length_is_local_only(self):
        local = self._profile(LOCAL_ENGINE, "text", context_length=4096)
        self.assertEqual(
            profile_store.profile_context_length(LOCAL_ENGINE, local), 4096
        )
        auto = self._profile(LOCAL_ENGINE, "text")
        self.assertIsNone(
            profile_store.profile_context_length(LOCAL_ENGINE, auto)
        )
        self.assertIsNone(profile_store.profile_context_length("Groq", local))

    def test_gemini_profile_maps_top_p_and_max_tokens(self):
        profile = self._profile(
            "Gemini", "text", temperature=0.4, top_p=0.8, max_tokens=1024
        )
        kwargs = profile_store.profile_request_kwargs("Gemini", profile)
        response = FakeResponse(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "a prompt"}]}}
                ]
            }
        )
        with patch.object(
            llm_client.requests, "post", return_value=response
        ) as post:
            llm_client.request_generated_prompt(
                "Gemini", "key", "gemini-model", "USER", **kwargs
            )
        generation_config = post.call_args.kwargs["json"]["generationConfig"]
        self.assertEqual(generation_config["temperature"], 0.4)
        self.assertEqual(generation_config["topP"], 0.8)
        self.assertEqual(generation_config["maxOutputTokens"], 1024)


class EnsureModelLoadedTests(unittest.TestCase):
    def test_loads_model_when_context_length_is_set_and_model_is_unloaded(self):
        models = FakeResponse(
            {
                "models": [
                    {
                        "key": "local-model",
                        "display_name": "Local Model",
                        "loaded_instances": [],
                    }
                ]
            }
        )
        with patch.object(
            lm_studio_api.requests, "get", return_value=models
        ) as get, patch.object(
            lm_studio_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            loaded = lm_studio_api.ensure_model_loaded(
                "local-model", context_length=8192, base_url="http://host:1234"
            )
        self.assertTrue(loaded)
        self.assertEqual(get.call_args.args[0], "http://host:1234/api/v1/models")
        self.assertEqual(
            post.call_args.args[0], "http://host:1234/api/v1/models/load"
        )
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"model": "local-model", "context_length": 8192},
        )

    def test_skips_load_when_loaded_context_length_matches(self):
        models = FakeResponse(
            {
                "models": [
                    {
                        "key": "local-model",
                        "display_name": "Local Model",
                        "loaded_instances": [
                            {
                                "id": "instance-1",
                                "config": {"context_length": 8192},
                            }
                        ],
                    }
                ]
            }
        )
        with patch.object(
            lm_studio_api.requests, "get", return_value=models
        ), patch.object(lm_studio_api.requests, "post") as post:
            loaded = lm_studio_api.ensure_model_loaded(
                "local-model", context_length=8192, base_url="http://host:1234"
            )
        self.assertFalse(loaded)
        post.assert_not_called()

    def test_reloads_when_loaded_context_length_differs(self):
        models = FakeResponse(
            {
                "models": [
                    {
                        "key": "local-model",
                        "display_name": "Local Model",
                        "loaded_instances": [
                            {
                                "id": "instance-1",
                                "config": {"context_length": 8192},
                            }
                        ],
                    }
                ]
            }
        )
        with patch.object(
            lm_studio_api.requests, "get", return_value=models
        ), patch.object(
            lm_studio_api.requests,
            "post",
            side_effect=[FakeResponse({}), FakeResponse({})],
        ) as post:
            loaded = lm_studio_api.ensure_model_loaded(
                "local-model", context_length=4096, base_url="http://host:1234"
            )
        self.assertTrue(loaded)
        self.assertEqual(len(post.call_args_list), 2)
        unload_call, load_call = post.call_args_list
        self.assertEqual(
            unload_call.args[0], "http://host:1234/api/v1/models/unload"
        )
        self.assertEqual(unload_call.kwargs["json"], {"instance_id": "instance-1"})
        self.assertEqual(load_call.args[0], "http://host:1234/api/v1/models/load")
        self.assertEqual(
            load_call.kwargs["json"],
            {"model": "local-model", "context_length": 4096},
        )

    def test_matches_display_name_and_leaves_auto_model_for_jit_loading(self):
        models = FakeResponse(
            {
                "models": [
                    {
                        "key": "vendor/model",
                        "display_name": "local-model",
                        "loaded_instances": [],
                    }
                ]
            }
        )
        with patch.object(
            lm_studio_api.requests, "get", return_value=models
        ), patch.object(lm_studio_api.requests, "post") as post:
            loaded = lm_studio_api.ensure_model_loaded(
                "local-model", context_length=None, base_url="http://host:1234"
            )
        self.assertFalse(loaded)
        post.assert_not_called()

    def test_unloads_different_model_when_context_length_is_auto(self):
        models = FakeResponse(
            {
                "models": [
                    {
                        "key": "local-model",
                        "display_name": "Local Model",
                        "loaded_instances": [],
                    },
                    {
                        "key": "other-model",
                        "display_name": "Other Model",
                        "loaded_instances": [{"id": "other-1"}],
                    },
                ]
            }
        )
        with patch.object(
            lm_studio_api.requests, "get", return_value=models
        ), patch.object(
            lm_studio_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            loaded = lm_studio_api.ensure_model_loaded(
                "local-model", context_length=None, base_url="http://host:1234"
            )
        self.assertFalse(loaded)
        self.assertEqual(len(post.call_args_list), 1)
        self.assertEqual(
            post.call_args.args[0], "http://host:1234/api/v1/models/unload"
        )
        self.assertEqual(post.call_args.kwargs["json"], {"instance_id": "other-1"})

    def test_keeps_target_instance_loaded_when_context_length_is_auto(self):
        models = FakeResponse(
            {
                "models": [
                    {
                        "key": "local-model",
                        "display_name": "Local Model",
                        "loaded_instances": [{"id": "target-1"}],
                    },
                    {
                        "key": "other-model",
                        "display_name": "Other Model",
                        "loaded_instances": [{"id": "other-1"}],
                    },
                ]
            }
        )
        with patch.object(
            lm_studio_api.requests, "get", return_value=models
        ), patch.object(
            lm_studio_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            loaded = lm_studio_api.ensure_model_loaded(
                "local-model", context_length=None, base_url="http://host:1234"
            )
        self.assertFalse(loaded)
        self.assertEqual(len(post.call_args_list), 1)
        self.assertEqual(post.call_args.kwargs["json"], {"instance_id": "other-1"})

    def test_load_errors_are_not_swallowed(self):
        models = FakeResponse(
            {
                "models": [
                    {
                        "key": "local-model",
                        "display_name": "Local Model",
                        "loaded_instances": [],
                    }
                ]
            }
        )
        with patch.object(
            lm_studio_api.requests, "get", return_value=models
        ), patch.object(
            lm_studio_api.requests,
            "post",
            return_value=FakeResponse({"error": "bad load"}, status_code=400),
        ):
            with self.assertRaises(requests.exceptions.HTTPError):
                lm_studio_api.ensure_model_loaded(
                    "local-model",
                    context_length=4096,
                    base_url="http://host:1234",
                )


class VRAMMonitorTests(unittest.TestCase):
    def setUp(self):
        vram_monitor.shutdown_nvml()

    def tearDown(self):
        vram_monitor.shutdown_nvml()

    def test_format_vram_usage(self):
        memory = {"used_gb": 8.04, "total_gb": 16.0, "percent": 50.2}
        self.assertEqual(
            vram_monitor.format_vram_usage(memory), "VRAM: 8.0 / 16.0 GB (50%)"
        )

    def test_format_falls_back_to_na(self):
        for memory in (None, {}, {"used_gb": "bad"}):
            with self.subTest(memory=memory):
                self.assertEqual(
                    vram_monitor.format_vram_usage(memory), "VRAM: N/A"
                )

    def test_color_thresholds(self):
        cases = {
            0: vram_monitor.VRAM_COLOR_GREEN,
            69.9: vram_monitor.VRAM_COLOR_GREEN,
            70: vram_monitor.VRAM_COLOR_ORANGE,
            85: vram_monitor.VRAM_COLOR_ORANGE,
            85.1: vram_monitor.VRAM_COLOR_RED,
            99.9: vram_monitor.VRAM_COLOR_RED,
        }
        for percent, expected in cases.items():
            with self.subTest(percent=percent):
                self.assertEqual(vram_monitor.vram_usage_color(percent), expected)
        self.assertEqual(
            vram_monitor.vram_usage_color(None),
            vram_monitor.VRAM_COLOR_NEUTRAL,
        )

    def test_returns_none_when_nvml_module_is_unavailable(self):
        with patch.object(vram_monitor, "pynvml", None):
            self.assertIsNone(vram_monitor.get_gpu_memory_usage())

    def test_returns_none_when_nvml_init_fails(self):
        fake_pynvml = Mock()
        fake_pynvml.nvmlInit.side_effect = RuntimeError("no driver")
        with patch.object(vram_monitor, "pynvml", fake_pynvml):
            self.assertIsNone(vram_monitor.get_gpu_memory_usage())
            self.assertIsNone(vram_monitor.get_gpu_memory_usage())
        fake_pynvml.nvmlInit.assert_called_once()

    def test_returns_none_when_device_query_fails(self):
        fake_pynvml = Mock()
        fake_pynvml.nvmlDeviceGetHandleByIndex.side_effect = RuntimeError("gone")
        with patch.object(vram_monitor, "pynvml", fake_pynvml):
            self.assertIsNone(vram_monitor.get_gpu_memory_usage())

    def test_reads_device_zero_memory(self):
        total = 16 * vram_monitor.BYTES_PER_GB
        used = 8 * vram_monitor.BYTES_PER_GB
        fake_pynvml = Mock()
        fake_pynvml.nvmlDeviceGetMemoryInfo.return_value = SimpleNamespace(
            total=total, used=used
        )
        with patch.object(vram_monitor, "pynvml", fake_pynvml):
            memory = vram_monitor.get_gpu_memory_usage()
        fake_pynvml.nvmlDeviceGetHandleByIndex.assert_called_once_with(0)
        self.assertAlmostEqual(memory["used_gb"], 8.0)
        self.assertAlmostEqual(memory["total_gb"], 16.0)
        self.assertAlmostEqual(memory["percent"], 50.0)
        self.assertEqual(
            vram_monitor.format_vram_usage(memory), "VRAM: 8.0 / 16.0 GB (50%)"
        )

    def test_init_runs_once_and_shutdown_is_clean(self):
        fake_pynvml = Mock()
        fake_pynvml.nvmlDeviceGetMemoryInfo.return_value = SimpleNamespace(
            total=100, used=10
        )
        with patch.object(vram_monitor, "pynvml", fake_pynvml):
            vram_monitor.get_gpu_memory_usage()
            vram_monitor.get_gpu_memory_usage()
            fake_pynvml.nvmlInit.assert_called_once()
            vram_monitor.shutdown_nvml()
            fake_pynvml.nvmlShutdown.assert_called_once()


class VramCleanupApiTests(unittest.TestCase):
    def test_free_comfyui_vram_payload_and_timeout(self):
        with patch.object(
            vram_cleanup_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            vram_cleanup_api.free_comfyui_vram("http://comfy:8188/")
        self.assertEqual(post.call_args.args[0], "http://comfy:8188/free")
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"unload_models": True, "free_memory": True},
        )
        self.assertEqual(post.call_args.kwargs["timeout"], 1.5)

    def test_free_forge_vram_payload_and_timeout(self):
        with patch.object(
            vram_cleanup_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            vram_cleanup_api.free_forge_vram("http://forge:7860")
        self.assertEqual(
            post.call_args.args[0],
            "http://forge:7860/sdapi/v1/unload-checkpoint",
        )
        self.assertEqual(post.call_args.kwargs["json"], {})
        self.assertEqual(post.call_args.kwargs["timeout"], 1.5)

    def test_free_functions_raise_on_http_error(self):
        for free_func in (
            vram_cleanup_api.free_comfyui_vram,
            vram_cleanup_api.free_forge_vram,
        ):
            with self.subTest(free_func=free_func.__name__):
                with patch.object(
                    vram_cleanup_api.requests,
                    "post",
                    return_value=FakeResponse({}, status_code=500),
                ):
                    with self.assertRaises(requests.exceptions.HTTPError):
                        free_func("http://host:1")

    def test_free_external_vram_reports_successful_backends(self):
        with patch.object(
            vram_cleanup_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            freed = vram_cleanup_api.free_external_vram(
                "http://comfy:8188", "http://forge:7860", timeout=2.0
            )
        self.assertEqual(freed, ["ComfyUI", "Forge Neo"])
        self.assertEqual(len(post.call_args_list), 2)
        for call in post.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 2.0)

    def test_free_external_vram_skips_blank_urls(self):
        with patch.object(
            vram_cleanup_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            freed = vram_cleanup_api.free_external_vram("", "   ")
        self.assertEqual(freed, [])
        post.assert_not_called()

    def test_free_external_vram_tolerates_connection_errors(self):
        with patch.object(
            vram_cleanup_api.requests,
            "post",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            freed = vram_cleanup_api.free_external_vram(
                "http://comfy:8188", "http://forge:7860"
            )
        self.assertEqual(freed, [])

    def test_free_external_vram_keeps_partial_success(self):
        def post(url, **kwargs):
            if url.startswith("http://comfy"):
                raise requests.exceptions.Timeout("slow")
            return FakeResponse({})

        with patch.object(vram_cleanup_api.requests, "post", side_effect=post):
            freed = vram_cleanup_api.free_external_vram(
                "http://comfy:8188", "http://forge:7860"
            )
        self.assertEqual(freed, ["Forge Neo"])

    def test_free_external_vram_uses_configured_urls(self):
        with patch.object(
            vram_cleanup_api,
            "get_comfyui_base_url",
            return_value="http://comfy:9000",
        ), patch.object(
            vram_cleanup_api, "get_forge_base_url", return_value=""
        ), patch.object(
            vram_cleanup_api.requests, "post", return_value=FakeResponse({})
        ) as post:
            freed = vram_cleanup_api.free_external_vram_from_config()
        self.assertEqual(freed, ["ComfyUI"])
        self.assertEqual(post.call_args.args[0], "http://comfy:9000/free")

    def test_config_url_helpers_use_defaults_and_trim(self):
        from promptwriter.storage import config_store

        self.assertEqual(
            config_store.get_comfyui_base_url({}), "http://127.0.0.1:8188"
        )
        self.assertEqual(
            config_store.get_forge_base_url({}), "http://127.0.0.1:7860"
        )
        config = {
            "comfyui_base_url": " http://comfy:9000/ ",
            "forge_base_url": "   ",
        }
        self.assertEqual(
            config_store.get_comfyui_base_url(config), "http://comfy:9000"
        )
        self.assertEqual(
            config_store.get_forge_base_url(config), "http://127.0.0.1:7860"
        )


class VramPreflightConditionTests(unittest.TestCase):
    def test_prompts_only_when_high_vram_and_no_loaded_model(self):
        memory = {"used_gb": 13.0, "total_gb": 16.0, "percent": 81.0}
        self.assertTrue(
            vram_cleanup_api.should_prompt_vram_unload(memory, [])
        )
        self.assertFalse(
            vram_cleanup_api.should_prompt_vram_unload(
                memory, [("Model", "instance-1")]
            )
        )
        self.assertFalse(
            vram_cleanup_api.should_prompt_vram_unload(memory, None)
        )

    def test_skips_at_or_below_threshold(self):
        for percent in (0.0, 50.0, 75.0):
            with self.subTest(percent=percent):
                memory = {
                    "used_gb": 12.0,
                    "total_gb": 16.0,
                    "percent": percent,
                }
                self.assertFalse(
                    vram_cleanup_api.should_prompt_vram_unload(memory, [])
                )

    def test_skips_when_vram_is_unavailable(self):
        for memory in (None, {}, {"percent": "high"}):
            with self.subTest(memory=memory):
                self.assertFalse(
                    vram_cleanup_api.should_prompt_vram_unload(memory, [])
                )


if __name__ == "__main__":
    unittest.main()
