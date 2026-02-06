# Source Tree

## Estrutura do SDK Python (src/beddel-py/)

```
src/beddel-py/
├── pyproject.toml              # Package configuration (PEP 621)
├── README.md                   # Package documentation
├── LICENSE                     # MIT License
│
├── src/
│   └── beddel/
│       ├── __init__.py         # Package exports
│       ├── py.typed            # PEP 561 marker
│       │
│       ├── domain/             # Domain Core (Hexagonal inner)
│       │   ├── __init__.py
│       │   ├── models.py       # Pydantic models (WorkflowDefinition, etc.)
│       │   ├── parser.py       # YAMLParser
│       │   ├── resolver.py     # VariableResolver
│       │   ├── executor.py     # WorkflowExecutor
│       │   ├── registry.py     # PrimitiveRegistry
│       │   └── ports.py        # Port interfaces (ILLMProvider, ITracer, etc.)
│       │
│       ├── primitives/         # Built-in Primitives
│       │   ├── __init__.py     # Primitive exports & registration
│       │   ├── llm.py          # llm primitive
│       │   ├── chat.py         # chat primitive
│       │   ├── output.py       # output-generator primitive
│       │   ├── call_agent.py   # call-agent primitive
│       │   ├── guardrail.py    # guardrail primitive
│       │   └── tool.py         # tool primitive (P1)
│       │
│       ├── adapters/           # Adapters (Hexagonal outer)
│       │   ├── __init__.py
│       │   ├── litellm.py      # LiteLLMAdapter
│       │   ├── tracing.py      # OpenTelemetryAdapter
│       │   └── hooks.py        # LifecycleHooksAdapter
│       │
│       └── integrations/       # Framework Integrations (optional extras)
│           ├── __init__.py
│           └── fastapi.py      # createBeddelHandler, SSE (requires: beddel[fastapi])
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Pytest fixtures
│   │
│   ├── unit/                   # Unit tests (mocked dependencies)
│   │   ├── domain/
│   │   │   ├── test_parser.py
│   │   │   ├── test_resolver.py
│   │   │   ├── test_executor.py
│   │   │   └── test_registry.py
│   │   └── primitives/
│   │       ├── test_llm.py
│   │       ├── test_chat.py
│   │       └── ...
│   │
│   ├── integration/            # Integration tests (real adapters)
│   │   ├── test_litellm.py
│   │   └── test_fastapi.py
│   │
│   └── fixtures/               # Shared YAML fixtures
│       └── workflows/
│           ├── simple.yaml
│           ├── multi_step.yaml
│           └── ...
│
└── examples/                   # Example applications
    ├── basic_workflow.py
    ├── fastapi_app.py
    └── workflows/
        └── assistant.yaml
```

## Estrutura Completa do Monorepo

```
botanarede/beddel/
├── spec/                           # Especificação compartilhada
│   ├── schemas/
│   │   ├── workflow.json           # JSON Schema para WorkflowDefinition
│   │   ├── step.json               # JSON Schema para StepDefinition
│   │   └── primitives/             # Schemas por primitivo
│   ├── fixtures/
│   │   ├── workflows/              # YAML fixtures para testes
│   │   │   ├── simple.yaml
│   │   │   ├── multi-step.yaml
│   │   │   ├── streaming.yaml
│   │   │   └── nested-agent.yaml
│   │   └── expected/               # Outputs esperados por fixture
│   └── docs/
│       └── spec.md                 # Documentação da especificação
│
├── src/
│   └── beddel-py/                  # (estrutura acima)
│
├── docs/
│   ├── brief.md
│   ├── prd.md
│   └── architecture.md
│
├── .bmad-core/                     # BMAD Method
├── .gitignore
├── README.md
└── LICENSE
```
