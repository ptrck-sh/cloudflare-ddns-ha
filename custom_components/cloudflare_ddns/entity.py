"""Shared entity base for Cloudflare DDNS."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ZONE_NAME, DOMAIN
from .coordinator import CloudflareDdnsCoordinator, FamilyState


class CloudflareDdnsEntity(CoordinatorEntity[CloudflareDdnsCoordinator]):
    """Base entity: one device per tracked record."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: CloudflareDdnsCoordinator, key: str, record_type: str
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._record_type = record_type
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{record_type}_{key}"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Cloudflare",
            model="DNS record",
            name=coordinator.record_name,
            configuration_url=(
                "https://dash.cloudflare.com/?to=/:account/"
                f"{entry.data.get(CONF_ZONE_NAME, '')}/dns/records"
            ),
        )

    @property
    def _family(self) -> FamilyState | None:
        """The state for this entity's address family."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.families.get(self._record_type)

    @property
    def available(self) -> bool:
        """Only available while its family is enabled and healthy."""
        family = self._family
        if family is None or not family.enabled:
            return False
        return super().available and family.error is None
