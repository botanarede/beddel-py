"""Integration tests for workflow listing endpoints (Story BC7.4, Task 5).

Tests the ``create_workflow_listing_router`` factory that creates two
``GET`` endpoints for workflow discovery:

- ``GET /workflows/`` — summary list of all loaded workflows.
- ``GET /workflows/{id}`` — full detail for a single workflow.

Uses ``httpx.AsyncClient`` with ``ASGITransport`` — no real server needed.

AC #5: ``GET /workflows`` returns list of loaded workflows
       (id, name, description, version, step_count).
AC #6: ``GET /workflows/{id}`` returns workflow detail
       (yaml_content, input_schema, steps).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from beddel_ag_ui.listing import create_workflow_listing_router
from fastapi import FastAPI

from beddel.domain.models import Step, Workflow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WF_ID_1 = "wf-alpha"
_WF_ID_2 = "wf-beta"

_YAML_CONTENT = "name: Test\nsteps:\n  - id: generate\n    primitive: llm\n"


def _make_workflow(
    wf_id: str,
    name: str = "Test Workflow",
    description: str = "",
    version: str = "1.0",
    input_schema: dict[str, Any] | None = None,
) -> Workflow:
    """Create a minimal single-step workflow."""
    return Workflow(
        id=wf_id,
        name=name,
        description=description,
        version=version,
        input_schema=input_schema,
        steps=[Step(id="generate", primitive="llm")],
    )


def _build_listing_app(
    workflows: dict[str, tuple[Workflow, Path]],
) -> FastAPI:
    """Build a FastAPI app with the listing router mounted at ``/workflows``."""
    app = FastAPI(title="Beddel Test")
    router = create_workflow_listing_router(workflows)
    app.include_router(router, prefix="/workflows")
    return app


# ---------------------------------------------------------------------------
# Subtask 5.1 — Workflow listing endpoint tests
# ---------------------------------------------------------------------------


class TestWorkflowList:
    """GET /workflows/ returns a summary list with correct fields."""

    @pytest.mark.asyncio
    async def test_list_returns_correct_fields(self, tmp_path: Path) -> None:
        """AC #5: response contains id, name, description, version, step_count."""
        wf = _make_workflow(_WF_ID_1, name="Alpha", description="First workflow")
        yaml_file = tmp_path / "alpha.yaml"
        yaml_file.write_text(_YAML_CONTENT)

        app = _build_listing_app({_WF_ID_1: (wf, yaml_file)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/workflows/")

        assert resp.status_code == 200
        items = resp.json()
        assert isinstance(items, list)
        assert len(items) == 1

        item = items[0]
        assert item["id"] == _WF_ID_1
        assert item["name"] == "Alpha"
        assert item["description"] == "First workflow"
        assert item["version"] == "1.0"
        assert item["step_count"] == 1

    @pytest.mark.asyncio
    async def test_list_empty_when_no_workflows(self) -> None:
        """AC #5: empty dict → empty list."""
        app = _build_listing_app({})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/workflows/")

        assert resp.status_code == 200
        assert resp.json() == []


class TestWorkflowDetail:
    """GET /workflows/{id} returns full detail with yaml_content, input_schema, steps."""

    @pytest.mark.asyncio
    async def test_detail_returns_yaml_content(self, tmp_path: Path) -> None:
        """AC #6: response includes raw yaml_content from the YAML file."""
        yaml_content = "name: Test\nsteps:\n  - id: generate\n    primitive: llm\n"
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content)

        wf = _make_workflow(_WF_ID_1)
        app = _build_listing_app({_WF_ID_1: (wf, yaml_file)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/workflows/{_WF_ID_1}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["yaml_content"] == yaml_content

    @pytest.mark.asyncio
    async def test_detail_returns_input_schema(self, tmp_path: Path) -> None:
        """AC #6: response includes input_schema when workflow defines one."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(_YAML_CONTENT)

        schema = {"type": "object", "properties": {"topic": {"type": "string"}}}
        wf = _make_workflow(_WF_ID_1, input_schema=schema)
        app = _build_listing_app({_WF_ID_1: (wf, yaml_file)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/workflows/{_WF_ID_1}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["input_schema"] == schema

    @pytest.mark.asyncio
    async def test_detail_returns_null_input_schema_when_absent(self, tmp_path: Path) -> None:
        """AC #6: input_schema is null when workflow has no schema."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(_YAML_CONTENT)

        wf = _make_workflow(_WF_ID_1)
        app = _build_listing_app({_WF_ID_1: (wf, yaml_file)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/workflows/{_WF_ID_1}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["input_schema"] is None

    @pytest.mark.asyncio
    async def test_detail_returns_steps_list(self, tmp_path: Path) -> None:
        """AC #6: response includes steps with id, name, primitive."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(_YAML_CONTENT)

        wf = _make_workflow(_WF_ID_1)
        app = _build_listing_app({_WF_ID_1: (wf, yaml_file)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/workflows/{_WF_ID_1}")

        assert resp.status_code == 200
        body = resp.json()
        steps = body["steps"]
        assert isinstance(steps, list)
        assert len(steps) == 1
        assert steps[0]["id"] == "generate"
        assert steps[0]["primitive"] == "llm"

    @pytest.mark.asyncio
    async def test_detail_returns_all_summary_fields(self, tmp_path: Path) -> None:
        """AC #6: detail also includes id, name, description, version, step_count."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(_YAML_CONTENT)

        wf = _make_workflow(_WF_ID_1, name="Alpha", description="Desc", version="2.0")
        app = _build_listing_app({_WF_ID_1: (wf, yaml_file)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/workflows/{_WF_ID_1}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == _WF_ID_1
        assert body["name"] == "Alpha"
        assert body["description"] == "Desc"
        assert body["version"] == "2.0"
        assert body["step_count"] == 1


class TestWorkflowNotFound:
    """GET /workflows/{id} with unknown ID returns 404."""

    @pytest.mark.asyncio
    async def test_unknown_id_returns_404(self, tmp_path: Path) -> None:
        """AC #6: 404 when workflow ID is not in the registry."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(_YAML_CONTENT)

        wf = _make_workflow(_WF_ID_1)
        app = _build_listing_app({_WF_ID_1: (wf, yaml_file)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/workflows/nonexistent")

        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"] == "Not found"

    @pytest.mark.asyncio
    async def test_empty_registry_returns_404(self) -> None:
        """AC #6: 404 when no workflows are loaded at all."""
        app = _build_listing_app({})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/workflows/anything")

        assert resp.status_code == 404


class TestMultipleWorkflows:
    """Multiple workflows are listed correctly."""

    @pytest.mark.asyncio
    async def test_multiple_workflows_listed(self, tmp_path: Path) -> None:
        """AC #5: all loaded workflows appear in the list."""
        yaml_1 = tmp_path / "alpha.yaml"
        yaml_1.write_text(_YAML_CONTENT)
        yaml_2 = tmp_path / "beta.yaml"
        yaml_2.write_text(_YAML_CONTENT)

        wf1 = _make_workflow(_WF_ID_1, name="Alpha", description="First")
        wf2 = _make_workflow(_WF_ID_2, name="Beta", description="Second")
        app = _build_listing_app({_WF_ID_1: (wf1, yaml_1), _WF_ID_2: (wf2, yaml_2)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/workflows/")

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2

        ids = {item["id"] for item in items}
        assert ids == {_WF_ID_1, _WF_ID_2}

        names = {item["name"] for item in items}
        assert names == {"Alpha", "Beta"}

    @pytest.mark.asyncio
    async def test_each_workflow_detail_accessible(self, tmp_path: Path) -> None:
        """AC #6: each workflow is individually accessible by ID."""
        yaml_1 = tmp_path / "alpha.yaml"
        yaml_1.write_text("name: Alpha\n")
        yaml_2 = tmp_path / "beta.yaml"
        yaml_2.write_text("name: Beta\n")

        wf1 = _make_workflow(_WF_ID_1, name="Alpha")
        wf2 = _make_workflow(_WF_ID_2, name="Beta")
        app = _build_listing_app({_WF_ID_1: (wf1, yaml_1), _WF_ID_2: (wf2, yaml_2)})

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.get(f"/workflows/{_WF_ID_1}")
            resp2 = await client.get(f"/workflows/{_WF_ID_2}")

        assert resp1.status_code == 200
        assert resp1.json()["name"] == "Alpha"
        assert resp1.json()["yaml_content"] == "name: Alpha\n"

        assert resp2.status_code == 200
        assert resp2.json()["name"] == "Beta"
        assert resp2.json()["yaml_content"] == "name: Beta\n"
