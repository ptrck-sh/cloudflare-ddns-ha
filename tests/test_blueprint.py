from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

BLUEPRINT = (
    Path(__file__).parent.parent
    / "blueprints"
    / "automation"
    / "cloudflare_ddns_notify.yaml"
)
UPDATED_MESSAGE = "{{ record_name }} {{ old_ip }} -> {{ new_ip }}"


@pytest.fixture(autouse=True)
def install_blueprint(hass: HomeAssistant) -> None:
    target = Path(hass.config.path("blueprints/automation/test"))
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, target / BLUEPRINT.name)


async def _setup(hass: HomeAssistant, entry: str = "") -> list:
    calls = async_mock_service(hass, "test", "notify")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": f"test/{BLUEPRINT.name}",
                    "input": {
                        "entry": entry,
                        "on_updated": [
                            {
                                "action": "test.notify",
                                "data": {"message": UPDATED_MESSAGE},
                            }
                        ],
                        "on_failed": [
                            {
                                "action": "test.notify",
                                "data": {"message": "failed {{ error }}"},
                            }
                        ],
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    return calls


async def test_updated_and_failed(hass: HomeAssistant) -> None:
    calls = await _setup(hass)

    hass.bus.async_fire(
        "cloudflare_ddns_record_updated",
        {
            "entry_id": "e1",
            "record_name": "home.example.com",
            "record_type": "A",
            "old_ip": "9.9.9.9",
            "new_ip": "93.184.216.34",
            "created": False,
            "proxied": True,
        },
    )
    hass.bus.async_fire(
        "cloudflare_ddns_record_failed",
        {
            "entry_id": "e1",
            "record_name": "home.example.com",
            "record_type": "A",
            "current_ip": "9.9.9.9",
            "attempted_ip": "93.184.216.34",
            "error": "nope",
        },
    )
    await hass.async_block_till_done()

    assert [call.data["message"] for call in calls] == [
        "home.example.com 9.9.9.9 -> 93.184.216.34",
        "failed nope",
    ]


async def test_entry_filter(hass: HomeAssistant) -> None:
    calls = await _setup(hass, entry="e2")

    hass.bus.async_fire(
        "cloudflare_ddns_record_updated",
        {"entry_id": "e1", "record_name": "x", "record_type": "A", "new_ip": "1.1.1.1"},
    )
    await hass.async_block_till_done()

    assert calls == []
