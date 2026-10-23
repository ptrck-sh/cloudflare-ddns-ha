"""The Cloudflare DDNS integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, SERVICE_UPDATE_NOW
from .coordinator import CloudflareDdnsConfigEntry, CloudflareDdnsCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

ATTR_ENTRY_ID = "entry_id"

SERVICE_UPDATE_NOW_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_ENTRY_ID): vol.All(cv.ensure_list, [cv.string])}
)


async def async_setup_entry(
    hass: HomeAssistant, entry: CloudflareDdnsConfigEntry
) -> bool:
    """Set up Cloudflare DDNS from a config entry."""
    coordinator = CloudflareDdnsCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _async_register_services(hass)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: CloudflareDdnsConfigEntry
) -> bool:
    """Unload a config entry, dropping the service with the last one."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded and not _loaded_entries(hass, exclude=entry.entry_id):
        hass.services.async_remove(DOMAIN, SERVICE_UPDATE_NOW)

    return unloaded


async def _async_options_updated(
    hass: HomeAssistant, entry: CloudflareDdnsConfigEntry
) -> None:
    """Reload the entry so option changes take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _loaded_entries(
    hass: HomeAssistant, *, exclude: str | None = None
) -> list[CloudflareDdnsConfigEntry]:
    """Return the entries that currently have a coordinator attached."""
    return [
        entry
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if entry.entry_id != exclude and hasattr(entry, "runtime_data")
    ]


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration services, once."""
    if hass.services.has_service(DOMAIN, SERVICE_UPDATE_NOW):
        return

    async def _async_update_now(call: ServiceCall) -> None:
        """Force an immediate check, bypassing the poll interval."""
        wanted = call.data.get(ATTR_ENTRY_ID)
        for entry in _loaded_entries(hass):
            if wanted and entry.entry_id not in wanted:
                continue
            await entry.runtime_data.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_NOW,
        _async_update_now,
        schema=SERVICE_UPDATE_NOW_SCHEMA,
    )
