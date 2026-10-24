"""Sensors for Cloudflare DDNS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
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
from .coordinator import (
    CloudflareDdnsConfigEntry,
    CloudflareDdnsCoordinator,
    FamilyState,
)
from .entity import CloudflareDdnsEntity


@dataclass(frozen=True, kw_only=True)
class CloudflareDdnsSensorDescription(SensorEntityDescription):
    """Describes a Cloudflare DDNS sensor."""

    value_fn: Callable[[FamilyState], str | datetime | None]


SENSORS: tuple[CloudflareDdnsSensorDescription, ...] = (
    CloudflareDdnsSensorDescription(
        key="public_ip",
        translation_key="public_ip",
        value_fn=lambda family: family.public_ip,
    ),
    CloudflareDdnsSensorDescription(
        key="record_ip",
        translation_key="record_ip",
        value_fn=lambda family: family.record.content if family.record else None,
    ),
    CloudflareDdnsSensorDescription(
        key="last_updated",
        translation_key="last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda family: family.last_updated,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CloudflareDdnsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for one tracked record."""
    coordinator = entry.runtime_data
    families = (
        (RECORD_TYPE_IPV4, entry.options.get(CONF_IPV4, DEFAULT_IPV4)),
        (RECORD_TYPE_IPV6, entry.options.get(CONF_IPV6, DEFAULT_IPV6)),
    )

    async_add_entities(
        CloudflareDdnsSensor(coordinator, description, record_type)
        for record_type, enabled in families
        if enabled
        for description in SENSORS
    )


class CloudflareDdnsSensor(CloudflareDdnsEntity, SensorEntity):
    """A sensor reflecting one aspect of one address family."""

    entity_description: CloudflareDdnsSensorDescription

    def __init__(
        self,
        coordinator: CloudflareDdnsCoordinator,
        description: CloudflareDdnsSensorDescription,
        record_type: str,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key, record_type)
        self.entity_description = description
        self._attr_translation_placeholders = {"record_type": record_type}

    @property
    def native_value(self) -> str | datetime | None:
        """Return the current value."""
        if (family := self._family) is None:
            return None
        return self.entity_description.value_fn(family)

    @property
    def available(self) -> bool:
        """The timestamp sensor stays available before the first change."""
        if self.entity_description.key == "last_updated":
            family = self._family
            return family is not None and family.enabled
        return super().available
