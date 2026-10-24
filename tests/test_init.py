from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.cloudflare_ddns.const import (
    CONF_IPV6,
    DOMAIN,
    EVENT_RECORD_FAILED,
    EVENT_RECORD_UPDATED,
    SERVICE_UPDATE_NOW,
)
from custom_components.cloudflare_ddns.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import OLD_V4, PUBLIC_V4, PUBLIC_V6, RECORD_NAME, TOKEN, ZONE_ID

SYNC_A = "binary_sensor.home_example_com_a_out_of_sync"
SYNC_AAAA = "binary_sensor.home_example_com_aaaa_out_of_sync"
PUBLIC_A = "sensor.home_example_com_public_a_address"
RECORD_A = "sensor.home_example_com_record_a_address"
UPDATED_A = "sensor.home_example_com_a_last_updated"
UPDATE_NOW = "button.home_example_com_update_now"


async def _setup(hass: HomeAssistant, entry) -> None:
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_in_sync(hass: HomeAssistant, cloudflare, config_entry) -> None:
    cloudflare.add_record("A", PUBLIC_V4)

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(SYNC_A).state == STATE_OFF
    assert hass.states.get(PUBLIC_A).state == PUBLIC_V4
    assert hass.states.get(RECORD_A).state == PUBLIC_V4
    assert hass.states.get(SYNC_AAAA) is None
    assert not cloudflare.requests("PATCH")


async def test_changed_ip_is_patched_and_announced(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    cloudflare.add_record("A", OLD_V4, ttl=300, proxied=True)
    events = async_capture_events(hass, EVENT_RECORD_UPDATED)

    await _setup(hass, config_entry)

    _, _, payload = cloudflare.requests("PATCH")[0]
    assert payload == {"type": "A", "name": RECORD_NAME, "content": PUBLIC_V4}
    assert cloudflare.records["A"]["proxied"] is True
    assert cloudflare.records["A"]["ttl"] == 300
    assert events[0].data == {
        "entry_id": config_entry.entry_id,
        "record_name": RECORD_NAME,
        "record_type": "A",
        "old_ip": OLD_V4,
        "new_ip": PUBLIC_V4,
        "created": False,
        "proxied": True,
    }
    assert hass.states.get(SYNC_A).state == STATE_OFF
    assert hass.states.get(UPDATED_A).state != STATE_UNAVAILABLE


async def test_update_now_service(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    cloudflare.add_record("A", PUBLIC_V4)
    await _setup(hass, config_entry)
    events = async_capture_events(hass, EVENT_RECORD_UPDATED)

    cloudflare.records["A"]["content"] = OLD_V4
    await hass.services.async_call(DOMAIN, SERVICE_UPDATE_NOW, {}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert len(cloudflare.requests("PATCH")) == 1
    assert events[0].data["old_ip"] == OLD_V4
    assert cloudflare.records["A"]["content"] == PUBLIC_V4


async def test_update_now_button(hass: HomeAssistant, cloudflare, config_entry) -> None:
    cloudflare.add_record("A", PUBLIC_V4)
    await _setup(hass, config_entry)

    assert hass.states.get(UPDATE_NOW) is not None

    cloudflare.records["A"]["content"] = OLD_V4
    await hass.services.async_call(
        "button", "press", {"entity_id": UPDATE_NOW}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert len(cloudflare.requests("PATCH")) == 1
    assert cloudflare.records["A"]["content"] == PUBLIC_V4


async def test_deleted_record_is_recreated(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    events = async_capture_events(hass, EVENT_RECORD_UPDATED)

    await _setup(hass, config_entry)

    assert cloudflare.records["A"]["content"] == PUBLIC_V4
    assert events[0].data["created"] is True
    assert events[0].data["old_ip"] is None


async def test_failed_patch_fires_event(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    cloudflare.add_record("A", OLD_V4)
    cloudflare.fail_patch = True
    events = async_capture_events(hass, EVENT_RECORD_FAILED)

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert events[0].data["current_ip"] == OLD_V4
    assert events[0].data["attempted_ip"] == PUBLIC_V4


async def test_broken_ipv6_keeps_ipv4_up(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_IPV6: True}
    )
    cloudflare.add_record("A", PUBLIC_V4)
    cloudflare.public_v6 = None

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(SYNC_A).state == STATE_OFF
    assert hass.states.get(SYNC_AAAA).state == STATE_UNAVAILABLE


async def test_ipv6_tracked(hass: HomeAssistant, cloudflare, config_entry) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_IPV6: True}
    )
    cloudflare.add_record("A", PUBLIC_V4)
    cloudflare.add_record("AAAA", PUBLIC_V6)
    cloudflare.public_v6 = PUBLIC_V6

    await _setup(hass, config_entry)

    assert hass.states.get(SYNC_AAAA).state == STATE_OFF


async def test_out_of_sync_when_patch_fails_later(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    cloudflare.add_record("A", PUBLIC_V4)
    await _setup(hass, config_entry)

    cloudflare.records["A"]["content"] = OLD_V4
    cloudflare.fail_patch = True
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(SYNC_A).state == STATE_UNAVAILABLE
    assert hass.states.get(UPDATE_NOW).state != STATE_UNAVAILABLE

    cloudflare.fail_patch = False
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=12))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get(SYNC_A).state == STATE_OFF


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    cloudflare.token_ok = False

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_unload_removes_service(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    cloudflare.add_record("A", PUBLIC_V4)
    await _setup(hass, config_entry)
    assert hass.services.has_service(DOMAIN, SERVICE_UPDATE_NOW)

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, SERVICE_UPDATE_NOW)


async def test_diagnostics_redact(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    cloudflare.add_record("A", PUBLIC_V4)
    await _setup(hass, config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    dumped = repr(diagnostics)
    for secret in (TOKEN, ZONE_ID, PUBLIC_V4):
        assert secret not in dumped
    assert diagnostics["families"]["A"]["in_sync"] is True


async def test_diagnostics_redact_ip_in_error(
    hass: HomeAssistant, cloudflare, config_entry
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_IPV6: True}
    )
    cloudflare.add_record("A", PUBLIC_V4)
    cloudflare.public_v6 = PUBLIC_V4

    await _setup(hass, config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert PUBLIC_V4 not in repr(diagnostics)
    assert (
        "returned '**REDACTED**', not a usable address"
        in diagnostics["families"]["AAAA"]["error"]
    )
