"""Unit tests for beddel.domain.kit — SolutionKit models and parse_kit_manifest."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from beddel.domain.errors import KitManifestError
from beddel.domain.kit import (
    KitContractDeclaration,
    KitManifest,
    KitToolDeclaration,
    KitWorkflowDeclaration,
    SolutionKit,
    parse_kit_manifest,
)
from beddel.error_codes import KIT_MANIFEST_INVALID, KIT_MANIFEST_NOT_FOUND

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _full_manifest_dict() -> dict[str, Any]:
    """Return a fully-populated manifest dict for testing."""
    return {
        "name": "my-cool-kit",
        "version": "1.2.3",
        "description": "A test kit",
        "author": "Test Author",
        "tools": [
            {
                "name": "greet",
                "target": "my_kit.tools:greet_user",
                "description": "Greets a user",
                "category": "utility",
            },
        ],
        "workflows": [
            {
                "name": "onboard",
                "path": "workflows/onboard.yaml",
                "description": "Onboarding workflow",
            },
        ],
        "adapters": [
            {
                "name": "my-adapter",
                "target": "my_kit.adapters:MyAdapter",
                "port": "ILLMPort",
            },
        ],
        "contracts": [
            {
                "name": "user-schema",
                "schema_path": "contracts/user.json",
                "description": "User contract",
            },
        ],
    }


def _minimal_manifest_dict() -> dict[str, Any]:
    """Return a manifest with only required fields."""
    return {
        "name": "minimal-kit",
        "version": "0.1.0",
        "description": "Bare minimum kit",
    }


# ---------------------------------------------------------------------------
# SolutionKit — valid parsing
# ---------------------------------------------------------------------------


class TestSolutionKitValidParsing:
    """Tests for valid SolutionKit model parsing."""

    def test_full_manifest_all_fields_populated(self) -> None:
        data = _full_manifest_dict()

        kit = SolutionKit.model_validate(data)

        assert kit.name == "my-cool-kit"
        assert kit.version == "1.2.3"
        assert kit.description == "A test kit"
        assert kit.author == "Test Author"
        assert len(kit.tools) == 1
        assert kit.tools[0].name == "greet"
        assert kit.tools[0].target == "my_kit.tools:greet_user"
        assert kit.tools[0].description == "Greets a user"
        assert kit.tools[0].category == "utility"
        assert len(kit.workflows) == 1
        assert kit.workflows[0].name == "onboard"
        assert kit.workflows[0].path == "workflows/onboard.yaml"
        assert len(kit.adapters) == 1
        assert kit.adapters[0].name == "my-adapter"
        assert kit.adapters[0].port == "ILLMPort"
        assert len(kit.contracts) == 1
        assert kit.contracts[0].name == "user-schema"
        assert kit.contracts[0].schema_path == "contracts/user.json"

    def test_minimal_manifest_only_required_fields(self) -> None:
        data = _minimal_manifest_dict()

        kit = SolutionKit.model_validate(data)

        assert kit.name == "minimal-kit"
        assert kit.version == "0.1.0"
        assert kit.description == "Bare minimum kit"
        assert kit.author is None
        assert kit.tools == []
        assert kit.workflows == []
        assert kit.adapters == []
        assert kit.contracts == []

    def test_tool_category_defaults_to_general(self) -> None:
        tool = KitToolDeclaration(name="t", target="m:f")

        assert tool.category == "general"

    def test_tool_description_defaults_to_none(self) -> None:
        tool = KitToolDeclaration(name="t", target="m:f")

        assert tool.description is None

    def test_workflow_description_defaults_to_none(self) -> None:
        wf = KitWorkflowDeclaration(name="w", path="w.yaml")

        assert wf.description is None

    def test_contract_description_defaults_to_none(self) -> None:
        c = KitContractDeclaration(name="c", schema_path="c.json")

        assert c.description is None


# ---------------------------------------------------------------------------
# SolutionKit — missing required fields
# ---------------------------------------------------------------------------


class TestSolutionKitMissingFields:
    """Tests that missing required fields raise ValidationError."""

    def test_missing_name_raises_validation_error(self) -> None:
        data = _minimal_manifest_dict()
        del data["name"]

        with pytest.raises(ValidationError):
            SolutionKit.model_validate(data)

    def test_missing_version_raises_validation_error(self) -> None:
        data = _minimal_manifest_dict()
        del data["version"]

        with pytest.raises(ValidationError):
            SolutionKit.model_validate(data)

    def test_missing_description_raises_validation_error(self) -> None:
        data = _minimal_manifest_dict()
        del data["description"]

        with pytest.raises(ValidationError):
            SolutionKit.model_validate(data)


# ---------------------------------------------------------------------------
# SolutionKit — name validation
# ---------------------------------------------------------------------------


class TestSolutionKitNameValidation:
    """Tests that invalid name formats raise ValueError."""

    @pytest.mark.parametrize(
        "bad_name",
        [
            "Has Spaces",
            "UpperCase",
            "ALLCAPS",
            "special!chars",
            "under_score",
            "trailing-",
            "-leading",
            "double--dash",
            "",
        ],
        ids=[
            "spaces",
            "mixed-case",
            "all-caps",
            "special-chars",
            "underscore",
            "trailing-dash",
            "leading-dash",
            "double-dash",
            "empty-string",
        ],
    )
    def test_invalid_name_raises_value_error(self, bad_name: str) -> None:
        data = _minimal_manifest_dict()
        data["name"] = bad_name

        with pytest.raises(ValidationError, match="kebab-case"):
            SolutionKit.model_validate(data)

    @pytest.mark.parametrize(
        "good_name",
        ["my-kit", "a", "kit-v2", "abc-def-ghi", "x1-y2"],
    )
    def test_valid_names_accepted(self, good_name: str) -> None:
        data = _minimal_manifest_dict()
        data["name"] = good_name

        kit = SolutionKit.model_validate(data)

        assert kit.name == good_name


# ---------------------------------------------------------------------------
# SolutionKit — version validation
# ---------------------------------------------------------------------------


class TestSolutionKitVersionValidation:
    """Tests that invalid version formats raise ValueError."""

    @pytest.mark.parametrize(
        "bad_version",
        [
            "1.0",
            "abc",
            "1",
            "1.0.0.0",
            "v1.0.0",
            "1.0.0-beta",
            "",
        ],
        ids=[
            "two-part",
            "alpha-only",
            "single-number",
            "four-part",
            "v-prefix",
            "prerelease-suffix",
            "empty-string",
        ],
    )
    def test_invalid_version_raises_value_error(self, bad_version: str) -> None:
        data = _minimal_manifest_dict()
        data["version"] = bad_version

        with pytest.raises(ValidationError, match="semver"):
            SolutionKit.model_validate(data)

    @pytest.mark.parametrize(
        "good_version",
        ["0.0.1", "1.0.0", "99.88.77"],
    )
    def test_valid_versions_accepted(self, good_version: str) -> None:
        data = _minimal_manifest_dict()
        data["version"] = good_version

        kit = SolutionKit.model_validate(data)

        assert kit.version == good_version


# ---------------------------------------------------------------------------
# SolutionKit — tool target format
# ---------------------------------------------------------------------------


class TestSolutionKitToolTarget:
    """Tests that tool target accepts any string (validation at import time)."""

    @pytest.mark.parametrize(
        "target",
        [
            "module:function",
            "no_colon_here",
            "just-a-string",
            "",
        ],
        ids=["with-colon", "no-colon", "dashes", "empty"],
    )
    def test_tool_target_accepts_any_string(self, target: str) -> None:
        tool = KitToolDeclaration(name="t", target=target)

        assert tool.target == target


# ---------------------------------------------------------------------------
# SolutionKit — round-trip serialization
# ---------------------------------------------------------------------------


class TestSolutionKitRoundTrip:
    """Tests round-trip: SolutionKit → dict → SolutionKit."""

    def test_full_manifest_round_trip(self) -> None:
        original = SolutionKit.model_validate(_full_manifest_dict())

        dumped = original.model_dump()
        restored = SolutionKit.model_validate(dumped)

        assert restored == original

    def test_minimal_manifest_round_trip(self) -> None:
        original = SolutionKit.model_validate(_minimal_manifest_dict())

        dumped = original.model_dump()
        restored = SolutionKit.model_validate(dumped)

        assert restored == original


# ---------------------------------------------------------------------------
# parse_kit_manifest — valid YAML
# ---------------------------------------------------------------------------


class TestParseKitManifestValid:
    """Tests parse_kit_manifest() with valid YAML files."""

    def test_valid_yaml_returns_kit_manifest(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "kit.yaml"
        manifest_file.write_text(yaml.dump(_full_manifest_dict()), encoding="utf-8")

        result = parse_kit_manifest(manifest_file)

        assert isinstance(result, KitManifest)
        assert result.kit.name == "my-cool-kit"
        assert result.kit.version == "1.2.3"

    def test_root_path_is_resolved_absolute(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "kit.yaml"
        manifest_file.write_text(yaml.dump(_minimal_manifest_dict()), encoding="utf-8")

        result = parse_kit_manifest(manifest_file)

        assert result.root_path.is_absolute()
        assert result.root_path == tmp_path.resolve()

    def test_loaded_at_is_timezone_aware_utc(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "kit.yaml"
        manifest_file.write_text(yaml.dump(_minimal_manifest_dict()), encoding="utf-8")

        before = datetime.now(tz=UTC)
        result = parse_kit_manifest(manifest_file)
        after = datetime.now(tz=UTC)

        assert result.loaded_at.tzinfo is not None
        assert result.loaded_at.tzinfo in (UTC,)
        assert before <= result.loaded_at <= after


# ---------------------------------------------------------------------------
# parse_kit_manifest — missing file
# ---------------------------------------------------------------------------


class TestParseKitManifestMissingFile:
    """Tests parse_kit_manifest() with a missing file."""

    def test_missing_file_raises_kit_manifest_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent" / "kit.yaml"

        with pytest.raises(KitManifestError) as exc_info:
            parse_kit_manifest(missing)

        assert exc_info.value.code == KIT_MANIFEST_NOT_FOUND
        assert exc_info.value.code == "BEDDEL-KIT-651"


# ---------------------------------------------------------------------------
# parse_kit_manifest — invalid YAML
# ---------------------------------------------------------------------------


class TestParseKitManifestInvalidYAML:
    """Tests parse_kit_manifest() with invalid YAML content."""

    def test_invalid_yaml_syntax_raises_kit_manifest_error(self, tmp_path: Path) -> None:
        bad_yaml = tmp_path / "kit.yaml"
        bad_yaml.write_text("name: [\ninvalid yaml", encoding="utf-8")

        with pytest.raises(KitManifestError) as exc_info:
            parse_kit_manifest(bad_yaml)

        assert exc_info.value.code == KIT_MANIFEST_INVALID
        assert exc_info.value.code == "BEDDEL-KIT-650"

    def test_valid_yaml_invalid_schema_raises_kit_manifest_error(self, tmp_path: Path) -> None:
        bad_schema = tmp_path / "kit.yaml"
        # Valid YAML but missing required 'name' field
        bad_schema.write_text(
            yaml.dump({"version": "1.0.0", "description": "no name"}),
            encoding="utf-8",
        )

        with pytest.raises(KitManifestError) as exc_info:
            parse_kit_manifest(bad_schema)

        assert exc_info.value.code == KIT_MANIFEST_INVALID
        assert exc_info.value.code == "BEDDEL-KIT-650"


# ---------------------------------------------------------------------------
# KitManifest — frozen (immutable)
# ---------------------------------------------------------------------------


class TestKitManifestFrozen:
    """Tests that KitManifest is frozen (immutable dataclass)."""

    def test_cannot_set_kit_attribute(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "kit.yaml"
        manifest_file.write_text(yaml.dump(_minimal_manifest_dict()), encoding="utf-8")
        result = parse_kit_manifest(manifest_file)

        with pytest.raises(AttributeError):
            result.kit = SolutionKit.model_validate(_minimal_manifest_dict())  # type: ignore[misc]

    def test_cannot_set_root_path_attribute(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "kit.yaml"
        manifest_file.write_text(yaml.dump(_minimal_manifest_dict()), encoding="utf-8")
        result = parse_kit_manifest(manifest_file)

        with pytest.raises(AttributeError):
            result.root_path = Path("/other")  # type: ignore[misc]

    def test_cannot_set_loaded_at_attribute(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "kit.yaml"
        manifest_file.write_text(yaml.dump(_minimal_manifest_dict()), encoding="utf-8")
        result = parse_kit_manifest(manifest_file)

        with pytest.raises(AttributeError):
            result.loaded_at = datetime.now(tz=UTC)  # type: ignore[misc]
