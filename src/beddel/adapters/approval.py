"""In-memory approval gate adapters for HOTL approval flows.

Implements :class:`~beddel.domain.ports.IApprovalGate` with two variants:

- :class:`InMemoryApprovalGate` — auto-approves every request immediately.
  Designed for testing and development where human approval is not needed.
- :class:`ConfigurableApprovalGate` — applies risk-based auto-approve logic
  using an :class:`~beddel.domain.models.ApprovalPolicy`.  Requests whose
  risk level is in ``policy.auto_approve_levels`` are auto-approved; all
  others are stored as PENDING for later resolution (CIBA async flow).

Both adapters use ``uuid.uuid4().hex`` for request IDs and ``time.time()``
for timestamps.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from beddel.domain.models import (
    ApprovalPolicy,
    ApprovalResult,
    ApprovalStatus,
    RiskLevel,
)

__all__ = [
    "ConfigurableApprovalGate",
    "InMemoryApprovalGate",
]


class InMemoryApprovalGate:
    """Auto-approving approval gate for testing and development.

    Satisfies the :class:`~beddel.domain.ports.IApprovalGate` protocol
    via structural subtyping.  Every request is immediately approved and
    stored in an internal history list for test assertions.

    Example::

        gate = InMemoryApprovalGate()
        result = await gate.request_approval("read_file", RiskLevel.LOW)
        assert result.status == ApprovalStatus.APPROVED
        assert len(gate.history) == 1
    """

    def __init__(self) -> None:
        self._history: list[ApprovalResult] = []

    async def request_approval(self, action: str, risk_level: RiskLevel) -> ApprovalResult:
        """Auto-approve the request immediately and record it in history.

        Args:
            action: Description of the action requiring approval.
            risk_level: The classified risk level of the action.

        Returns:
            An :class:`ApprovalResult` with status ``APPROVED``.
        """
        result = ApprovalResult(
            request_id=uuid.uuid4().hex,
            status=ApprovalStatus.APPROVED,
            approver="auto",
            timestamp=time.time(),
            metadata={"action": action, "risk_level": risk_level.value},
        )
        self._history.append(result)
        return result

    async def check_status(self, request_id: str) -> ApprovalStatus:
        """Look up the status of a previously submitted request.

        Args:
            request_id: The unique identifier from a prior approval result.

        Returns:
            The :class:`ApprovalStatus` of the matching request, or
            ``PENDING`` if the request ID is not found.
        """
        for entry in self._history:
            if entry.request_id == request_id:
                return entry.status
        return ApprovalStatus.PENDING

    async def request_approval_async(self, action: str, risk_level: RiskLevel) -> str:
        """Auto-approve asynchronously and return the request_id immediately.

        Args:
            action: Description of the action requiring approval.
            risk_level: The classified risk level of the action.

        Returns:
            The ``request_id`` for subsequent polling via :meth:`check_status`.
        """
        result = await self.request_approval(action, risk_level)
        return result.request_id

    @property
    def history(self) -> list[ApprovalResult]:
        """Return the list of all approval results for test assertions."""
        return list(self._history)


class ConfigurableApprovalGate:
    """Risk-based approval gate driven by an :class:`ApprovalPolicy`.

    Satisfies the :class:`~beddel.domain.ports.IApprovalGate` protocol
    via structural subtyping.  Requests whose risk level appears in
    ``policy.auto_approve_levels`` are auto-approved immediately.  All
    other requests are stored as ``PENDING`` and a background timeout
    task monitors the escalation window (CIBA async flow).

    Args:
        policy: The approval policy controlling auto-approve behaviour.
            Defaults to ``ApprovalPolicy()`` when ``None``.

    Example::

        policy = ApprovalPolicy(auto_approve_levels=[RiskLevel.LOW])
        gate = ConfigurableApprovalGate(policy=policy)

        low = await gate.request_approval("read_file", RiskLevel.LOW)
        assert low.status == ApprovalStatus.APPROVED

        high = await gate.request_approval("delete_db", RiskLevel.HIGH)
        assert high.status == ApprovalStatus.PENDING
    """

    def __init__(self, policy: ApprovalPolicy | None = None) -> None:
        self._policy = policy or ApprovalPolicy()
        self._requests: dict[str, ApprovalResult] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def request_approval(self, action: str, risk_level: RiskLevel) -> ApprovalResult:
        """Evaluate the request against the policy and return a result.

        If ``risk_level`` is in ``policy.auto_approve_levels``, the request
        is auto-approved immediately.  Otherwise it is stored as ``PENDING``
        and a background task monitors the timeout for escalation.

        Args:
            action: Description of the action requiring approval.
            risk_level: The classified risk level of the action.

        Returns:
            An :class:`ApprovalResult` with status ``APPROVED`` or
            ``PENDING`` depending on the policy.
        """
        request_id = uuid.uuid4().hex
        if risk_level in self._policy.auto_approve_levels:
            status = ApprovalStatus.APPROVED
            approver: str | None = "policy"
        else:
            status = ApprovalStatus.PENDING
            approver = None

        result = ApprovalResult(
            request_id=request_id,
            status=status,
            approver=approver,
            timestamp=time.time(),
            metadata={"action": action, "risk_level": risk_level.value},
        )
        self._requests[request_id] = result

        # Start background timeout escalation for PENDING requests
        if status == ApprovalStatus.PENDING:
            self._start_timeout_task(request_id)

        return result

    async def request_approval_async(self, action: str, risk_level: RiskLevel) -> str:
        """Request approval asynchronously using the CIBA pattern.

        Submits the request and returns the ``request_id`` immediately
        without blocking.  The caller polls :meth:`check_status` to
        retrieve the eventual decision.  A background task monitors the
        timeout and applies the escalation policy if no human responds.

        Args:
            action: Description of the action requiring approval.
            risk_level: The classified risk level of the action.

        Returns:
            The ``request_id`` for subsequent polling via :meth:`check_status`.
        """
        result = await self.request_approval(action, risk_level)
        return result.request_id

    async def check_status(self, request_id: str) -> ApprovalStatus:
        """Return the current status of a pending or resolved request.

        Args:
            request_id: The unique identifier from a prior approval result.

        Returns:
            The :class:`ApprovalStatus` of the matching request, or
            ``PENDING`` if the request ID is not found.
        """
        if request_id in self._requests:
            return self._requests[request_id].status
        return ApprovalStatus.PENDING

    async def resolve(
        self, request_id: str, status: ApprovalStatus, approver: str
    ) -> ApprovalResult | None:
        """Externally resolve a pending approval request.

        Used when a human approves or denies via an external channel
        (webhook, UI, CLI).  If the request is still ``PENDING``, its
        status is updated to the given value.  Already-resolved requests
        are left unchanged.

        Args:
            request_id: The unique identifier of the request to resolve.
            status: The new approval status (e.g. ``APPROVED``, ``DENIED``).
            approver: Identity of the human or system resolving the request.

        Returns:
            The updated :class:`ApprovalResult`, or ``None`` if the
            request ID is not found.
        """
        if request_id not in self._requests:
            return None

        current = self._requests[request_id]
        if current.status != ApprovalStatus.PENDING:
            return current

        updated = ApprovalResult(
            request_id=request_id,
            status=status,
            approver=approver,
            timestamp=time.time(),
            metadata=current.metadata,
        )
        self._requests[request_id] = updated
        return updated

    def _start_timeout_task(self, request_id: str) -> None:
        """Start a background task that applies escalation after timeout.

        The task is stored in ``_background_tasks`` to prevent garbage
        collection (standard asyncio pattern).
        """
        task = asyncio.create_task(self._timeout_escalation(request_id))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _timeout_escalation(self, request_id: str) -> None:
        """Background coroutine that waits for timeout then escalates.

        After ``policy.timeout_seconds``, checks if the request is still
        ``PENDING``.  If so, applies the configured ``escalation_policy``:

        - ``"auto-approve"`` → status becomes ``APPROVED``
        - ``"auto-deny"`` → status becomes ``DENIED``
        - ``"delegate"`` → status becomes ``ESCALATED``
        """
        await asyncio.sleep(self._policy.timeout_seconds)

        if request_id not in self._requests:
            return

        current = self._requests[request_id]
        if current.status != ApprovalStatus.PENDING:
            return

        escalation = self._policy.escalation_policy
        if escalation == "auto-approve":
            new_status = ApprovalStatus.APPROVED
        elif escalation == "auto-deny":
            new_status = ApprovalStatus.DENIED
        else:  # "delegate" or any other value
            new_status = ApprovalStatus.ESCALATED

        updated = ApprovalResult(
            request_id=request_id,
            status=new_status,
            approver=f"escalation:{escalation}",
            timestamp=time.time(),
            metadata=current.metadata,
        )
        self._requests[request_id] = updated

    @property
    def policy(self) -> ApprovalPolicy:
        """Return the configured approval policy."""
        return self._policy

    @property
    def pending_requests(self) -> dict[str, ApprovalResult]:
        """Return a copy of all stored requests (for test assertions)."""
        return dict(self._requests)
