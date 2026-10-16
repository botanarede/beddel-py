"""Guard tests: the core stays generic and adds no command-line verb (AC 15).

Three guards, none of which needs a network, a kit or a credential:

1. ``src`` contains none of the profile vocabulary terms below (case-insensitive,
   text files only, ``__pycache__`` skipped).
2. When an out-of-tree list of destination terms is supplied through the
   test-only environment variable ``BEDDEL_GUARD_TERMS_FILE`` (one term per
   line), neither ``src`` nor any tracked text file of the package contains
   one of them. The list is untracked and local; when it is absent the test is
   reported as skipped. Failure messages name files and the position of the
   term in the list, never the term itself, so the list does not leak into
   logs. Only this test module reads the variable; no ``src`` file does.
3. The click command tree of ``beddel`` equals the set pinned below, which was
   recorded from the base commit ``1663df8f`` of Story 1.2b: no verb was added
   (NFR-E2, NFR-E6).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path

import click
import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PACKAGE_ROOT / "src"

GUARD_TERMS_ENV = "BEDDEL_GUARD_TERMS_FILE"

# Profile vocabulary that must never appear in the generic core (AC 15).
FORBIDDEN_TERMS: tuple[str, ...] = (
    "Verdict",
    "Verification Report",
    "Affected point",
    "Re-verification",
    "InventorySnapshot",
    "VerificationAttempt",
    "has pendency",
)

# Full space-separated paths of every command of ``beddel.cli.commands.cli`` at
# the base commit of Story 1.2b (27 entries). Adding or removing a verb must be
# a deliberate change of this set.
PINNED_COMMANDS: frozenset[str] = frozenset(
    {
        "config",
        "config reset",
        "config set",
        "config show",
        "connect",
        "connect dev",
        "connect remote",
        "deploy",
        "flow",
        "flow disable",
        "flow enable",
        "flow list",
        "init",
        "kit",
        "kit disable",
        "kit doctor",
        "kit enable",
        "kit export",
        "kit install",
        "kit list",
        "launch",
        "list-primitives",
        "run",
        "serve",
        "status",
        "validate",
        "version",
    }
)


def _read_text(path: Path) -> str | None:
    """Return the text of *path*, or ``None`` for a binary or unreadable file."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _iter_files(root: Path) -> Iterator[Path]:
    """Yield every regular file under *root*, skipping ``__pycache__``."""
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        if path.is_file():
            yield path


def find_term_hits(files: Iterable[Path], terms: tuple[str, ...]) -> list[tuple[Path, int]]:
    """Return ``(file, index_of_term)`` for every case-insensitive hit.

    Binary files are skipped. The result carries the index of the term in
    *terms*, not the term, so callers can report a hit without echoing it.
    """
    lowered = tuple(term.lower() for term in terms)
    hits: list[tuple[Path, int]] = []
    for path in files:
        text = _read_text(path)
        if text is None:
            continue
        haystack = text.lower()
        for index, term in enumerate(lowered):
            if term and term in haystack:
                hits.append((path, index))
    return hits


def _tracked_text_files() -> list[Path]:
    """Return the tracked files of the package root (``git ls-files``)."""
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail("git ls-files failed; cannot scan the tracked files of the package")
    names = [n for n in completed.stdout.decode("utf-8").split("\0") if n]
    return [PACKAGE_ROOT / name for name in names if (PACKAGE_ROOT / name).is_file()]


def _enumerate_commands(group: click.Group, prefix: tuple[str, ...] = ()) -> Iterator[str]:
    for name, command in sorted(group.commands.items()):
        path = (*prefix, name)
        yield " ".join(path)
        if isinstance(command, click.Group):
            yield from _enumerate_commands(command, path)


class TestScanner:
    """The scanner itself must not be vacuous."""

    def test_detects_case_insensitively_and_reports_the_term_index(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 'a VERDICT here'\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("nothing to see\n", encoding="utf-8")
        hits = find_term_hits(_iter_files(tmp_path), ("verdict", "other"))
        assert hits == [(tmp_path / "a.py", 0)]

    def test_skips_pycache_and_binary_files(self, tmp_path: Path) -> None:
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "m.pyc").write_text("verdict\n", encoding="utf-8")
        (tmp_path / "blob.bin").write_bytes(b"verdict\x00\x01\x02")
        (tmp_path / "latin.txt").write_bytes(b"verdict \xff\xfe")
        assert find_term_hits(_iter_files(tmp_path), ("verdict",)) == []

    def test_every_forbidden_term_is_detected(self, tmp_path: Path) -> None:
        for number, term in enumerate(FORBIDDEN_TERMS):
            (tmp_path / f"f{number}.txt").write_text(f"prefix {term.upper()} suffix", "utf-8")
        hits = find_term_hits(_iter_files(tmp_path), FORBIDDEN_TERMS)
        assert sorted(index for _, index in hits) == list(range(len(FORBIDDEN_TERMS)))


class TestCoreIsGeneric:
    def test_src_is_scanned(self) -> None:
        assert SRC_ROOT.is_dir()
        assert any(path.suffix == ".py" for path in _iter_files(SRC_ROOT))

    def test_src_has_no_profile_vocabulary(self) -> None:
        hits = find_term_hits(_iter_files(SRC_ROOT), FORBIDDEN_TERMS)
        found = sorted(
            f"{path.relative_to(PACKAGE_ROOT)}: forbidden term #{index}" for path, index in hits
        )
        assert found == []

    def test_untracked_destination_terms_are_absent(self) -> None:
        list_path_value = os.environ.get(GUARD_TERMS_ENV)
        if not list_path_value or not Path(list_path_value).is_file():
            pytest.skip(f"{GUARD_TERMS_ENV} is not set to an existing file")
        raw = Path(list_path_value).read_text(encoding="utf-8")
        terms = tuple(line.strip() for line in raw.splitlines() if line.strip())
        if not terms:
            pytest.fail("the destination terms list is present but holds no term")
        files = set(_iter_files(SRC_ROOT)) | set(_tracked_text_files())
        hits = find_term_hits(sorted(files), terms)
        found = sorted(
            f"{path.relative_to(PACKAGE_ROOT)}: listed term #{index}" for path, index in hits
        )
        assert found == []


class TestNoNewVerb:
    def test_command_tree_equals_the_pinned_set(self) -> None:
        from beddel.cli.commands import cli

        current = set(_enumerate_commands(cli))
        assert current - PINNED_COMMANDS == set(), "a command was added"
        assert PINNED_COMMANDS - current == set(), "a pinned command is gone"
        assert len(PINNED_COMMANDS) == 27
