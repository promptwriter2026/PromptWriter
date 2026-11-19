import threading

import requests

from promptwriter.config import LOCAL_ENGINE
from promptwriter.services.lm_studio_api import (
    get_lm_studio_loaded_models,
    unload_lm_studio_models,
)


class LMStudioMixin:
    def _update_lm_studio_controls(
        self, engine, auto_unload_checkbox, clear_vram_button, status_label
    ):
        state = "normal" if engine == LOCAL_ENGINE else "disabled"
        auto_unload_checkbox.configure(state=state)
        clear_vram_button.configure(state=state)
        status_label.configure(state=state)

    def _has_local_engine_selected(self):
        return (
            self.engine_menu.get() == LOCAL_ENGINE
            or self.image_engine_menu.get() == LOCAL_ENGINE
        )

    def _refresh_lm_studio_status(self):
        if not self._has_local_engine_selected():
            return
        if self._lm_studio_status_check_in_progress:
            return
        self._lm_studio_status_check_in_progress = True
        self.after(200, self._start_lm_studio_status_worker)

    def _start_lm_studio_status_worker(self):
        if not self._has_local_engine_selected():
            self._lm_studio_status_check_in_progress = False
            return
        threading.Thread(
            target=self._lm_studio_status_worker, daemon=True
        ).start()

    def _lm_studio_status_worker(self):
        try:
            loaded_models = get_lm_studio_loaded_models()
            model_names = list(dict.fromkeys(name for name, _ in loaded_models))
            status = ", ".join(model_names) if model_names else "Empty"
            color = "gray"
        except (requests.exceptions.RequestException, ValueError) as error:
            status = f"Unavailable: {error}"
            color = "red"
        self.after(0, self._finish_lm_studio_status_refresh, status, color)

    def _finish_lm_studio_status_refresh(self, status, color):
        status_text = f"LM Studio Status: {status}"
        self.generator_lm_studio_status_label.configure(
            text=status_text, text_color=color
        )
        self.image_lm_studio_status_label.configure(
            text=status_text, text_color=color
        )
        self._lm_studio_status_check_in_progress = False
        if self._has_local_engine_selected():
            self.after(4000, self._refresh_lm_studio_status)

    def _clear_lm_studio_vram(self):
        self.generator_clear_vram_button.configure(state="disabled")
        self.image_clear_vram_button.configure(state="disabled")
        self._set_lm_studio_status("Unloading...", "gray")
        threading.Thread(
            target=self._clear_lm_studio_vram_worker,
            daemon=True,
        ).start()

    def _clear_lm_studio_vram_worker(self):
        try:
            with self._lm_studio_unload_lock:
                unload_lm_studio_models()
            loaded_models = get_lm_studio_loaded_models()
            model_names = list(dict.fromkeys(name for name, _ in loaded_models))
            status = ", ".join(model_names) if model_names else "Empty"
            color = "gray"
        except (requests.exceptions.RequestException, ValueError) as error:
            status = f"Unload failed: {error}"
            color = "red"
        self.after(0, self._finish_lm_studio_unload, status, color)

    def _finish_lm_studio_unload(self, status, color):
        self._set_lm_studio_status(status, color)
        self._update_lm_studio_controls(
            self.engine_menu.get(),
            self.generator_auto_unload_checkbox,
            self.generator_clear_vram_button,
            self.generator_lm_studio_status_label,
        )
        self._update_lm_studio_controls(
            self.image_engine_menu.get(),
            self.image_auto_unload_checkbox,
            self.image_clear_vram_button,
            self.image_lm_studio_status_label,
        )

    def _set_lm_studio_status(self, status, color):
        status_text = f"LM Studio Status: {status}"
        self.generator_lm_studio_status_label.configure(
            text=status_text, text_color=color
        )
        self.image_lm_studio_status_label.configure(
            text=status_text, text_color=color
        )

    def _auto_unload_lm_studio_model(self):
        try:
            with self._lm_studio_unload_lock:
                unload_lm_studio_models()
            self.after(0, self._refresh_lm_studio_status)
        except (requests.exceptions.RequestException, ValueError) as error:
            self.after(
                0,
                self._set_lm_studio_status,
                f"Unload failed: {error}",
                "red",
            )
