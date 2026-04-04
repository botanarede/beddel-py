"""Tests for YAMLKnowledgeAdapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from beddel.adapters.knowledge_provider import YAMLKnowledgeAdapter
from beddel.domain.errors import KnowledgeError
from beddel.domain.models import KnowledgeEntry, KnowledgeSource
from beddel.error_codes import (
    KNOWLEDGE_GET_FAILED,
    KNOWLEDGE_LIST_FAILED,
    KNOWLEDGE_QUERY_FAILED,
)


def _write_yaml(path: Path, content: str) -> None:
    """Helper to write a YAML file."""
    path.write_text(content)


class TestYAMLKnowledgeAdapter:
    """Unit tests for the YAMLKnowledgeAdapter."""

    @pytest.mark.asyncio
    async def test_loads_yaml_files(self, tmp_path: Path) -> None:
        """Adapter loads .yaml and .yml files from directory."""
        _write_yaml(tmp_path / "config.yaml", "key: value\n")
        _write_yaml(tmp_path / "settings.yml", "name: beddel\n")
        # Non-YAML file should be ignored
        (tmp_path / "readme.txt").write_text("ignored")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        sources = await adapter.list_sources()

        names = {s.name for s in sources}
        assert names == {"config.yaml", "settings.yml"}

    @pytest.mark.asyncio
    async def test_get_flat_key(self, tmp_path: Path) -> None:
        """get() retrieves a flat top-level key."""
        _write_yaml(tmp_path / "data.yaml", "max_retries: 3\nhost: localhost\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        result = await adapter.get("max_retries")

        assert result is not None
        assert result.content == "3"
        assert result.source == "data.yaml"
        assert result.confidence == 1.0
        assert result.metadata == {"key": "max_retries"}

    @pytest.mark.asyncio
    async def test_get_nested_key_dot_notation(self, tmp_path: Path) -> None:
        """get() traverses nested dicts via dot notation."""
        _write_yaml(
            tmp_path / "deploy.yaml",
            "deployment:\n  max_retries: 5\n  timeout: 30\n",
        )

        adapter = YAMLKnowledgeAdapter(tmp_path)
        result = await adapter.get("deployment.max_retries")

        assert result is not None
        assert result.content == "5"
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        """get() returns None for a key that doesn't exist."""
        _write_yaml(tmp_path / "data.yaml", "key: value\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        result = await adapter.get("nonexistent.deep.key")

        assert result is None

    @pytest.mark.asyncio
    async def test_query_with_results(self, tmp_path: Path) -> None:
        """query() finds matching entries with confidence scoring."""
        _write_yaml(
            tmp_path / "config.yaml",
            "database:\n  host: localhost\n  port: 5432\napp:\n  name: beddel\n",
        )

        adapter = YAMLKnowledgeAdapter(tmp_path)
        results = await adapter.query("localhost database")

        assert len(results) > 0
        # "localhost" matches the value "localhost" — both terms match
        top = results[0]
        assert isinstance(top, KnowledgeEntry)
        assert top.confidence > 0.0

    @pytest.mark.asyncio
    async def test_query_empty_results(self, tmp_path: Path) -> None:
        """query() returns empty list when nothing matches."""
        _write_yaml(tmp_path / "data.yaml", "key: value\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        results = await adapter.query("nonexistent_term_xyz")

        assert results == []

    @pytest.mark.asyncio
    async def test_query_case_insensitive(self, tmp_path: Path) -> None:
        """query() performs case-insensitive matching."""
        _write_yaml(tmp_path / "data.yaml", "greeting: Hello World\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        results = await adapter.query("hello")

        assert len(results) == 1
        assert results[0].content == "Hello World"

    @pytest.mark.asyncio
    async def test_query_sorted_by_confidence(self, tmp_path: Path) -> None:
        """query() results are sorted by confidence descending."""
        _write_yaml(
            tmp_path / "data.yaml",
            "a: deploy retry logic\nb: retry\nc: unrelated stuff\n",
        )

        adapter = YAMLKnowledgeAdapter(tmp_path)
        results = await adapter.query("deploy retry")

        # "deploy retry logic" matches both terms (score=1.0)
        # "retry" matches one of two terms (score=0.5)
        assert len(results) >= 2
        assert results[0].confidence >= results[1].confidence

    @pytest.mark.asyncio
    async def test_query_empty_question(self, tmp_path: Path) -> None:
        """query() with empty string returns empty list."""
        _write_yaml(tmp_path / "data.yaml", "key: value\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        results = await adapter.query("")

        assert results == []

    @pytest.mark.asyncio
    async def test_list_sources(self, tmp_path: Path) -> None:
        """list_sources() returns one KnowledgeSource per YAML file."""
        _write_yaml(tmp_path / "a.yaml", "x: 1\n")
        _write_yaml(tmp_path / "b.yml", "y: 2\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        sources = await adapter.list_sources()

        assert len(sources) == 2
        assert all(isinstance(s, KnowledgeSource) for s in sources)
        assert all(s.type == "yaml" for s in sources)
        names = [s.name for s in sources]
        assert "a.yaml" in names
        assert "b.yml" in names

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_path: Path) -> None:
        """Adapter handles empty directory gracefully."""
        adapter = YAMLKnowledgeAdapter(tmp_path)

        assert await adapter.get("anything") is None
        assert await adapter.query("anything") == []
        assert await adapter.list_sources() == []

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """Adapter handles nonexistent directory gracefully."""
        adapter = YAMLKnowledgeAdapter(tmp_path / "does_not_exist")

        assert await adapter.get("anything") is None
        assert await adapter.query("anything") == []
        assert await adapter.list_sources() == []

    @pytest.mark.asyncio
    async def test_get_error_raises_knowledge_error(self, tmp_path: Path) -> None:
        """Internal error during get raises KnowledgeError(KNOWLEDGE_GET_FAILED)."""
        adapter = YAMLKnowledgeAdapter(tmp_path)

        with patch.object(adapter, "_ensure_loaded", side_effect=RuntimeError("boom")):
            with pytest.raises(KnowledgeError) as exc_info:
                await adapter.get("key")
            assert exc_info.value.code == KNOWLEDGE_GET_FAILED

    @pytest.mark.asyncio
    async def test_query_error_raises_knowledge_error(self, tmp_path: Path) -> None:
        """Internal error during query raises KnowledgeError(KNOWLEDGE_QUERY_FAILED)."""
        adapter = YAMLKnowledgeAdapter(tmp_path)

        with patch.object(adapter, "_ensure_loaded", side_effect=RuntimeError("boom")):
            with pytest.raises(KnowledgeError) as exc_info:
                await adapter.query("question")
            assert exc_info.value.code == KNOWLEDGE_QUERY_FAILED

    @pytest.mark.asyncio
    async def test_list_error_raises_knowledge_error(self, tmp_path: Path) -> None:
        """Internal error during list_sources raises KnowledgeError(KNOWLEDGE_LIST_FAILED)."""
        adapter = YAMLKnowledgeAdapter(tmp_path)

        with patch.object(adapter, "_ensure_loaded", side_effect=RuntimeError("boom")):
            with pytest.raises(KnowledgeError) as exc_info:
                await adapter.list_sources()
            assert exc_info.value.code == KNOWLEDGE_LIST_FAILED

    @pytest.mark.asyncio
    async def test_lazy_loading_caches(self, tmp_path: Path) -> None:
        """YAML files are loaded once and cached on subsequent access."""
        _write_yaml(tmp_path / "data.yaml", "key: value\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        # First access triggers load
        await adapter.get("key")
        assert adapter._loaded is True

        # Modify file after load — adapter should still return cached data
        _write_yaml(tmp_path / "data.yaml", "key: changed\n")
        result = await adapter.get("key")
        assert result is not None
        assert result.content == "value"  # cached, not re-read

    @pytest.mark.asyncio
    async def test_skips_empty_yaml_files(self, tmp_path: Path) -> None:
        """Empty YAML files (parsing to None) are skipped."""
        _write_yaml(tmp_path / "empty.yaml", "")
        _write_yaml(tmp_path / "valid.yaml", "key: value\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        sources = await adapter.list_sources()

        assert len(sources) == 1
        assert sources[0].name == "valid.yaml"

    @pytest.mark.asyncio
    async def test_query_context_param_accepted(self, tmp_path: Path) -> None:
        """query() accepts context parameter without error (reserved for future)."""
        _write_yaml(tmp_path / "data.yaml", "key: value\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        results = await adapter.query("value", context={"scope": "test"})

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_intermediate_non_dict_returns_none(self, tmp_path: Path) -> None:
        """get() returns None when intermediate key is not a dict."""
        _write_yaml(tmp_path / "data.yaml", "top: a_string\n")

        adapter = YAMLKnowledgeAdapter(tmp_path)
        result = await adapter.get("top.nested")

        assert result is None
