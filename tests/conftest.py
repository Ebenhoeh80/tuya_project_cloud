"""Fixtures for Tuya Project Cloud tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in all tests."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry with project credentials."""
    return MockConfigEntry(
        domain="tuya_project_cloud",
        title="Tuya Cloud – Europa (Zentral)",
        data={
            "access_id": "test_access_id",
            "access_secret": "test_access_secret",
            "region": "eu",
        },
        unique_id="test_access_id",
    )
