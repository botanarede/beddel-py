# External APIs

## LiteLLM (Internal Dependency)

- **Purpose:** Unified LLM provider abstraction
- **Documentation:** https://docs.litellm.ai/
- **Base URL(s):** Provider-specific (configured via LiteLLM)
- **Authentication:** API keys via environment variables
- **Rate Limits:** Provider-dependent

**Key Endpoints Used:**
- `litellm.acompletion()` - Async chat completion
- `litellm.acompletion(stream=True)` - Streaming completion

**Integration Notes:** LiteLLM handles provider-specific authentication and request formatting. Beddel only interacts with the unified LiteLLM interface.

## OpenTelemetry Collector (Optional)

- **Purpose:** Distributed tracing export
- **Documentation:** https://opentelemetry.io/docs/
- **Base URL(s):** User-configured OTLP endpoint
- **Authentication:** User-configured
- **Rate Limits:** N/A

**Key Endpoints Used:**
- OTLP gRPC or HTTP export

**Integration Notes:** Optional integration. Users configure their own collector endpoint.
