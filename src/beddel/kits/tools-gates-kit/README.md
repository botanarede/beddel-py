# tools-gates-kit

Validation gate tools (pytest, ruff, mypy) via shell_exec.

## Dependencies

None (stdlib only).

## Tools

| Name | Description |
|------|-------------|
| pytest_run | Run pytest |
| ruff_check | Run ruff check |
| ruff_format | Run ruff format check |
| mypy_check | Run mypy type check |

## Usage

Install with the appropriate extra:

```
pip install beddel[default]
```

The kit is auto-discovered by the Beddel engine when its dependencies are installed.
