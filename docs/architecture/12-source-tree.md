# 12. Source Tree

```
beddel/
├── spec/                              # Shared specification — single source of truth
│   ├── schemas/                       # JSON Schema definitions for workflow format
│   │   └── workflow.schema.json       # Workflow JSON Schema (mirrors Pydantic models)
│   ├── fixtures/                      # YAML test fixtures
│   │   ├── valid/                     # Valid workflow definitions
│   │   │   ├── simple.yaml            # Minimal single-step workflow
│   │   │   ├── branching.yaml         # If/then/else conditional workflow
│   │   │   ├── retry.yaml             # Retry with backoff workflow
│   │   │   └── multi-step.yaml        # Multi-step with variable resolution
│   │   ├── invalid/                   # Invalid workflows (parser rejection tests)
│   │   │   ├── missing-steps.yaml     # Missing required fields
│   │   │   ├── bad-strategy.yaml      # Invalid execution strategy
│   │   │   └── circular-ref.yaml      # Circular variable reference
│   │   └── expected/                  # Expected execution results
│   │       ├── simple.expected.json   # Expected output for simple.yaml
│   │       └── branching.expected.json
│   └── tests/                         # Cross-SDK test files
│       └── test_fixtures.py           # Fixture validation tests
├── src/
│   └── beddel-py/                     # Python SDK
│       ├── pyproject.toml             # Build config, dependencies, extras
│       ├── src/
│       │   └── beddel/
│       │       ├── __init__.py        # Public API exports, version
│       │       ├── domain/            # Core (zero external imports)
│       │       │   ├── __init__.py
│       │       │   ├── models.py      # Workflow, Step, ExecutionContext, etc.
│       │       │   ├── parser.py      # YAML parsing + Pydantic validation
│       │       │   ├── resolver.py    # Variable resolution engine
│       │       │   ├── executor.py    # Adaptive workflow executor
│       │       │   ├── registry.py    # Primitive registry + @primitive decorator
│       │       │   ├── ports.py       # Abstract interfaces (ILLMProvider, etc.)
│       │       │   └── errors.py      # BeddelError + error code catalog
│       │       ├── primitives/        # Compositional primitives
│       │       │   ├── __init__.py    # register_builtins()
│       │       │   ├── llm.py         # Single-turn LLM invocation
│       │       │   ├── chat.py        # Multi-turn conversation
│       │       │   ├── output_generator.py  # Template rendering
│       │       │   ├── call_agent.py  # Nested workflow invocation
│       │       │   ├── guardrail.py   # Input/output validation
│       │       │   └── tool.py        # External function invocation
│       │       ├── adapters/          # Port implementations
│       │       │   ├── __init__.py
│       │       │   ├── litellm_adapter.py   # LiteLLM multi-provider adapter
│       │       │   ├── otel_adapter.py      # OpenTelemetry tracing
│       │       │   └── hooks.py             # Lifecycle hook manager
│       │       └── integrations/      # Optional framework extras
│       │           ├── __init__.py
│       │           ├── fastapi.py     # Handler factory + routing
│       │           └── sse.py         # SSE adapter (W3C compliant)
│       └── tests/                     # SDK-specific tests
│           ├── conftest.py            # Shared fixtures, mock providers
│           ├── domain/
│           │   ├── test_parser.py
│           │   ├── test_resolver.py
│           │   ├── test_executor.py
│           │   └── test_registry.py
│           ├── primitives/
│           │   ├── test_llm.py
│           │   ├── test_chat.py
│           │   └── ...
│           ├── adapters/
│           │   └── test_litellm_adapter.py
│           └── integration/
│               ├── test_wiring.py     # Full path: factory → executor → primitive → adapter
│               └── test_fastapi.py    # HTTP endpoint integration
├── examples/                          # Quickstart examples
│   ├── workflows/
│   │   ├── simple.yaml                # Hello world workflow (stable model names)
│   │   └── streaming.yaml             # Streaming workflow example
│   ├── run_workflow.py                # Programmatic execution example
│   └── fastapi_app.py                # FastAPI integration example
├── docs/
│   ├── brief.md                       # Project brief
│   ├── prd.md                         # Product requirements
│   ├── architecture.md                # This file
│   └── stories/                       # BMAD stories (task tracking)
├── .github/
│   └── workflows/
│       ├── ci.yml                     # PR checks: pytest, ruff, mypy
│       └── release.yml                # PyPI publish (manual/tag trigger)
├── .gitignore
├── README.md
└── .bmad-core/                        # BMAD Method
```

---
