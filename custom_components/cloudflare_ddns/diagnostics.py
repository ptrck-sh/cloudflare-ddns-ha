"""Diagnostics for Cloudflare DDNS.

The public IP is as identifying as the token is secret, so both are redacted.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_API_TOKEN, CONF_ZONE_ID
from .coordinator import CloudflareDdnsConfigEntry

TO_REDACT = {CONF_API_TOKEN, CONF_ZONE_ID, "public_ip", "content", "record_ip"}
IP_LITERAL = re.compile(
    r"(?<![0-9A-Fa-f:])(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9A-Fa-f:]*:[0-9A-Fa-f:]+)(?![0-9A-Fa-f:])"
)


def _redact_error(error: str | None) -> str | None:
    """Replace IP address literals in an error message."""

    def replace(match: re.Match[str]) -> str:
        """Redact a matched literal when it is an IP address."""
        try:
            ipaddress.ip_address(match[0])
        except ValueError:
            return match[0]
        return "**REDACTED**"

    return IP_LITERAL.sub(replace, error) if error else error


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CloudflareDdnsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    states = coordinator.data.families if coordinator.data else {}
    families = {
        record_type: async_redact_data(
            {
                **asdict(state),
                "error": _redact_error(state.error),
                "in_sync": state.in_sync,
            },
            TO_REDACT,
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
