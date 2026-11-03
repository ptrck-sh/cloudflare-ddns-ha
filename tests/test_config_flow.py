from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.cloudflare_ddns.const import (
    CONF_API_TOKEN,
    CONF_IPV4,
    CONF_IPV6,
    CONF_PROXIED,
    CONF_RECORD_NAME,
    CONF_SYNC_PROXIED,
    CONF_TTL,
    CONF_UPDATE_INTERVAL,
    CONF_ZONE_ID,
    DOMAIN,
)

from .conftest import PUBLIC_V4, PUBLIC_V6, RECORD_NAME, TOKEN, ZONE_ID, ZONE_NAME

RECORD_INPUT = {
    CONF_RECORD_NAME: "home",
    CONF_IPV4: True,
    CONF_IPV6: False,
    CONF_PROXIED: False,
    CONF_SYNC_PROXIED: False,
    CONF_TTL: 1,
    CONF_UPDATE_INTERVAL: 5,
}


async def _start(hass: HomeAssistant, token: str = f"Bearer {TOKEN}"):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: token}
    )


async def test_existing_record(hass: HomeAssistant, cloudflare) -> None:
    cloudflare.add_record("A", PUBLIC_V4)

    result = await _start(hass)
    assert result["step_id"] == "record"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], RECORD_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == RECORD_NAME
    assert result["data"][CONF_API_TOKEN] == TOKEN
    assert result["data"][CONF_ZONE_ID] == ZONE_ID
    assert result["options"][CONF_IPV4] is True
    assert not cloudflare.requests("POST")


async def test_zone_choice_with_several_zones(hass: HomeAssistant, cloudflare) -> None:
    cloudflare.zones.append({"id": "zone-2", "name": "example.org"})
    cloudflare.add_record("A", PUBLIC_V4)

    result = await _start(hass)
    assert result["step_id"] == "zone"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ZONE_ID: ZONE_ID}
    )
    assert result["step_id"] == "record"
    assert result["description_placeholders"]["zone"] == ZONE_NAME


async def test_offer_to_create_record(hass: HomeAssistant, cloudflare) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], RECORD_INPUT
    )
    assert result["step_id"] == "create_records"
    assert result["description_placeholders"]["types"] == "A"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    _, _, payload = cloudflare.requests("POST")[0]
    assert payload["content"] == PUBLIC_V4
    assert payload["name"] == RECORD_NAME


async def test_create_without_public_ip(hass: HomeAssistant, cloudflare) -> None:
    cloudflare.public_v4 = None
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], RECORD_INPUT
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["errors"] == {"base": "no_public_ip"}


async def test_create_records_retries_only_missing_type(
    hass: HomeAssistant, cloudflare
) -> None:
    cloudflare.public_v6 = None
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**RECORD_INPUT, CONF_IPV6: True}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["errors"] == {"base": "no_public_ip"}

    cloudflare.public_v6 = PUBLIC_V6
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [payload["type"] for _, _, payload in cloudflare.requests("POST")] == [
        "A",
        "AAAA",
    ]


async def test_already_configured(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    config_entry.add_to_hass(hass)
    cloudflare.add_record("A", PUBLIC_V4)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], RECORD_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_invalid_auth(hass: HomeAssistant, cloudflare) -> None:
    cloudflare.token_ok = False

    result = await _start(hass)

    assert result["errors"] == {"base": "invalid_auth"}


async def test_no_zones(hass: HomeAssistant, cloudflare) -> None:
    cloudflare.zones.clear()

    result = await _start(hass)

    assert result["errors"] == {"base": "no_zones"}


async def test_no_record_type(hass: HomeAssistant, cloudflare) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**RECORD_INPUT, CONF_IPV4: False}
    )

    assert result["errors"] == {"base": "no_record_type"}


async def test_rejects_record_in_another_zone(hass: HomeAssistant, cloudflare) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**RECORD_INPUT, CONF_RECORD_NAME: "foo.other.org"}
    )

    assert result["errors"] == {CONF_RECORD_NAME: "wrong_zone"}


async def test_rejects_record_with_zone_name_suffix(
    hass: HomeAssistant, cloudflare
) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**RECORD_INPUT, CONF_RECORD_NAME: "notexample.com"}
    )

    assert result["errors"] == {CONF_RECORD_NAME: "wrong_zone"}


async def test_accepts_record_in_selected_zone(hass: HomeAssistant, cloudflare) -> None:
    cloudflare.add_record("A", PUBLIC_V4)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**RECORD_INPUT, CONF_RECORD_NAME: "home.example.com"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_RECORD_NAME] == "home.example.com"


async def test_accepts_zone_apex(hass: HomeAssistant, cloudflare) -> None:
    cloudflare.add_record("A", PUBLIC_V4, name=ZONE_NAME)

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**RECORD_INPUT, CONF_RECORD_NAME: "@"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_RECORD_NAME] == ZONE_NAME


async def test_reauth(hass: HomeAssistant, cloudflare, config_entry) -> None:
    config_entry.add_to_hass(hass)
    cloudflare.add_record("A", PUBLIC_V4)

    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "Bearer new-token"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_API_TOKEN] == "new-token"
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(config_entry.entry_id)


async def test_options_flow(hass: HomeAssistant, cloudflare, config_entry) -> None:
    config_entry.add_to_hass(hass)
    cloudflare.add_record("A", PUBLIC_V4)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_IPV4: True,
            CONF_IPV6: False,
            CONF_PROXIED: True,
            CONF_SYNC_PROXIED: True,
            CONF_TTL: 1,
            CONF_UPDATE_INTERVAL: 10,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_UPDATE_INTERVAL] == 10
    assert config_entry.options[CONF_PROXIED] is True
    assert config_entry.options[CONF_SYNC_PROXIED] is True
