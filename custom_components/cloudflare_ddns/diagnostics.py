"""Diagnostics for Cloudflare DDNS.

The public IP is as identifying as the token is secret, so both are redacted.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_API_TOKEN, CONF_ZONE_ID
from .coordinator import CloudflareDdnsConfigEntry

TO_REDACT = {CONF_API_TOKEN, CONF_ZONE_ID, "public_ip", "content", "record_ip"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CloudflareDdnsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    states = coordinator.data.families if coordinator.data else {}
    families = {
        record_type: async_redact_data(
            {**asdict(state), "in_sync": state.in_sync}, TO_REDACT
        )
        for record_type, state in states.items()
    }

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "families": families,
    }
