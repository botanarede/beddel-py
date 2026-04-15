# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.8] - 2026-04-07

### Changed

- Public API surface reduction: `__all__` reduced from 93 to ~40 symbols, deprecation warnings for moved symbols
- CLI import guards: helpful error messages for missing optional kits
- Source tree documentation sync: remove phantom entries from architecture docs
- Error code registry cleanup: resolve range overlaps, add comprehensive range tests
- README test count update

### Removed

- `beddel/integrations/` directory deleted, CLI redirected to kit adapters
- Empty `tests/integrations/` scaffold deleted
- Stale imports fixed in `serve-fastapi-kit`
- Architecture docs updated to reflect kit boundary enforcement

### Added

- `py.typed` markers for all kits
- Kit READMEs and authoring guide
- `--json` CLI output flag
- Click dependency deduplication
- Integration test: import guard for `beddel run`

## [0.1.7] - 2026-04-06

### Fixed

- Include `kits/__init__.py` in build artifacts

## [0.1.6] - 2026-04-05

### Fixed

- Include bundled kits in both sdist and wheel distributions

## [0.1.5] - 2026-04-05

### Fixed

- Include bundled kits in wheel distribution

## [0.1.4] - 2026-04-04

### Added

- HOTL approval gates: `IApprovalGate` port, `ApprovalPolicy`/`ApprovalResult`/`ApprovalStatus` models, `InMemoryApprovalGate` + `ConfigurableApprovalGate` adapters, CIBA async flow, `on_approval_requested`/`on_approval_received` lifecycle hooks
- Bundled kits: 7 kit directories in `[default]` extra, 3-path discovery (bundled/local/global), `kit list` SOURCE column, graceful degradation for missing deps
- PII tokenization: `IPIITokenizer` port, `TokenMap`/`PIIPattern` models, `RegexPIITokenizer` adapter (4 default patterns), `PIIMiddleware` LLM wrapper
- State persistence: `IStateStore` port, `JSONFileStateStore` + `InMemoryStateStore` adapters, `InterruptibleContext` checkpoint/restore
- Episodic memory: `IMemoryProvider` port, `MemoryEntry`/`Episode` models, `InMemoryMemoryProvider` adapter, `CompositeMemoryProvider` with async buffering
- Knowledge architecture: `IKnowledgeProvider` port, `KnowledgeEntry`/`KnowledgeSource` models, `YAMLKnowledgeAdapter`
- Decision-centric runtime: `Decision` dataclass, `IDecisionStore` port, `InMemoryDecisionStore` adapter, `DecidePrimitive`, `on_decision` hook, Langfuse integration
- Multi-agent coordination: `ICoordinationStrategy` port, `CoordinationTask`/`CoordinationResult` models, `SupervisorStrategy`, `HandoffStrategy`, `ParallelDispatchStrategy` (merge/first/vote)
- Event-driven execution: `TriggerConfig`/`TriggerEvent` models, `EventDrivenExecutionStrategy`, `WebhookTriggerHandler`, `ScheduleTriggerHandler` (interval+cron), `SSETriggerHandler`
- Skill composition: `SkillReference` model, `SkillResolver` with version constraints, `call-agent` skill invocation, `SKILL.md` export metadata
- Adapter auto-discovery: `load_kit_adapters()`, `_build_adapter_registries()`, dynamic adapter discovery in `run`/`serve` commands
- `serve-mcp-kit`: expose YAML workflows as MCP tools
- `beddel serve --mcp` CLI command
- CLI auth browser handoff: token exchange + conditional browser open
- SSE connect channel: CLI listen mode, dashboard relay, workflow dispatch
- GitHub OAuth web flow with CSRF protection (`state` parameter) and `redirect_uri` validation
- `beddel.setup()` for Python API kit paths
- Kit install from GitHub repositories

### Changed

- Legacy `WorkflowExecutor` constructor removed, 133 test instantiations migrated to `deps=` pattern
- Spec contracts, exports, constants, and type safety fixes across codebase
- Stale docstrings and legacy code cleaned up (8 audit tasks)
- SDK CLI dashboard decoupling: dead code removed, `connect` command wired
- Connect URL parameterized: `--url` flag required
- `click` moved to core dependencies, meta-extras removed
- README synced with Epics 1–7 + hero banner

### Removed

- Kit-bound adapters from public API
- Deprecated adapter import shim
- 14 orphan test stubs migrated to kits

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
