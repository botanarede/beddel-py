"""Tests for the ``mcp_servers`` field of the Workflow model (AD-21, AD-3).

The field is a map from a snake_case server name to an entry that accepts
exactly ``transport``, ``endpoint`` and ``authorization`` (provisional names,
decision D-11).  Rejections surface at load time as ``BEDDEL-PARSE-002`` and
never echo the offending value.  These tests use no network and import no kit.
"""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from beddel.domain.errors import ParseError
from beddel.domain.models import MCPServerDeclaration, Workflow
from beddel.domain.parser import WorkflowParser
from beddel.error_codes import ALL_CODES, PARSE_SCHEMA_VALIDATION

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "valid"

# Obviously fake marker that stands in for a secret.  Every "no echo" test
# plants it in the value under test and asserts it appears nowhere in the error.
_FAKE_SECRET = "ZZfakeSecretValue0123456789"

_BASE_WORKFLOW: dict[str, Any] = {
    "id": "t",
    "name": "t",
    "steps": [{"id": "s1", "primitive": "llm"}],
}


def _entry(**overrides: Any) -> dict[str, Any]:
    """Return a valid entry; ``None`` as an override removes that field."""
    entry: dict[str, Any] = {
        "transport": "mcp-http",
        "endpoint": "https://mcp.example.com/mcp",
        "authorization": "oauth",
    }
    entry.update(overrides)
    return {key: value for key, value in entry.items() if value is not None}


def _yaml(mcp_servers: Any) -> str:
    return yaml.safe_dump({**_BASE_WORKFLOW, "mcp_servers": mcp_servers})


def _parse(mcp_servers: Any) -> Workflow:
    return WorkflowParser.parse(_yaml(mcp_servers))


def _reject(mcp_servers: Any) -> ParseError:
    """Parse a workflow that must be refused and return the ParseError."""
    with pytest.raises(ParseError) as exc_info:
        _parse(mcp_servers)
    error = exc_info.value
    assert error.code == PARSE_SCHEMA_VALIDATION
    fields = [item["field"] for item in error.details["errors"]]
    assert fields, "a rejection must name at least one field"
    assert all(field.startswith("mcp_servers") for field in fields)
    return error


def _messages(error: ParseError) -> str:
    return " ".join(item["message"] for item in error.details["errors"])


def _everything_printable(error: BaseException) -> str:
    """Concatenate every text an error could surface through."""
    parts = [str(error), repr(error), "".join(traceback.format_exception(error))]
    if isinstance(error, ParseError):
        parts += [error.message, json.dumps(error.details)]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Accept path
# ---------------------------------------------------------------------------


class TestAcceptPath:
    """A well-formed declaration is parsed into typed entries."""

    def test_valid_entry_is_parsed_into_typed_fields(self) -> None:
        workflow = _parse({"docs_server": _entry()})

        assert workflow.mcp_servers is not None
        entry = workflow.mcp_servers["docs_server"]
        assert isinstance(entry, MCPServerDeclaration)
        assert entry.transport == "mcp-http"
        assert entry.endpoint == "https://mcp.example.com/mcp"
        assert entry.authorization == "oauth"

    def test_entry_has_exactly_three_fields(self) -> None:
        assert set(MCPServerDeclaration.model_fields) == {
            "transport",
            "endpoint",
            "authorization",
        }

    def test_several_servers_are_kept_by_name(self) -> None:
        workflow = _parse(
            {
                "docs": _entry(),
                "issue_tracker": _entry(endpoint="https://issues.example.com/mcp"),
                "a1_b2": _entry(transport="mcp_stream", authorization="oauth2"),
            }
        )

        assert workflow.mcp_servers is not None
        assert set(workflow.mcp_servers) == {"docs", "issue_tracker", "a1_b2"}

    def test_empty_map_and_null_are_accepted(self) -> None:
        assert _parse({}).mcp_servers == {}
        assert _parse(None).mcp_servers is None

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://mcp.example.com/mcp",
            "https://mcp.example.com",
            "https://mcp.example.com:8443/a/b",
            "http://127.0.0.1:8080/mcp",
            "http://localhost:3000/mcp",
            "https://[::1]:8443/mcp",
            "https://mcp.example.com/a%3Fb",
            "HTTPS://mcp.example.com/mcp",
        ],
    )
    def test_absolute_urls_without_userinfo_query_or_fragment(self, endpoint: str) -> None:
        workflow = _parse({"srv": _entry(endpoint=endpoint)})

        assert workflow.mcp_servers is not None
        assert workflow.mcp_servers["srv"].endpoint == endpoint

    @pytest.mark.parametrize("name", ["a", "oauth", "oauth2", "mcp-http", "mcp_stream", "a" * 32])
    def test_name_shapes_for_transport_and_authorization(self, name: str) -> None:
        workflow = _parse({"srv": _entry(transport=name, authorization=name)})

        assert workflow.mcp_servers is not None
        assert workflow.mcp_servers["srv"].transport == name
        assert workflow.mcp_servers["srv"].authorization == name

    def test_model_can_be_built_directly(self) -> None:
        workflow = Workflow.model_validate({**_BASE_WORKFLOW, "mcp_servers": {"srv": _entry()}})

        assert workflow.mcp_servers is not None
        assert workflow.mcp_servers["srv"].authorization == "oauth"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestWorkflowsWithoutMcpServers:
    """Workflows that do not declare ``mcp_servers`` behave as before."""

    def test_field_defaults_to_none_and_is_unset(self) -> None:
        workflow = WorkflowParser.parse(yaml.safe_dump(_BASE_WORKFLOW))

        assert workflow.mcp_servers is None
        assert "mcp_servers" not in workflow.model_fields_set
        assert "mcp_servers" not in workflow.model_dump(exclude_unset=True)

    def test_previous_workflow_fields_are_unchanged(self) -> None:
        assert set(Workflow.model_fields) - {"mcp_servers"} == {
            "id",
            "name",
            "description",
            "version",
            "input_schema",
            "steps",
            "metadata",
            "allowed_tools",
            "tools",
            "requires_kits",
        }

    def test_unknown_top_level_keys_are_still_ignored(self) -> None:
        workflow = WorkflowParser.parse(yaml.safe_dump({**_BASE_WORKFLOW, "x_unknown": {"a": 1}}))

        assert workflow.id == "t"

    @pytest.mark.parametrize(
        "fixture_path",
        sorted(_VALID_FIXTURES_DIR.glob("*.yaml")),
        ids=lambda path: path.stem,
    )
    def test_existing_valid_fixtures_still_parse_without_the_field(
        self, fixture_path: Path
    ) -> None:
        workflow = WorkflowParser.parse(fixture_path.read_text(encoding="utf-8"))

        assert workflow.mcp_servers is None


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------


class TestRejectionPaths:
    """Every unsafe or malformed declaration is refused when the workflow loads."""

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("headers", {"Authorization": "x"}),
            ("env", {"TOKEN": "x"}),
            ("args", ["--flag"]),
            ("command", "run-server"),
            ("timeout", 30),
            ("token", "x"),
            ("unknown", "x"),
        ],
    )
    def test_any_key_beyond_the_three_fields_is_rejected(self, key: str, value: Any) -> None:
        error = _reject({"srv": _entry(**{key: value})})

        # The location stops at the entry: the rejected key is never repeated.
        assert [item["field"] for item in error.details["errors"]] == ["mcp_servers.srv"]
        assert error.details["errors"][0]["type"] == "value_error"
        assert "only transport, endpoint and authorization" in _messages(error)
        assert key not in " ".join(item["field"] for item in error.details["errors"])

    @pytest.mark.parametrize("missing", ["transport", "endpoint", "authorization"])
    def test_every_field_is_required(self, missing: str) -> None:
        error = _reject({"srv": _entry(**{missing: None})})

        fields = [item["field"] for item in error.details["errors"]]
        assert fields == [f"mcp_servers.srv.{missing}"]
        assert error.details["errors"][0]["type"] == "missing"

    @pytest.mark.parametrize("field", ["transport", "endpoint", "authorization"])
    @pytest.mark.parametrize("value", [42, True, ["a"], {"a": "b"}], ids=repr)
    def test_non_string_values_are_rejected(self, field: str, value: Any) -> None:
        error = _reject({"srv": _entry(**{field: value})})

        assert error.details["errors"][0]["field"] == f"mcp_servers.srv.{field}"

    @pytest.mark.parametrize(
        "key",
        ["Docs", "docs-server", "docs server", "1docs", "_docs", "docs_", "do__cs", "a:b", ""],
    )
    def test_server_keys_must_be_snake_case(self, key: str) -> None:
        error = _reject({key: _entry()})

        # The location stops at the map: the rejected key is never repeated.
        assert [item["field"] for item in error.details["errors"]] == ["mcp_servers"]
        assert error.details["errors"][0]["type"] == "value_error"
        assert "server keys must be snake_case" in _messages(error)

    @pytest.mark.parametrize("key", [1, 2.5, True, None], ids=repr)
    def test_server_keys_must_be_strings(self, key: Any) -> None:
        error = _reject({key: _entry()})

        assert [item["field"] for item in error.details["errors"]] == ["mcp_servers"]

    @pytest.mark.parametrize("field", ["transport", "authorization"])
    @pytest.mark.parametrize(
        "name",
        [
            "OAuth",
            "has space",
            "has.dot",
            "has/slash",
            "-leading",
            "trailing-",
            "double--dash",
            "1leading_digit",
            "a" * 33,
            "",
        ],
    )
    def test_names_must_be_short_lowercase_identifiers(self, field: str, name: str) -> None:
        error = _reject({"srv": _entry(**{field: name})})

        assert error.details["errors"][0]["field"] == f"mcp_servers.srv.{field}"

    @pytest.mark.parametrize(
        "token_like",
        [
            f"Bearer {_FAKE_SECRET}",
            _FAKE_SECRET,
            _FAKE_SECRET.lower() + "abcdefghij",
            f"ey.{_FAKE_SECRET}.fake",
            f"{_FAKE_SECRET}==",
        ],
        ids=["bearer-prefix", "mixed-case", "too-long", "jwt-shaped", "base64-padding"],
    )
    def test_authorization_that_looks_like_a_token_is_rejected(self, token_like: str) -> None:
        error = _reject({"srv": _entry(authorization=token_like)})

        assert error.details["errors"][0]["field"] == "mcp_servers.srv.authorization"

    @pytest.mark.parametrize(
        ("endpoint", "reason"),
        [
            ("https://user:pw@mcp.example.com/mcp", "userinfo"),
            ("https://token@mcp.example.com/mcp", "userinfo"),
            ("https://@mcp.example.com/mcp", "userinfo"),
            ("https://mcp.example.com@evil.example/mcp", "userinfo"),
            ("https://user:p%40ss@mcp.example.com/mcp", "userinfo"),
        ],
    )
    def test_endpoint_with_userinfo_is_rejected(self, endpoint: str, reason: str) -> None:
        error = _reject({"srv": _entry(endpoint=endpoint)})

        assert reason in _messages(error)

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://mcp.example.com/mcp?token=x",
            "https://mcp.example.com/mcp?api_key=x",
            "https://mcp.example.com/mcp?access_token=x&x=1",
            "https://mcp.example.com/mcp?harmless=1",
            "https://mcp.example.com/mcp?",
            "https://mcp.example.com?sig=x",
            "https://mcp.example.com/mcp#access_token=x",
            "https://mcp.example.com/mcp#",
        ],
    )
    def test_endpoint_with_any_query_or_fragment_is_rejected(self, endpoint: str) -> None:
        error = _reject({"srv": _entry(endpoint=endpoint)})

        assert "query string or a fragment" in _messages(error)

    @pytest.mark.parametrize(
        "endpoint",
        [
            "",
            "   ",
            "mcp.example.com/mcp",
            "localhost:8080/mcp",
            "/mcp",
            "https:///mcp",
            "https://:8080/mcp",
            "https://mcp.example.com:notaport/mcp",
            "https://mcp.example.com:99999/mcp",
            "https://mcp.example.com /mcp",
            "https://mcp.example.com/\tmcp",
            "https://mcp.example.com\\@evil.example/mcp",
            "https://m\u00f4p.example.com/mcp",
            "https://mcp.example.com/" + "a" * 2100,
        ],
        ids=[
            "empty",
            "blank",
            "no-scheme",
            "host-port-without-scheme",
            "path-only",
            "no-host",
            "no-host-with-port",
            "port-not-a-number",
            "port-out-of-range",
            "space",
            "control-character",
            "backslash",
            "non-ascii",
            "too-long",
        ],
    )
    def test_endpoint_that_is_not_a_clean_absolute_url_is_rejected(self, endpoint: str) -> None:
        error = _reject({"srv": _entry(endpoint=endpoint)})

        assert error.details["errors"][0]["field"] == "mcp_servers.srv.endpoint"

    @pytest.mark.parametrize(
        "endpoint",
        [
            "file://localhost/x",
            "ftp://h/x",
            "ws://h/x",
            "wss://h/x",
            "FILE://localhost/x",
            "stdio://server/x",
        ],
    )
    def test_endpoint_scheme_other_than_http_or_https_is_rejected(self, endpoint: str) -> None:
        error = _reject({"srv": _entry(endpoint=endpoint)})

        assert error.details["errors"][0]["field"] == "mcp_servers.srv.endpoint"
        assert "scheme must be http or https" in _messages(error)

    @pytest.mark.parametrize("value", [["a"], "text", 7], ids=["list", "string", "int"])
    def test_mcp_servers_must_be_a_mapping(self, value: Any) -> None:
        error = _reject(value)

        assert error.details["errors"][0]["field"] == "mcp_servers"

    @pytest.mark.parametrize("value", ["oauth", ["a"], 7], ids=["string", "list", "int"])
    def test_an_entry_must_be_a_mapping(self, value: Any) -> None:
        error = _reject({"srv": value})

        assert error.details["errors"][0]["field"] == "mcp_servers.srv"

    def test_rejection_names_the_entry_but_neither_key_nor_value(self) -> None:
        error = _reject({"srv": _entry(headers={"Authorization": f"Bearer {_FAKE_SECRET}"})})

        assert [item["field"] for item in error.details["errors"]] == ["mcp_servers.srv"]
        assert "headers" not in _everything_printable(error)
        assert _FAKE_SECRET not in _everything_printable(error)


class TestRejectionIsRegistered:
    """Rejections reuse a registered error code; no code is added."""

    def test_parse_schema_validation_is_registered(self) -> None:
        assert PARSE_SCHEMA_VALIDATION in ALL_CODES.values()

    def test_rejection_is_a_parse_error_with_that_code(self) -> None:
        error = _reject({"srv": _entry(endpoint="https://u:p@mcp.example.com/mcp")})

        assert isinstance(error, ParseError)
        assert error.code == "BEDDEL-PARSE-002"
        assert error.message == "Workflow schema validation failed with 1 error(s)"


# ---------------------------------------------------------------------------
# No secret is ever echoed
# ---------------------------------------------------------------------------

_SECRET_SCENARIOS: dict[str, dict[str, Any]] = {
    "userinfo-password": _entry(endpoint=f"https://user:{_FAKE_SECRET}@mcp.example.com/mcp"),
    "userinfo-token": _entry(endpoint=f"https://{_FAKE_SECRET}@mcp.example.com/mcp"),
    "query-parameter": _entry(endpoint=f"https://mcp.example.com/mcp?api_key={_FAKE_SECRET}"),
    "fragment": _entry(endpoint=f"https://mcp.example.com/mcp#access_token={_FAKE_SECRET}"),
    "authorization-literal": _entry(authorization=_FAKE_SECRET),
    "authorization-bearer": _entry(authorization=f"Bearer {_FAKE_SECRET}"),
    "transport-literal": _entry(transport=_FAKE_SECRET),
    "extra-headers": _entry(headers={"Authorization": f"Bearer {_FAKE_SECRET}"}),
    "extra-env": _entry(env={"API_TOKEN": _FAKE_SECRET}),
    "extra-args": _entry(args=["--token", _FAKE_SECRET]),
    "extra-scalar": _entry(token=_FAKE_SECRET),
    "wrong-type-nested": _entry(authorization={"token": _FAKE_SECRET}),
    "entry-is-a-secret": _FAKE_SECRET,
    "extra-key-is-a-secret": _entry(**{_FAKE_SECRET: "x"}),
    "extra-key-with-bearer-prefix": _entry(**{f"Bearer {_FAKE_SECRET}": "x"}),
    "extra-key-and-value-are-secrets": _entry(**{_FAKE_SECRET: _FAKE_SECRET}),
}

# Scenarios whose secret sits in the map itself, not in the entry named ``srv``.
_WHOLE_MAP_SCENARIOS: dict[str, Any] = {
    "map-is-a-secret": _FAKE_SECRET,
    "server-key-is-a-secret": {_FAKE_SECRET: _entry()},
    "server-key-with-bearer-prefix": {f"Bearer {_FAKE_SECRET}": _entry()},
}

_ALL_SCENARIOS = sorted([*_SECRET_SCENARIOS, *_WHOLE_MAP_SCENARIOS])


def _mcp_servers_for(scenario: str) -> Any:
    if scenario in _WHOLE_MAP_SCENARIOS:
        return _WHOLE_MAP_SCENARIOS[scenario]
    return {"srv": _SECRET_SCENARIOS[scenario]}


class TestNoSecretEcho:
    """The offending value appears in no message, detail, repr or traceback."""

    @pytest.mark.parametrize("scenario", _ALL_SCENARIOS)
    def test_parse_error_never_contains_the_secret(
        self, scenario: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            error = _reject(_mcp_servers_for(scenario))

        assert _FAKE_SECRET not in error.message
        assert _FAKE_SECRET not in str(error)
        assert _FAKE_SECRET not in repr(error)
        for item in error.details["errors"]:
            assert _FAKE_SECRET not in item["field"]
            assert _FAKE_SECRET not in item["message"]
            assert _FAKE_SECRET not in item["type"]
        assert _FAKE_SECRET not in _everything_printable(error)
        assert _FAKE_SECRET not in caplog.text

    @pytest.mark.parametrize("scenario", _ALL_SCENARIOS)
    def test_validation_error_of_the_model_never_contains_the_secret(self, scenario: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Workflow.model_validate({**_BASE_WORKFLOW, "mcp_servers": _mcp_servers_for(scenario)})

        error = exc_info.value
        # Printable surfaces only: ``ValidationError.errors()`` keeps the raw
        # ``input`` for programmatic callers, and ``WorkflowParser`` copies just
        # location, message and type from it (see Dev Notes of Story 1.2a).
        assert _FAKE_SECRET not in _everything_printable(error)
        assert all(_FAKE_SECRET not in ".".join(map(str, e["loc"])) for e in error.errors())

    @pytest.mark.parametrize("scenario", sorted(_SECRET_SCENARIOS))
    def test_entry_validated_directly_never_contains_the_secret(self, scenario: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            MCPServerDeclaration.model_validate(_SECRET_SCENARIOS[scenario])

        error = exc_info.value
        assert _FAKE_SECRET not in _everything_printable(error)
        assert all(_FAKE_SECRET not in ".".join(map(str, e["loc"])) for e in error.errors())

    def test_non_dict_mappings_are_accepted_like_dicts(self) -> None:
        servers = MappingProxyType({"srv": MappingProxyType(_entry())})

        workflow = Workflow.model_validate({**_BASE_WORKFLOW, "mcp_servers": servers})

        assert workflow.mcp_servers is not None
        assert workflow.mcp_servers["srv"].authorization == "oauth"

    @pytest.mark.parametrize(
        ("mcp_servers", "expected_loc"),
        [
            (MappingProxyType({_FAKE_SECRET: _entry()}), ("mcp_servers",)),
            (MappingProxyType({f"Bearer {_FAKE_SECRET}": _entry()}), ("mcp_servers",)),
            (
                MappingProxyType({"srv": MappingProxyType(_entry(**{_FAKE_SECRET: "x"}))}),
                ("mcp_servers", "srv"),
            ),
            (
                {"srv": MappingProxyType(_entry(**{f"Bearer {_FAKE_SECRET}": "x"}))},
                ("mcp_servers", "srv"),
            ),
        ],
        ids=[
            "server-key-is-a-secret",
            "server-key-with-bearer-prefix",
            "extra-key-is-a-secret",
            "extra-key-with-bearer-prefix",
        ],
    )
    def test_secret_keys_of_non_dict_mappings_are_not_echoed(
        self, mcp_servers: Any, expected_loc: tuple[str, ...]
    ) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Workflow.model_validate({**_BASE_WORKFLOW, "mcp_servers": mcp_servers})

        error = exc_info.value
        assert _FAKE_SECRET not in _everything_printable(error)
        assert [tuple(item["loc"]) for item in error.errors()] == [expected_loc]

    def test_secret_extra_key_of_a_non_dict_entry_validated_directly_is_not_echoed(self) -> None:
        entry = MappingProxyType(_entry(**{_FAKE_SECRET: "x"}))

        with pytest.raises(ValidationError) as exc_info:
            MCPServerDeclaration.model_validate(entry)

        error = exc_info.value
        assert _FAKE_SECRET not in _everything_printable(error)
        assert [tuple(item["loc"]) for item in error.errors()] == [()]

    def test_opaque_path_segments_are_accepted(self) -> None:
        # Documented limit: a secret placed in the PATH of an otherwise clean URL
        # cannot be told apart from a path.  The model refuses every channel that
        # is detectable by shape (userinfo, query, fragment, token-like names).
        workflow = _parse({"srv": _entry(endpoint="https://mcp.example.com/tenant/opaque-id")})

        assert workflow.mcp_servers is not None


# ---------------------------------------------------------------------------
# Generated schema (the shared contract follows the model, AD-3)
# ---------------------------------------------------------------------------


class TestGeneratedSchema:
    """``Workflow.model_json_schema()`` carries the same shape as the model."""

    def test_schema_describes_the_entry(self) -> None:
        schema = Workflow.model_json_schema()
        entry = schema["$defs"]["MCPServerDeclaration"]

        assert "mcp_servers" in schema["properties"]
        assert "mcp_servers" not in schema.get("required", [])
        assert entry["additionalProperties"] is False
        assert set(entry["properties"]) == {"transport", "endpoint", "authorization"}
        assert set(entry["required"]) == {"transport", "endpoint", "authorization"}

    def test_schema_accepts_and_rejects_like_the_model(self) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        schema = Workflow.model_json_schema()

        jsonschema.validate({**_BASE_WORKFLOW, "mcp_servers": {"srv": _entry()}}, schema)
        jsonschema.validate(_BASE_WORKFLOW, schema)

        refused: list[dict[str, Any]] = [
            {"srv": _entry(headers={})},
            {"srv": _entry(env={})},
            {"srv": _entry(args=[])},
            {"srv": _entry(transport=None)},
            {"srv": _entry(transport="Not A Name")},
            {"Bad-Key": _entry()},
            {"a:b": _entry()},
        ]
        for mcp_servers in refused:
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate({**_BASE_WORKFLOW, "mcp_servers": mcp_servers}, schema)
