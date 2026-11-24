import inspect
import json
import re
import sqlite3
import tempfile
import time
import tkinter
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
import customtkinter as ctk

from promptwriter.config import LOCAL_ENGINE
from promptwriter.services import (
    llm_client,
    lm_studio_api,
    model_catalog,
    vram_cleanup_api,
    vram_monitor,
)
from promptwriter.storage import app_files, history_db, personal_data_reset, profile_store
from promptwriter.services.prompt_builder import (
    VISION_DEFAULT_USER_PROMPT,
    assemble_image_request,
    assemble_text_request,
)
from promptwriter.ui import generator_tab, help_tab
from promptwriter.ui.generator_tab import GeneratorTabMixin
from promptwriter.ui.help_tab import (
    HELP_GUIDE_TAB,
    HELP_LICENSE_TAB,
    HELP_LINKS,
    KOFI_URL,
    LICENSE_ENTRIES,
    HelpTabMixin,
)
from promptwriter.ui.tooltip import ToolTip, clamp_tooltip_position
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
            parts["user"],
            f"{VISION_DEFAULT_USER_PROMPT}\n\n"
            "Additional context and instructions:\nmake it cinematic",
        )

    def test_vision_assembly_trims_context_before_appending(self):
        parts = assemble_image_request(
            self.prompt_path, "None", [], "  make it cinematic \n"
        )
        self.assertEqual(
            parts["user"],
            f"{VISION_DEFAULT_USER_PROMPT}\n\n"
            "Additional context and instructions:\nmake it cinematic",
        )

    def test_vision_assembly_defaults_user_prompt_when_context_empty(self):
        parts = assemble_image_request(self.prompt_path, "None", [], "")
        self.assertEqual(parts["user"], VISION_DEFAULT_USER_PROMPT)

    def test_vision_assembly_treats_whitespace_context_as_empty(self):
        parts = assemble_image_request(self.prompt_path, "None", [], "  \n\t ")
        self.assertEqual(parts["user"], VISION_DEFAULT_USER_PROMPT)

    def test_vision_assembly_treats_none_context_as_empty(self):
        parts = assemble_image_request(self.prompt_path, "None", [], None)
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

    def test_presence_penalty_is_sent_to_groq_and_local(self):
        for engine in ("Groq", LOCAL_ENGINE):
            with self.subTest(engine=engine):
                _, post = self._capture(
                    engine,
                    chat_response("a prompt"),
                    request_text={"system": "SYS", "user": "USER"},
                    presence_penalty=1.25,
                    base_url="http://127.0.0.1:1234",
                )
                self.assertEqual(
                    post.call_args.kwargs["json"]["presence_penalty"], 1.25
                )

    def test_presence_penalty_is_omitted_when_inactive_or_out_of_range(self):
        for engine in ("Groq", LOCAL_ENGINE):
            for value in (0.0, -0.5, 2.5):
                with self.subTest(engine=engine, value=value):
                    _, post = self._capture(
                        engine,
                        chat_response("a prompt"),
                        request_text={"system": "SYS", "user": "USER"},
                        presence_penalty=value,
                        base_url="http://127.0.0.1:1234",
                    )
                    self.assertNotIn(
                        "presence_penalty", post.call_args.kwargs["json"]
                    )

    def test_gemini_never_receives_presence_penalty(self):
        response = FakeResponse(
            {"candidates": [{"content": {"parts": [{"text": "a prompt"}]}}]}
        )
        _, post = self._capture(
            "Gemini",
            response,
            request_text={"system": "SYS", "user": "USER"},
            presence_penalty=1.25,
        )
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("presence_penalty", payload)
        self.assertNotIn("presencePenalty", payload["generationConfig"])

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
        self.assertEqual(gemini_text["presence_penalty"], 0.0)
        self.assertIsNone(gemini_text["max_tokens"])
        vision_local = profile_store.default_profile(LOCAL_ENGINE, "vision")
        self.assertEqual(vision_local["temperature"], 0.1)
        self.assertEqual(vision_local["top_p"], 0.2)
        self.assertEqual(vision_local["presence_penalty"], 0.0)
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
            "Groq", "qwen-test", "text", {"temperature": 0.6}
        )
        profile = profile_store.get_profile("Groq", "qwen-test", "text")
        self.assertEqual(profile["temperature"], 0.6)
        self.assertEqual(profile["top_p"], 0.95)
        self.assertEqual(profile["max_tokens"], 6500)

    def test_profile_temperature_above_one_is_capped(self):
        for temperature in (1.1, 1.5, 2.0):
            with self.subTest(temperature=temperature):
                saved = profile_store.save_profile(
                    "Gemini", "gemini-test", "text", {"temperature": temperature}
                )
                self.assertEqual(saved["temperature"], 1.0)
                self.assertEqual(
                    profile_store.get_profile(
                        "Gemini", "gemini-test", "text"
                    )["temperature"],
                    1.0,
                )
        entries = profile_store.list_profiles()
        self.assertTrue(all(entry["profile"]["temperature"] <= 1.0 for entry in entries))

    def test_presence_penalty_defaults_and_validation(self):
        self.path.write_text(
            json.dumps(
                {"Groq": {"legacy": {"text": {"temperature": 0.4}}}}
            ),
            encoding="utf-8",
        )
        legacy = profile_store.get_profile("Groq", "legacy", "text")
        self.assertEqual(legacy["presence_penalty"], 0.0)

        saved = profile_store.save_profile(
            "Groq", "pp-test", "text", {"presence_penalty": 1.25}
        )
        self.assertEqual(saved["presence_penalty"], 1.25)
        self.assertEqual(
            profile_store.get_profile("Groq", "pp-test", "text")[
                "presence_penalty"
            ],
            1.25,
        )

        for value in (2.5, -0.1):
            with self.subTest(value=value):
                saved = profile_store.save_profile(
                    "Groq", "pp-test", "text", {"presence_penalty": value}
                )
                self.assertEqual(saved["presence_penalty"], 0.0)

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
        self.assertIn("Temp:\u00A00.55", summary)
        self.assertIn("Ctx:\u00A08192", summary)
        self.assertIn("Max:\u00A02048", summary)
        self.assertIn("Top-P:\u00A00.95", summary)
        self.assertIn("Min-P:\u00A00.05", summary)
        self.assertTrue(summary.endswith("Think:\u00A0On"))
        first_row, second_row = summary.splitlines()
        self.assertIn("Min-P:", first_row)
        self.assertIn("Ctx:", second_row)
        saved["disable_thinking"] = True
        summary = profile_store.format_profile_summary(
            LOCAL_ENGINE, saved, True, temperature=0.55
        )
        self.assertTrue(summary.endswith("Think:\u00A0Off"))

    def test_presence_penalty_summary_only_when_active_and_supported(self):
        def summary(engine, value):
            profile = profile_store.default_profile(engine, "text")
            profile["presence_penalty"] = value
            return profile_store.format_profile_summary(engine, profile, True)

        groq_row_one, groq_row_two = summary("Groq", 1.25).splitlines()
        self.assertIn("Pres:\u00A01.25", groq_row_two)
        self.assertNotIn("Pres:", groq_row_one)

        local_row_one, local_row_two = summary(LOCAL_ENGINE, 1.25).splitlines()
        self.assertIn("Pres:\u00A01.25", local_row_one)
        self.assertIn("Think:\u00A0On", local_row_two)

        self.assertNotIn("Pres:", summary("Groq", 0.0))
        self.assertNotIn("Pres:", summary("Gemini", 1.25))


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
            presence_penalty=1.25,
            min_p=0.05,
            repeat_penalty=1.1,
            max_tokens=1024,
            disable_thinking=True,
        )
        kwargs = profile_store.profile_request_kwargs(LOCAL_ENGINE, profile)
        self.assertEqual(kwargs["presence_penalty"], 1.25)
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
        self.assertEqual(payload["presence_penalty"], 1.25)
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
        self.assertNotIn("presence_penalty", payload)
        self.assertNotIn("cache_prompt", payload)
        self.assertEqual(payload["messages"][-1]["content"], "USER")

    def test_presence_penalty_kwargs_follow_engine_support(self):
        for engine in ("Groq", LOCAL_ENGINE):
            with self.subTest(engine=engine):
                active = self._profile(
                    engine, "text", presence_penalty=1.25
                )
                self.assertEqual(
                    profile_store.profile_request_kwargs(engine, active)[
                        "presence_penalty"
                    ],
                    1.25,
                )
                inactive = self._profile(
                    engine, "text", presence_penalty=0.0
                )
                self.assertNotIn(
                    "presence_penalty",
                    profile_store.profile_request_kwargs(engine, inactive),
                )
        gemini = self._profile("Gemini", "text", presence_penalty=1.25)
        self.assertNotIn(
            "presence_penalty",
            profile_store.profile_request_kwargs("Gemini", gemini),
        )

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
            "Gemini",
            "text",
            temperature=0.4,
            top_p=0.8,
            presence_penalty=1.25,
            max_tokens=1024,
        )
        kwargs = profile_store.profile_request_kwargs("Gemini", profile)
        self.assertNotIn("presence_penalty", kwargs)
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
        payload = post.call_args.kwargs["json"]
        generation_config = payload["generationConfig"]
        self.assertEqual(generation_config["temperature"], 0.4)
        self.assertEqual(generation_config["topP"], 0.8)
        self.assertEqual(generation_config["maxOutputTokens"], 1024)
        self.assertNotIn("presence_penalty", payload)
        self.assertNotIn("presencePenalty", generation_config)


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

    def test_non_nvidia_device_failure_is_cached(self):
        fake_pynvml = Mock()
        fake_pynvml.nvmlDeviceGetHandleByIndex.side_effect = RuntimeError(
            "not an NVIDIA GPU"
        )
        with patch.object(vram_monitor, "pynvml", fake_pynvml):
            self.assertIsNone(vram_monitor.get_gpu_memory_usage())
            self.assertFalse(vram_monitor.is_vram_supported())
            self.assertIsNone(vram_monitor.get_gpu_memory_usage())
            self.assertIsNone(vram_monitor.get_gpu_memory_usage())
        fake_pynvml.nvmlDeviceGetHandleByIndex.assert_called_once_with(0)

    def test_unsupported_label_for_non_nvidia_device(self):
        fake_pynvml = Mock()
        fake_pynvml.nvmlDeviceGetHandleByIndex.side_effect = RuntimeError(
            "not an NVIDIA GPU"
        )
        with patch.object(vram_monitor, "pynvml", fake_pynvml):
            memory = vram_monitor.get_gpu_memory_usage()
            self.assertEqual(
                vram_monitor.vram_label_text(memory), "VRAM: Not supported"
            )

    def test_unsupported_label_when_nvml_module_is_missing(self):
        with patch.object(vram_monitor, "pynvml", None):
            self.assertIsNone(vram_monitor.get_gpu_memory_usage())
            self.assertFalse(vram_monitor.is_vram_supported())
            self.assertEqual(
                vram_monitor.vram_label_text(None), "VRAM: Not supported"
            )

    def test_na_label_for_unreadable_memory_on_supported_device(self):
        fake_pynvml = Mock()
        fake_pynvml.nvmlDeviceGetMemoryInfo.return_value = SimpleNamespace(
            total=0, used=0
        )
        with patch.object(vram_monitor, "pynvml", fake_pynvml):
            memory = vram_monitor.get_gpu_memory_usage()
            self.assertIsNone(memory)
            self.assertTrue(vram_monitor.is_vram_supported())
            self.assertEqual(vram_monitor.vram_label_text(memory), "VRAM: N/A")

    def test_supported_label_for_live_memory(self):
        memory = {"used_gb": 8.04, "total_gb": 16.0, "percent": 50.2}
        self.assertEqual(
            vram_monitor.vram_label_text(memory), "VRAM: 8.0 / 16.0 GB (50%)"
        )

    def test_shutdown_clears_cached_unsupported_state(self):
        fake_pynvml = Mock()
        fake_pynvml.nvmlDeviceGetHandleByIndex.side_effect = RuntimeError(
            "not an NVIDIA GPU"
        )
        with patch.object(vram_monitor, "pynvml", fake_pynvml):
            self.assertIsNone(vram_monitor.get_gpu_memory_usage())
            self.assertFalse(vram_monitor.is_vram_supported())
            vram_monitor.shutdown_nvml()
            fake_pynvml.nvmlDeviceGetHandleByIndex.side_effect = None
            fake_pynvml.nvmlDeviceGetMemoryInfo.return_value = SimpleNamespace(
                total=100, used=10
            )
            self.assertTrue(vram_monitor.is_vram_supported())
            self.assertIsNotNone(vram_monitor.get_gpu_memory_usage())
        self.assertEqual(
            fake_pynvml.nvmlDeviceGetHandleByIndex.call_count, 2
        )

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
        memory = {"used_gb": 9.0, "total_gb": 16.0, "percent": 56.0}
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

    def test_skips_at_or_below_fifty_percent(self):
        for percent in (0.0, 25.0, 50.0):
            with self.subTest(percent=percent):
                memory = {
                    "used_gb": 8.0,
                    "total_gb": 16.0,
                    "percent": percent,
                }
                self.assertFalse(
                    vram_cleanup_api.should_prompt_vram_unload(memory, [])
                )

    def test_prompts_just_above_fifty_percent(self):
        memory = {"used_gb": 8.1, "total_gb": 16.0, "percent": 50.1}
        self.assertTrue(vram_cleanup_api.should_prompt_vram_unload(memory, []))

    def test_skips_when_vram_is_unavailable(self):
        for memory in (None, {}, {"percent": "high"}):
            with self.subTest(memory=memory):
                self.assertFalse(
                    vram_cleanup_api.should_prompt_vram_unload(memory, [])
                )

    def test_dialog_outcomes_map_to_generation_flags(self):
        self.assertEqual(
            vram_cleanup_api.preflight_flags(
                vram_cleanup_api.PREFLIGHT_UNLOAD
            ),
            (True, True),
        )
        self.assertEqual(
            vram_cleanup_api.preflight_flags(
                vram_cleanup_api.PREFLIGHT_LOAD_ANYWAY
            ),
            (True, False),
        )
        self.assertEqual(
            vram_cleanup_api.preflight_flags(
                vram_cleanup_api.PREFLIGHT_CANCEL
            ),
            (False, False),
        )
        self.assertEqual(
            vram_cleanup_api.preflight_flags("unknown"), (False, False)
        )


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "history.db"
        self.path_patch = patch.object(history_db, "HISTORY_DB_PATH", self.path)
        self.path_patch.start()
        history_db.initialize_history_database()

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def _insert(self, idea, prompt):
        history_db.insert_generation(
            idea,
            prompt,
            {"llm_engine": "Groq"},
            source_tab="generator",
            engine="Groq",
            model="test-model",
        )

    def test_delete_generation_removes_entry(self):
        self._insert("idea one", "prompt one")
        entry_id = history_db.fetch_recent_generations()[0][0]

        self.assertTrue(history_db.delete_generation(entry_id))
        self.assertEqual(history_db.fetch_recent_generations(), [])
        self.assertIsNone(history_db.fetch_generation(entry_id))
        self.assertFalse(history_db.delete_generation(entry_id))

    def test_delete_removes_favorite_prompt(self):
        self._insert("favorite idea", "favorite prompt")
        entry_id = history_db.fetch_recent_generations()[0][0]
        history_db.toggle_favorite(entry_id)

        history_db.delete_generation(entry_id)

        self.assertEqual(history_db.fetch_favorite_prompts(), [])
        self.assertEqual(
            history_db.fetch_recent_generations("", favorites_only=True), []
        )

    def test_search_reaches_entries_beyond_previous_list_window(self):
        self._insert("needle idea", "first prompt")
        for index in range(60):
            self._insert(f"filler idea {index}", f"filler prompt {index}")

        rows = history_db.fetch_recent_generations("needle")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "needle idea")

    def test_favorites_only_filter_keeps_favorite_entries(self):
        self._insert("plain idea", "plain prompt")
        self._insert("favorite idea", "favorite prompt")
        favorite_id = history_db.fetch_recent_generations()[0][0]
        history_db.toggle_favorite(favorite_id)

        rows = history_db.fetch_recent_generations("", favorites_only=True)

        self.assertEqual([row[0] for row in rows], [favorite_id])
        self.assertEqual(history_db.fetch_favorite_prompts(), ["favorite prompt"])

    def test_bulk_delete_keeps_favorites_by_default(self):
        self._insert("idea one", "prompt one")
        self._insert("idea two", "prompt two")
        self._insert("favorite idea", "favorite prompt")
        favorite_id = history_db.fetch_recent_generations()[0][0]
        history_db.toggle_favorite(favorite_id)

        self.assertEqual(history_db.count_generations_for_delete(), 2)
        self.assertEqual(history_db.bulk_delete_generations(), 2)

        remaining = history_db.fetch_recent_generations()
        self.assertEqual([row[0] for row in remaining], [favorite_id])
        self.assertEqual(history_db.fetch_favorite_prompts(), ["favorite prompt"])

    def test_bulk_delete_includes_favorites_when_requested(self):
        self._insert("idea one", "prompt one")
        self._insert("favorite idea", "favorite prompt")
        favorite_id = history_db.fetch_recent_generations()[0][0]
        history_db.toggle_favorite(favorite_id)

        self.assertEqual(
            history_db.count_generations_for_delete(include_favorites=True), 2
        )
        self.assertEqual(history_db.bulk_delete_generations(include_favorites=True), 2)

        self.assertEqual(history_db.fetch_recent_generations(), [])
        self.assertEqual(history_db.fetch_favorite_prompts(), [])

    def test_bulk_delete_cutoff_removes_only_older_entries(self):
        self._insert("old idea", "old prompt")
        old_id = history_db.fetch_recent_generations()[0][0]
        self._insert("new idea", "new prompt")
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE generations SET timestamp = ? WHERE id = ?",
                ("2020-01-01T00:00:00+00:00", old_id),
            )
            connection.commit()
        finally:
            connection.close()

        cutoff = datetime.now().astimezone() - timedelta(days=30)

        self.assertEqual(
            history_db.count_generations_for_delete(older_than=cutoff), 1
        )
        self.assertEqual(history_db.bulk_delete_generations(older_than=cutoff), 1)

        remaining = history_db.fetch_recent_generations()
        self.assertEqual([row[2] for row in remaining], ["new idea"])


class PersonalDataResetTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.data_dir = root / "data"
        self.data_dir.mkdir()
        self.text_dir = root / "system_prompts"
        self.vision_dir = root / "system_prompts_vision"
        self.text_dir.mkdir()
        self.vision_dir.mkdir()
        self.config_path = root / "config.json"
        self.rough_path = root / "rough_idea_cache.txt"
        self.history_path = self.data_dir / "history.db"
        self.cameras_path = self.data_dir / "cameras.json"
        self.lora_path = self.data_dir / "lora_profiles.json"
        self.profiles_path = self.data_dir / "model_profiles.json"
        self.json_files = {
            self.cameras_path: [],
            self.lora_path: [],
            self.profiles_path: {},
        }

        self.path_patch = patch.multiple(
            personal_data_reset,
            CONFIG_PATH=self.config_path,
            ROUGH_IDEA_CACHE_PATH=self.rough_path,
            BASELINE_PROMPTS={
                self.text_dir: ("single_prompt.txt", "multi_prompt.txt"),
                self.vision_dir: ("image_to_prompt.txt",),
            },
            DEFAULT_JSON_FILES=self.json_files,
        )
        self.path_patch.start()
        self.history_patch = patch.multiple(
            history_db,
            HISTORY_DB_PATH=self.history_path,
            DATA_DIR=self.data_dir,
        )
        self.history_patch.start()

        self.config_path.write_text(
            json.dumps(
                {
                    "gemini_api_key": "gemini-key",
                    "groq_api_key": "groq-key",
                    "engine": "Groq",
                    "selected_api_model": "custom-model",
                    "selected_api_models": {
                        "Gemini": "custom-model",
                        "Groq": "custom-model",
                    },
                    "available_models": {"Gemini": ["custom-model"]},
                    "cached_models_gemini": ["custom-model"],
                    "cached_models_groq": ["custom-model"],
                    "ui_state": {"generator": {"engine": "Groq"}},
                }
            ),
            encoding="utf-8",
        )
        self.cameras_path.write_text(json.dumps(["Camera X"]), encoding="utf-8")
        self.lora_path.write_text(
            json.dumps([{"name": "Hero", "trigger_word": "hero"}]), encoding="utf-8"
        )
        self.profiles_path.write_text(
            json.dumps({"Groq": {"custom-model": {"text": {"temperature": 0.9}}}}),
            encoding="utf-8",
        )
        self.rough_path.write_text("old idea", encoding="utf-8")
        history_db.initialize_history_database()
        history_db.insert_generation("idea", "prompt", {"llm_engine": "Groq"})
        history_db.insert_generation("idea 2", "prompt 2", {"llm_engine": "Groq"})
        for directory, name, text in (
            (self.text_dir, "single_prompt.txt", "old single\n"),
            (self.text_dir, "multi_prompt.txt", "old multi\n"),
            (self.vision_dir, "image_to_prompt.txt", "old image\n"),
        ):
            (directory / name).write_text(text, encoding="utf-8")
        (self.text_dir / "CustomPrompt.txt").write_text("custom\n", encoding="utf-8")
        (self.vision_dir / "CustomVision.txt").write_text(
            "custom vision\n", encoding="utf-8"
        )

    def tearDown(self):
        self.history_patch.stop()
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def _load_config(self):
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def _load_json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def _baseline_text(self, name):
        return (personal_data_reset.BASELINE_PROMPTS_DIR / name).read_text(
            encoding="utf-8"
        )

    def test_reset_keeps_api_keys_when_toggle_is_off(self):
        summary = personal_data_reset.reset_personal_data(delete_api_keys=False)

        config = self._load_config()
        self.assertEqual(config["gemini_api_key"], "gemini-key")
        self.assertEqual(config["groq_api_key"], "groq-key")
        self.assertEqual(config["cached_models_gemini"], [])
        self.assertEqual(config["cached_models_groq"], [])
        self.assertEqual(config["selected_api_model"], "")
        self.assertNotIn("ui_state", config)

        self.assertEqual(self._load_json(self.cameras_path), [])
        self.assertEqual(self._load_json(self.lora_path), [])
        self.assertEqual(self._load_json(self.profiles_path), {})
        self.assertEqual(history_db.fetch_recent_generations(), [])
        self.assertFalse(self.rough_path.exists())
        self.assertFalse((self.text_dir / "CustomPrompt.txt").exists())
        self.assertFalse((self.vision_dir / "CustomVision.txt").exists())

        self.assertEqual(summary["history_entries_deleted"], 2)
        self.assertEqual(summary["prompts_removed"], 2)
        self.assertEqual(summary["errors"], [])
        self.assertFalse(summary["api_keys_deleted"])

    def test_reset_keeps_baseline_prompts_intact(self):
        personal_data_reset.reset_personal_data(delete_api_keys=True)

        for directory, name in (
            (self.text_dir, "single_prompt.txt"),
            (self.text_dir, "multi_prompt.txt"),
            (self.vision_dir, "image_to_prompt.txt"),
        ):
            with self.subTest(name=name):
                self.assertTrue((directory / name).is_file())
                self.assertEqual(
                    (directory / name).read_text(encoding="utf-8"),
                    self._baseline_text(name),
                )

    def test_reset_restores_deleted_baseline_prompts(self):
        self.text_dir.joinpath("single_prompt.txt").unlink()
        self.vision_dir.joinpath("image_to_prompt.txt").unlink()

        summary = personal_data_reset.reset_personal_data(delete_api_keys=False)

        self.assertEqual(
            self.text_dir.joinpath("single_prompt.txt").read_text(encoding="utf-8"),
            self._baseline_text("single_prompt.txt"),
        )
        self.assertEqual(
            self.vision_dir.joinpath("image_to_prompt.txt").read_text(
                encoding="utf-8"
            ),
            self._baseline_text("image_to_prompt.txt"),
        )
        self.assertEqual(
            sorted(summary["baseline_prompts"]),
            ["image_to_prompt.txt", "multi_prompt.txt", "single_prompt.txt"],
        )

    def test_reset_deletes_api_keys_when_toggle_is_on(self):
        summary = personal_data_reset.reset_personal_data(delete_api_keys=True)

        config = self._load_config()
        self.assertEqual(config["gemini_api_key"], "")
        self.assertEqual(config["groq_api_key"], "")
        self.assertTrue(summary["api_keys_deleted"])

    def test_reset_tolerates_missing_files(self):
        self.config_path.unlink()
        self.rough_path.unlink()
        self.history_path.unlink()
        for path in self.json_files:
            path.unlink()
        (self.text_dir / "CustomPrompt.txt").unlink()
        (self.vision_dir / "CustomVision.txt").unlink()

        summary = personal_data_reset.reset_personal_data(delete_api_keys=False)

        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["prompts_removed"], 0)
        self.assertEqual(summary["history_entries_deleted"], 0)
        self.assertEqual(self._load_config()["gemini_api_key"], "")
        self.assertEqual(history_db.fetch_recent_generations(), [])
        self.assertTrue((self.text_dir / "multi_prompt.txt").is_file())
        self.assertTrue((self.vision_dir / "image_to_prompt.txt").is_file())


class GeminiModelFetchTests(unittest.TestCase):
    def test_unusable_catalog_returns_message_instead_of_fallback(self):
        fake_model = SimpleNamespace(
            name="models/gemini-embedding-001",
            supported_actions=["embedContent"],
        )
        fake_genai = SimpleNamespace(
            Client=lambda api_key: SimpleNamespace(
                models=SimpleNamespace(list=lambda: [fake_model])
            )
        )
        fake_google = SimpleNamespace(genai=fake_genai)

        with patch.dict(
            "sys.modules", {"google": fake_google, "google.genai": fake_genai}
        ):
            models, message = model_catalog.fetch_provider_models("Gemini", "key")

        self.assertEqual(models, [])
        self.assertIsNotNone(message)


class AppFilesBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.text_dir = root / "system_prompts"
        self.vision_dir = root / "system_prompts_vision"
        self.defaults_dir = root / "defaults"
        self.defaults_dir.mkdir()
        for name in ("single_prompt.txt", "multi_prompt.txt", "image_to_prompt.txt"):
            (self.defaults_dir / name).write_text(
                f"baseline {name}\n", encoding="utf-8"
            )
        self.patcher = patch.multiple(
            app_files,
            APP_DIR=root,
            CONFIG_PATH=root / "config.json",
            DATA_DIR=root / "data",
            SYSTEM_PROMPTS_DIR=self.text_dir,
            VISION_SYSTEM_PROMPTS_DIR=self.vision_dir,
            BASELINE_PROMPTS_DIR=self.defaults_dir,
            BASELINE_PROMPTS={
                self.text_dir: ("single_prompt.txt", "multi_prompt.txt"),
                self.vision_dir: ("image_to_prompt.txt",),
            },
            LEGACY_BOOTSTRAP_PROMPTS={
                self.text_dir: ("Flux-2-Klein.txt",),
                self.vision_dir: ("Vision-Default.txt",),
            },
            DEFAULT_JSON_FILES={},
        )
        self.patcher.start()
        self.history_patcher = patch.object(app_files, "initialize_history_database")
        self.history_patcher.start()

    def tearDown(self):
        self.history_patcher.stop()
        self.patcher.stop()
        self.temp_dir.cleanup()

    def _prompt_names(self, directory):
        return sorted(path.name for path in directory.glob("*.txt"))

    def test_first_run_seeds_only_baseline_prompts(self):
        app_files.ensure_app_files()

        self.assertEqual(
            self._prompt_names(self.text_dir),
            ["multi_prompt.txt", "single_prompt.txt"],
        )
        self.assertEqual(
            self._prompt_names(self.vision_dir), ["image_to_prompt.txt"]
        )
        self.assertEqual(
            (self.text_dir / "single_prompt.txt").read_text(encoding="utf-8"),
            "baseline single_prompt.txt\n",
        )

    def test_first_run_replaces_legacy_bootstrap_prompts(self):
        self.text_dir.mkdir()
        (self.text_dir / "Flux-2-Klein.txt").write_text("legacy\n", encoding="utf-8")
        self.vision_dir.mkdir()
        (self.vision_dir / "Vision-Default.txt").write_text(
            "legacy\n", encoding="utf-8"
        )

        app_files.ensure_app_files()

        self.assertEqual(
            self._prompt_names(self.text_dir),
            ["multi_prompt.txt", "single_prompt.txt"],
        )
        self.assertEqual(
            self._prompt_names(self.vision_dir), ["image_to_prompt.txt"]
        )

    def test_existing_user_prompts_are_kept(self):
        self.text_dir.mkdir()
        (self.text_dir / "MyPrompt.txt").write_text("mine\n", encoding="utf-8")
        self.vision_dir.mkdir()

        app_files.ensure_app_files()

        self.assertEqual(self._prompt_names(self.text_dir), ["MyPrompt.txt"])
        self.assertEqual(
            self._prompt_names(self.vision_dir), ["image_to_prompt.txt"]
        )

    def test_missing_baseline_source_raises(self):
        self.defaults_dir.joinpath("single_prompt.txt").unlink()

        with self.assertRaises(FileNotFoundError):
            app_files.ensure_app_files()


class _GeneratorErrorHost(GeneratorTabMixin, tkinter.Frame):
    def __init__(self, master):
        tkinter.Frame.__init__(self, master)
        self._status_wrap_job = None
        self._status_wrap_width = None
        self._status_wrap_busy = False
        self.generate_button = tkinter.Button(self, state="normal")
        self.rough_idea_text = tkinter.Text(self)
        self.rough_idea_text.insert("1.0", "A lone lighthouse at dusk")
        self.status_label = ctk.CTkLabel(self, text="Ready", wraplength=400)
        self.status_label.pack()
        self.model_menu = SimpleNamespace(get=lambda: "single_prompt")
        self.lora_menu = SimpleNamespace(get=lambda: "None")
        self.camera_menu = SimpleNamespace(get=lambda: "None / Auto")
        self.engine_menu = SimpleNamespace(get=lambda: "Gemini")
        self.lora_profiles = []


class GeneratorStatusWrapTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tkinter.Tk()
        except tkinter.TclError:
            self.skipTest("Tk is unavailable")
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = (
            lambda exc, val, tb: self.errors.append(val)
        )
        self.host = _GeneratorErrorHost(self.root)
        self.host.pack()
        self.root.update_idletasks()

    def tearDown(self):
        try:
            self.root.destroy()
        except tkinter.TclError:
            pass

    def _pump(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.root.update()
            time.sleep(0.01)

    def test_missing_api_key_error_has_no_recursive_wrap_loop(self):
        with patch.object(generator_tab, "load_config", return_value={}):
            self.host._generate_prompt()

        self.assertIn("API Key missing", self.host.status_label.cget("text"))
        self.assertEqual(self.errors, [])

        configure_calls = []
        original_configure = self.host.status_label.configure

        def reentrant_configure(**kwargs):
            configure_calls.append(kwargs.get("wraplength"))
            if len(configure_calls) > 25:
                raise RecursionError("recursive wraplength configure loop")
            # Simulate the <Configure> Tk may dispatch while the label resizes:
            # the new width feeds straight back into the scheduler.
            self.host._update_status_wraplength(
                SimpleNamespace(width=int(kwargs.get("wraplength", 200)) + 24)
            )
            return original_configure(**kwargs)

        self.host.status_label.configure = reentrant_configure
        for width in (329, 780, 340, 520, 340, 940, 329):
            self.host._update_status_wraplength(SimpleNamespace(width=width))
            self._pump(0.12)
        self._pump(0.3)

        self.assertLessEqual(len(configure_calls), 25)
        self.assertEqual(self.errors, [])
        self.assertIsNone(self.host._status_wrap_job)

    def test_nested_apply_callback_is_ignored(self):
        configure_calls = []
        original_configure = self.host.status_label.configure

        def nested_apply_configure(**kwargs):
            self.host._apply_status_wraplength(999)
            configure_calls.append(kwargs.get("wraplength"))
            return original_configure(**kwargs)

        self.host.status_label.configure = nested_apply_configure
        self.host._apply_status_wraplength(321)

        self.assertEqual(configure_calls, [321])

    def test_wraplength_update_is_deferred_not_synchronous(self):
        self.host._update_status_wraplength(SimpleNamespace(width=640))
        self.assertIsNotNone(self.host._status_wrap_job)
        self.assertEqual(self.host.status_label.cget("wraplength"), 400)

        self._pump(0.2)
        self.assertEqual(self.host.status_label.cget("wraplength"), 616)
        self.assertIsNone(self.host._status_wrap_job)


class TooltipPositionTests(unittest.TestCase):
    def test_keeps_position_inside_secondary_monitor(self):
        work_area = (1920, 0, 3600, 1032)

        self.assertEqual(
            clamp_tooltip_position(2500, 500, 300, 100, work_area),
            (2500, 500),
        )
        self.assertEqual(
            clamp_tooltip_position(3590, 1030, 300, 100, work_area),
            (3296, 928),
        )
        self.assertEqual(
            clamp_tooltip_position(1900, 300, 300, 100, work_area),
            (1924, 300),
        )

    def test_keeps_position_inside_left_monitor(self):
        work_area = (-1920, 0, 0, 1032)

        self.assertEqual(
            clamp_tooltip_position(-1930, 10, 300, 100, work_area),
            (-1916, 10),
        )

    def test_oversized_tooltip_anchors_to_work_area_corner(self):
        work_area = (0, 0, 200, 100)

        self.assertEqual(
            clamp_tooltip_position(50, 50, 300, 200, work_area),
            (4, 4),
        )


class HelpContentTests(unittest.TestCase):
    def test_cloud_api_and_lm_studio_links(self):
        self.assertEqual(
            dict(HELP_LINKS),
            {
                "Google Gemini API (Google AI Studio)": (
                    "https://aistudio.google.com/"
                ),
                "Groq API": "https://console.groq.com/",
                "LM Studio": "https://lmstudio.ai/",
            },
        )

    def test_intro_entries_include_overview_context_and_all_links(self):
        entries = HelpTabMixin._help_intro_entries(None)
        links = [value for tag, value in entries if tag == "link"]
        text = "".join(
            value if isinstance(value, str) else value[1] for _, value in entries
        )
        self.assertIn(("LM Studio", "https://lmstudio.ai/"), links)
        self.assertIn(
            ("Google Gemini API (Google AI Studio)", "https://aistudio.google.com/"),
            links,
        )
        self.assertIn(("Groq API", "https://console.groq.com/"), links)
        self.assertIn("PWLP was tested with", text)
        for phrase in (
            "System prompt matters most",
            "free cloud key",
            "GPU VRAM usage",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_license_entries_cover_disclaimer(self):
        text = " ".join(
            value if isinstance(value, str) else value[1]
            for _, value in LICENSE_ENTRIES
        ).lower()
        for phrase in (
            "mit license",
            "permission is hereby granted",
            "completely free",
            "as-is",
            "warranty",
            "responsible",
            "liability",
            "data loss",
            "third-party",
            "lm studio",
            "gemini",
            "groq",
            "not affiliated",
            "endorsed",
            "ko-fi",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_license_entries_include_kofi_link(self):
        links = [value for tag, value in LICENSE_ENTRIES if tag == "link"]
        self.assertIn(("Ko-fi", KOFI_URL), links)


class ReleaseFilesTests(unittest.TestCase):
    root = Path(__file__).resolve().parent.parent

    def test_requirements_include_tkinterdnd2_and_drop_unused_groq(self):
        text = (self.root / "requirements.txt").read_text(encoding="utf-8")
        names = {
            re.split(r"[<>=!~\s]", line.strip(), maxsplit=1)[0].lower()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        self.assertIn("tkinterdnd2", names)
        self.assertNotIn("groq", names)

    def test_root_license_is_mit(self):
        text = (self.root / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2026 The PWLP Authors", text)
        self.assertIn("Permission is hereby granted", text)

    def test_readme_documents_setup_and_safety_notes(self):
        text = (self.root / "README.md").read_text(encoding="utf-8")
        for phrase in (
            "pip install -r requirements.txt",
            "LM Studio",
            "Gemini",
            "Groq",
            "NVIDIA",
            "Reset / Delete All Personal Data",
            "https://ko-fi.com/promptwriter",
            "as-is",
            "MIT License",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_third_party_notices_cover_bundled_components(self):
        text = (self.root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for phrase in (
            "CustomTkinter",
            "tkinterdnd2",
            "TkDND",
            "Requests",
            "Pillow",
            "nvidia-ml-py",
            "Roboto",
            "Apache License 2.0",
            "MPL-2.0",
            "PSF License 2.0",
            "George Petasis",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


class _HelpTabHost(tkinter.Frame, HelpTabMixin):
    def __init__(self, master):
        super().__init__(master)
        self.help_tab = tkinter.Frame(self)
        self.help_tab.pack(fill="both", expand=True)

    def _add_tooltip(self, widget, text):
        return None


class HelpTabLayoutTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tkinter.Tk()
        except tkinter.TclError:
            self.skipTest("Tk is unavailable")
        self.root.withdraw()
        self.host = _HelpTabHost(self.root)
        self.host.pack(fill="both", expand=True)
        self.host._build_help_tab()
        self.root.update_idletasks()

    def tearDown(self):
        try:
            self.root.destroy()
        except tkinter.TclError:
            pass

    def test_inner_tabs_exist(self):
        tabview = self.host.help_tabview
        self.assertIsNotNone(tabview.tab(HELP_GUIDE_TAB))
        self.assertIsNotNone(tabview.tab(HELP_LICENSE_TAB))
        self.assertEqual(HELP_GUIDE_TAB, "Guide / Usage")
        self.assertEqual(HELP_LICENSE_TAB, "License & Disclaimer")

    def test_kofi_button_sits_between_intro_and_guide(self):
        rows = (
            int(self.host.help_intro_text.grid_info()["row"]),
            int(self.host.kofi_button.grid_info()["row"]),
            int(self.host.help_text.grid_info()["row"]),
        )
        self.assertEqual(rows, (0, 1, 2))
        self.assertEqual(
            self.host.kofi_button.cget("text"), "Support PWLP on Ko-fi"
        )

    def test_intro_renders_clickable_lm_studio_link(self):
        raw = self.host.help_intro_text._textbox
        link_tags = [tag for tag in raw.tag_names() if tag.startswith("link_")]
        self.assertEqual(len(link_tags), 3)
        self.assertIn("https://lmstudio.ai/", raw.get("1.0", "end"))
        self.assertTrue(
            raw.tk.call(raw._w, "tag", "bind", link_tags[0], "<Button-1>")
        )
        self.assertEqual(KOFI_URL, "https://ko-fi.com/promptwriter")

    def test_guide_starts_with_generator_tab_after_kofi(self):
        intro = self.host.help_intro_text._textbox.get("1.0", "end")
        guide = self.host.help_text._textbox.get("1.0", "end")
        for context in (
            "System prompt matters most",
            "free cloud key",
            "GPU VRAM usage",
        ):
            with self.subTest(phrase=context):
                self.assertIn(context, intro)
                self.assertNotIn(context, guide)
        first_line = next(line for line in guide.splitlines() if line.strip())
        self.assertEqual(first_line.strip(), "Generator tab")
        for heading in (
            "Generator tab",
            "Image to Prompt tab",
            "Settings tab",
            "History tab",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, guide)

    def test_license_tab_renders_disclaimer(self):
        raw = self.host.help_license_text._textbox
        text = raw.get("1.0", "end")
        lowered = text.lower()
        self.assertIn("mit license", lowered)
        self.assertIn("permission is hereby granted", lowered)
        self.assertIn("as-is", lowered)
        self.assertIn("no liability", lowered)
        self.assertIn("third-party names", lowered)
        self.assertIn(KOFI_URL, text)
        link_tags = [tag for tag in raw.tag_names() if tag.startswith("link_")]
        self.assertTrue(link_tags)
        self.assertTrue(
            raw.tk.call(
                raw._w, "tag", "bind", link_tags[-1], "<Button-1>"
            )
        )

    def test_intro_height_fits_content_and_caps_for_guide(self):
        host = self.host
        with (
            patch.object(
                host.help_intro_text._textbox, "count", return_value=(204,)
            ),
            patch.object(host.help_tabview, "winfo_height", return_value=600),
        ):
            host._fit_help_intro_height()
        self.assertEqual(int(float(host.help_intro_text.cget("height"))), 214)

        with (
            patch.object(
                host.help_intro_text._textbox, "count", return_value=(1000,)
            ),
            patch.object(host.help_tabview, "winfo_height", return_value=600),
        ):
            host._fit_help_intro_height()
        self.assertEqual(int(float(host.help_intro_text.cget("height"))), 330)

    def test_kofi_button_opens_browser_safely(self):
        with patch.object(
            help_tab.webbrowser, "open", return_value=True
        ) as opener:
            self.assertTrue(self.host._open_kofi())
        opener.assert_called_once_with(KOFI_URL, new=2)

        with patch.object(
            help_tab.webbrowser, "open", side_effect=OSError("no browser")
        ):
            self.assertFalse(self.host._open_kofi())


class TooltipDismissBindingTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tkinter.Tk()
        except tkinter.TclError:
            self.skipTest("Tk is unavailable")
        self.root.withdraw()
        self.frame = tkinter.Frame(self.root)
        self.frame.pack()

    def tearDown(self):
        try:
            self.root.destroy()
        except tkinter.TclError:
            pass

    def _bind_script(self, sequence):
        return self.root.tk.call("bind", self.root._w, sequence) or ""

    def _add_labels(self, count, prefix):
        for index in range(count):
            label = tkinter.Label(self.frame, text=f"{prefix} {index}")
            label.pack()
            ToolTip(label, f"{prefix} tip {index}")

    def test_toplevel_dismiss_bindings_do_not_grow_with_tooltips(self):
        self._add_labels(3, "first")
        unmap_before = self._bind_script("<Unmap>")
        focus_before = self._bind_script("<FocusOut>")

        self._add_labels(40, "extra")

        self.assertEqual(self._bind_script("<Unmap>"), unmap_before)
        self.assertEqual(self._bind_script("<FocusOut>"), focus_before)
        self.assertLess(len(unmap_before), 1000)

    def test_hide_without_open_window_is_a_no_op(self):
        label = tkinter.Label(self.frame, text="x")
        label.pack()
        tooltip = ToolTip(label, "tip")

        tooltip._hide()

        self.assertIsNone(tooltip._window)


if __name__ == "__main__":
    unittest.main()
