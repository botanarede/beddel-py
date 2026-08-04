"""Real-executor streaming regression tests for Epic SH1 (Story SH1.4).

These tests drive a REAL ``WorkflowExecutor`` (no ``execute_stream()`` mocking)
through the actual HTTP surface kit factories over a real ASGI transport, proving
that the stream-scoped event transport fix (ADR-0015 Option C, landed in SH1.1)
keeps the streaming surfaces from silently emitting empty SSE bodies.

WHAT WAS BROKEN (pre-SH1.1):
    Every HTTP-level streaming test patched WorkflowExecutor with MagicMock
    and injected a canned execute_stream() generator. A real executor with
    DefaultDependencies() (no lifecycle_hooks) yielded ZERO events because
    the internal _Collector was registered on the no-op IHookManager() fallback,
    so add_hook() silently did nothing. These tests ensure that defect cannot
    re-emerge without a failing test at the HTTP layer.

Surfaces covered:
    - /workflows/{id} with stream=True step (via create_beddel_handler)
    - /ag-ui/{id}  (via create_agui_endpoint)
    - /ag-ui (unified, via create_unified_agui_endpoint + WorkflowExecutor)

Dashboard bridge gap:
    repo/kits/serve-fastapi-kit/python/beddel_serve_fastapi/dashboard/bridge.py
    uses execute_stream() but has no exported factory and requires a WebSocket
    transport layer, not HTTP SSE. A regression test harness would need to mock
    the WebSocket protocol, which is not feasible within this story. The bridge
    is structurally fixed by SH1.1 (the stream-scoped fan-out applies to every
    execute_stream() call regardless of caller). This gap is explicitly documented
    rather than silently assumed fixed (per PRD FR-SH1.3 and SH1.4 Dev Notes).

Validation:
    source src/beddel-py/.venv/bin/activate
    python -m pytest src/beddel-py/tests/integration/test_streaming_regression.py -v
    bash scripts/run-gates.sh
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from beddel_ag_ui.endpoint import create_agui_endpoint
from beddel_ag_ui.unified import create_unified_agui_endpoint
from beddel_serve_fastapi.handler import create_beddel_handler
from fastapi import FastAPI

from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import DefaultDependencies, Step, Workflow
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WF_ID = "sh1-regression-wf"
_WF_ID_2 = "sh1-regression-wf-2"


def _make_registry() -> PrimitiveRegistry:
    """Return a PrimitiveRegistry with all builtins registered."""
    registry = PrimitiveRegistry()
    register_builtins(registry)
    return registry


def _make_output_gen_workflow(
    wf_id: str = _WF_ID,
    *,
    stream: bool = False,
) -> Workflow:
    """A provider-free single-step workflow using output-generator.

    No LLM, no API key, no network required. The output-generator primitive
    renders a static template string, making this workflow hermetic for tests.
    When stream=True, the handler's _has_stream_steps gate routes through
    execute_stream() rather than the fallback execute() + hand-built events path.
    """
    return Workflow(
        id=wf_id,
        name="SH1 Regression Workflow",
        steps=[
            Step(
                id="echo",
                primitive="output-generator",
                config={"format": "text", "template": "sh1-ok"},
                stream=stream,
            )
        ],
    )


def _parse_sse_events(text: str) -> list[dict[str, str]]:
    """Parse raw SSE text into a list of {event?, data?} dicts.

    Handles both \\n\\n and \\r\\n\\r\\n separators. Skips empty blocks.
    """
    text = text.replace("\r\n", "\n")
    blocks = text.split("\n\n")
    events: list[dict[str, str]] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        event_dict: dict[str, str] = {}
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_dict["event"] = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if data_lines:
            event_dict["data"] = "\n".join(data_lines)
        if event_dict:
            events.append(event_dict)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkflowsStreamingRealExecutor:
    """/workflows/{id} with stream=True step, real executor, no execute_stream mocking.

    Guards the SSE handler path in beddel_serve_fastapi.handler.
    When a step has stream=True, handler._has_stream_steps is True and the
    handler calls execute_stream() rather than the fallback execute() path.
    Pre-SH1.1 this would return a 200 with an empty body; now it must return
    a non-empty SSE body with WORKFLOW_END as the terminal event.
    """

    async def test_streaming_step_workflow_returns_nonempty_sse_with_terminal_event(
        self,
    ) -> None:
        """AC1 (SH1.4): /workflows/{id} with stream=True step drives real execute_stream().

        Uses DefaultDependencies() with lifecycle_hooks=None (pre-SH1.3 construction,
        to prove the structural SH1.1 fix alone is sufficient) AND also tests with
        the post-SH1.3 concrete manager to prove the companion fix doesn't break anything.

        Assertion: non-empty SSE body, WORKFLOW_END event present.
        """
        registry = _make_registry()
        # Use stream=True so _has_stream_steps=True, forcing execute_stream() path
        wf = _make_output_gen_workflow(stream=True)

        # --- Pre-SH1.3 construction: DefaultDependencies() with no lifecycle_hooks ---
        # This is the exact construction used by commands.py before SH1.3.
        # The SH1.1 structural fix must ensure this still yields events.
        deps_no_hooks = DefaultDependencies(
            registry=registry,
        )
        app = FastAPI()
        router = create_beddel_handler(wf, deps=deps_no_hooks)
        app.include_router(router, prefix=f"/workflows/{wf.id}")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/workflows/{wf.id}/",
                json={},
                headers={"Accept": "text/event-stream"},
            )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:500]}"
        )
        sse_text = response.text
        assert sse_text.strip(), (
            "SSE body is empty — execute_stream() yielded zero events (pre-SH1.1 regression)"
        )

        events = _parse_sse_events(sse_text)
        assert events, f"No SSE events parsed from body: {sse_text[:500]}"

        # Must contain WORKFLOW_END as terminal event
        event_types = [
            json.loads(e["data"]).get("event_type", "") for e in events if e.get("data")
        ]
        assert "workflow_end" in event_types, (
            f"WORKFLOW_END not found in SSE events: {event_types!r}"
        )

    async def test_post_sh13_concrete_hooks_also_streams_correctly(self) -> None:
        """AC1 (SH1.4): post-SH1.3 DefaultDependencies with concrete LifecycleHookManager
        also yields a non-empty SSE body with WORKFLOW_END.

        Confirms the SH1.3 companion fix doesn't break the streaming path.
        """
        registry = _make_registry()
        wf = _make_output_gen_workflow(stream=True)

        deps_with_hooks = DefaultDependencies(
            registry=registry,
            lifecycle_hooks=LifecycleHookManager(),
        )
        app = FastAPI()
        router = create_beddel_handler(wf, deps=deps_with_hooks)
        app.include_router(router, prefix=f"/workflows/{wf.id}")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/workflows/{wf.id}/",
                json={},
                headers={"Accept": "text/event-stream"},
            )

        assert response.status_code == 200
        sse_text = response.text
        assert sse_text.strip(), "SSE body is empty with concrete hooks — unexpected regression"

        events = _parse_sse_events(sse_text)
        event_types = [
            json.loads(e["data"]).get("event_type", "") for e in events if e.get("data")
        ]
        assert "workflow_end" in event_types, (
            f"WORKFLOW_END not found in SSE events: {event_types!r}"
        )


class TestAGUIEndpointRealExecutor:
    """/ag-ui/{id} (per-workflow AG-UI endpoint), real executor, no execute_stream mocking.

    Guards the AG-UI SSE path in beddel_ag_ui.endpoint.
    The endpoint always calls execute_stream() regardless of step.stream flag.
    Pre-SH1.1 this returned 200 with an empty body; now it must return a
    non-empty SSE body with a RunFinishedEvent.
    """

    async def test_agui_endpoint_real_executor_returns_nonempty_sse(self) -> None:
        """AC1 (SH1.4): /ag-ui/{id} drives real execute_stream() and returns non-empty SSE.

        Uses DefaultDependencies() with lifecycle_hooks=None (exact pre-SH1.3
        construction) to prove SH1.1 structural fix is sufficient.
        """
        registry = _make_registry()
        # stream=False: AG-UI always calls execute_stream() regardless
        wf = _make_output_gen_workflow()

        deps = DefaultDependencies(registry=registry)
        app = FastAPI()
        router = create_agui_endpoint(wf, deps=deps)
        app.include_router(router, prefix="/ag-ui")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ag-ui/",
                json={},
                headers={"Accept": "text/event-stream"},
            )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:500]}"
        )
        sse_text = response.text
        assert sse_text.strip(), (
            "AG-UI SSE body is empty — execute_stream() yielded zero events (pre-SH1.1 regression)"
        )

        events = _parse_sse_events(sse_text)
        assert events, f"No SSE events parsed from AG-UI body: {sse_text[:500]}"

        # AG-UI events are serialized as RunFinishedEvent or similar ag-ui types.
        # At minimum, at least one data-bearing event must be present.
        data_events = [e for e in events if e.get("data")]
        assert data_events, f"No data-bearing SSE events in AG-UI response: {events!r}"

        # Verify a RunFinishedEvent is present (terminal event for AG-UI protocol).
        # The event type is sent as SSE "event:" field by the AG-UI adapter.
        event_field_values = [e.get("event", "") for e in events]
        has_run_finished = any(
            "RunFinished" in ev or "run_finished" in ev.lower() for ev in event_field_values
        )
        assert has_run_finished, (
            f"No RunFinishedEvent found in AG-UI SSE stream. "
            f"Events: {event_field_values!r}\nRaw SSE: {sse_text[:1000]}"
        )

    async def test_agui_endpoint_with_concrete_hooks_also_streams(self) -> None:
        """Verifies that post-SH1.3 concrete hooks don't break the AG-UI stream."""
        registry = _make_registry()
        wf = _make_output_gen_workflow()

        deps = DefaultDependencies(
            registry=registry,
            lifecycle_hooks=LifecycleHookManager(),
        )
        app = FastAPI()
        router = create_agui_endpoint(wf, deps=deps)
        app.include_router(router, prefix="/ag-ui")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ag-ui/",
                json={},
                headers={"Accept": "text/event-stream"},
            )

        assert response.status_code == 200
        assert response.text.strip(), "AG-UI SSE body empty with concrete hooks"


class TestUnifiedAGUIRealExecutor:
    """Unified /ag-ui endpoint, real executor, no execute_stream mocking.

    Guards the unified AG-UI SSE path in beddel_ag_ui.unified.
    The unified endpoint routes by workflow_id and calls execute_stream().
    Pre-SH1.1 this returned 200 with an empty body; now it must return a
    non-empty SSE body.
    """

    async def test_unified_agui_real_executor_returns_nonempty_sse(self) -> None:
        """AC1 (SH1.4): unified /ag-ui drives real execute_stream() and returns non-empty SSE.

        Uses DefaultDependencies() with lifecycle_hooks=None (exact pre-SH1.3
        construction) to prove SH1.1 structural fix is sufficient.
        """
        registry = _make_registry()
        wf = _make_output_gen_workflow()

        deps = DefaultDependencies(registry=registry)
        executor = WorkflowExecutor(registry, deps=deps)
        executors: dict[str, Any] = {wf.id: (wf, executor)}

        app = FastAPI()
        router = create_unified_agui_endpoint(executors)
        app.include_router(router, prefix="/ag-ui")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ag-ui/",
                json={"state": {"workflow_id": wf.id}},
                headers={"Accept": "text/event-stream"},
            )

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:500]}"
        )
        sse_text = response.text
        assert sse_text.strip(), (
            "Unified AG-UI SSE body is empty — execute_stream() yielded zero events "
            "(pre-SH1.1 regression)"
        )

        events = _parse_sse_events(sse_text)
        assert events, f"No SSE events parsed from unified AG-UI body: {sse_text[:500]}"

        data_events = [e for e in events if e.get("data")]
        assert data_events, f"No data-bearing SSE events in unified AG-UI response: {events!r}"

    async def test_unified_agui_with_concrete_hooks_also_streams(self) -> None:
        """Verifies that post-SH1.3 concrete hooks don't break the unified AG-UI stream."""
        registry = _make_registry()
        wf = _make_output_gen_workflow()

        deps = DefaultDependencies(
            registry=registry,
            lifecycle_hooks=LifecycleHookManager(),
        )
        executor = WorkflowExecutor(registry, deps=deps)
        executors: dict[str, Any] = {wf.id: (wf, executor)}

        app = FastAPI()
        router = create_unified_agui_endpoint(executors)
        app.include_router(router, prefix="/ag-ui")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ag-ui/",
                json={"state": {"workflow_id": wf.id}},
                headers={"Accept": "text/event-stream"},
            )

        assert response.status_code == 200
        assert response.text.strip(), "Unified AG-UI SSE body empty with concrete hooks"

    async def test_unified_agui_single_workflow_default_no_workflow_id(
        self,
    ) -> None:
        """Unified endpoint with a single workflow uses it as default (no workflow_id needed)."""
        registry = _make_registry()
        wf = _make_output_gen_workflow()

        deps = DefaultDependencies(registry=registry)
        executor = WorkflowExecutor(registry, deps=deps)
        executors: dict[str, Any] = {wf.id: (wf, executor)}

        app = FastAPI()
        router = create_unified_agui_endpoint(executors)
        app.include_router(router, prefix="/ag-ui")

        # No state.workflow_id — should default to the only loaded workflow
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/ag-ui/",
                json={},
                headers={"Accept": "text/event-stream"},
            )

        assert response.status_code == 200
        assert response.text.strip(), (
            "Unified AG-UI SSE body empty when using single-workflow default"
        )
