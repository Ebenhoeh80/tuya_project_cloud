"""Repairs support for Tuya Project Cloud."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import (
    DOMAIN,
    ISSUE_API_NOT_AUTHORIZED,
    ISSUE_IOT_CORE_NOT_AUTHORIZED,
    ISSUE_REGION_MISMATCH,
)


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, object] | None,
) -> None:
    """Repairs issues have no automated fix; they are informational."""
    return


def async_update_issues(
    hass: HomeAssistant,
    entry_id: str,
    *,
    api_not_authorized: bool,
    iot_core_not_authorized: bool,
    device_count: int,
) -> None:
    """Create or delete issues based on coordinator state."""
    api_issue = f"{entry_id}_{ISSUE_API_NOT_AUTHORIZED}"
    if api_not_authorized:
        ir.async_create_issue(
            hass,
            DOMAIN,
            api_issue,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_API_NOT_AUTHORIZED,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, api_issue)

    iot_issue = f"{entry_id}_{ISSUE_IOT_CORE_NOT_AUTHORIZED}"
    if iot_core_not_authorized:
        ir.async_create_issue(
            hass,
            DOMAIN,
            iot_issue,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_IOT_CORE_NOT_AUTHORIZED,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, iot_issue)

    region_issue = f"{entry_id}_{ISSUE_REGION_MISMATCH}"
    if device_count == 0:
        ir.async_create_issue(
            hass,
            DOMAIN,
            region_issue,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_REGION_MISMATCH,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, region_issue)
