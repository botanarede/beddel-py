# TOOLS.md - Beddel Dev Environment (agent main)

## Project Path

/home/ubuntu/shared/beddel/src/beddel-py/

## Python Environment

```bash
# Activate venv (ALWAYS do this first)
source /home/ubuntu/shared/beddel/src/beddel-py/.venv/bin/activate
cd /home/ubuntu/shared/beddel/src/beddel-py

# Run tests (ALWAYS use tail to limit output)
pytest tests/ -x --timeout=30 --tb=short 2>&1 | tail -20

# Lint (short output only)
ruff check src/ 2>&1 | tail -5

# Type check (short output only)
mypy src/ 2>&1 | tail -5

# Format
ruff format src/ tests/

# Full validation (run after each task)
pytest -x --timeout=30 && ruff check . && mypy src/
```

## Git (from repo root)

```bash
cd /home/ubuntu/shared/beddel
git status
git add -A
git commit -m "feat(beddel-py): description"
```

## Key Files

- TASK.md — your checklist (in src/beddel-py/)
- PROGRESS.md — track what you've done
- STUCK.md — document blockers

## Domain Core (already implemented by Kiro)

These files are DONE. Use them as reference, do NOT rewrite them:

- `src/beddel/domain/models.py` — Pydantic models + exception hierarchy
- `src/beddel/domain/ports.py` — Protocol interfaces (ILLMProvider, ITracer, ILifecycleHook)
- `src/beddel/domain/registry.py` — PrimitiveRegistry with @register decorator
- `src/beddel/domain/parser.py` — YAMLParser with yaml.safe_load + Pydantic validation
- `src/beddel/domain/resolver.py` — VariableResolver for $input.*, $stepResult.*, $env.*
- `src/beddel/domain/executor.py` — WorkflowExecutor async sequential with hooks/tracing
- `src/beddel/domain/__init__.py` — Exports all domain types

## Test Fixtures

- `tests/fixtures/workflows/simple.yaml` — Single LLM step
- `tests/fixtures/workflows/multi_step.yaml` — 3-step pipeline
- `tests/fixtures/workflows/nested_agent.yaml` — call-agent + guardrail

## Limitations

- No external network (except Qwen API)
- No pip install of new packages (use what's in pyproject.toml)
- No browser access
- Shared folder via SSHFS — files may have slight delay
- venv is at .venv/ inside the project dir — always activate it

## Output Rules

- NEVER cat entire test output — use tail
- NEVER print full file contents if > 50 lines — use head/tail
- Log verbose output to src/beddel-py/logs/
- Keep your context window clean
