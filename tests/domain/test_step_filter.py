"""Unit tests for beddel.domain.utils — StepFilter."""

from __future__ import annotations

from beddel.domain.models import Step
from beddel.domain.utils import StepFilter


def _step(primitive: str = "llm", tags: list[str] | None = None) -> Step:
    """Create a minimal Step for testing."""
    return Step(id="s1", primitive=primitive, tags=tags or [])


class TestFilterByPrimitive:
    def test_matches(self) -> None:
        pred = StepFilter.filter_by_primitive(["llm", "chat"])
        assert pred(_step("llm")) is True
        assert pred(_step("chat")) is True

    def test_no_match(self) -> None:
        pred = StepFilter.filter_by_primitive(["llm"])
        assert pred(_step("tool")) is False

    def test_empty_list_rejects_all(self) -> None:
        pred = StepFilter.filter_by_primitive([])
        assert pred(_step("llm")) is False


class TestFilterByTag:
    def test_matches(self) -> None:
        pred = StepFilter.filter_by_tag(["generate"])
        assert pred(_step(tags=["generate", "evaluate"])) is True

    def test_no_match(self) -> None:
        pred = StepFilter.filter_by_tag(["generate"])
        assert pred(_step(tags=["evaluate"])) is False

    def test_empty_tags_on_step(self) -> None:
        pred = StepFilter.filter_by_tag(["generate"])
        assert pred(_step()) is False

    def test_empty_filter_list(self) -> None:
        pred = StepFilter.filter_by_tag([])
        assert pred(_step(tags=["generate"])) is False


class TestCompose:
    def test_all_pass(self) -> None:
        p1 = StepFilter.filter_by_primitive(["llm"])
        p2 = StepFilter.filter_by_tag(["generate"])
        composed = StepFilter.compose(p1, p2)
        assert composed(_step("llm", tags=["generate"])) is True

    def test_one_fails(self) -> None:
        p1 = StepFilter.filter_by_primitive(["llm"])
        p2 = StepFilter.filter_by_tag(["evaluate"])
        composed = StepFilter.compose(p1, p2)
        assert composed(_step("llm", tags=["generate"])) is False

    def test_empty_predicates(self) -> None:
        composed = StepFilter.compose()
        assert composed(_step()) is True


class TestFilterIntegration:
    def test_filter_list_of_steps(self) -> None:
        steps = [
            _step("llm", tags=["generate"]),
            _step("chat", tags=["evaluate"]),
            _step("tool"),
            _step("llm", tags=["evaluate"]),
        ]
        pred = StepFilter.filter_by_primitive(["llm"])
        result = list(filter(pred, steps))
        assert len(result) == 2
        assert all(s.primitive == "llm" for s in result)
