"""Unit tests for beddel.tools.file — file_read and file_write tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from beddel.tools.file import file_read, file_write


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

    def test_rejects_absolute_path(self) -> None:
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

    def test_rejects_absolute_path(self) -> None:
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
        import os

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
        import os

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
        import os

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
        import os

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = file_write(path="sub/dir/file.txt", content="nested")

            assert result == {"written": True, "path": "sub/dir/file.txt"}
            assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"
        finally:
            os.chdir(original_cwd)

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        import os

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "existing.txt").write_text("old")

            file_write(path="existing.txt", content="new")

            assert (tmp_path / "existing.txt").read_text() == "new"
        finally:
            os.chdir(original_cwd)
