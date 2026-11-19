# LM Studio Context Investigation

## Confirmed findings

### Current app behavior

- The Local (LM Studio) request path in `main.py` uses the OpenAI-compatible `/v1/chat/completions` endpoint.
- The app sends its Context slider value in the request as `n_ctx`. LM Studio did not apply that field as a model context setting: the initial server log showed `n_ctx_slot = 16384`.
- The existing OpenAI-compatible Local route accepted a Temperature value of 1.44.
- Gemini and Groq use separate online request routes. Any future Context implementation must be limited to Local and leave Gemini and Groq unchanged.
- The app can select among many Local models. Any future solution must work with whichever Local model is selected, rather than being hard-coded to Dolphin Mistral.

### Native API tests

- A native `/api/v1/chat` request using temperature 1.44 was rejected with HTTP 400 and the message that temperature must be less than or equal to 1. The rejection occurred before inference.
- Dolphin Mistral was already loaded when a native chat request was sent with `context_length: 4096`, `temperature: 1.0`, `max_output_tokens: 8`, and `store: false`. The request succeeded.
- The first successful request reported `model_load_time_seconds` of about 9.854 seconds and returned a new model instance at context 4,096. The previously listed instance was no longer present afterward. No explicit model load or unload endpoint was called.
- The post-request model-list configuration continued to report Flash Attention enabled and KV-cache GPU offload enabled.
- A later request at the same context succeeded using the same instance ID and omitted `model_load_time_seconds`.
- These observations confirm that native chat applied the requested context. The first context change caused an instance load; the later request at the already-active context reused that instance.

### Current active model state

- During testing, the active Dolphin Mistral instance was changed to context 4,096.
- The user can reload Dolphin Mistral in LM Studio if they want to restore the prior context.

## Unknown or unverified

- The models API did not expose K/V cache quantization. Whether the configured IQ4_NL quantization was preserved during the context-changing request is unknown; it was not verified.
- Whether the current `cache_prompt` option has any real effect is unknown. Native `/api/v1/chat` documentation does not document an equivalent field.

## Future decision

- No application code changes have been made.
- The user has decided not to change the app for now because they want to retain Local Temperature values above 1.
- If revisited, the goal is to make Context effective for all selected Local models while preserving Local Temperature behavior as far as possible, and leaving Gemini and Groq unchanged.
