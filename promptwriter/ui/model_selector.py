import json
import threading

from promptwriter.config import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_FALLBACK_MODELS,
    LOCAL_ENGINE,
    model_cache_key,
)
from promptwriter.services.model_catalog import fetch_provider_models
from promptwriter.storage.config_store import load_config, save_config


class ModelSelectorMixin:
    def _set_api_model_options(self, context, engine):
        cached_models = self.available_models.get(engine, [])
        models = []
        if isinstance(cached_models, (list, tuple)):
            for model in cached_models:
                if model is None:
                    continue
                model_name = str(model).strip()
                if model_name and model_name not in models:
                    models.append(model_name)
        if context == "generator":
            menu = self.api_model_menu
            selected_models = self.generator_selected_models
            saved_model = self.saved_generator_api_model
            saved_engine = self.saved_generator_api_engine
        else:
            menu = self.image_api_model_menu
            selected_models = self.vision_selected_models
            saved_model = self.saved_vision_api_model
            saved_engine = self.saved_vision_api_engine

        selected_model = selected_models.get(engine, "")
        if not models:
            placeholder = selected_model or (
                DEFAULT_GEMINI_MODEL if engine == "Gemini" else "Fetch models first"
            )
            model_list = [str(placeholder)]
            menu.configure(values=model_list)
            menu.set(model_list[0])
            return
        model_list = [str(model) for model in models]
        menu.configure(values=model_list)
        menu.set(model_list[0])
        if saved_engine == engine:
            if saved_model in model_list:
                selected_model = saved_model
            if context == "generator":
                self.saved_generator_api_model = None
                self.saved_generator_api_engine = None
            else:
                self.saved_vision_api_model = None
                self.saved_vision_api_engine = None
        if selected_model not in model_list:
            selected_model = (
                DEFAULT_GEMINI_MODEL
                if engine == "Gemini" and DEFAULT_GEMINI_MODEL in model_list
                else model_list[0]
            )
        menu.set(selected_model)
        selected_models[engine] = selected_model

    def _on_engine_changed(self, engine):
        self._set_api_model_options("generator", engine)
        self._update_lm_studio_controls(
            engine,
            self.generator_auto_unload_checkbox,
            self.generator_clear_vram_button,
            self.generator_lm_studio_status_label,
        )
        self.after(200, self._refresh_lm_studio_status)

    def _on_generator_engine_selected(self, engine):
        self._on_engine_changed(engine)
        self.update_engine_color()

    def _on_image_engine_selected(self, engine):
        self._on_image_engine_changed(engine)
        self.update_engine_color()

    def _on_api_model_changed(self, model):
        engine = self.engine_menu.get()
        if model and model != "Fetch models first":
            self.generator_selected_models[engine] = model

    def _on_image_engine_changed(self, engine):
        self._set_api_model_options("vision", engine)
        self._update_lm_studio_controls(
            engine,
            self.image_auto_unload_checkbox,
            self.image_clear_vram_button,
            self.image_lm_studio_status_label,
        )
        self.after(200, self._refresh_lm_studio_status)

    def _on_image_api_model_changed(self, model):
        engine = self.image_engine_menu.get()
        if model and model != "Fetch models first":
            self.vision_selected_models[engine] = model

    def _fetch_available_models(self, context):
        if context == "generator":
            engine = self.engine_menu.get()
            status_label = self.status_label
        else:
            engine = self.image_engine_menu.get()
            status_label = self.image_status_label
        try:
            config_data = load_config()
        except (OSError, ValueError, json.JSONDecodeError) as error:
            status_label.configure(
                text=f"Could not read saved API settings: {error}",
                text_color="red",
            )
            return
        api_key = (
            ""
            if engine == LOCAL_ENGINE
            else config_data.get(
                "gemini_api_key" if engine == "Gemini" else "groq_api_key", ""
            )
        )
        if not isinstance(api_key, str):
            api_key = ""
        api_key = api_key.strip()
        if engine != LOCAL_ENGINE and not api_key:
            status_label.configure(
                text=f"Save your {engine} API key in Settings before fetching models.",
                text_color="red",
            )
            return
        self._set_fetch_buttons_state("disabled")
        status_label.configure(
            text=f"Fetching {engine} models...", text_color="gray"
        )
        threading.Thread(
            target=self._fetch_models_worker,
            args=(engine, api_key, context),
            daemon=True,
        ).start()

    def _fetch_models_worker(self, engine, api_key, context):
        try:
            models, fallback_message = fetch_provider_models(engine, api_key)
        except Exception as error:
            if engine == LOCAL_ENGINE:
                print(f"Could not fetch Local models: {error}")
            if engine == "Gemini":
                self.after(
                    0,
                    self._on_models_fetched,
                    engine,
                    GEMINI_FALLBACK_MODELS.copy(),
                    f"Could not fetch Gemini models: {error}. Showing fallback models.",
                    context,
                )
            else:
                self.after(0, self._on_models_error, engine, error, context)
            return
        self.after(0, self._on_models_fetched, engine, models, fallback_message, context)

    def _on_models_fetched(
        self, engine, models, fallback_message=None, context="generator"
    ):
        model_list = []
        if isinstance(models, (list, tuple)):
            for model in models:
                if model is None:
                    continue
                model_name = str(model).strip()
                if model_name and model_name not in model_list:
                    model_list.append(str(model_name))
        if not model_list:
            self.available_models[engine] = []
            self._on_models_error(
                engine,
                fallback_message or f"No {engine} models were returned.",
                context,
            )
            return
        models = model_list
        self.available_models[engine] = models
        cache_error = None
        if fallback_message is None:
            try:
                config_data = load_config()
                available_models = config_data.get("available_models", {})
                if not isinstance(available_models, dict):
                    available_models = {}
                available_models[engine] = models
                config_data["available_models"] = available_models
                config_data[model_cache_key(engine)] = models
                save_config(config_data)
                self.config_data = config_data
            except (OSError, ValueError, json.JSONDecodeError) as error:
                cache_error = error

        if self.engine_menu.get() == engine:
            self._set_api_model_options("generator", engine)
        if self.image_engine_menu.get() == engine:
            self._set_api_model_options("vision", engine)
        self._set_fetch_buttons_state("normal")
        status_label = (
            self.status_label if context == "generator" else self.image_status_label
        )
        status_label.configure(
            text=(
                fallback_message
                or (
                    f"Fetched {len(models)} {engine} models, but could not cache them: "
                    f"{cache_error}"
                    if cache_error
                    else f"Fetched and cached {len(models)} {engine} models."
                )
            ),
            text_color="red" if fallback_message or cache_error else "green",
        )

    def _on_models_error(self, engine, error, context):
        self._set_fetch_buttons_state("normal")
        for selected_engine, menu in (
            (self.engine_menu.get(), self.api_model_menu),
            (self.image_engine_menu.get(), self.image_api_model_menu),
        ):
            if selected_engine == engine:
                model_list = ["Fetch models first"]
                menu.configure(values=model_list)
                menu.set(model_list[0])
        status_label = (
            self.status_label if context == "generator" else self.image_status_label
        )
        status_label.configure(
            text=f"Could not fetch {engine} models: {error}", text_color="red"
        )

    def _set_fetch_buttons_state(self, state):
        self.generator_fetch_button.configure(state=state)
        self.image_fetch_button.configure(state=state)
