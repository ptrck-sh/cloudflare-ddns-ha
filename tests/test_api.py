from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.cloudflare_ddns.api import (
    CloudflareAuthError,
    CloudflareClient,
    DnsRecord,
    PublicIpError,
    _is_valid_ip,
    async_get_public_ip,
)
from custom_components.cloudflare_ddns.const import IPV4_PROVIDERS, IPV6_PROVIDERS

from .conftest import PUBLIC_V4, PUBLIC_V6, RECORD_NAME, TOKEN, ZONE_ID


@pytest.mark.parametrize(
    ("value", "want_v6", "valid"),
    [
        ("93.184.216.34", False, True),
        ("2606:4700:4700::1111", True, True),
        ("93.184.216.34", True, False),
        ("2606:4700:4700::1111", False, False),
        ("192.168.1.10", False, False),
        ("10.0.0.1", False, False),
        ("169.254.1.1", False, False),
        ("100.64.0.1", False, False),
        ("fe80::1", True, False),
        ("fd00::1", True, False),
        ("<html>captive portal</html>", False, False),
        ("", False, False),
    ],
)
def test_is_valid_ip(value: str, want_v6: bool, valid: bool) -> None:
    assert _is_valid_ip(value, want_v6=want_v6) is valid


async def test_public_ip_falls_back_to_second_provider(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.get(IPV4_PROVIDERS[0], text="192.168.0.2")
    aioclient_mock.get(IPV4_PROVIDERS[1], text=f"{PUBLIC_V4}\n")

    ip = await async_get_public_ip(
        async_get_clientsession(hass), IPV4_PROVIDERS, want_v6=False
    )

    assert ip == PUBLIC_V4


async def test_public_ip_rejects_private_answers(
    hass: HomeAssistant, aioclient_mock
) -> None:
    for url in IPV4_PROVIDERS:
        aioclient_mock.get(url, text="10.1.2.3")

    with pytest.raises(PublicIpError, match="not a usable address"):
        await async_get_public_ip(
            async_get_clientsession(hass), IPV4_PROVIDERS, want_v6=False
        )


async def test_public_ip_v6(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(IPV6_PROVIDERS[0], text=PUBLIC_V6)

    ip = await async_get_public_ip(
        async_get_clientsession(hass), IPV6_PROVIDERS, want_v6=True
    )

    assert ip == PUBLIC_V6


async def test_update_patches_only_type_name_content(
    hass: HomeAssistant, cloudflare
) -> None:
    cloudflare.add_record("A", "93.184.216.1", ttl=300, proxied=True)
    client = CloudflareClient(async_get_clientsession(hass), TOKEN)
    record = DnsRecord("rec-A", "A", RECORD_NAME, "93.184.216.1", 300, True)

    updated = await client.async_update_record_content(ZONE_ID, record, PUBLIC_V4)

    _, _, payload = cloudflare.requests("PATCH")[0]
    assert payload == {"type": "A", "name": RECORD_NAME, "content": PUBLIC_V4}
    assert updated.proxied is True
    assert updated.ttl == 300


@pytest.mark.parametrize(("proxied", "has_ttl"), [(True, False), (False, True)])
async def test_create_omits_ttl_when_proxied(
    hass: HomeAssistant, cloudflare, proxied: bool, has_ttl: bool
) -> None:
    client = CloudflareClient(async_get_clientsession(hass), TOKEN)

    await client.async_create_record(
        ZONE_ID, "A", RECORD_NAME, PUBLIC_V4, ttl=120, proxied=proxied
    )

    _, _, payload = cloudflare.requests("POST")[0]
    assert ("ttl" in payload) is has_ttl
    assert payload["proxied"] is proxied


async def test_auth_error(hass: HomeAssistant, cloudflare) -> None:
    cloudflare.token_ok = False
    client = CloudflareClient(async_get_clientsession(hass), TOKEN)

    with pytest.raises(CloudflareAuthError):
        await client.async_verify_token()
