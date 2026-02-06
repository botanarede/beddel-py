# Next Steps

## For Architect

The Architect should create `docs/architecture.md` based on this PRD. Key areas:

1. **Hexagonal Architecture** - Define ports (domain interfaces) and adapters (LiteLLM, optional framework integrations)
2. **Module Structure** - `beddel/domain/`, `beddel/adapters/`, `beddel/primitives/`
3. **Data Flow** - YAML → Parser → Executor → Primitives → Output
4. **OpenTelemetry Integration** - Span hierarchy for workflows and steps

```
Prompt: @architect Create architecture.md for Beddel Python based on docs/prd.md
```

## For Scrum Master

After architecture approval, begin story creation:

```
Prompt: @sm → *draft (start with E1.1: YAML Parser)
```

## For Developer

After first story is approved:

```
Prompt: @dev Implement story from docs/stories/e1.1-yaml-parser.md
```
