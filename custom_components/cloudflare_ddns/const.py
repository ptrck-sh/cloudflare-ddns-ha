"""Constants for the Cloudflare DDNS integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "cloudflare_ddns"

CONF_API_TOKEN: Final = "api_token"
CONF_ZONE_ID: Final = "zone_id"
CONF_ZONE_NAME: Final = "zone_name"
CONF_RECORD_NAME: Final = "record_name"

CONF_IPV4: Final = "ipv4"
CONF_IPV6: Final = "ipv6"
CONF_PROXIED: Final = "proxied"
CONF_SYNC_PROXIED: Final = "sync_proxied"
CONF_TTL: Final = "ttl"
CONF_UPDATE_INTERVAL: Final = "update_interval"

DEFAULT_IPV4: Final = True
DEFAULT_IPV6: Final = False
DEFAULT_PROXIED: Final = False
DEFAULT_SYNC_PROXIED: Final = False
DEFAULT_TTL: Final = 1
DEFAULT_UPDATE_INTERVAL: Final = 5

MIN_UPDATE_INTERVAL: Final = 1
MAX_UPDATE_INTERVAL: Final = 1440

EVENT_RECORD_UPDATED: Final = f"{DOMAIN}_record_updated"
EVENT_RECORD_FAILED: Final = f"{DOMAIN}_record_failed"

SERVICE_UPDATE_NOW: Final = "update_now"

RECORD_TYPE_IPV4: Final = "A"
RECORD_TYPE_IPV6: Final = "AAAA"

IPV4_PROVIDERS: Final = (
    "https://api.ipify.org",
    "https://ipv4.icanhazip.com",
)
IPV6_PROVIDERS: Final = (
    "https://api6.ipify.org",
    "https://ipv6.icanhazip.com",
)

IP_REQUEST_TIMEOUT: Final = timedelta(seconds=15)
API_REQUEST_TIMEOUT: Final = timedelta(seconds=20)

CLOUDFLARE_API_BASE: Final = "https://api.cloudflare.com/client/v4"
