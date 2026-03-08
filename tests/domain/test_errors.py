"""Unit tests for beddel.domain.errors module."""

from __future__ import annotations

import pytest

from beddel.domain.errors import (
    AdapterError,
    BeddelError,
    ExecutionError,
    ParseError,
    PrimitiveError,
    ResolveError,
    TracingError,
)

# All concrete subclasses paired with their expected code prefix.
_SUBCLASSES: list[tuple[type[BeddelError], str]] = [
    (ParseError, "BEDDEL-PARSE-001"),
    (ResolveError, "BEDDEL-RESOLVE-001"),
    (ExecutionError, "BEDDEL-EXEC-001"),
    (PrimitiveError, "BEDDEL-PRIM-001"),
    (AdapterError, "BEDDEL-ADAPT-001"),
    (TracingError, "BEDDEL-ADAPT-010"),
]


class TestBeddelError:
    """Tests for the BeddelError base exception."""

    def test_instantiation_with_all_args(self) -> None:
        details = {"line": 42, "file": "workflow.yaml"}
        err = BeddelError("BEDDEL-TEST-001", "something broke", details)

        assert err.code == "BEDDEL-TEST-001"
        assert err.message == "something broke"
        assert err.details == {"line": 42, "file": "workflow.yaml"}

    def test_details_defaults_to_empty_dict(self) -> None:
        err = BeddelError("BEDDEL-TEST-002", "no details")

        assert err.details == {}

    def test_details_none_becomes_empty_dict(self) -> None:
        err = BeddelError("BEDDEL-TEST-003", "explicit none", None)

        assert err.details == {}

    def test_str_includes_code_and_message(self) -> None:
        err = BeddelError("BEDDEL-TEST-004", "readable message")

        assert str(err) == "BEDDEL-TEST-004: readable message"

    def test_is_subclass_of_exception(self) -> None:
        assert issubclass(BeddelError, Exception)


class TestSubclassInheritance:
    """Tests that every subclass inherits from BeddelError."""

    @pytest.mark.parametrize(
        ("cls", "code"),
        _SUBCLASSES,
        ids=[c.__name__ for c, _ in _SUBCLASSES],
    )
    def test_is_instance_of_beddel_error(self, cls: type[BeddelError], code: str) -> None:
        err = cls(code, "test")

        assert isinstance(err, BeddelError)

    @pytest.mark.parametrize(
        ("cls", "code"),
        _SUBCLASSES,
        ids=[c.__name__ for c, _ in _SUBCLASSES],
    )
    def test_catchable_via_except_beddel_error(self, cls: type[BeddelError], code: str) -> None:
        with pytest.raises(BeddelError):
            raise cls(code, "catch via base")

    @pytest.mark.parametrize(
        ("cls", "code"),
        _SUBCLASSES,
        ids=[c.__name__ for c, _ in _SUBCLASSES],
    )
    def test_preserves_attributes(self, cls: type[BeddelError], code: str) -> None:
        details = {"ctx": "value"}
        err = cls(code, "msg", details)

        assert err.code == code
        assert err.message == "msg"
        assert err.details == {"ctx": "value"}

    @pytest.mark.parametrize(
        ("cls", "code"),
        _SUBCLASSES,
        ids=[c.__name__ for c, _ in _SUBCLASSES],
    )
    def test_str_representation(self, cls: type[BeddelError], code: str) -> None:
        err = cls(code, "description")

        assert str(err) == f"{code}: description"


class TestAllExports:
    """Tests that __all__ contains all expected error classes."""

    def test_all_contains_expected_classes(self) -> None:
        from beddel.domain import errors

        expected = {
            "BeddelError",
            "ParseError",
            "ResolveError",
            "ExecutionError",
            "PrimitiveError",
            "AdapterError",
            "TracingError",
        }
        assert set(errors.__all__) == expected


class TestTracingError:
    """Tests for TracingError with fail_silent flag."""

    def test_inherits_from_beddel_error(self) -> None:
        err = TracingError("BEDDEL-ADAPT-010", "tracing failed")

        assert isinstance(err, BeddelError)

    def test_inherits_from_adapter_error(self) -> None:
        err = TracingError("BEDDEL-ADAPT-010", "tracing failed")

        assert isinstance(err, AdapterError)

    def test_fail_silent_defaults_to_true(self) -> None:
        err = TracingError("BEDDEL-ADAPT-010", "tracing failed")

        assert err.fail_silent is True

    def test_fail_silent_false_is_settable(self) -> None:
        err = TracingError("BEDDEL-ADAPT-010", "tracing failed", fail_silent=False)

        assert err.fail_silent is False

    def test_preserves_code_and_message(self) -> None:
        err = TracingError("BEDDEL-ADAPT-010", "span export failed")

        assert err.code == "BEDDEL-ADAPT-010"
        assert err.message == "span export failed"

    def test_details_defaults_to_empty_dict(self) -> None:
        err = TracingError("BEDDEL-ADAPT-010", "tracing failed")

        assert err.details == {}

    def test_details_preserved(self) -> None:
        details = {"span": "root", "exporter": "otlp"}
        err = TracingError("BEDDEL-ADAPT-010", "export failed", details)

        assert err.details == {"span": "root", "exporter": "otlp"}

    def test_str_representation(self) -> None:
        err = TracingError("BEDDEL-ADAPT-010", "tracing failed")

        assert str(err) == "BEDDEL-ADAPT-010: tracing failed"
