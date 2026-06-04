"""Beddel file tools — safe filesystem I/O.

Provides :func:`file_read` and :func:`file_write` with path validation
that rejects absolute paths and directory traversal.
"""

from __future__ import annotations

from pathlib import Path

from beddel.tools import beddel_tool


def _validate_path(path: str) -> None:
    """Validate that a path is relative and contains no directory traversal.

    Args:
        path: File path to validate.

    Raises:
        ValueError: If the path is absolute or contains ``..`` components.
    """
    if path.startswith("/"):
        raise ValueError(f"Absolute paths are not allowed: {path}")
    if ".." in Path(path).parts:
        raise ValueError(f"Directory traversal is not allowed: {path}")


@beddel_tool(name="file_read", description="Read file content", category="file")
def file_read(path: str) -> str:
    """Read and return the content of a file.

    Args:
        path: Relative file path to read.

    Returns:
        File content as a string.

    Raises:
        ValueError: If the path is absolute or contains directory traversal.
        FileNotFoundError: If the file does not exist.
    """
    _validate_path(path)
    return Path(path).read_text()


@beddel_tool(name="file_write", description="Write file content", category="file")
def file_write(path: str, content: str) -> dict[str, object]:
    """Write content to a file, creating parent directories as needed.

    Args:
        path: Relative file path to write.
        content: String content to write.

    Returns:
        Dict with ``{"written": True, "path": path}``.

    Raises:
        ValueError: If the path is absolute or contains directory traversal.
    """
    _validate_path(path)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return {"written": True, "path": path}
