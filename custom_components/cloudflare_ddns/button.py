"""Button for immediately refreshing a Cloudflare DDNS record."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CloudflareDdnsConfigEntry, CloudflareDdnsCoordinator
from .entity import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CloudflareDdnsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the immediate-update button for one tracked record."""
    async_add_entities([CloudflareDdnsUpdateNowButton(entry.runtime_data)])


class CloudflareDdnsUpdateNowButton(ButtonEntity):
    """Request an immediate refresh for one tracked record."""

    _attr_device_class = ButtonDeviceClass.UPDATE
    _attr_has_entity_name = True
    _attr_translation_key = "update_now"

    def __init__(self, coordinator: CloudflareDdnsCoordinator) -> None:
        """Initialise the button."""
        self.coordinator = coordinator
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_update_now"
        self._attr_device_info = device_info(coordinator)

    @property
    def available(self) -> bool:
        """Keep the button available after a failed refresh."""
        return True

    async def async_press(self) -> None:
        """Request an immediate refresh."""
        await self.coordinator.async_request_refresh()
