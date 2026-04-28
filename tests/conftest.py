# -*- coding: utf-8 -*-
"""Shared pytest fixtures."""

from pathlib import Path

import pytest

UNDER_TEST_DIR = Path(__file__).parent.parent / "under_test"
SAMPLE_PROJECT = UNDER_TEST_DIR / "sample-java-project"


@pytest.fixture
def sample_project() -> Path:
    """Path to the sample Java project fixture."""
    return SAMPLE_PROJECT
