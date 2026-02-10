"""Beddel Example — FastAPI Application.

A reference FastAPI application demonstrating how to expose Beddel workflows
as HTTP endpoints using ``create_beddel_handler``.

Two workflows are mounted:

- ``POST /agent/simple``    — blocking JSON response
- ``POST /agent/streaming`` — Server-Sent Events (SSE) stream

Prerequisites::

    pip install beddel[fastapi]

Run from the ``src/beddel-py/`` directory::

    uvicorn examples.fastapi_app:app --reload

Or directly::

    python -m examples.fastapi_app
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

# --- Beddel imports ---------------------------------------------------------
# YAMLParser parses workflow YAML files into WorkflowDefinition objects.
# create_beddel_handler wraps a WorkflowDefinition as an async HTTP handler.
from beddel import YAMLParser
from beddel.integrations.fastapi import create_beddel_handler

# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(title="Beddel Example", version="0.1.0")

# ---------------------------------------------------------------------------
# Health check — simple liveness probe
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a simple health-check response."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Workflow loading — parse YAML definitions from the examples/workflows/ dir
# ---------------------------------------------------------------------------

_WORKFLOWS_DIR = Path(__file__).parent / "workflows"

_parser = YAMLParser()
_simple_workflow = _parser.parse_file(_WORKFLOWS_DIR / "simple.yaml")
_streaming_workflow = _parser.parse_file(_WORKFLOWS_DIR / "streaming.yaml")

# ---------------------------------------------------------------------------
# Handler creation — create_beddel_handler returns an async callable that
# accepts a Starlette Request and returns JSONResponse (blocking) or
# EventSourceResponse (streaming) depending on the workflow configuration.
# ---------------------------------------------------------------------------

_simple_handler = create_beddel_handler(_simple_workflow)
_streaming_handler = create_beddel_handler(_streaming_workflow)

# ---------------------------------------------------------------------------
# Route mounting — attach handlers to FastAPI routes.
# We use add_api_route with response_model=None so FastAPI does not try to
# infer a response schema from the handler's union return type.
# ---------------------------------------------------------------------------

app.add_api_route(
    "/agent/simple",
    _simple_handler,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/agent/streaming",
    _streaming_handler,
    methods=["POST"],
    response_model=None,
)

# ---------------------------------------------------------------------------
# Startup — run with uvicorn when executed directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # noqa: S104
