# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-04-01

### Added

- Kit manifest model (SolutionKit) with Pydantic validation
- Kit bootstrap loader with dependency validation
- Kit namespace resolution with collision detection
- Taxonomy formalization (7 kit categories)
- Backward compatibility layer for pre-kit imports
- Reference kit: software-development-kit
- Core SDK slimmed to pydantic+pyyaml+click only
- 14 solution kits extracted from monolith (4 agent, 1 provider, 2 observability, 1 serve, 1 protocol, 1 auth, 4 tools)
- Kit dependency declaration with multi-language targets
- `beddel kit export` CLI (skill, kit, mcp, endpoint formats)
- Cross-language kit spec: JSON Schema, port contracts, validation fixtures
- ADR-0008: Kit ecosystem decomposition strategy

### Changed

- All adapter imports now use kit module paths (e.g., `from beddel_provider_litellm.adapter import LiteLLMAdapter`)
- `discover_builtin_tools()` returns empty dict — all tools in kits
- Package-level `from beddel.adapters import X` emits DeprecationWarning

### Removed

- All adapter source files from `beddel/adapters/` (moved to kits)
- All tool implementations from `beddel/tools/` (moved to kits)
- `httpx` from core dependencies

## [0.1.2] - 2026-03-XX

### Added

- Dashboard remote access: GitHub OAuth device flow (`beddel connect`)
- Dashboard token validation middleware
- Cloudflare Tunnel setup for Lightsail VPS
- CLI token injection for authenticated requests
- OpenClaw agent adapter (Gateway HTTP API)
- Claude agent adapter (claude-agent-sdk)
- Codex agent adapter (Docker subprocess)
- Langfuse tracer adapter
- Model tier selection and effort control
- Cost controls and budget enforcement
- Dashboard agent adapter pipeline views
- Kit manifest model: dependencies, targets, KitLanguageTarget
- Kit CLI: `beddel kit install`, `beddel kit list`

## [0.1.1] - 2026-03-XX

### Added

- CLI runner with dependency wiring (`beddel run`, `beddel validate`, `beddel serve`)
- FastAPI serve command with tool registration
- Tool execution safety baseline (SafeSubprocessRunner)
- Builtin tool library: file (read/write), shell (exec), gates (pytest, ruff, mypy), http (request)
- IContextReducer wired into chat primitive for context windowing
- Per-step primitive filtering and registry unregister
- Function calling / tool-use loop for LLM primitives
- Streaming execution strategy delegation (execute_stream)
- Thread-safe hook registration
- Reflection loops (generate-evaluate-refine cycles)
- Parallel execution (fan-out/fan-in with concurrency limits)
- Advanced parallel: dependency graphs, partial failure, result aggregation
- Circuit breaker pattern for provider resilience
- Conditional branching (if/then/else at step level)
- Goal-oriented execution loops (loop-until-outcome)
- Durable execution: event sourcing port + in-memory store
- Durable execution: SQLite store with exactly-once semantics
- MCP client: stdio transport
- MCP client: SSE transport with tool discovery
- Solution Kit subsystem: kit.yaml manifest, discover_kits(), load_kit(), namespace resolution

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
