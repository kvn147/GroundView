# ADR-0001: OpenRouter as the single LLM gateway

## Decision
All LLM calls go through OpenRouter via one shared client. Use the `openai` SDK pointed at `https://openrouter.ai/api/v1`.

## Why
One key, one schema, one billing surface. Per-call model selection lets us swap models without code changes.

## Implications for contributors
- Import the LLM client from `backend/app/shared/llm_clients.py`. Do not construct your own `httpx`/`openai` calls.
- Reference models via `MODELS["..."]` in `backend/app/shared/model_config.py`. Never hard-code model strings in pipeline code.
- Use OpenAI-style JSON mode / function calling for structured output. Not Anthropic-native tool use.
- Cache keys must include the model string.
- Each developer uses their own `OPENROUTER_API_KEY` in `.env.local`.
