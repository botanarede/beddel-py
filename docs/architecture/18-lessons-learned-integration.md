# 18. Lessons Learned Integration

This section maps all 11 post-implementation lessons from the project brief (§13) to specific architecture decisions in this document. Every lesson is reflected in at least one architectural constraint or design rule.

| Lesson | Brief § | Architecture Decision | Document Reference |
|--------|---------|----------------------|-------------------|
| LLM provider not injected into ExecutionContext | §13.1 | `WorkflowExecutor.__init__` accepts `provider: ILLMProvider` and injects into `metadata["llm_provider"]`. Integration tests verify full wiring path. | §5.1, §9 (Wiring Contract), §16.2 |
| No default LLM provider in factory | §13.2 | `create_beddel_handler` auto-creates `LiteLLMAdapter()` when no provider supplied. Factory functions always produce usable instances. | §2.4 (Factory Pattern), §15.3 |
| LiteLLM does not auto-resolve API keys | §13.3 | `LiteLLMAdapter._build_params()` explicitly resolves API keys from well-known env vars. Never relies on third-party auto-detection. | §7.1, §15.3, §17.2 |
| Example used discontinued model name | §13.4 | All examples use stable model names only. No `-exp` suffixes. Comments note model names may need updating. | §15.3 |
| ExecutionContext metadata wiring undefined | §13.5 | Wiring Contract table (§9) documents every metadata key, provider, consumer, and error behavior. Enforced by integration tests. | §9 |
| Streaming as response format, not execution concern | §13.6 | `execute_stream()` on executor returns `AsyncGenerator[BeddelEvent, None]`. Executor owns event emission lifecycle. | §4.5, §8.2 |
| Private function imported cross-module | §13.7 | Cross-module functions MUST be public (no underscore prefix). Added to `__all__`. | §15.3 |
| SSE multi-line data violation | §13.8 | `SSEEvent.serialize()` splits data on `\n` and emits each line as separate `data:` field per W3C spec. Tested with realistic payloads. | §8.2, §16.2 |
| output-generator docs say Jinja2, uses VariableResolver | §13.9 | Documentation accurately describes "variable interpolation via VariableResolver". No Jinja2 dependency. | §5.2 |
| Lifecycle hooks dual-channel mismatch | §13.10 | Single unified hook dispatch mechanism. Executor injects `self._hooks` into `metadata["lifecycle_hooks"]` — both channels reference same instances. | §6.2, §9 |
| Primitive registry empty by default | §13.11 | `register_builtins()` called on all default registries. Factory functions never produce empty registries. | §2.4 (Factory Pattern), §15.3 |

---
