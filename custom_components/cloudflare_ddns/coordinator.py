"""Coordinator that keeps the Cloudflare records in step with the public IP."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    CloudflareAuthError,
    CloudflareClient,
    CloudflareError,
    DnsRecord,
    PublicIpError,
    async_get_public_ip,
)
from .const import (
    CONF_API_TOKEN,
    CONF_IPV4,
    CONF_IPV6,
    CONF_PROXIED,
    CONF_RECORD_NAME,
    CONF_TTL,
    CONF_UPDATE_INTERVAL,
    CONF_ZONE_ID,
    DEFAULT_IPV4,
    DEFAULT_IPV6,
    DEFAULT_PROXIED,
    DEFAULT_TTL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_RECORD_FAILED,
    EVENT_RECORD_UPDATED,
    IPV4_PROVIDERS,
    IPV6_PROVIDERS,
    RECORD_TYPE_IPV4,
    RECORD_TYPE_IPV6,
)

_LOGGER = logging.getLogger(__name__)

type CloudflareDdnsConfigEntry = ConfigEntry[CloudflareDdnsCoordinator]


@dataclass(slots=True)
class FamilyState:
    """What we know about one record type (A or AAAA)."""

    record_type: str
    enabled: bool
    public_ip: str | None = None
    record: DnsRecord | None = None
    last_updated: datetime | None = None
    error: str | None = None

    @property
    def in_sync(self) -> bool | None:
        """Whether Cloudflare currently matches the public IP."""
        if not self.enabled:
            return None
        if self.error is not None or self.public_ip is None or self.record is None:
            return None
        return self.record.content == self.public_ip


@dataclass(slots=True)
class CloudflareDdnsData:
    """Coordinator payload: one state per address family."""

    families: dict[str, FamilyState] = field(default_factory=dict)

    @property
    def any_error(self) -> str | None:
        """First error across the enabled families, if any."""
        for state in self.families.values():
            if state.enabled and state.error:
                return state.error
        return None


class CloudflareDdnsCoordinator(DataUpdateCoordinator[CloudflareDdnsData]):
    """Fetches the public IP and reconciles it with Cloudflare."""

    config_entry: CloudflareDdnsConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: CloudflareDdnsConfigEntry
    ) -> None:
        """Initialise the coordinator."""
        self._session = async_get_clientsession(hass)
        self.client = CloudflareClient(self._session, config_entry.data[CONF_API_TOKEN])
        self.zone_id: str = config_entry.data[CONF_ZONE_ID]
        self.record_name: str = config_entry.data[CONF_RECORD_NAME]

        interval = config_entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {self.record_name}",
            update_interval=timedelta(minutes=interval),
        )

    @property
    def _ttl(self) -> int:
        return self.config_entry.options.get(CONF_TTL, DEFAULT_TTL)

    @property
    def _proxied(self) -> bool:
        return self.config_entry.options.get(CONF_PROXIED, DEFAULT_PROXIED)

    async def _async_update_data(self) -> CloudflareDdnsData:
        """Reconcile every enabled record type with the current public IP.

        The refresh only fails when every enabled family failed, so one broken
        family does not take the other one's entities unavailable.
        """
        options = self.config_entry.options
        wanted = (
            (RECORD_TYPE_IPV4, options.get(CONF_IPV4, DEFAULT_IPV4), IPV4_PROVIDERS),
            (RECORD_TYPE_IPV6, options.get(CONF_IPV6, DEFAULT_IPV6), IPV6_PROVIDERS),
        )

        data = CloudflareDdnsData()
        previous = self.data.families if self.data else {}

        for record_type, enabled, providers in wanted:
            state = FamilyState(record_type=record_type, enabled=enabled)
            if prior := previous.get(record_type):
                state.last_updated = prior.last_updated
            data.families[record_type] = state

            if not enabled:
                continue

            try:
                await self._async_reconcile(state, providers)
            except CloudflareAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except (CloudflareError, PublicIpError) as err:
                state.error = str(err)
                _LOGGER.warning("%s (%s): %s", self.record_name, record_type, err)

        active = [s for s in data.families.values() if s.enabled]
        if active and all(s.error for s in active):
            raise UpdateFailed(active[0].error)

        return data

    async def _async_reconcile(
        self, state: FamilyState, providers: tuple[str, ...]
    ) -> None:
        """Bring one record type in line with the public IP.

        A record that has gone missing is recreated: the user opted into
        creation at setup, so self-healing beats erroring forever.
        """
        want_v6 = state.record_type == RECORD_TYPE_IPV6
        state.public_ip = await async_get_public_ip(
            self._session, providers, want_v6=want_v6
        )

        record = await self.client.async_get_record(
            self.zone_id, state.record_type, self.record_name
        )

        if record is None:
            _LOGGER.info(
                "Creating missing %s record for %s",
                state.record_type,
                self.record_name,
            )
            record = await self.client.async_create_record(
                self.zone_id,
                state.record_type,
                self.record_name,
                state.public_ip,
                ttl=self._ttl,
                proxied=self._proxied,
            )
            state.record = record
            state.last_updated = dt_util.utcnow()
            self._fire_updated(state, old_ip=None, new_ip=state.public_ip, created=True)
            return

        if record.content == state.public_ip:
            state.record = record
            return

        old_ip = record.content
        try:
            state.record = await self.client.async_update_record_content(
                self.zone_id, record, state.public_ip
            )
        except CloudflareError as err:
            state.record = record
            self.hass.bus.async_fire(
                EVENT_RECORD_FAILED,
                {
                    "entry_id": self.config_entry.entry_id,
                    "record_name": self.record_name,
                    "record_type": state.record_type,
                    "current_ip": old_ip,
                    "attempted_ip": state.public_ip,
                    "error": str(err),
                },
            )
            raise

        state.last_updated = dt_util.utcnow()
        _LOGGER.info(
            "Updated %s %s: %s -> %s",
            self.record_name,
            state.record_type,
            old_ip,
            state.public_ip,
        )
        self._fire_updated(state, old_ip=old_ip, new_ip=state.public_ip, created=False)

    def _fire_updated(
        self,
        state: FamilyState,
        *,
        old_ip: str | None,
        new_ip: str,
        created: bool,
    ) -> None:
        """Announce a change so users can automate on it."""
        self.hass.bus.async_fire(
            EVENT_RECORD_UPDATED,
            {
                "entry_id": self.config_entry.entry_id,
                "record_name": self.record_name,
                "record_type": state.record_type,
                "old_ip": old_ip,
                "new_ip": new_ip,
                "created": created,
                "proxied": state.record.proxied if state.record else None,
            },
        )
