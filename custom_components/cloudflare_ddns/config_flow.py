"""Config flow for Cloudflare DDNS."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import (
    CloudflareAuthError,
    CloudflareClient,
    CloudflareError,
    PublicIpError,
    Zone,
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
    CONF_ZONE_NAME,
    DEFAULT_IPV4,
    DEFAULT_IPV6,
    DEFAULT_PROXIED,
    DEFAULT_TTL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    IPV4_PROVIDERS,
    IPV6_PROVIDERS,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    RECORD_TYPE_IPV4,
    RECORD_TYPE_IPV6,
)

_LOGGER = logging.getLogger(__name__)


class CloudflareDdnsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Walk the user from a token to a record that keeps itself current."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._token: str = ""
        self._zones: list[Zone] = []
        self._zone: Zone | None = None
        self._record_name: str = ""
        self._options: dict[str, Any] = {}
        self._missing: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Take the API token and look up the available zones."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._token = _strip_bearer(user_input[CONF_API_TOKEN])

            client = CloudflareClient(async_get_clientsession(self.hass), self._token)
            try:
                await client.async_verify_token()
                self._zones = await client.async_get_zones()
            except CloudflareAuthError:
                errors["base"] = "invalid_auth"
            except CloudflareError:
                errors["base"] = "cannot_connect"
            else:
                if not self._zones:
                    errors["base"] = "no_zones"
                else:
                    return await self.async_step_zone()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): TextSelector()}),
            errors=errors,
        )

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which zone the record lives in, skipped when there is only one."""
        if user_input is not None:
            self._zone = next(
                z for z in self._zones if z.id == user_input[CONF_ZONE_ID]
            )
            return await self.async_step_record()

        if len(self._zones) == 1:
            self._zone = self._zones[0]
            return await self.async_step_record()

        return self.async_show_form(
            step_id="zone",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ZONE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=z.id, label=z.name)
                                for z in sorted(self._zones, key=lambda z: z.name)
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_record(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Take the record name and the options that shape it."""
        assert self._zone is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            self._record_name = _normalise_record_name(
                user_input[CONF_RECORD_NAME], self._zone.name
            )
            self._options = {
                CONF_IPV4: user_input[CONF_IPV4],
                CONF_IPV6: user_input[CONF_IPV6],
                CONF_PROXIED: user_input[CONF_PROXIED],
                CONF_TTL: int(user_input[CONF_TTL]),
                CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
            }

            if not (self._options[CONF_IPV4] or self._options[CONF_IPV6]):
                errors["base"] = "no_record_type"
            elif not self._record_name.endswith(self._zone.name):
                errors[CONF_RECORD_NAME] = "wrong_zone"
            else:
                await self.async_set_unique_id(f"{self._zone.id}:{self._record_name}")
                self._abort_if_unique_id_configured()

                client = CloudflareClient(
                    async_get_clientsession(self.hass), self._token
                )
                try:
                    self._missing = await self._async_find_missing(client)
                except CloudflareAuthError:
                    errors["base"] = "invalid_auth"
                except CloudflareError:
                    errors["base"] = "cannot_connect"
                else:
                    if self._missing:
                        return await self.async_step_create_records()
                    return self._create_entry()

        return self.async_show_form(
            step_id="record",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RECORD_NAME, default=""): TextSelector(),
                    vol.Required(CONF_IPV4, default=DEFAULT_IPV4): BooleanSelector(),
                    vol.Required(CONF_IPV6, default=DEFAULT_IPV6): BooleanSelector(),
                    vol.Required(
                        CONF_PROXIED, default=DEFAULT_PROXIED
                    ): BooleanSelector(),
                    vol.Required(CONF_TTL, default=DEFAULT_TTL): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=86400, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"zone": self._zone.name},
        )

    async def async_step_create_records(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to create the records that do not exist yet."""
        assert self._zone is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = CloudflareClient(session, self._token)
            try:
                for record_type in self._missing:
                    want_v6 = record_type == RECORD_TYPE_IPV6
                    providers = IPV6_PROVIDERS if want_v6 else IPV4_PROVIDERS
                    ip = await async_get_public_ip(session, providers, want_v6=want_v6)
                    await client.async_create_record(
                        self._zone.id,
                        record_type,
                        self._record_name,
                        ip,
                        ttl=self._options[CONF_TTL],
                        proxied=self._options[CONF_PROXIED],
                    )
            except PublicIpError:
                errors["base"] = "no_public_ip"
            except CloudflareAuthError:
                errors["base"] = "invalid_auth"
            except CloudflareError as err:
                _LOGGER.error("Could not create record: %s", err)
                errors["base"] = "create_failed"
            else:
                return self._create_entry()

        return self.async_show_form(
            step_id="create_records",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "record": self._record_name,
                "types": ", ".join(self._missing),
                "proxied": "yes" if self._options[CONF_PROXIED] else "no",
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a re-authentication after the token stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Take a replacement token for an existing entry."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            token = _strip_bearer(user_input[CONF_API_TOKEN])

            client = CloudflareClient(async_get_clientsession(self.hass), token)
            try:
                await client.async_verify_token()
                await client.async_get_zone(entry.data[CONF_ZONE_ID])
            except CloudflareAuthError:
                errors["base"] = "invalid_auth"
            except CloudflareError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_TOKEN: token}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): TextSelector()}),
            errors=errors,
            description_placeholders={"record": entry.data[CONF_RECORD_NAME]},
        )

    async def _async_find_missing(self, client: CloudflareClient) -> list[str]:
        """Return the wanted record types that Cloudflare does not have."""
        assert self._zone is not None
        missing: list[str] = []
        wanted = (
            (RECORD_TYPE_IPV4, self._options[CONF_IPV4]),
            (RECORD_TYPE_IPV6, self._options[CONF_IPV6]),
        )
        for record_type, enabled in wanted:
            if not enabled:
                continue
            record = await client.async_get_record(
                self._zone.id, record_type, self._record_name
            )
            if record is None:
                missing.append(record_type)
        return missing

    @callback
    def _create_entry(self) -> ConfigFlowResult:
        """Finish the flow."""
        assert self._zone is not None
        return self.async_create_entry(
            title=self._record_name,
            data={
                CONF_API_TOKEN: self._token,
                CONF_ZONE_ID: self._zone.id,
                CONF_ZONE_NAME: self._zone.name,
                CONF_RECORD_NAME: self._record_name,
            },
            options=self._options,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> CloudflareDdnsOptionsFlow:
        """Return the options flow."""
        return CloudflareDdnsOptionsFlow()


class CloudflareDdnsOptionsFlow(OptionsFlow):
    """Let the user change what is tracked and how often."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        options = self.config_entry.options

        if user_input is not None:
            if not (user_input[CONF_IPV4] or user_input[CONF_IPV6]):
                errors["base"] = "no_record_type"
            else:
                return self.async_create_entry(
                    data={
                        CONF_IPV4: user_input[CONF_IPV4],
                        CONF_IPV6: user_input[CONF_IPV6],
                        CONF_PROXIED: user_input[CONF_PROXIED],
                        CONF_TTL: int(user_input[CONF_TTL]),
                        CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                    }
                )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IPV4, default=options.get(CONF_IPV4, DEFAULT_IPV4)
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_IPV6, default=options.get(CONF_IPV6, DEFAULT_IPV6)
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_PROXIED,
                        default=options.get(CONF_PROXIED, DEFAULT_PROXIED),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_TTL, default=options.get(CONF_TTL, DEFAULT_TTL)
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=86400, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    ),
                }
            ),
            errors=errors,
        )


def _strip_bearer(value: str) -> str:
    """Accept a bare token or a pasted 'Bearer ...' header."""
    token = value.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def _normalise_record_name(value: str, zone_name: str) -> str:
    """Accept a bare host or a full name, return the FQDN.

    "home" and "home.example.com" both become "home.example.com", and the
    zone apex can be given as "@" or the zone name itself.
    """
    name = value.strip().rstrip(".").lower()
    if name in ("", "@", zone_name):
        return zone_name
    if name.endswith(f".{zone_name}"):
        return name
    return f"{name}.{zone_name}"
