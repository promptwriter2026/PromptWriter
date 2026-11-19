# Project Status

## Goals
Build a modular Python desktop application with a CustomTkinter interface that expands rough ideas into detailed English text-to-image prompts using selectable LLM providers and model-specific system instructions.

## Architecture
- `main.py`: Entry point; runs startup initialization and launches the app.
- `promptwriter/config.py`: Application paths, engine constants, and defaults.
- `promptwriter/storage/`: JSON config/app-file seeding and the SQLite history layer.
- `promptwriter/services/`: LLM client, LM Studio API, model catalog, LoRA rules, prompt assembly, image preparation, GPU VRAM monitoring, and ComfyUI/Forge Neo VRAM cleanup.
- `promptwriter/ui/`: CustomTkinter app split into tab/view mixins plus shared tooltip/text-action helpers.
- `config.json`: API keys and selected LLM engine.
- `system_prompts/`: Model-specific instructions, loaded from `.txt` files.
- `data/cameras.json`: Camera and lens choices.
- `data/lora_profiles.json`: Character/LoRA profiles.
- `data/model_profiles.json`: Per-model sampling/context profiles (ignored user runtime data).
- `data/history.db`: Generated prompt history in SQLite.

## Implemented Features
- Startup logic creates missing data/config directories and JSON files, initializes the SQLite history database, and seeds a default model prompt when none exists.
- Added the initial Generator, Settings, and History tabs with data-driven model/camera/LoRA controls.
- Added API-key and engine settings UI, camera/system-prompt managers, history selection, and clipboard actions.
- Added `requirements.txt` for CustomTkinter, Gemini, and Groq dependencies.
- Confirmed startup initialization in an isolated directory and smoke-tested GUI creation.
- Generate now assembles model, optional LoRA, camera, and user instructions and calls Gemini or Groq on a background thread.
- Generation results and errors update the GUI through Tk's event loop; successful outputs are saved to history.
- Clipboard copy now reports empty/copy errors and resets its success feedback after 1.5 seconds.
- Mocked Gemini/Groq generation, failure handling, history persistence, prompt assembly, and clipboard behavior pass.
- Main generation status/error text wraps to the available width.
- Settings can fetch Gemini/Groq model lists asynchronously and select/cache provider models.
- Selected API models and fetched model lists are saved in `config.json`; generation calls the selected model, with `gemini-3.8-flash` as the Gemini fallback.
- Mocked model fetching/filtering, selection persistence, and use of the selected model pass.
- Gemini model fetching now keeps only `gemini-` text-generation models, excludes preview/audio/image/specialized names, and shows known free-tier fallback choices after fetch errors or empty filtered results.
- Targeted checks for filtering, non-generation model rejection, and Gemini fallback behavior pass.
- Groq model fetching now uses `requests` against the Groq REST models endpoint with the saved config API key; it keeps all returned model IDs except those containing `guard`, `safeguard`, `whisper`, `orpheus`, or `canopylabs`.
- Mocked Groq REST response parsing, request headers/key, dropdown population, and HTTP error reporting pass.
- Groq filtering preserves API order and selects the first valid model after fetching, without forcing a Llama-family model.
- Blacklist tests using GPT-OSS, Qwen, Allam, guard, Whisper, Orpheus, and Canopy Labs IDs pass.
- Moved the active LLM engine and selected API model controls to the top of the Generator tab; Settings retains API keys, model fetching, and Save Settings.
- Changing the Generator engine immediately updates the API model options from cached config/memory, and generation reads engine/model directly from those controls while continuing to load API keys from config.
- Mocked UI checks verify control placement, switching model lists, generation with the current UI selection, and saving the active selection.
- Added a Clear button beside Rough idea and a Tk context menu with Cut, Copy, Paste, and Select All for both rough idea and generated output textboxes.
- Verified the Clear action, right-click bindings, Select All, Cut/Copy/Paste, and copying from the read-only output textbox.
- Replaced the Settings system-prompt name Entry with an editable Combobox populated from `.txt` prompt filenames.
- Loading reads the prompt named in that Combobox; saving refreshes both the prompt-name list and Generator target-model list and selects the saved prompt.
- GUI checks verify existing prompt load/edit and new prompt creation, dropdown refresh, and Generator availability.
- Bound the Settings system-prompt editor to the shared right-click Cut/Copy/Paste/Select All menu and Select All virtual-event handler.
- Verified the prompt editor's `<Button-3>` opens the shared menu for the correct widget and each menu action routes its corresponding Tk virtual event.
- Added an Image to Prompt tab with shared LLM engine/model, target system prompt, and LoRA controls; image selection/preview; optional context; generation output; and clipboard copy.
- Added proportional image preview and a JPEG/Base64 preparation helper that limits the image's longest edge to 1024 pixels.
- Gemini and Groq generation requests now support image payloads, and image analysis/generation runs on a background thread with UI-safe success/error updates.
- Added Pillow as an explicit dependency. Mocked checks pass for image optimization, both provider payload formats, shared selector synchronization, and image generation.
- History records include generation settings, engine, and API model for each successful generation.
- The History tab supports reviewing generated prompts and original ideas, restoring original ideas to Generator, and copying selected prompts.
- Groq generation now extracts only `response.choices[0].message.content`, validates it is text, and rejects unexpected numeric/metadata values.
- Mocked Groq text extraction and non-text response validation pass.
- Traced generation result flow: Groq `message.content` -> string-only `generated_prompt` -> `_on_generation_success` -> output textbox. Added guards against non-string or empty results at the UI boundary.
- End-to-end mocked Groq text reaches the output textbox unchanged; numeric callback values are rejected before insertion.
- Generation now uses live HTTP POST requests for Gemini and Groq, with API keys read from `config.json`; no SDK generation client, mock output, timer, or fallback prompt is used.
- API/network failures are shown as `Error:` status messages and do not create generated output; request construction, parsing, missing-key, and timeout checks pass.
- Full `main.py` scan confirms there is no random generator, execution timer, mock generation value, or exception fallback output.
- Numeric-only provider responses are rejected as invalid prompts, stale output is cleared at the start of a valid generation attempt, and numeric-only legacy history entries cannot be loaded into the generated output.
- Worker exceptions now pass `str(error)` to the status callback; mocked checks confirm network errors are visible and no numeric value reaches the output textbox.
- Added a Settings-tab LoRA manager with editable name, trigger words, and character profile; save/delete persist `data/lora_profiles.json`, load fills the editor, and changes immediately synchronize Generator and Image to Prompt options.
- Both prompt paths now inject strict LoRA instructions requiring trigger words first and preserving user-specified dynamic attributes over profile defaults; additional image context is included in the override rule.
- Successful text and image generations enforce the selected trigger words at the beginning of the returned prompt before display/history handling.
- LoRA manager CRUD, file persistence, dropdown synchronization, both request assemblies, override instructions, and trigger-prefix enforcement pass isolated GUI checks; Python syntax and diagnostics pass.
- Image to Prompt now uses a dedicated Character Replacement Rule for active LoRAs, replacing the source person's physical appearance with the profile while preserving pose, clothing, actions, expression, and the original scene; ordinary Generator requests retain the standard LoRA instructions.
- Verified image-specific rule content, trigger words at prompt start, disabled behavior when no LoRA is selected, and unchanged text-generation instructions in isolated GUI checks; diagnostics pass.
- Updated Generator LoRA instructions to separate immutable core identity (ethnicity, age, facial features, base body type) from mutable styling (hair color/style, makeup, clothing), apply explicit user styling choices, use profile styling defaults otherwise, and require trigger words first. Image to Prompt's Character Replacement Rule remains isolated and unchanged.
- Verified Generator rule content, no-LoRA behavior, Image to Prompt isolation, Python syntax, and diagnostics.
- SQLite history supports search across rough ideas and generated prompts, a favorites-only switch, ★ list markers, selected-entry favorite toggling, and text export of favorite prompts.
- Rough idea state persists between application sessions in `rough_idea_cache.txt` in the application directory: startup restores the saved text, and closing the window saves the current text.
- Text generation requests use `top_p=0.95` and Vision requests use `top_p=0.2`; Groq requests allow up to 6500 tokens and Local requests keep `max_tokens` fixed at 2048.
- The Generator Temperature slider ranges from 0.0 to 1.5 (Vision remains 0.0 to 1.0); both values are passed as floats in Gemini, Groq, and Local request payloads, and saved Generator values through 1.5 are restored.
- Removed the former Context Length slider; Local generation no longer sends an `n_ctx` value or context length in its request payload.
- Generation reads `total_tokens` from the API JSON `usage` object and displays the actual usage in the Local and Groq token status labels (alongside Groq quota information when available).

## Work In Progress
- None.

## Pending Tasks
- Validate live provider model fetching/generation when valid credentials are available.

## Known Bugs
- None known.

## VRAM Management Updates
- Removed the Context slider and label from both the Generator and Image to Prompt tabs, along with its state and Local request payload parameter.
- Added an “Auto-Unload Model from VRAM” checkbox, a “Clear VRAM / Unload Model” button, and an LM Studio status label to both Generator and Image to Prompt. The checkbox preference is shared across both tabs.
- These controls are enabled only when the corresponding LLM Engine selection is Local (LM Studio); Gemini and Groq disable them.
- LM Studio status refreshes on Local engine selection and then polls every four seconds. It shows `Empty` when no models are loaded, or the loaded model name(s).
- Status checks use `GET http://127.0.0.1:1234/api/v1/models`; loaded models are identified through each model's `loaded_instances`.
- Manual and automatic unloads use `POST http://127.0.0.1:1234/api/v1/models/unload` with a JSON body containing the loaded instance's `instance_id`. Each loaded instance is unloaded separately.
- Successful Local text and image generations automatically unload loaded models when the shared checkbox is checked. An unload error is shown in the LM Studio status label without discarding the generated prompt.
- Mocked checks pass for loaded-model parsing, unload request construction, omission of `n_ctx`, Local-only UI states, and auto-unload in both generation paths.

## SQLite History Updates
- Replaced JSON history storage with `data/history.db`; old `data/history.json` was deleted without data migration as requested.
- The `generations` table schema is: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `timestamp TEXT`, `source_tab TEXT`, `rough_idea TEXT`, `generated_prompt TEXT`, `engine TEXT`, `model TEXT`, `is_favorite INTEGER DEFAULT 0`, `image_path TEXT`, and `settings_json TEXT`.
- Successful Generator and Image to Prompt generations insert directly into SQLite. `settings_json` contains generation parameters including temperature, profile sampling settings, LoRA, and auto-unload; image records also store their image path.
- Added a shared, enabled-by-default “Enforce Single-Line Prompts” checkbox to Generator and Image to Prompt. When enabled, successful callbacks collapse wrapped lines within paragraphs before both display and SQLite persistence; `settings_json` records the `force_single_line` preference.
- The History content panel now uses “Generated Prompts” and “Original Idea” tabs. “Load back to Generator” restores the original idea and switches to Generator.
- The History list queries only the newest 50 rows, loads prompt bodies only when an entry is selected, formats timestamps and topic snippets, and shows the complete original idea in each button's tooltip.
- Search, favorites-only filtering, favorite toggling, and favorite export now query/update SQLite.

## Backend & API Modernization (Phase 1)
- Prompt assembly now returns separate `system` and `user` parts. Target-model instructions, LoRA rules, and the camera line are sent as a `system` message for Groq and Local; the rough idea or vision context is the `user` message, with the image kept in the multimodal `user` content array.
- Gemini receives the same split through `system_instruction`, with the user text and `inline_data` image in `contents`.
- Reasoning cleanup is centralized in `llm_client.py` and runs before LoRA trigger-prefix enforcement. It strips `<think>`, `<thinking>`, and `<|think|>` blocks case-insensitively, removes unclosed opening tags (truncated output), and raises a clear error when only reasoning remains.
- When LM Studio returns empty `message.content` with a populated `reasoning_content`, the client reports that the output budget was consumed by reasoning and suggests increasing `max_tokens` or disabling thinking mode.
- `request_generated_prompt` accepts optional `top_p`, `min_p`, `repeat_penalty`, and `max_tokens`. Defaults preserve current behavior (top_p 0.95/0.2, Groq 6500 tokens, Local 2048); `min_p` and `repeat_penalty` are sent only to Local and only when explicitly provided.
- Added `load_model(model_key, context_length=None, base_url=None)` for the native `POST /api/v1/models/load` endpoint, ready for the Phase 2 profile system; JIT auto-load behavior is unchanged.
- The LM Studio base URL is configurable via `lm_studio_base_url` in `config.json` (default `http://127.0.0.1:1234`) and is used by generation, model listing, status, and unload.
- Empty-choices errors now report the active engine instead of always naming Groq.
- Added 23 unit tests covering role splitting, vision payloads, think-tag variants and truncation, `reasoning_content`, provider-specific errors, sampling-field gating, `load_model`, and base-URL resolution; tests pass and the GUI smoke check succeeds.

## Groq Model Fetch Fix
- Restored the `return filtered_models` statement that was lost during the v2.0.0 modular refactor; `filter_groq_models` had been returning `None`, so Fetch always reported "Groq returned no available models" even though the API key and network were valid.
- Groq filtering now also excludes models whose advertised `output_modalities` lack `text` and models whose `input_modalities` support neither `text` nor `image`, while retaining the existing `guard`, `safeguard`, `whisper`, `orpheus`, and `canopylabs` blacklist. Models without modality fields are still accepted for backward compatibility.
- Added five unit tests covering filter ordering/deduplication, blacklist and modality exclusions, a mocked Fetch call (URL and auth header, no key in URL), and the empty-result error. All 28 tests pass.
- Live verification against Groq returned 4 usable models: `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` (text + image input), and `allam-2-7b`.

## Model Profiles & Settings (Phase 2)
- Removed local prompt caching entirely: the “Enable Local Prompt Caching” checkbox, variables, callbacks, config persistence, and the `cache_prompt` request field are gone; tests assert it never appears in payloads or the client signature.
- Added `promptwriter/storage/profile_store.py` backed by `data/model_profiles.json` (git-ignored). Profiles are keyed by `(engine, model_id, mode)` so text and vision settings stay separate. Fields: `temperature`, `top_p`, `min_p` (Local), `repeat_penalty` (Local), `max_tokens`, `context_length` (Local, `None` = Auto), `disable_thinking`. Missing fields fall back to engine/mode defaults (text 0.7/0.95, vision 0.1/0.2, Groq 6500 / Local 2048 max tokens).
- Added a compact `⚙` button beside Fetch on both tabs and a one-line profile summary (`Default profile` or e.g. `Temp: 0.60 · Ctx: 8192 · Max: 4096 · Top-P: 0.9 · Min-P: 0.05`). Switching engine, model, or profile reloads the saved profile and syncs the Temp slider.
- Added a modal `Model Profile: <model>` dialog with Temperature, Top-P, Min-P, Repeat Penalty, Max Tokens, Context Length (`Auto`/`4096`/`8192`/`16384`/`32768`), and Disable Thinking, plus Reset to Default / Save Profile / Cancel. Local-only fields are hidden for Gemini and Groq, replaced by a short explanatory note.
- `disable_thinking` is implemented for Local by sending `"reasoning_effort": "none"` (verified against LM Studio; see the v2.2.2 section). Prompt text is never modified, and the field is omitted for Gemini and Groq.
- Explicit `context_length` values are honored before Local generation: `/api/v1/models` is checked, and an unloaded model is loaded via `POST /api/v1/models/load` with that context size. `Auto` keeps the existing JIT behavior and sends no context value.
- Settings now includes an editable LM Studio base URL (`lm_studio_base_url`, default `http://127.0.0.1:1234`) and a Saved model profiles section with a count, readonly list, and Delete action. Deleting the active profile refreshes both tabs and their Temp sliders.
- UI cleanup: the “Enforce Single-Line Prompts” checkbox moved beside the “Generated prompt” / “Output Prompt” header, and menu/control spacing was tightened on both tabs so Local-only controls and the Copy button fit without clipping at 780×600. LM Studio status, auto-unload, and Unload controls are hidden (not just disabled) for Gemini/Groq.
- Verified all four tabs and both profile dialogs (text and vision) at 1000×760 and 780×600 in Gemini and Local states, including output/copy geometry. All 41 unit tests pass.

## Model Profile Preload Fix (v2.2.1)
- Fixed explicit `context_length` never reaching the generation workers: `profile_request_kwargs()` intentionally excludes context (it is not a chat-request field), so `generation_settings.get("context_length")` was always `None` and `ensure_model_loaded()` was skipped, letting LM Studio JIT-load with its default 8192. Added `profile_context_length(engine, profile)` and wired both Generator and Image to Prompt to store it in `generation_settings`; verified the live worker receives 4096.
- Corrected the native load payload to `{"model": <identifier>, "context_length": <int>}`. Live probes against LM Studio 0.4 confirmed `model` is required (`model_key` returns HTTP 400 "Missing required field 'model'"), and unload requires `instance_id`. The earlier `model_key` payload would have failed once the preload trigger fired.
- Context-aware preload: `GET /api/v1/models` loaded instances expose `config.context_length`. If a loaded instance already matches the requested context, no reload happens; if the context differs, only that model's instances are unloaded and the model is reloaded with the requested context. Missing/unreadable instance config is treated as a mismatch. `Auto` leaves existing instances and JIT behavior untouched, and the model-not-found case raises a clear error.
- Load/unload HTTP errors propagate to the generation worker's error handler instead of being swallowed.
- Gemma 4 reasoning: `strip_think_tags()` now also removes `<|channel>thought ... <channel|>` blocks, including unclosed blocks and multiple occurrences, case-insensitively.
- Added four tests (now 45 total): differing-context unload+reload, load-error propagation, Local-only context plumbing, and Gemma channel-thought stripping; updated the payload and matching-context assertions for the corrected `model` field. All 45 tests pass.

## Local Disable-Thinking Fix (v2.2.2)
- The `/no_think` text suffix did not disable reasoning in LM Studio. Live probes against `/v1/chat/completions` (Gemma 4 31B, `max_tokens` 32–64) showed: baseline and `/no_think` both returned empty `content` with 29 `reasoning_tokens`; `"chat_template_kwargs": {"enable_thinking": false}` was accepted with HTTP 200 but had no effect; `"reasoning_effort": "off"` returned HTTP 400; `"reasoning_effort": "none"` returned `content: "OK"` with `reasoning_tokens: 0`; `"minimal"` still spent 47 tokens on reasoning.
- Removed `_append_no_think()` and all prompt-text mutation. Local requests now add `"reasoning_effort": "none"` only when `disable_thinking=True` and omit the field entirely otherwise; Gemini and Groq never receive it. The profile checkbox label is now simply “Disable Thinking”.
- End-to-end live check through `request_generated_prompt()`: `disable_thinking=True` returned `OK`; `disable_thinking=False` hit the reasoning-budget error, confirming the switch is effective.
- Updated payload tests for text and vision (True sets `reasoning_effort`, False omits it, prompt text stays unchanged) and the Local profile-injection test. All 46 tests pass.

## Local Model Switching & Summary Fixes (v2.2.3)
- Local generation now runs the LM Studio pre-flight unconditionally, including when Context Length is `Auto`. `ensure_model_loaded()` queries `GET /api/v1/models` and unloads (by `instance_id`) every loaded instance belonging to a different model before preparing the target model, preventing stale VRAM instances after switching models.
- Target-model behavior is unchanged otherwise: explicit context reloads only on a mismatch, `Auto` reuses a loaded target or leaves an unloaded one for JIT loading, and unload/load HTTP errors propagate to the worker's error handler. The calls run in the generation worker thread, so the UI stays responsive.
- Removed the `context_length is not None` gate in both the Generator and Image to Prompt workers; `profile_context_length()` still supplies the explicit value or `None`.
- Local profile summaries now always end with `Think: Off` or `Think: On` instead of showing `No-Think` only when disabled. Gemini/Groq summaries are unchanged.
- Added three tests (now 48 total): unloading a different loaded model with `Auto`, preserving the loaded target while unloading others with `Auto`, and Auto display-name matching that leaves an unloaded model for JIT loading; also asserts `Think: On`/`Think: Off` in the summary. All 48 tests pass.

## Real-Time VRAM Monitor & Pre-Flight (Phase 3)
- Added `promptwriter/services/vram_monitor.py` using `nvidia-ml-py` (`pynvml`). NVML is initialized once behind a lock, shut down on app exit, and any missing module/GPU/driver leaves the monitor in an "unavailable" state that returns `None` instead of raising. GPU 0 usage is returned as `used_gb`, `total_gb`, and `percent`.
- The main window now has a single global `VRAM: X.X / Y.Y GB (ZZ%)` label in the top-right corner, placed in the empty space to the right of the `History` tab and vertically centered on the tab bar. It is polled every 2 seconds, stops on window close, and shows `VRAM: N/A` when NVML is unavailable. Colors: green below 70%, orange from 70% to 85%, red above 85%.
- Layout checks at 1000×760 and 780×600 (Generator, Image to Prompt, Settings) confirm the label stays right of the tab bar (72 px gap at 780 px width) with zero vertical-center offset and no tab clipping.
- Added `promptwriter/services/vram_cleanup_api.py` with `free_comfyui_vram` (`POST /free` with `{"unload_models": true, "free_memory": true}`), `free_forge_vram` (`POST /sdapi/v1/unload-checkpoint` with `{}`), and `free_external_vram`, which skips blank URLs, swallows connection/timeout/HTTP errors, and returns the backends that responded. Both calls default to a 1.5 s timeout.
- `config.json` now stores `comfyui_base_url` (default `http://127.0.0.1:8188`) and `forge_base_url` (default `http://127.0.0.1:7860`). Both are editable on the Settings tab directly below the LM Studio base URL and are persisted by Save Settings; blank values fall back to the defaults.
- Local generation on both Generator and Image to Prompt now runs a pre-flight before the worker starts: when GPU VRAM is above 50% and LM Studio reports no loaded model, a modal `High VRAM Usage Detected` dialog offers three actions. `Unload & Load` passes a flag to the background worker, which calls `free_external_vram`, shows an "Unloading ComfyUI / Forge Neo VRAM..." status, waits 1.0 s when at least one backend succeeded, and then continues with the normal Local load/generation pre-flight. `Load Anyway` starts the normal Local flow immediately without freeing external VRAM. `Cancel` closes the dialog and returns without unloading, loading, generating, disabling buttons, or clearing the current output. If LM Studio cannot be reached or VRAM is unavailable, the prompt is skipped.
- Added two unit tests (now 70 total) for the `> 50%` boundary and the three dialog outcomes; the existing VRAM monitor, cleanup payload/timeout, blank-URL, and error-handling tests continue to pass.

## Version History
- 2026-11-19 — v2.3.1: Lowered the Local pre-flight VRAM trigger from 75% to 50% and replaced the two-button prompt with a modal three-action dialog (`Unload & Load`, `Load Anyway`, `Cancel`). `Cancel` leaves output, status, and buttons untouched; `Load Anyway` skips external VRAM cleanup. Added threshold and dialog-outcome tests; all 70 tests pass.
- 2026-11-19 — v2.3.0: Real-time GPU 0 VRAM monitor in the top-right header, refreshed every 2 s with green/orange/red thresholds and graceful N/A fallback; configurable ComfyUI and Forge Neo URLs on Settings; `free_comfyui_vram` / `free_forge_vram` / `free_external_vram` helpers with 1.5 s timeouts; and a Local-generation pre-flight that offers to unload ComfyUI / Forge Neo VRAM when usage exceeds 75% and no LM Studio model is loaded. Verified at 1000×760 and 780×600; all 68 tests pass.
- 2026-11-19 — v2.2.3: Local generation now unloads other loaded LM Studio models before every run, including Context Length `Auto`, to avoid stale VRAM instances on model switches; Local profile summaries always show `Think: On`/`Think: Off`; added Auto unload/reuse tests. All 48 tests pass.
- 2026-11-19 — v2.2.2: Replaced the ineffective `/no_think` prompt suffix with LM Studio’s verified `reasoning_effort: "none"` request field for Local generation. Removed all prompt-text mutation, updated the profile dialog label, and added True/False payload coverage. Live-verified against Gemma 4 on LM Studio; all 46 tests pass.
- 2026-11-19 — v2.2.1: Fixed model profile `context_length` preload. Profiles now pass context length into both generation workers; the native load payload uses the correct `model` field; loaded instances are compared via `config.context_length` and reloaded when they differ; load errors surface in the UI. Also strips Gemma 4 `<|channel>thought...<channel|>` reasoning blocks. Validated payloads against the live LM Studio API; all 45 tests pass.
- 2026-11-19 — v2.2.0: Model profiles and Settings phase. Removed local prompt caching completely; added per-`(engine, model, mode)` profiles in `data/model_profiles.json` with a compact `⚙` dialog and live summary; wired `context_length` to pre-load unloaded Local models; added the LM Studio base URL and Saved Profiles management to Settings; added initial Local `disable_thinking` handling via `/no_think` (superseded in v2.2.2); relocated the Single-Line checkbox and tightened both generation tabs for clean 780×600 rendering. All 41 tests pass.
- 2026-11-19 — v2.1.1: Fixed Groq model Fetch failing with "Groq returned no available models". The refactor dropped `filter_groq_models`'s return statement; restored it and added modality-based filtering so Whisper/TTS models are excluded while chat and vision-capable models are kept. Added five regression tests; all 28 tests pass.
- 2026-11-19 — v2.1.0: Backend and API modernization (Phase 1). System/user role separation for Groq, Local, and Gemini; centralized reasoning cleanup with unclosed-tag and `reasoning_content` handling; extensible sampling parameters with Local-only llama.cpp fields; native `load_model` helper; configurable `lm_studio_base_url`; engine-correct error messages; and a 23-test unit suite. No UI layout changes.
- 2026-11-19 — v2.0.1: Fixed Generator layout corruption when LM Studio is offline. Raw `HTTPConnectionPool` errors are now formatted as short messages (`Offline — cannot connect to 127.0.0.1:1234`, `Timed out (...)`, `HTTP <code> (...)`), both tabs use equal `uniform` column weights so a long status can never push the right column off-screen, the status labels wrap to their column width, and the Generator controls row is held at its measured height (including padding) so the LM Studio status label is no longer clipped above Generate Prompt. Verified offline rendering at 1000×760 and 780×600, including a forced over-long status string.
- 2026-11-19 — v2.0.0: Refactored the monolithic `main.py` (3,661 lines) into the modular `promptwriter` package — `config`, `utils.text`, `storage` (app files, config, SQLite history), `services` (LLM client, LM Studio API, model catalog, LoRA, prompt assembly, image tools), and `ui` (app shell plus seven tab/view mixins). No behavioral or UI changes. Verified all four tabs, both generation pipelines with mocked providers, history reads/search/selection, image preview, and entry-point startup. No changes to config, history database, or user data.
- 2026-11-19 — v1.0.0: Git baseline before modular refactoring; added the persistent auto-logging rule (`AGENTS.md`, `.qoder/rules/project-rules.md`) and `.gitignore` for caches, virtual environments, backups, databases, and local secrets.
