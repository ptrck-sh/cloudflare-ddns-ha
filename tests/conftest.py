from __future__ import annotations

import re
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

import pytest
from aiohttp import ClientError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.cloudflare_ddns.const import (
    CONF_API_TOKEN,
    CONF_IPV4,
    CONF_IPV6,
    CONF_PROXIED,
    CONF_RECORD_NAME,
    CONF_TTL,
    CONF_UPDATE_INTERVAL,
    CONF_ZONE_ID,
    CONF_ZONE_NAME,
    DOMAIN,
    IPV4_PROVIDERS,
    IPV6_PROVIDERS,
)

TOKEN = "cf-token"
ZONE_ID = "zone-1"
ZONE_NAME = "example.com"
RECORD_NAME = "home.example.com"
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:4700:4700::1111"
OLD_V4 = "93.184.216.1"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@dataclass
class FakeCloudflare:
    zones: list[dict[str, str]] = field(
        default_factory=lambda: [{"id": ZONE_ID, "name": ZONE_NAME}]
    )
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    token_ok: bool = True
    fail_patch: bool = False
    public_v4: str | None = PUBLIC_V4
    public_v6: str | None = None
    calls: list[tuple[str, str, Any]] = field(default_factory=list)

    def add_record(
        self,
        record_type: str,
        content: str,
        *,
        name: str = RECORD_NAME,
        ttl: int = 300,
        proxied: bool = False,
    ) -> None:
        self.records[record_type] = {
            "id": f"rec-{record_type}",
            "type": record_type,
            "name": name,
            "content": content,
            "ttl": ttl,
            "proxied": proxied,
        }

    def requests(self, method: str) -> list[tuple[str, str, Any]]:
        return [call for call in self.calls if call[0] == method]

    async def handle(self, method: str, url, data) -> AiohttpClientMockResponse:
        method = method.upper()
        path = url.path.removeprefix("/client/v4")
        self.calls.append((method, path, data))

        if not self.token_ok:
            return self._reply(
                method,
                url,
                {"success": False, "errors": [{"code": 1000, "message": "bad"}]},
                HTTPStatus.UNAUTHORIZED,
            )

        if path == "/user/tokens/verify":
            return self._ok(method, url, {"status": "active"})
        if path == "/zones":
            per_page = int(url.query.get("per_page", 50))
            page = int(url.query.get("page", 1))
            total_pages = max(1, -(-len(self.zones) // per_page))
            start = (page - 1) * per_page
            return self._ok(
                method,
                url,
                self.zones[start : start + per_page],
                result_info={"page": page, "total_pages": total_pages},
            )
        if path == f"/zones/{ZONE_ID}":
            return self._ok(method, url, self.zones[0])
        if path == f"/zones/{ZONE_ID}/dns_records" and method == "GET":
            record = self.records.get(url.query.get("type"))
            return self._ok(method, url, [record] if record else [])
        if path == f"/zones/{ZONE_ID}/dns_records" and method == "POST":
            self.add_record(
                data["type"],
                data["content"],
                name=data["name"],
                ttl=data.get("ttl", 1),
                proxied=data["proxied"],
            )
            return self._ok(method, url, self.records[data["type"]])
        if match := re.fullmatch(rf"/zones/{ZONE_ID}/dns_records/rec-(\w+)", path):
            if self.fail_patch:
                return self._reply(
                    method,
                    url,
                    {"success": False, "errors": [{"code": 9999, "message": "no"}]},
                    HTTPStatus.BAD_REQUEST,
                )
            record = self.records[match[1]]
            record.update(data)
            return self._ok(method, url, record)

        raise AssertionError(f"Unexpected Cloudflare call {method} {path}")

    def _ok(
        self, method, url, result, *, result_info=None
    ) -> AiohttpClientMockResponse:
        body = {"success": True, "result": result}
        if result_info is not None:
            body["result_info"] = result_info
        return self._reply(method, url, body)

    @staticmethod
    def _reply(method, url, body, status=HTTPStatus.OK) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, status=status, json=body)


def _ip_handler(fake: FakeCloudflare, attr: str):
    async def handler(method, url, data) -> AiohttpClientMockResponse:
        value = getattr(fake, attr)
        if value is None:
            return AiohttpClientMockResponse(method, url, exc=ClientError("down"))
        return AiohttpClientMockResponse(method, url, text=value)

    return handler


@pytest.fixture
def cloudflare(aioclient_mock: AiohttpClientMocker) -> FakeCloudflare:
    fake = FakeCloudflare()
    aioclient_mock.request(
        "GET", re.compile(r"^https://api\.cloudflare\.com/"), side_effect=fake.handle
    )
    for verb in ("POST", "PATCH"):
        aioclient_mock.request(
            verb, re.compile(r"^https://api\.cloudflare\.com/"), side_effect=fake.handle
        )
    for url in IPV4_PROVIDERS:
        aioclient_mock.get(url, side_effect=_ip_handler(fake, "public_v4"))
    for url in IPV6_PROVIDERS:
        aioclient_mock.get(url, side_effect=_ip_handler(fake, "public_v6"))
    return fake


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=RECORD_NAME,
        unique_id=f"{ZONE_ID}:{RECORD_NAME}",
        data={
            CONF_API_TOKEN: TOKEN,
            CONF_ZONE_ID: ZONE_ID,
            CONF_ZONE_NAME: ZONE_NAME,
            CONF_RECORD_NAME: RECORD_NAME,
        },
        options={
            CONF_IPV4: True,
            CONF_IPV6: False,
            CONF_PROXIED: False,
            CONF_TTL: 1,
            CONF_UPDATE_INTERVAL: 5,
        },
    )
