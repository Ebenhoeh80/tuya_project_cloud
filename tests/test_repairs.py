"""Tests for informational repair issues."""

from __future__ import annotations

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.tuya_project_cloud.const import (
    DOMAIN,
    ISSUE_API_NOT_AUTHORIZED,
    ISSUE_COMMAND_NOT_AUTHORIZED,
    ISSUE_IOT_CORE_NOT_AUTHORIZED,
    ISSUE_REGION_MISMATCH,
)
from custom_components.tuya_project_cloud.repairs import (
    async_create_fix_flow,
    async_update_command_issue,
    async_update_issues,
)


def _issue(hass, entry_id: str, suffix: str):
    """Return the issue for one config entry and suffix."""
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{entry_id}_{suffix}")


@pytest.mark.asyncio
async def test_update_issues_creates_and_clears_all_issues(hass) -> None:
    """Every warning appears only while its underlying problem exists."""
    entry_id = "entry-1"
    async_update_issues(
        hass,
        entry_id,
        api_not_authorized=True,
        iot_core_not_authorized=True,
        device_count=0,
    )
    assert _issue(hass, entry_id, ISSUE_API_NOT_AUTHORIZED) is not None
    assert _issue(hass, entry_id, ISSUE_IOT_CORE_NOT_AUTHORIZED) is not None
    assert _issue(hass, entry_id, ISSUE_REGION_MISMATCH) is not None

    async_update_issues(
        hass,
        entry_id,
        api_not_authorized=False,
        iot_core_not_authorized=False,
        device_count=1,
    )
    assert _issue(hass, entry_id, ISSUE_API_NOT_AUTHORIZED) is None
    assert _issue(hass, entry_id, ISSUE_IOT_CORE_NOT_AUTHORIZED) is None
    assert _issue(hass, entry_id, ISSUE_REGION_MISMATCH) is None


@pytest.mark.asyncio
async def test_command_issue_is_created_and_cleared(hass) -> None:
    """A rejected command repair follows the latest command result."""
    entry_id = "entry-2"
    async_update_command_issue(hass, entry_id, not_authorized=True)
    assert _issue(hass, entry_id, ISSUE_COMMAND_NOT_AUTHORIZED) is not None

    async_update_command_issue(hass, entry_id, not_authorized=False)
    assert _issue(hass, entry_id, ISSUE_COMMAND_NOT_AUTHORIZED) is None


@pytest.mark.asyncio
async def test_fix_flow_is_informational(hass) -> None:
    """Repairs do not offer an automated fix that could expose credentials."""
    assert await async_create_fix_flow(hass, "issue", None) is None
