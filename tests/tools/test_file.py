"""Unit tests for beddel_tools_file.tools — file_read and file_write tools."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from beddel_tools_file.tools import file_read, file_write


class TestFileToolMetadata:
    """Tests for file tool metadata."""

    def test_file_read_metadata(self) -> None:
        meta: dict[str, str] = file_read._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["name"] == "file_read"
        assert meta["category"] == "file"

    def test_file_write_metadata(self) -> None:
        meta: dict[str, str] = file_write._beddel_tool_meta  # type: ignore[attr-defined]
        assert meta["name"] == "file_write"
        assert meta["category"] == "file"


class TestFileReadPathValidation:
    """Tests for file_read path validation."""

    def test_rejects_absolute_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BEDDEL_FLOWS_DIR", raising=False)
        with pytest.raises(ValueError, match="Absolute paths"):
            file_read(path="/etc/passwd")

    def test_rejects_directory_traversal(self) -> None:
        with pytest.raises(ValueError, match="Directory traversal"):
            file_read(path="../etc/passwd")

    def test_rejects_nested_traversal(self) -> None:
        with pytest.raises(ValueError, match="Directory traversal"):
            file_read(path="foo/../../etc/passwd")


class TestFileWritePathValidation:
    """Tests for file_write path validation."""

    def test_rejects_absolute_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BEDDEL_FLOWS_DIR", raising=False)
        with pytest.raises(ValueError, match="Absolute paths"):
            file_write(path="/etc/passwd", content="hack")

    def test_rejects_directory_traversal(self) -> None:
        with pytest.raises(ValueError, match="Directory traversal"):
            file_write(path="../etc/passwd", content="hack")


class TestFileRead:
    """Tests for file_read execution."""

    def test_reads_file_content(self, tmp_path: Path) -> None:
        # Arrange
        target = tmp_path / "hello.txt"
        target.write_text("hello world")

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            # Act
            content = file_read(path="hello.txt")

            # Assert
            assert content == "hello world"
        finally:
            os.chdir(original_cwd)

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with pytest.raises(FileNotFoundError):
                file_read(path="nonexistent.txt")
        finally:
            os.chdir(original_cwd)


class TestFileWrite:
    """Tests for file_write execution."""

    def test_writes_file_and_returns_dict(self, tmp_path: Path) -> None:
        # Arrange
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            # Act
            result = file_write(path="output.txt", content="written content")

            # Assert
            assert result == {"written": True, "path": "output.txt"}
            assert (tmp_path / "output.txt").read_text() == "written content"
        finally:
            os.chdir(original_cwd)

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = file_write(path="sub/dir/file.txt", content="nested")

            assert result == {"written": True, "path": "sub/dir/file.txt"}
            assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"
        finally:
            os.chdir(original_cwd)

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "existing.txt").write_text("old")

            file_write(path="existing.txt", content="new")

            assert (tmp_path / "existing.txt").read_text() == "new"
        finally:
            os.chdir(original_cwd)


class TestFileWriteFlowsDir:
    """Tests for file_write behavior with BEDDEL_FLOWS_DIR env var."""

    def test_absolute_path_inside_flows_dir_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absolute path inside BEDDEL_FLOWS_DIR is accepted and file is written."""
        monkeypatch.setenv("BEDDEL_FLOWS_DIR", str(tmp_path))
        target = tmp_path / "output.txt"

        result = file_write(path=str(target), content="hello flows")

        assert result == {"written": True, "path": str(target)}
        assert target.read_text() == "hello flows"

    def test_absolute_path_outside_flows_dir_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absolute path outside BEDDEL_FLOWS_DIR raises ValueError."""
        flows_dir = tmp_path / "flows"
        flows_dir.mkdir()
        monkeypatch.setenv("BEDDEL_FLOWS_DIR", str(flows_dir))

        outside_path = tmp_path / "elsewhere" / "hack.txt"
        with pytest.raises(ValueError, match="not inside BEDDEL_FLOWS_DIR"):
            file_write(path=str(outside_path), content="nope")

    def test_absolute_path_without_flows_dir_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absolute path when BEDDEL_FLOWS_DIR is unset raises ValueError."""
        monkeypatch.delenv("BEDDEL_FLOWS_DIR", raising=False)

        with pytest.raises(ValueError, match="Absolute paths"):
            file_write(path=str(tmp_path / "file.txt"), content="nope")

    def test_traversal_inside_flows_dir_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Path with '..' traversal raises ValueError even within BEDDEL_FLOWS_DIR."""
        monkeypatch.setenv("BEDDEL_FLOWS_DIR", str(tmp_path))

        traversal_path = str(tmp_path / "sub" / ".." / "file.txt")
        with pytest.raises(ValueError, match="Directory traversal"):
            file_write(path=traversal_path, content="nope")

    def test_relative_path_still_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative paths continue to work regardless of BEDDEL_FLOWS_DIR."""
        monkeypatch.delenv("BEDDEL_FLOWS_DIR", raising=False)
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = file_write(path="relative.txt", content="relative content")

            assert result == {"written": True, "path": "relative.txt"}
            assert (tmp_path / "relative.txt").read_text() == "relative content"
        finally:
            os.chdir(original_cwd)

    def test_absolute_path_nested_inside_flows_dir_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absolute path in a subdirectory of BEDDEL_FLOWS_DIR succeeds."""
        monkeypatch.setenv("BEDDEL_FLOWS_DIR", str(tmp_path))
        target = tmp_path / "sub" / "deep" / "file.txt"

        result = file_write(path=str(target), content="deep content")

        assert result == {"written": True, "path": str(target)}
        assert target.read_text() == "deep content"
