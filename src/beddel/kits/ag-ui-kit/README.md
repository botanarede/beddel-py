# ag-ui-kit

AG-UI protocol adapter for dashboard integration.

## Dependencies

- `ag-ui-protocol>=0.1`
- `fastapi>=0.100`
- `sse-starlette>=1.6`

## Integrations

| Name | Description |
|------|-------------|
| BeddelAGUIAdapter | AG-UI adapter for Beddel workflow event streams |
| create_agui_endpoint | FastAPI AG-UI endpoint factory |

## Usage

Install with the appropriate extra:

```
pip install beddel[default]
```

The kit is auto-discovered by the Beddel engine when its dependencies are installed.
