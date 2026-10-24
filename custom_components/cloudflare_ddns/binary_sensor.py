"""Binary sensor telling you whether Cloudflare is current."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_IPV4,
    CONF_IPV6,
    DEFAULT_IPV4,
    DEFAULT_IPV6,
    RECORD_TYPE_IPV4,
    RECORD_TYPE_IPV6,
)
from .coordinator import CloudflareDdnsConfigEntry, CloudflareDdnsCoordinator
from .entity import CloudflareDdnsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CloudflareDdnsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one in-sync sensor per tracked address family."""
    coordinator = entry.runtime_data
    families = (
        (RECORD_TYPE_IPV4, entry.options.get(CONF_IPV4, DEFAULT_IPV4)),
        (RECORD_TYPE_IPV6, entry.options.get(CONF_IPV6, DEFAULT_IPV6)),
    )

    async_add_entities(
        CloudflareDdnsInSyncSensor(coordinator, record_type)
        for record_type, enabled in families
        if enabled
    )


class CloudflareDdnsInSyncSensor(CloudflareDdnsEntity, BinarySensorEntity):
    """On while the Cloudflare record differs from the public IP."""

    _attr_translation_key = "in_sync"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: CloudflareDdnsCoordinator, record_type: str
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "in_sync", record_type)
        self._attr_translation_placeholders = {"record_type": record_type}

    @property
    def is_on(self) -> bool | None:
        """True means there is a problem: Cloudflare is out of step."""
        if (family := self._family) is None:
            return None
        in_sync = family.in_sync
        if in_sync is None:
            return None
        return not in_sync

    @property
    def extra_state_attributes(self) -> dict[str, str | int | bool | None] | None:
        """Expose the detail behind the state."""
        if (family := self._family) is None:
            return None
        record = family.record
        return {
            "record_name": self.coordinator.record_name,
            "record_type": family.record_type,
            "public_ip": family.public_ip,
            "record_ip": record.content if record else None,
            "proxied": record.proxied if record else None,
            "ttl": record.ttl if record else None,
            "error": family.error,
        }
