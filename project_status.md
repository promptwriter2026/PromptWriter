# Project Status

## Goals
Build a modular Python desktop application with a CustomTkinter interface that expands rough ideas into detailed English text-to-image prompts using selectable LLM providers and model-specific system instructions.

## Architecture
- `main.py`: Entry point; runs startup initialization and launches the app.
- `promptwriter/config.py`: Application paths, engine constants, and defaults.
- `promptwriter/storage/`: JSON config/app-file seeding and the SQLite history layer.
- `promptwriter/services/`: LLM client, LM Studio API, model catalog, LoRA rules, prompt assembly, and image preparation.
- `promptwriter/ui/`: CustomTkinter app split into tab/view mixins plus shared tooltip/text-action helpers.
- `config.json`: API keys and selected LLM engine.
- `system_prompts/`: Model-specific instructions, loaded from `.txt` files.
- `data/cameras.json`: Camera and lens choices.
- `data/lora_profiles.json`: Character/LoRA profiles.
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
- Successful Generator and Image to Prompt generations insert directly into SQLite. `settings_json` contains generation parameters including temperature, cache preference, LoRA, and auto-unload; image records also store their image path.
- Added a shared, enabled-by-default “Enforce Single-Line Prompts” checkbox to Generator and Image to Prompt. When enabled, successful callbacks collapse wrapped lines within paragraphs before both display and SQLite persistence; `settings_json` records the `force_single_line` preference.
- The History content panel now uses “Generated Prompts” and “Original Idea” tabs. “Load back to Generator” restores the original idea and switches to Generator.
- The History list queries only the newest 50 rows, loads prompt bodies only when an entry is selected, formats timestamps and topic snippets, and shows the complete original idea in each button's tooltip.
- Search, favorites-only filtering, favorite toggling, and favorite export now query/update SQLite.

## Version History
- 2026-11-19 — v2.0.1: Fixed Generator layout corruption when LM Studio is offline. Raw `HTTPConnectionPool` errors are now formatted as short messages (`Offline — cannot connect to 127.0.0.1:1234`, `Timed out (...)`, `HTTP <code> (...)`), both tabs use equal `uniform` column weights so a long status can never push the right column off-screen, the status labels wrap to their column width, and the Generator controls row is held at its measured height (including padding) so the LM Studio status label is no longer clipped above Generate Prompt. Verified offline rendering at 1000×760 and 780×600, including a forced over-long status string.
- 2026-11-19 — v2.0.0: Refactored the monolithic `main.py` (3,661 lines) into the modular `promptwriter` package — `config`, `utils.text`, `storage` (app files, config, SQLite history), `services` (LLM client, LM Studio API, model catalog, LoRA, prompt assembly, image tools), and `ui` (app shell plus seven tab/view mixins). No behavioral or UI changes. Verified all four tabs, both generation pipelines with mocked providers, history reads/search/selection, image preview, and entry-point startup. No changes to config, history database, or user data.
- 2026-11-19 — v1.0.0: Git baseline before modular refactoring; added the persistent auto-logging rule (`AGENTS.md`, `.qoder/rules/project-rules.md`) and `.gitignore` for caches, virtual environments, backups, databases, and local secrets.
