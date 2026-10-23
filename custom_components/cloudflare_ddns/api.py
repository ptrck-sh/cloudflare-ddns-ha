"""Minimal async Cloudflare DNS client.

Only the four calls this integration needs, so the integration carries no
third-party requirements and uses Home Assistant's shared aiohttp session.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import (
    API_REQUEST_TIMEOUT,
    CLOUDFLARE_API_BASE,
    IP_REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class CloudflareError(Exception):
    """Base error for Cloudflare API problems."""


class CloudflareAuthError(CloudflareError):
    """The token was rejected, or lacks permission on the zone."""


class CloudflareApiError(CloudflareError):
    """Cloudflare returned an error for an otherwise well-formed request."""


class PublicIpError(Exception):
    """The public IP could not be determined."""


@dataclass(slots=True)
class DnsRecord:
    """One DNS record, as far as this integration cares about it."""

    id: str
    type: str
    name: str
    content: str
    ttl: int
    proxied: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DnsRecord:
        """Build a record from a Cloudflare API result object."""
        return cls(
            id=data["id"],
            type=data["type"],
            name=data["name"],
            content=data["content"],
            ttl=data.get("ttl", 1),
            proxied=data.get("proxied", False),
        )


@dataclass(slots=True)
class Zone:
    """A Cloudflare zone."""

    id: str
    name: str


class CloudflareClient:
    """Talks to the Cloudflare v4 API."""

    def __init__(self, session: aiohttp.ClientSession, api_token: str) -> None:
        """Initialise the client."""
        self._session = session
        self._token = api_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Make a request and unwrap Cloudflare's envelope."""
        url = f"{CLOUDFLARE_API_BASE}{path}"
        timeout = aiohttp.ClientTimeout(total=API_REQUEST_TIMEOUT.total_seconds())

        try:
            async with self._session.request(
                method,
                url,
                headers=self._headers,
                json=json,
                params=params,
                timeout=timeout,
            ) as resp:
                try:
                    body = await resp.json()
                except (aiohttp.ContentTypeError, ValueError) as err:
                    raise CloudflareApiError(
                        f"Cloudflare returned a non-JSON response (HTTP {resp.status})"
                    ) from err

                if resp.status in (401, 403):
                    raise CloudflareAuthError(
                        _describe_errors(body) or "Token rejected"
                    )

                if not body.get("success", False):
                    raise CloudflareApiError(
                        _describe_errors(body) or f"HTTP {resp.status}"
                    )

                return body.get("result")

        except TimeoutError as err:
            raise CloudflareApiError("Timed out talking to Cloudflare") from err
        except aiohttp.ClientError as err:
            raise CloudflareApiError(f"Error talking to Cloudflare: {err}") from err

    async def async_verify_token(self) -> None:
        """Check the token is valid. Raises on failure."""
        result = await self._request("GET", "/user/tokens/verify")
        if isinstance(result, dict) and result.get("status") != "active":
            raise CloudflareAuthError(f"Token status is {result.get('status')!r}")

    async def async_get_zones(self) -> list[Zone]:
        """List the zones this token can see."""
        result = await self._request("GET", "/zones", params={"per_page": "50"})
        return [Zone(id=z["id"], name=z["name"]) for z in result or []]

    async def async_get_zone(self, zone_id: str) -> Zone:
        """Fetch a single zone."""
        result = await self._request("GET", f"/zones/{zone_id}")
        return Zone(id=result["id"], name=result["name"])

    async def async_get_record(
        self, zone_id: str, record_type: str, name: str
    ) -> DnsRecord | None:
        """Return the record of this type and name, or None if absent."""
        result = await self._request(
            "GET",
            f"/zones/{zone_id}/dns_records",
            params={"type": record_type, "name": name},
        )
        if not result:
            return None
        return DnsRecord.from_api(result[0])

    async def async_create_record(
        self,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        *,
        ttl: int = 1,
        proxied: bool = False,
    ) -> DnsRecord:
        """Create a record.

        Cloudflare forces automatic TTL on proxied records and rejects an
        explicit one, so TTL is only sent when the record is unproxied.
        """
        payload: dict[str, Any] = {
            "type": record_type,
            "name": name,
            "content": content,
            "proxied": proxied,
        }
        if not proxied:
            payload["ttl"] = ttl

        result = await self._request(
            "POST", f"/zones/{zone_id}/dns_records", json=payload
        )
        return DnsRecord.from_api(result)

    async def async_update_record_content(
        self, zone_id: str, record: DnsRecord, content: str
    ) -> DnsRecord:
        """Point an existing record at a new address.

        Only type, name and content are sent. A Cloudflare PATCH leaves
        unsent fields alone, so the record keeps whatever ttl and proxied
        setting it already had - this can never flip a proxied record to
        DNS-only by accident.
        """
        result = await self._request(
            "PATCH",
            f"/zones/{zone_id}/dns_records/{record.id}",
            json={"type": record.type, "name": record.name, "content": content},
        )
        return DnsRecord.from_api(result)


async def async_get_public_ip(
    session: aiohttp.ClientSession, providers: tuple[str, ...], *, want_v6: bool
) -> str:
    """Return the current public IP, trying each provider in turn."""
    timeout = aiohttp.ClientTimeout(total=IP_REQUEST_TIMEOUT.total_seconds())
    errors: list[str] = []

    for url in providers:
        try:
            async with session.get(url, timeout=timeout) as resp:
                resp.raise_for_status()
                raw = (await resp.text()).strip()
        except (aiohttp.ClientError, TimeoutError) as err:
            errors.append(f"{url}: {err}")
            continue

        if _is_valid_ip(raw, want_v6=want_v6):
            return raw

        errors.append(f"{url}: returned {raw[:60]!r}, not a usable address")

    family = "IPv6" if want_v6 else "IPv4"
    detail = "; ".join(errors)
    raise PublicIpError(f"Could not determine public {family} address. {detail}")


def _is_valid_ip(value: str, *, want_v6: bool) -> bool:
    """Check the value is a global address of the wanted family.

    A private or link-local answer means something intercepted the request;
    publishing it to public DNS would be worse than failing.
    """
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False

    if want_v6 != (addr.version == 6):
        return False

    return addr.is_global


def _describe_errors(body: dict[str, Any]) -> str:
    """Flatten Cloudflare's error list into one readable string."""
    errors = body.get("errors") or []
    parts = [
        f"{err.get('message', 'unknown error')} (code {err.get('code')})"
        for err in errors
        if isinstance(err, dict)
    ]
    return "; ".join(parts)
