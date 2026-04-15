# serve-fastapi-kit

FastAPI serving + SSE.

## Dependencies

- `fastapi>=0.100`
- `sse-starlette>=1.6`

## Integrations

| Name | Description |
|------|-------------|
| create_beddel_handler | One-line workflow-to-endpoint factory with SSE streaming |
| BeddelSSEAdapter | SSE adapter for Beddel workflow event streams |

## Usage

Install with the appropriate extra:

```
pip install beddel[default]
```

The kit is auto-discovered by the Beddel engine when its dependencies are installed.
