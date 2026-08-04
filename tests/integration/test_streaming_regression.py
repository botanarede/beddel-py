"""Real-executor streaming regression tests for Epic SH1 (Stories SH1.4 and SH1.3).

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

Surfaces covered (SH1.4 — streaming non-regression):
    - /workflows/{id} with stream=True step (via create_beddel_handler)
    - /ag-ui/{id}  (via create_agui_endpoint)
    - /ag-ui (unified, via create_unified_agui_endpoint + WorkflowExecutor)

Hook-notification tests (SH1.3 post-review fix):
    The 4 CLI streaming surfaces in commands.py (lines 1810, 1868, 1896, 1983)
    each inject ``lifecycle_hooks=LifecycleHookManager()`` into DefaultDependencies
    (the SH1.3 fix).  The tests in ``TestHookNotificationBeddelHandler``,
    ``TestHookNotificationAGUIEndpoint``, and ``TestHookNotificationUnifiedAGUI``
    verify that a user-supplied ILifecycleHook registered into a LifecycleHookManager
    and wired through the same construction pattern as each CLI site actually has its
    ``on_workflow_start`` and ``on_workflow_end`` callbacks invoked at least once when
    a workflow is executed.  These tests are structurally capable of failing: if the
    lifecycle_hooks kwarg is omitted from DefaultDependencies (or a bare IHookManager()
    is used instead of LifecycleHookManager), the hook's callbacks will not fire and
    the assertions will fail — exactly the silent-delivery regression class this epic
    exists to prevent.

    Surfaces 1–3 (create_beddel_handler, create_agui_endpoint,
    create_unified_agui_endpoint) are covered directly here.

    Surface 4 — A2A (BeddelA2AExecutor / commands.py line 1983) — is DEFERRED
    to repo/kits/serve-a2a-kit/tests/.  Rationale:
        • ``beddel_serve_a2a`` is not installed in the SDK venv (it lives in the
          serve-a2a-kit and is only available via conftest.py sys.path injection
          when running from the kit's test directory, or when serve-a2a-kit is
          installed as an editable extra).
        • BeddelA2AExecutor.execute() requires a real a2a-sdk RequestContext,
          EventQueue, and DefaultRequestHandler, which means the test harness
          must boot the full a2a JSON-RPC stack.  The existing
          test_a2a_integration.py in serve-a2a-kit already validates that
          BeddelA2AExecutor drives execute_stream() end-to-end.  Adding hook
          assertions there (with a _TrackingHook wired into the WorkflowExecutor
          stored in the _StubWorkflowExecutor's place) is the correct location.
        • Running those tests in this module would duplicate the entire a2a kit
          harness and depend on proto/google packages that are kit-external.
    See: repo/kits/serve-a2a-kit/tests/test_a2a_integration.py

Dashboard bridge — DashboardSSEBridge.execute_and_stream() (FIX 1, SH1.4 post-review):
    The original claim that DashboardSSEBridge requires a WebSocket transport and
    is not directly testable was FALSE. DashboardSSEBridge.execute_and_stream() is
    a plain async method that calls self._executor.execute_stream() and returns an
    async generator of SSE dicts via BeddelSSEAdapter — no WebSocket, no HTTP,
    no ASGI transport anywhere in the class. A grep across beddel_serve_fastapi/
    for WebSocket found zero matches. The bridge IS directly testable by constructing
    a real WorkflowExecutor + ExecutionHistoryStore and calling execute_and_stream().
    Direct regression coverage is now provided in TestDashboardBridgeRealExecutor
    (see below): it constructs a real WorkflowExecutor with DefaultDependencies()
    (no lifecycle_hooks, matching the pre-SH1.3 CLI pattern), calls execute_and_stream(),
    iterates the async generator, and asserts non-empty events, a "workflow_end" terminal
    event in the SSE event field, and that the ExecutionHistoryStore record ends with
    status "success". This class is NOT deferred — it is present and passing.

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
from beddel_serve_fastapi.dashboard.bridge import DashboardSSEBridge
from beddel_serve_fastapi.dashboard.history import ExecutionHistoryStore
from beddel_serve_fastapi.handler import create_beddel_handler
from fastapi import FastAPI

from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import DefaultDependencies, Step, Workflow
from beddel.domain.ports import ILifecycleHook
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

        Router is mounted at prefix=/ag-ui/{wf.id}, matching the production
        _build_runtime_app() composition in commands.py line 1871:
            app.include_router(agui_router, prefix=f"/ag-ui/{wf_id}")
        Testing at the bare /ag-ui/ prefix would not exercise the per-workflow-ID
        composition boundary that this epic fixed.
        """
        registry = _make_registry()
        # stream=False: AG-UI always calls execute_stream() regardless
        wf = _make_output_gen_workflow()

        deps = DefaultDependencies(registry=registry)
        app = FastAPI()
        router = create_agui_endpoint(wf, deps=deps)
        # Use the real per-workflow prefix pattern from commands.py line 1871
        app.include_router(router, prefix=f"/ag-ui/{wf.id}")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/ag-ui/{wf.id}/",
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
        # BeddelAGUIAdapter maps WORKFLOW_END → RunFinishedEvent whose type.value is
        # "RUN_FINISHED" (ag_ui.core.EventType.RUN_FINISHED).
        event_field_values = [e.get("event", "") for e in events]
        has_run_finished = any(
            "RunFinished" in ev or "run_finished" in ev.lower() or "RUN_FINISHED" in ev
            for ev in event_field_values
        )
        assert has_run_finished, (
            f"No RunFinishedEvent found in AG-UI SSE stream. "
            f"Events: {event_field_values!r}\nRaw SSE: {sse_text[:1000]}"
        )

    async def test_agui_endpoint_with_concrete_hooks_also_streams(self) -> None:
        """Verifies that post-SH1.3 concrete hooks don't break the AG-UI stream.

        Router is mounted at prefix=/ag-ui/{wf.id} (production pattern).
        """
        registry = _make_registry()
        wf = _make_output_gen_workflow()

        deps = DefaultDependencies(
            registry=registry,
            lifecycle_hooks=LifecycleHookManager(),
        )
        app = FastAPI()
        router = create_agui_endpoint(wf, deps=deps)
        app.include_router(router, prefix=f"/ag-ui/{wf.id}")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/ag-ui/{wf.id}/",
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

        Also asserts a terminal RunFinishedEvent (SSE event field "RUN_FINISHED") is
        present — a stream that hangs or ends abnormally without a terminal frame would
        previously have passed this test (SH1.4 post-review FIX 2).
        The unified endpoint emits AG-UI events via _agui_sse_stream which uses
        event.type.value as the SSE event field; WORKFLOW_END maps to RunFinishedEvent
        whose type.value is "RUN_FINISHED" (ag_ui.core.EventType.RUN_FINISHED).
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

        # Assert terminal RunFinishedEvent is present.
        # The unified endpoint's _agui_sse_stream serialises events using event.type.value
        # as the SSE "event:" field. WORKFLOW_END → RunFinishedEvent → type.value = "RUN_FINISHED".
        event_field_values = [e.get("event", "") for e in events]
        has_run_finished = any(
            "RUN_FINISHED" in ev or "RunFinished" in ev or "run_finished" in ev.lower()
            for ev in event_field_values
        )
        assert has_run_finished, (
            f"No RunFinishedEvent (RUN_FINISHED) found in unified AG-UI SSE stream. "
            f"A stream that terminates abnormally or hangs without a terminal frame "
            f"would produce this failure. "
            f"Events: {event_field_values!r}\nRaw SSE: {sse_text[:1000]}"
        )

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


# ---------------------------------------------------------------------------
# SH1.4 post-review fix — Dashboard bridge real-executor regression
# ---------------------------------------------------------------------------
# FIX 1: DashboardSSEBridge.execute_and_stream() is a plain async method that
# calls self._executor.execute_stream() and returns an async generator of SSE
# dicts via BeddelSSEAdapter — no WebSocket, no HTTP, no ASGI transport.
# A grep across beddel_serve_fastapi/ for WebSocket found zero matches.
# The original claim in the story Dev Notes and the module docstring that a
# harness was "not feasible" due to WebSocket requirements was FALSE.
# This class directly tests the bridge with a real WorkflowExecutor, proving:
#   (a) events are non-empty
#   (b) a "workflow_end" terminal event is present in the SSE event field
#   (c) the ExecutionHistoryStore record for that run_id ends with status "success"
# ---------------------------------------------------------------------------


class TestDashboardBridgeRealExecutor:
    """DashboardSSEBridge.execute_and_stream() with real executor, no mocking.

    Guards the dashboard bridge path in
    beddel_serve_fastapi.dashboard.bridge.DashboardSSEBridge.

    The bridge is a plain async class: execute_and_stream() calls
    self._executor.execute_stream() and pipes results through
    BeddelSSEAdapter.stream_events(), returning (run_id, sse_stream).
    No WebSocket, no HTTP transport, no ASGI required — the class is
    directly instantiable with a WorkflowExecutor + ExecutionHistoryStore.

    This test class disproves the original (false) claim that the bridge
    was not directly testable due to WebSocket requirements.
    """

    async def test_bridge_execute_and_stream_returns_nonempty_events_with_terminal(
        self,
    ) -> None:
        """DashboardSSEBridge yields non-empty SSE dicts with a workflow_end terminal event.

        Constructs a real WorkflowExecutor with DefaultDependencies() (no
        lifecycle_hooks, matching the pre-SH1.3 CLI pattern) and a real
        ExecutionHistoryStore, calls execute_and_stream(), iterates the
        returned async generator, and asserts:
          (a) the event list is non-empty,
          (b) a "workflow_end" terminal event is present (SSE dict "event" field),
          (c) the ExecutionHistoryStore record for that run_id ends with status "success".

        BeddelSSEAdapter.stream_events() yields dicts where the "event" key is
        set to event.event_type.value — so the terminal event has event="workflow_end".
        """
        registry = _make_registry()
        wf = _make_output_gen_workflow()

        # DefaultDependencies() with no lifecycle_hooks — mirrors pre-SH1.3 CLI pattern
        deps = DefaultDependencies(registry=registry)
        executor = WorkflowExecutor(registry, deps=deps)
        store = ExecutionHistoryStore()

        bridge = DashboardSSEBridge(executor=executor, history=store)
        run_id, sse_stream = await bridge.execute_and_stream(wf)

        # Drain the async generator
        collected: list[dict[str, str]] = []
        async for sse_dict in sse_stream:
            collected.append(sse_dict)

        # (a) non-empty events
        assert collected, (
            "DashboardSSEBridge.execute_and_stream() yielded zero SSE dicts — "
            "execute_stream() returned no events (pre-SH1.1 regression in bridge path)"
        )

        # (b) terminal "workflow_end" event must be present
        # BeddelSSEAdapter yields {"event": event.event_type.value, "data": ...}
        # so the terminal event has event="workflow_end".
        event_values = [d.get("event", "") for d in collected]
        assert "workflow_end" in event_values, (
            f"No workflow_end terminal event in DashboardSSEBridge SSE output. "
            f"event values: {event_values!r}"
        )

        # (c) ExecutionHistoryStore record ends with status "success"
        record = store.get(run_id)
        assert record is not None, (
            f"ExecutionHistoryStore has no record for run_id={run_id!r} — "
            "bridge.execute_and_stream() did not call history.add() for this run"
        )
        assert record.status == "success", (
            f"ExecutionHistoryStore record for run_id={run_id!r} has status={record.status!r}, "
            f"expected 'success'. events collected: {collected!r}"
        )
        assert record.finished_at is not None, (
            "ExecutionHistoryStore record has no finished_at — stream did not complete cleanly"
        )


# ---------------------------------------------------------------------------
# SH1.3 post-review fix — hook-notification tests for CLI streaming surfaces
# ---------------------------------------------------------------------------
# Each test below registers a real _TrackingHook (an ILifecycleHook subclass
# that records which on_* callbacks were called) into a LifecycleHookManager,
# drives it through the construction pattern that each CLI injection site
# (commands.py lines 1810, 1868, 1896) actually uses, executes one workflow,
# and asserts that on_workflow_start and on_workflow_end were each called at
# least once.
#
# Why these tests are structurally capable of failing
# ---------------------------------------------------
# The assertion `assert "on_workflow_start" in hook.calls` will fail if:
#   - lifecycle_hooks is not supplied to DefaultDependencies (the pre-SH1.3
#     state), because the executor falls back to a no-op IHookManager and
#     add_hook() silently does nothing — hooks registered on the fallback
#     manager are never invoked.
#   - A bare IHookManager() is used instead of LifecycleHookManager, same result.
#   - The LifecycleHookManager is constructed but the hook is not added to it.
#   - execute_stream() is bypassed (e.g. stream=False on the step for site 1,
#     which routes through the non-streaming code path — see note on Site 1).
#
# Site 4 (A2A / BeddelA2AExecutor at commands.py line 1983) is deferred to
# repo/kits/serve-a2a-kit/tests/. See the module docstring for full rationale.
# ---------------------------------------------------------------------------


class _TrackingHook(ILifecycleHook):
    """Records every on_* callback invocation by name.

    Reusable across all 3 surface tests.  Instantiate fresh per test
    (do not share across tests — calls list is mutable).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
        self.calls.append("on_workflow_start")

    async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:
        self.calls.append("on_workflow_end")

    async def on_step_start(self, step_id: str, primitive: str) -> None:
        self.calls.append(f"on_step_start:{step_id}")

    async def on_step_end(self, step_id: str, result: Any) -> None:
        self.calls.append(f"on_step_end:{step_id}")


class TestHookNotificationBeddelHandler:
    """Site 1 — create_beddel_handler (commands.py line 1810).

    The CLI construction pattern at this site is:
        deps = DefaultDependencies(
            ...,
            lifecycle_hooks=_LifecycleHookManager(),
        )
        router = create_beddel_handler(workflow, deps=deps)

    This test replicates that pattern exactly, registers a _TrackingHook into
    the manager, drives one workflow execution via HTTP, and asserts the hook's
    on_workflow_start and on_workflow_end were called.

    NOTE: stream=True is required on the step so that
    beddel_serve_fastapi.handler._has_stream_steps is True and the handler
    calls execute_stream() rather than the fallback execute() path.  The
    lifecycle hook notifications are emitted by execute_stream(); the non-
    streaming execute() path may or may not call them (out of scope for this
    story).  This matches what the CLI uses when a workflow file declares a
    streaming step.
    """

    async def test_tracking_hook_receives_workflow_start_and_end(self) -> None:
        """on_workflow_start and on_workflow_end are called via create_beddel_handler.

        Fails if lifecycle_hooks is omitted from DefaultDependencies (pre-SH1.3
        regression) because the executor's no-op IHookManager silently discards
        add_hook() calls and the tracking hook's callbacks are never invoked.
        """
        registry = _make_registry()
        # stream=True forces execute_stream() path in the handler (see class docstring)
        wf = _make_output_gen_workflow(stream=True)

        hook = _TrackingHook()
        manager = LifecycleHookManager([hook])

        # Mirror commands.py site 1 (line 1810):
        #   deps = DefaultDependencies(..., lifecycle_hooks=_LifecycleHookManager())
        deps = DefaultDependencies(
            registry=registry,
            lifecycle_hooks=manager,
        )
        app = FastAPI()
        router = create_beddel_handler(wf, deps=deps)
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
            f"Expected 200, got {response.status_code}: {response.text[:200]}"
        )
        assert response.text.strip(), "SSE body is empty — execute_stream() yielded zero events"

        # Hook notification assertions — these fail if lifecycle_hooks was
        # omitted from DefaultDependencies (the pre-SH1.3 regression).
        assert "on_workflow_start" in hook.calls, (
            f"on_workflow_start was not called. hook.calls={hook.calls!r}\n"
            "This means LifecycleHookManager was not wired into DefaultDependencies "
            "(pre-SH1.3 regression: silent hook non-delivery on CLI streaming surface 1)."
        )
        assert "on_workflow_end" in hook.calls, (
            f"on_workflow_end was not called. hook.calls={hook.calls!r}\n"
            "Workflow may have failed before completion, or hooks are not wired."
        )


class TestHookNotificationAGUIEndpoint:
    """Site 2 — create_agui_endpoint (commands.py line 1868).

    The CLI construction pattern at this site is:
        wf_deps = DefaultDependencies(
            ...,
            lifecycle_hooks=_LifecycleHookManager(),
        )
        agui_router = create_agui_endpoint(wf, deps=wf_deps)

    This test replicates that pattern exactly with a tracking hook and
    asserts on_workflow_start and on_workflow_end were called.

    The AG-UI endpoint always calls execute_stream() regardless of whether
    any step has stream=True, so stream=False (the default) is fine here.
    """

    async def test_tracking_hook_receives_workflow_start_and_end(self) -> None:
        """on_workflow_start and on_workflow_end are called via create_agui_endpoint.

        Fails if lifecycle_hooks is omitted from DefaultDependencies (pre-SH1.3
        regression) because the executor's no-op IHookManager silently discards
        add_hook() calls and the tracking hook's callbacks are never invoked.
        """
        registry = _make_registry()
        wf = _make_output_gen_workflow()  # stream=False is fine; AG-UI always streams

        hook = _TrackingHook()
        manager = LifecycleHookManager([hook])

        # Mirror commands.py site 2 (line 1868):
        #   wf_deps = DefaultDependencies(..., lifecycle_hooks=_LifecycleHookManager())
        #   agui_router = create_agui_endpoint(wf, deps=wf_deps)
        deps = DefaultDependencies(
            registry=registry,
            lifecycle_hooks=manager,
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

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:200]}"
        )
        assert response.text.strip(), (
            "AG-UI SSE body is empty — execute_stream() yielded zero events"
        )

        assert "on_workflow_start" in hook.calls, (
            f"on_workflow_start was not called via AG-UI endpoint. hook.calls={hook.calls!r}\n"
            "This means LifecycleHookManager was not wired into DefaultDependencies "
            "(pre-SH1.3 regression: silent hook non-delivery on CLI streaming surface 2)."
        )
        assert "on_workflow_end" in hook.calls, (
            f"on_workflow_end was not called via AG-UI endpoint. hook.calls={hook.calls!r}"
        )


class TestHookNotificationUnifiedAGUI:
    """Site 3 — create_unified_agui_endpoint + WorkflowExecutor (commands.py line 1896).

    The CLI construction pattern at this site is:
        _wf_deps = DefaultDependencies(
            ...,
            lifecycle_hooks=_LifecycleHookManager(),
        )
        _executor = _WFExec(registry, deps=_wf_deps)
        _agui_executors[_wf_id] = (_wf, _executor)
        unified_router = create_unified_agui_endpoint(_agui_executors)

    This test replicates that pattern exactly with a tracking hook and
    asserts on_workflow_start and on_workflow_end were called.
    """

    async def test_tracking_hook_receives_workflow_start_and_end(self) -> None:
        """on_workflow_start and on_workflow_end are called via create_unified_agui_endpoint.

        Fails if lifecycle_hooks is omitted from DefaultDependencies (pre-SH1.3
        regression) because the executor's no-op IHookManager silently discards
        add_hook() calls and the tracking hook's callbacks are never invoked.
        """
        registry = _make_registry()
        wf = _make_output_gen_workflow()

        hook = _TrackingHook()
        manager = LifecycleHookManager([hook])

        # Mirror commands.py site 3 (line 1896):
        #   _wf_deps = DefaultDependencies(..., lifecycle_hooks=_LifecycleHookManager())
        #   _executor = _WFExec(registry, deps=_wf_deps)
        #   _agui_executors[_wf_id] = (_wf, _executor)
        #   unified_router = create_unified_agui_endpoint(_agui_executors)
        deps = DefaultDependencies(
            registry=registry,
            lifecycle_hooks=manager,
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

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text[:200]}"
        )
        assert response.text.strip(), (
            "Unified AG-UI SSE body is empty — execute_stream() yielded zero events"
        )

        assert "on_workflow_start" in hook.calls, (
            f"on_workflow_start was not called via unified AG-UI endpoint. "
            f"hook.calls={hook.calls!r}\n"
            "This means LifecycleHookManager was not wired into DefaultDependencies "
            "(pre-SH1.3 regression: silent hook non-delivery on CLI streaming surface 3)."
        )
        assert "on_workflow_end" in hook.calls, (
            f"on_workflow_end was not called via unified AG-UI endpoint. hook.calls={hook.calls!r}"
        )
