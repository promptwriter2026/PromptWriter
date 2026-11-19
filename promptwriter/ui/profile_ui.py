from promptwriter.storage.profile_store import (
    default_profile,
    delete_profile,
    format_profile_summary,
    get_saved_profile,
    merge_profile,
    save_profile,
)
from promptwriter.ui.profile_dialog import ModelProfileDialog


class ProfileMixin:
    def _profile_context(self, mode):
        if mode == "vision":
            return {
                "engine_menu": self.image_engine_menu,
                "model_menu": self.image_api_model_menu,
                "temperature_var": self.vision_temp_var,
                "temperature_label": self.vision_temp_label,
                "temperature_max": 1.0,
                "summary_label": self.vision_profile_label,
                "status_label": self.image_status_label,
            }
        return {
            "engine_menu": self.engine_menu,
            "model_menu": self.api_model_menu,
            "temperature_var": self.generator_temp_var,
            "temperature_label": self.generator_temp_label,
            "temperature_max": 1.5,
            "summary_label": self.generator_profile_label,
            "status_label": self.status_label,
        }

    def _load_active_profile(self, mode):
        context = self._profile_context(mode)
        engine = context["engine_menu"].get()
        model_id = context["model_menu"].get().strip()
        if not model_id or model_id == "Fetch models first":
            return default_profile(engine, mode), False
        saved = get_saved_profile(engine, model_id, mode)
        return merge_profile(saved, engine, mode), saved is not None

    def _refresh_profile(self, mode, sync_temperature=None):
        if not hasattr(self, "generator_profile_label"):
            return
        if sync_temperature is None:
            sync_temperature = getattr(self, "_profiles_sync_enabled", False)
        profile, has_saved = self._load_active_profile(mode)
        if mode == "vision":
            self.vision_profile = profile
            self.vision_profile_saved = has_saved
        else:
            self.generator_profile = profile
            self.generator_profile_saved = has_saved

        context = self._profile_context(mode)
        if sync_temperature:
            temperature = min(
                max(profile["temperature"], 0.0), context["temperature_max"]
            )
            context["temperature_var"].set(temperature)
            self._update_profile_temperature_label(mode)

        self._update_profile_summary(mode)

    def _update_profile_temperature_label(self, mode):
        if mode == "vision":
            self._update_vision_temp_label()
        else:
            self._update_generator_temp_label()

    def _update_profile_summary(self, mode):
        label = getattr(
            self,
            "vision_profile_label" if mode == "vision" else "generator_profile_label",
            None,
        )
        if label is None:
            return
        context = self._profile_context(mode)
        profile = (
            self.vision_profile if mode == "vision" else self.generator_profile
        )
        has_saved = (
            self.vision_profile_saved
            if mode == "vision"
            else self.generator_profile_saved
        )
        temperature = context["temperature_var"].get()
        label.configure(
            text=format_profile_summary(
                context["engine_menu"].get(),
                profile,
                has_saved,
                temperature=temperature,
            )
        )

    def _open_profile_dialog(self, mode):
        existing = getattr(self, "_profile_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        context = self._profile_context(mode)
        engine = context["engine_menu"].get()
        model_id = context["model_menu"].get().strip()
        if not model_id or model_id == "Fetch models first":
            context["status_label"].configure(
                text=f"Select an {engine} model before editing its profile.",
                text_color="red",
            )
            return
        profile, _ = self._load_active_profile(mode)
        profile = dict(profile)
        profile["temperature"] = context["temperature_var"].get()
        self._profile_dialog = ModelProfileDialog(
            self,
            engine,
            model_id,
            profile,
            on_save=lambda values: self._save_active_profile(mode, values),
            on_reset=lambda: self._reset_active_profile(mode),
        )

    def _save_active_profile(self, mode, values):
        context = self._profile_context(mode)
        engine = context["engine_menu"].get()
        model_id = context["model_menu"].get().strip()
        profile = save_profile(engine, model_id, mode, values)
        if mode == "vision":
            self.vision_profile = profile
            self.vision_profile_saved = True
        else:
            self.generator_profile = profile
            self.generator_profile_saved = True
        temperature = min(
            max(profile["temperature"], 0.0), context["temperature_max"]
        )
        context["temperature_var"].set(temperature)
        self._update_profile_temperature_label(mode)
        self._update_profile_summary(mode)
        if hasattr(self, "_refresh_saved_profiles"):
            self._refresh_saved_profiles()

    def _reset_active_profile(self, mode):
        context = self._profile_context(mode)
        delete_profile(
            context["engine_menu"].get(),
            context["model_menu"].get().strip(),
            mode,
        )
        self._refresh_profile(mode, sync_temperature=True)
        if hasattr(self, "_refresh_saved_profiles"):
            self._refresh_saved_profiles()
