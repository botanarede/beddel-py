"""Shared pytest fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "workflows"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def simple_workflow_yaml() -> str:
    return (FIXTURES_DIR / "simple.yaml").read_text()


@pytest.fixture
def multi_step_workflow_yaml() -> str:
    return (FIXTURES_DIR / "multi_step.yaml").read_text()
