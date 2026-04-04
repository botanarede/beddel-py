"""Integration tests for knowledge provider (Story 6.5, Task 4).

Tests the full pipeline: DefaultDependencies with YAMLKnowledgeAdapter →
query → get → list_sources round-trip, backward compatibility when
knowledge_provider is None, and multi-file cross-file query with per-file
source attribution.

AC #9: YAML knowledge loading, query matching with scoring, key lookup
       (flat and nested), list_sources, error handling for missing provider,
       error code registration, backward compatibility (knowledge_provider=None).
AC #10: All 4 validation gates pass.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from beddel.adapters.knowledge_provider import YAMLKnowledgeAdapter
from beddel.domain.models import (
    DefaultDependencies,
    ExecutionContext,
    KnowledgeEntry,
    KnowledgeSource,
)


def _write_yaml(path: Path, content: str) -> None:
    """Helper to write a YAML file."""
    path.write_text(content)


# ---------------------------------------------------------------------------
# 4.1 Full pipeline: create context → query → get → list_sources → round-trip
# ---------------------------------------------------------------------------


class TestFullPipelineKnowledgeRoundTrip:
    """Full pipeline: ExecutionContext with YAMLKnowledgeAdapter."""

    @pytest.mark.asyncio
    async def test_full_round_trip_via_deps(self, tmp_path: Path) -> None:
        """Create deps with YAMLKnowledgeAdapter, query, get, list_sources."""
        _write_yaml(
            tmp_path / "config.yaml",
            "deployment:\n  max_retries: 3\n  timeout: 30\napp_name: beddel\n",
        )
        provider = YAMLKnowledgeAdapter(tmp_path)
        deps = DefaultDependencies(knowledge_provider=provider)
        ctx = ExecutionContext(workflow_id="wf-knowledge-test", deps=deps)

        assert ctx.deps.knowledge_provider is provider

        # get flat key
        result = await provider.get("app_name")
        assert result is not None
        assert isinstance(result, KnowledgeEntry)
        assert result.content == "beddel"
        assert result.source == "config.yaml"
        assert result.confidence == 1.0

        # get nested key via dot notation
        result = await provider.get("deployment.max_retries")
        assert result is not None
        assert result.content == "3"
        assert result.confidence == 1.0

        # query with scoring
        results = await provider.query("beddel deployment")
        assert len(results) > 0
        assert all(isinstance(r, KnowledgeEntry) for r in results)
        # Results sorted by confidence descending
        for i in range(len(results) - 1):
            assert results[i].confidence >= results[i + 1].confidence

        # list_sources
        sources = await provider.list_sources()
        assert len(sources) == 1
        assert isinstance(sources[0], KnowledgeSource)
        assert sources[0].name == "config.yaml"
        assert sources[0].type == "yaml"

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, tmp_path: Path) -> None:
        """get() returns None for a non-existent key via deps pipeline."""
        _write_yaml(tmp_path / "data.yaml", "key: value\n")
        provider = YAMLKnowledgeAdapter(tmp_path)
        deps = DefaultDependencies(knowledge_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-missing", deps=deps)

        result = await provider.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_query_empty_returns_empty(self, tmp_path: Path) -> None:
        """query() with no matches returns empty list via deps pipeline."""
        _write_yaml(tmp_path / "data.yaml", "key: value\n")
        provider = YAMLKnowledgeAdapter(tmp_path)
        deps = DefaultDependencies(knowledge_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-empty-query", deps=deps)

        results = await provider.query("zzz_no_match_xyz")
        assert results == []


# ---------------------------------------------------------------------------
# 4.2 Backward compatibility: knowledge_provider=None
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Verify no errors when knowledge_provider is not configured."""

    def test_default_deps_knowledge_provider_is_none(self) -> None:
        """DefaultDependencies() without knowledge_provider has None."""
        deps = DefaultDependencies()
        assert deps.knowledge_provider is None

    def test_execution_context_without_knowledge_provider(self) -> None:
        """ExecutionContext with default deps works without knowledge_provider."""
        ctx = ExecutionContext(workflow_id="wf-no-knowledge")
        assert ctx.deps.knowledge_provider is None

    def test_execution_context_with_other_deps_no_knowledge(self) -> None:
        """DefaultDependencies with other deps but no knowledge_provider is fine."""
        deps = DefaultDependencies(delegate_model="gpt-4o")
        assert deps.knowledge_provider is None
        assert deps.delegate_model == "gpt-4o"

    def test_knowledge_provider_coexists_with_memory_provider(self) -> None:
        """Both knowledge_provider and memory_provider can be None independently."""
        deps = DefaultDependencies()
        assert deps.knowledge_provider is None
        assert deps.memory_provider is None


# ---------------------------------------------------------------------------
# 4.3 Multiple YAML files: cross-file query and per-file source attribution
# ---------------------------------------------------------------------------


class TestMultipleYAMLFiles:
    """Test multiple YAML files in directory with cross-file query."""

    @pytest.mark.asyncio
    async def test_cross_file_query(self, tmp_path: Path) -> None:
        """query() finds matches across multiple YAML files."""
        _write_yaml(
            tmp_path / "database.yaml",
            "host: production-server\nport: 5432\nengine: postgres\n",
        )
        _write_yaml(
            tmp_path / "app.yaml",
            "name: beddel\nversion: 0.1.0\nhost: production-server\n",
        )

        provider = YAMLKnowledgeAdapter(tmp_path)
        deps = DefaultDependencies(knowledge_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-multi-file", deps=deps)

        # "production" appears as a value in both files
        results = await provider.query("production")
        assert len(results) >= 2

        sources_found = {r.source for r in results}
        assert "database.yaml" in sources_found
        assert "app.yaml" in sources_found

    @pytest.mark.asyncio
    async def test_per_file_source_attribution(self, tmp_path: Path) -> None:
        """Each result carries the correct source filename."""
        _write_yaml(tmp_path / "alpha.yaml", "color: red\n")
        _write_yaml(tmp_path / "beta.yml", "color: blue\n")

        provider = YAMLKnowledgeAdapter(tmp_path)
        deps = DefaultDependencies(knowledge_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-attribution", deps=deps)

        results = await provider.query("red")
        assert len(results) >= 1
        red_result = [r for r in results if "red" in r.content.lower()]
        assert len(red_result) == 1
        assert red_result[0].source == "alpha.yaml"

        results = await provider.query("blue")
        assert len(results) >= 1
        blue_result = [r for r in results if "blue" in r.content.lower()]
        assert len(blue_result) == 1
        assert blue_result[0].source == "beta.yml"

    @pytest.mark.asyncio
    async def test_list_sources_multiple_files(self, tmp_path: Path) -> None:
        """list_sources() returns one entry per YAML file."""
        _write_yaml(tmp_path / "one.yaml", "a: 1\n")
        _write_yaml(tmp_path / "two.yaml", "b: 2\n")
        _write_yaml(tmp_path / "three.yml", "c: 3\n")

        provider = YAMLKnowledgeAdapter(tmp_path)
        deps = DefaultDependencies(knowledge_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-list-multi", deps=deps)

        sources = await provider.list_sources()
        assert len(sources) == 3
        names = {s.name for s in sources}
        assert names == {"one.yaml", "two.yaml", "three.yml"}
        assert all(s.type == "yaml" for s in sources)

    @pytest.mark.asyncio
    async def test_get_finds_key_in_correct_file(self, tmp_path: Path) -> None:
        """get() returns the entry from the first file containing the key."""
        _write_yaml(tmp_path / "db.yaml", "host: db-server\nport: 5432\n")
        _write_yaml(tmp_path / "web.yaml", "host: web-server\nport: 8080\n")

        provider = YAMLKnowledgeAdapter(tmp_path)
        deps = DefaultDependencies(knowledge_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-get-multi", deps=deps)

        # get() returns first match (files loaded in sorted order: db.yaml < web.yaml)
        result = await provider.get("host")
        assert result is not None
        assert result.source == "db.yaml"
        assert result.content == "db-server"

    @pytest.mark.asyncio
    async def test_nested_key_across_files(self, tmp_path: Path) -> None:
        """get() with dot notation finds nested keys across files."""
        _write_yaml(
            tmp_path / "deploy.yaml",
            "deployment:\n  max_retries: 5\n",
        )
        _write_yaml(
            tmp_path / "logging.yaml",
            "logging:\n  level: DEBUG\n",
        )

        provider = YAMLKnowledgeAdapter(tmp_path)
        deps = DefaultDependencies(knowledge_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-nested-multi", deps=deps)

        result = await provider.get("deployment.max_retries")
        assert result is not None
        assert result.content == "5"
        assert result.source == "deploy.yaml"

        result = await provider.get("logging.level")
        assert result is not None
        assert result.content == "DEBUG"
        assert result.source == "logging.yaml"


# ---------------------------------------------------------------------------
# 4.5 Domain isolation: no adapter imports in domain core
# ---------------------------------------------------------------------------


class TestDomainIsolation:
    """Verify domain core never imports from adapters."""

    def test_no_adapter_imports_in_domain(self) -> None:
        """grep for adapter imports in domain/ returns zero matches."""
        result = subprocess.run(
            [
                "grep",
                "-r",
                "from beddel.adapters",
                "src/beddel-py/src/beddel/domain/",
            ],
            capture_output=True,
            text=True,
        )
        assert result.stdout == "", f"Domain core imports from adapters:\n{result.stdout}"
