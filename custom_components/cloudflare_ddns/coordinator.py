"""Coordinator that keeps the Cloudflare records in step with the public IP."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
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
    CONF_NOTIFY,
    CONF_NOTIFY_TARGETS,
    CONF_PROXIED,
    CONF_RECORD_NAME,
    CONF_SYNC_PROXIED,
    CONF_TTL,
    CONF_UPDATE_INTERVAL,
    CONF_ZONE_ID,
    DEFAULT_IPV4,
    DEFAULT_IPV6,
    DEFAULT_NOTIFY,
    DEFAULT_PROXIED,
    DEFAULT_SYNC_PROXIED,
    DEFAULT_TTL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_RECORD_FAILED,
    EVENT_RECORD_UPDATED,
    FAILURES_BEFORE_NOTIFY,
    IPV4_PROVIDERS,
    IPV6_PROVIDERS,
    NOTIFY_ALL,
    NOTIFY_OFF,
    RECORD_TYPE_IPV4,
    RECORD_TYPE_IPV6,
)

_LOGGER = logging.getLogger(__name__)

type CloudflareDdnsConfigEntry = ConfigEntry[CloudflareDdnsCoordinator]


def managed_comment(hass: HomeAssistant) -> str:
    """Return the Cloudflare comment that marks a record as managed here."""
    return f"managed by cloudflare-ddns on {hass.config.location_name}"[:100]


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
        self._failures: dict[str, int] = {}

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

    @property
    def _sync_proxied(self) -> bool:
        return self.config_entry.options.get(CONF_SYNC_PROXIED, DEFAULT_SYNC_PROXIED)

    @property
    def _notify(self) -> str:
        return self.config_entry.options.get(CONF_NOTIFY, DEFAULT_NOTIFY)

    def _notification_id(self, state: FamilyState, kind: str) -> str:
        return f"{DOMAIN}_{self.config_entry.entry_id}_{state.record_type}_{kind}"

    def _notify_updated(
        self, state: FamilyState, old_ip: str | None, new_ip: str
    ) -> None:
        if self._notify == NOTIFY_OFF:
            return
        change = f"{old_ip} → {new_ip}" if old_ip else f"created with {new_ip}"
        self._send(state, "updated", "Cloudflare DDNS updated", change)

    def _notify_failed(self, state: FamilyState) -> None:
        if self._notify != NOTIFY_ALL:
            return
        self._send(state, "failed", "Cloudflare DDNS failed", state.error or "")

    def _send(self, state: FamilyState, kind: str, title: str, text: str) -> None:
        message = f"{self.record_name} ({state.record_type}): {text}"
        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=self._notification_id(state, kind),
        )
        targets = self.config_entry.options.get(CONF_NOTIFY_TARGETS, [])
        if targets:
            self.config_entry.async_create_background_task(
                self.hass,
                self._async_push(targets, title, message),
                name=f"{DOMAIN} notify",
            )

    async def _async_push(self, targets: list[str], title: str, message: str) -> None:
        for target in targets:
            domain, _, service = target.partition(".")
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {"title": title, "message": message},
                    blocking=True,
                )
            except (HomeAssistantError, vol.Invalid) as err:
                _LOGGER.warning("Could not notify %s: %s", target, err)

    @property
    def _comment(self) -> str:
        """Return the Cloudflare comment that identifies this managed record."""
        return managed_comment(self.hass)

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
                self._failures[record_type] = self._failures.get(record_type, 0) + 1
                if self._failures[record_type] == FAILURES_BEFORE_NOTIFY:
                    self._notify_failed(state)
            else:
                if self._failures.pop(record_type, 0) >= FAILURES_BEFORE_NOTIFY:
                    persistent_notification.async_dismiss(
                        self.hass, self._notification_id(state, "failed")
                    )

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
                comment=self._comment,
            )
            state.record = record
            state.last_updated = dt_util.utcnow()
            self._fire_updated(state, old_ip=None, new_ip=state.public_ip, created=True)
            return

        content_changed = record.content != state.public_ip
        comment_changed = record.comment != self._comment
        proxied_changed = self._sync_proxied and record.proxied != self._proxied
        if not (content_changed or comment_changed or proxied_changed):
            state.record = record
            return

        old_ip = record.content
        try:
            state.record = await self.client.async_update_record(
                self.zone_id,
                record,
                content=state.public_ip if content_changed else None,
                comment=self._comment if comment_changed else None,
                proxied=self._proxied if proxied_changed else None,
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

        if content_changed:
            state.last_updated = dt_util.utcnow()
            _LOGGER.info(
                "Updated %s %s: %s -> %s",
                self.record_name,
                state.record_type,
                old_ip,
                state.public_ip,
            )
            self._fire_updated(
                state, old_ip=old_ip, new_ip=state.public_ip, created=False
            )
        else:
            _LOGGER.info(
                "Corrected settings for %s %s", self.record_name, state.record_type
            )

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
        self._notify_updated(state, old_ip, new_ip)
