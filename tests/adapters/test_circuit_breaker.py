"""Tests for InMemoryCircuitBreaker adapter."""

from __future__ import annotations

import concurrent.futures
from unittest.mock import patch

import pytest

from beddel.adapters.circuit_breaker import InMemoryCircuitBreaker
from beddel.domain.models import CircuitBreakerConfig


class TestInMemoryCircuitBreaker:
    """Unit tests for the InMemoryCircuitBreaker adapter."""

    def test_initial_state_closed(self) -> None:
        """New provider returns 'closed' and is_open returns False."""
        cb = InMemoryCircuitBreaker()

        assert cb.state("openai") == "closed"
        assert cb.is_open("openai") is False

    def test_opens_after_threshold(self) -> None:
        """Circuit opens after failure_threshold consecutive failures."""
        cb = InMemoryCircuitBreaker()

        for _ in range(5):  # default failure_threshold=5
            cb.record_failure("openai")

        assert cb.state("openai") == "open"
        assert cb.is_open("openai") is True

    def test_stays_closed_below_threshold(self) -> None:
        """Circuit stays closed with fewer than failure_threshold failures."""
        cb = InMemoryCircuitBreaker()

        for _ in range(4):  # one below default threshold of 5
            cb.record_failure("openai")

        assert cb.state("openai") == "closed"
        assert cb.is_open("openai") is False

    def test_success_resets_failure_count(self) -> None:
        """Success resets failure count — threshold restarts from 0."""
        cb = InMemoryCircuitBreaker()

        # Record 3 failures (below threshold of 5)
        for _ in range(3):
            cb.record_failure("openai")

        # Success resets the counter
        cb.record_success("openai")

        # Need full 5 failures again to open
        for _ in range(4):
            cb.record_failure("openai")
        assert cb.state("openai") == "closed"

        # One more tips it over
        cb.record_failure("openai")
        assert cb.state("openai") == "open"

    def test_half_open_after_recovery_window(self) -> None:
        """Circuit transitions to half-open after recovery_window elapses."""
        cb = InMemoryCircuitBreaker(
            CircuitBreakerConfig(failure_threshold=2, recovery_window=60.0)
        )

        # Open the circuit
        cb.record_failure("openai")
        cb.record_failure("openai")
        assert cb.state("openai") == "open"

        # Advance time past recovery window
        with patch("beddel.adapters.circuit_breaker.time") as mock_time:
            # First monotonic() call was during record_failure (real).
            # Now simulate time advancing 61 seconds.
            mock_time.monotonic.return_value = 1_000_061.0

            # Patch the stored last_failure_time to a known value
            cb._states["openai"].last_failure_time = 1_000_000.0  # noqa: SLF001

            assert cb.is_open("openai") is False
            assert cb.state("openai") == "half-open"

    def test_half_open_to_closed_after_successes(self) -> None:
        """Half-open circuit closes after success_threshold successes."""
        cb = InMemoryCircuitBreaker(
            CircuitBreakerConfig(failure_threshold=2, recovery_window=0.0, success_threshold=2)
        )

        # Open the circuit
        cb.record_failure("openai")
        cb.record_failure("openai")
        assert cb.state("openai") == "open"

        # Transition to half-open (recovery_window=0 means immediate)
        assert cb.is_open("openai") is False
        assert cb.state("openai") == "half-open"

        # Record success_threshold successes
        cb.record_success("openai")
        assert cb.state("openai") == "half-open"  # not yet

        cb.record_success("openai")
        assert cb.state("openai") == "closed"

    def test_half_open_to_open_on_failure(self) -> None:
        """Half-open circuit reopens on any failure."""
        cb = InMemoryCircuitBreaker(CircuitBreakerConfig(failure_threshold=2, recovery_window=0.0))

        # Open → half-open
        cb.record_failure("openai")
        cb.record_failure("openai")
        assert cb.is_open("openai") is False  # transitions to half-open
        assert cb.state("openai") == "half-open"

        # Single failure → back to open
        cb.record_failure("openai")
        assert cb.state("openai") == "open"

    def test_custom_config(self) -> None:
        """Custom CircuitBreakerConfig thresholds are respected."""
        config = CircuitBreakerConfig(
            failure_threshold=3, recovery_window=30.0, success_threshold=1
        )
        cb = InMemoryCircuitBreaker(config)

        # Need 3 failures to open (not 5)
        cb.record_failure("openai")
        cb.record_failure("openai")
        assert cb.state("openai") == "closed"

        cb.record_failure("openai")
        assert cb.state("openai") == "open"

        # Transition to half-open
        with patch("beddel.adapters.circuit_breaker.time") as mock_time:
            cb._states["openai"].last_failure_time = 1_000_000.0  # noqa: SLF001
            mock_time.monotonic.return_value = 1_000_031.0
            assert cb.is_open("openai") is False

        assert cb.state("openai") == "half-open"

        # Only 1 success needed to close (not 2)
        cb.record_success("openai")
        assert cb.state("openai") == "closed"

    def test_independent_providers(self) -> None:
        """Two providers have independent circuit states."""
        cb = InMemoryCircuitBreaker(CircuitBreakerConfig(failure_threshold=2))

        # Open circuit for openai
        cb.record_failure("openai")
        cb.record_failure("openai")
        assert cb.state("openai") == "open"

        # Anthropic remains closed
        assert cb.state("anthropic") == "closed"
        assert cb.is_open("anthropic") is False

        # Record failure for anthropic — still below threshold
        cb.record_failure("anthropic")
        assert cb.state("anthropic") == "closed"

    def test_thread_safety(self) -> None:
        """Concurrent record_failure calls don't corrupt state."""
        cb = InMemoryCircuitBreaker(CircuitBreakerConfig(failure_threshold=100))

        def fail_many() -> None:
            for _ in range(100):
                cb.record_failure("openai")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(fail_many) for _ in range(10)]
            for f in futures:
                f.result()

        # 10 threads × 100 failures = 1000 total, threshold is 100
        # Circuit must be open and failure_count must be exactly 1000
        assert cb.state("openai") == "open"
        assert cb._states["openai"].failure_count == 1000  # noqa: SLF001

    def test_invalid_config_raises(self) -> None:
        """Invalid config values raise ValueError."""
        with pytest.raises(ValueError, match="failure_threshold must be >= 1"):
            InMemoryCircuitBreaker(CircuitBreakerConfig(failure_threshold=0))

        with pytest.raises(ValueError, match="recovery_window must be >= 0"):
            InMemoryCircuitBreaker(CircuitBreakerConfig(recovery_window=-1))

        with pytest.raises(ValueError, match="success_threshold must be >= 1"):
            InMemoryCircuitBreaker(CircuitBreakerConfig(success_threshold=0))
