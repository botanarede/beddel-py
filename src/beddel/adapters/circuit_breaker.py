"""In-memory circuit breaker adapter for per-provider fault tolerance.

Implements :class:`~beddel.domain.ports.ICircuitBreaker` with thread-safe
in-memory state tracking.  Each provider has independent circuit state
that transitions through CLOSED → OPEN → HALF_OPEN → CLOSED.

Uses ``threading.Lock`` for synchronization — safe for short critical
sections in asyncio code (no ``await`` inside lock).

Uses ``time.monotonic()`` for recovery window timing — immune to system
clock changes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from beddel.domain.models import CircuitBreakerConfig, CircuitState


@dataclass
class _ProviderState:
    """Internal per-provider circuit breaker state.

    Not part of the public API — used only by :class:`InMemoryCircuitBreaker`.
    """

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None


class InMemoryCircuitBreaker:
    """Thread-safe in-memory circuit breaker tracking per-provider state.

    Satisfies the :class:`~beddel.domain.ports.ICircuitBreaker` protocol
    via structural subtyping.

    Args:
        config: Circuit breaker configuration.  Defaults to
            ``CircuitBreakerConfig()`` when ``None``.

    Raises:
        ValueError: If ``failure_threshold < 1``, ``recovery_window < 0``,
            or ``success_threshold < 1``.
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        if self._config.failure_threshold < 1:
            msg = f"failure_threshold must be >= 1, got {self._config.failure_threshold}"
            raise ValueError(msg)
        if self._config.recovery_window < 0:
            msg = f"recovery_window must be >= 0, got {self._config.recovery_window}"
            raise ValueError(msg)
        if self._config.success_threshold < 1:
            msg = f"success_threshold must be >= 1, got {self._config.success_threshold}"
            raise ValueError(msg)
        self._states: dict[str, _ProviderState] = {}
        self._lock = threading.Lock()

    def _get_or_create(self, provider: str) -> _ProviderState:
        """Return existing state or create a new CLOSED state for *provider*.

        Must be called while holding ``self._lock``.
        """
        if provider not in self._states:
            self._states[provider] = _ProviderState()
        return self._states[provider]

    def record_failure(self, provider: str) -> None:
        """Record a failed request for *provider*.

        Increments the failure counter.  If the failure threshold is
        reached, transitions to OPEN and records the timestamp.  If
        already in HALF_OPEN, transitions back to OPEN immediately.
        """
        with self._lock:
            ps = self._get_or_create(provider)
            ps.failure_count += 1

            if ps.state == CircuitState.HALF_OPEN:
                # Any failure in half-open → back to open
                ps.state = CircuitState.OPEN
                ps.last_failure_time = time.monotonic()
                ps.success_count = 0
            elif ps.failure_count >= self._config.failure_threshold:
                ps.state = CircuitState.OPEN
                ps.last_failure_time = time.monotonic()

    def record_success(self, provider: str) -> None:
        """Record a successful request for *provider*.

        Resets the failure counter.  In HALF_OPEN state, increments the
        success counter and transitions to CLOSED when the success
        threshold is reached.
        """
        with self._lock:
            ps = self._get_or_create(provider)
            ps.failure_count = 0

            if ps.state == CircuitState.HALF_OPEN:
                ps.success_count += 1
                if ps.success_count >= self._config.success_threshold:
                    ps.state = CircuitState.CLOSED
                    ps.success_count = 0

    def is_open(self, provider: str) -> bool:
        """Check whether the circuit is open for *provider*.

        Returns ``True`` when requests should be blocked (OPEN state
        within the recovery window).  Returns ``False`` for CLOSED,
        HALF_OPEN, or OPEN-past-recovery-window (which transitions to
        HALF_OPEN to allow a probe).

        Unknown providers return ``False``.
        """
        with self._lock:
            if provider not in self._states:
                return False
            ps = self._states[provider]

            if ps.state == CircuitState.CLOSED:
                return False

            if ps.state == CircuitState.HALF_OPEN:
                return False

            # OPEN — check recovery window
            if ps.last_failure_time is not None:
                elapsed = time.monotonic() - ps.last_failure_time
                if elapsed >= self._config.recovery_window:
                    ps.state = CircuitState.HALF_OPEN
                    ps.failure_count = 0
                    ps.success_count = 0
                    return False

            return True

    def state(self, provider: str) -> str:
        """Return the current circuit state string for *provider*.

        Unknown providers return ``"closed"``.
        """
        with self._lock:
            if provider not in self._states:
                return CircuitState.CLOSED.value
            return self._states[provider].state.value
