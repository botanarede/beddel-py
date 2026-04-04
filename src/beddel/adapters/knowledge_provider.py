"""Knowledge provider adapter for YAML-based domain knowledge.

Provides :class:`YAMLKnowledgeAdapter` — a file-based implementation of
:class:`~beddel.domain.ports.IKnowledgeProvider` that reads structured
YAML files from a configurable directory, supports nested key access via
dot notation, and performs case-insensitive substring matching for queries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from beddel.domain.errors import KnowledgeError
from beddel.domain.models import KnowledgeEntry, KnowledgeSource
from beddel.error_codes import (
    KNOWLEDGE_GET_FAILED,
    KNOWLEDGE_LIST_FAILED,
    KNOWLEDGE_QUERY_FAILED,
)


class YAMLKnowledgeAdapter:
    """YAML file-based knowledge provider.

    Satisfies the :class:`~beddel.domain.ports.IKnowledgeProvider` protocol
    via structural subtyping.

    Loads all ``.yaml`` / ``.yml`` files from the configured directory on
    first access (lazy), caches parsed content in ``_data`` keyed by filename.

    Args:
        knowledge_dir: Path to the directory containing YAML knowledge files.
    """

    def __init__(self, knowledge_dir: str | Path) -> None:
        self._knowledge_dir = Path(knowledge_dir)
        self._data: dict[str, Any] = {}
        self._loaded: bool = False

    def _ensure_loaded(self) -> None:
        """Load all YAML files from the knowledge directory on first access."""
        if self._loaded:
            return
        if self._knowledge_dir.is_dir():
            for path in sorted(self._knowledge_dir.iterdir()):
                if path.suffix in (".yaml", ".yml") and path.is_file():
                    with open(path) as fh:
                        content = yaml.safe_load(fh)
                    if content is not None:
                        self._data[path.name] = content
        self._loaded = True

    async def get(self, key: str) -> KnowledgeEntry | None:
        """Retrieve a knowledge entry by key with dot-notation nested access.

        ``get("deployment.max_retries")`` splits on ``"."`` and traverses
        nested dicts: ``{"deployment": {"max_retries": 3}}``.

        Returns a :class:`KnowledgeEntry` with ``confidence=1.0`` for an
        exact match, or ``None`` if the key is not found.
        """
        try:
            self._ensure_loaded()
            parts = key.split(".")
            for filename, data in self._data.items():
                result = self._traverse(data, parts)
                if result is not None:
                    return KnowledgeEntry(
                        content=str(result),
                        source=filename,
                        confidence=1.0,
                        metadata={"key": key},
                    )
            return None
        except KnowledgeError:
            raise
        except Exception as exc:
            raise KnowledgeError(
                KNOWLEDGE_GET_FAILED,
                f"Failed to get knowledge key {key!r}: {exc}",
            ) from exc

    async def query(
        self, question: str, context: dict[str, Any] | None = None
    ) -> list[KnowledgeEntry]:
        """Query knowledge using case-insensitive substring matching.

        Splits the question into terms and searches all stringified YAML
        values. Score = (matching terms / total terms). Results are sorted
        by confidence descending.

        The *context* parameter is accepted but not used by this adapter
        (reserved for future adapters).
        """
        try:
            self._ensure_loaded()
            terms = question.lower().split()
            if not terms:
                return []
            results: list[KnowledgeEntry] = []
            for filename, data in self._data.items():
                flat_values = self._flatten_values(data)
                for value_str in flat_values:
                    value_lower = value_str.lower()
                    matching = sum(1 for t in terms if t in value_lower)
                    if matching > 0:
                        score = matching / len(terms)
                        results.append(
                            KnowledgeEntry(
                                content=value_str,
                                source=filename,
                                confidence=score,
                                metadata={"question": question},
                            )
                        )
            results.sort(key=lambda e: e.confidence, reverse=True)
            return results
        except KnowledgeError:
            raise
        except Exception as exc:
            raise KnowledgeError(
                KNOWLEDGE_QUERY_FAILED,
                f"Failed to query knowledge for {question!r}: {exc}",
            ) from exc

    async def list_sources(self) -> list[KnowledgeSource]:
        """List loaded YAML knowledge sources.

        Returns one :class:`KnowledgeSource` per loaded YAML file with
        ``type="yaml"``.
        """
        try:
            self._ensure_loaded()
            return [KnowledgeSource(name=filename, type="yaml") for filename in sorted(self._data)]
        except KnowledgeError:
            raise
        except Exception as exc:
            raise KnowledgeError(
                KNOWLEDGE_LIST_FAILED,
                f"Failed to list knowledge sources: {exc}",
            ) from exc

    @staticmethod
    def _traverse(data: Any, parts: list[str]) -> Any | None:
        """Traverse nested dicts following dot-notation key parts."""
        current = data
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    @staticmethod
    def _flatten_values(data: Any, _prefix: str = "") -> list[str]:
        """Recursively flatten all leaf values to strings."""
        results: list[str] = []
        if isinstance(data, dict):
            for value in data.values():
                results.extend(YAMLKnowledgeAdapter._flatten_values(value))
        elif isinstance(data, list):
            for item in data:
                results.extend(YAMLKnowledgeAdapter._flatten_values(item))
        else:
            results.append(str(data))
        return results
