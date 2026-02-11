# 7. External APIs

## 7.1 LLM Provider APIs (via LiteLLM)

- **Purpose:** Multi-provider LLM completion and streaming
- **Documentation:** https://docs.litellm.ai/
- **Base URL(s):** Varies by provider (managed by LiteLLM)
- **Authentication:** API keys via environment variables, explicitly resolved by `LiteLLMAdapter` (lesson §13.3)
- **Rate Limits:** Provider-dependent; circuit breaker planned for Epic 4

**Key Endpoints Used (abstracted by LiteLLM):**
- `litellm.acompletion()` — Async chat completion
- `litellm.acompletion(stream=True)` — Async streaming completion

**Integration Notes:**
- The `LiteLLMAdapter` explicitly resolves API keys from well-known environment variables (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AWS_ACCESS_KEY_ID`, etc.) — never relies solely on LiteLLM auto-detection (lesson §13.3)
- Model names use provider prefix format: `gemini/gemini-2.0-flash`, `openai/gpt-4o`, `anthropic/claude-3.5-sonnet`
- Only stable model names are used — never experimental `-exp` suffixes (lesson §13.4)
- Version pinning on LiteLLM; adapter pattern absorbs breaking changes at the port boundary

## 7.2 OpenTelemetry Collector

- **Purpose:** Distributed tracing and observability
- **Documentation:** https://opentelemetry.io/docs/
- **Authentication:** Collector-dependent (typically none for local, token for cloud)
- **Rate Limits:** N/A

**Integration Notes:**
- Opt-in — tracing has zero overhead when disabled
- Spans emitted for workflow, step, and primitive execution
- Token usage tracked as span attributes

---
