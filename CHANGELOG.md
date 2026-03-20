# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-19

### Added

- Adaptive core engine: YAML parser, variable resolver, workflow executor
- Five execution strategies: fail, skip, retry (with exponential backoff), fallback, delegate
- Seven built-in primitives: llm, chat, output-generator, guardrail, call-agent, tool, agent-exec
- LiteLLM adapter for multi-provider LLM access (100+ providers)
- OpenTelemetry adapter with three-level span nesting and token usage tracking
- Lifecycle hooks: workflow/step start/end, error, retry events
- FastAPI integration with SSE streaming
- CLI: validate, run, serve, list-primitives, version
- Hexagonal architecture with strict port/adapter separation
- Pydantic 2.x model validation
- Strict mypy type checking
