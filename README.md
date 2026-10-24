# Cloudflare DDNS for Home Assistant

Keeps Cloudflare DNS records pointed at your current public IP. Set up in the
UI, no YAML, no add-on, no container, no shell script.

Works on every install type — HA OS, Supervised, Container and Core.

## What it does

Every few minutes it looks up your public address, compares it with what
Cloudflare has, and updates the record only if they differ. It exposes the
result as entities and fires an event when something changes, so you decide
how you want to be told.

- **IPv4 and IPv6** — tracks the `A` record, the `AAAA` record, or both.
- **Creates the record for you** if it does not exist yet, rather than failing
  until you go and make one by hand.
- **Never clobbers your settings.** Updates send only the address, so
  Cloudflare keeps the record's existing TTL and proxy setting. It cannot flip
  a proxied record to DNS-only by accident.
- **Self-healing.** If the record is deleted in Cloudflare, the next check
  recreates it.
- **No third-party Python dependencies.** It uses Home Assistant's own HTTP
  session.

## Install

Requires Home Assistant 2024.12 or newer.

### HACS

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ptrck-sh&repository=cloudflare-ddns-ha&category=integration)

1. HACS → three-dot menu → **Custom repositories**
2. Add `https://github.com/ptrck-sh/cloudflare-ddns-ha`, category
   **Integration**
3. Install **Cloudflare DDNS**, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Cloudflare DDNS**

### Manual

Copy `custom_components/cloudflare_ddns/` from the
[latest release](https://github.com/ptrck-sh/cloudflare-ddns-ha/releases/latest)
into your `config/custom_components/` directory and restart.

## Setup

You need a Cloudflare API token with **Zone → DNS → Edit** on the zone.
Create one at **Cloudflare dashboard → My Profile → API Tokens → Create
Token**, using the *Edit zone DNS* template.

The config flow then asks for:

| Field | |
|---|---|
| **API token** | Pasting the whole `Bearer ...` header works too. |
| **Zone** | Skipped if the token only reaches one zone. |
| **Record name** | A single label such as `home`, a full name in the selected zone such as `home.example.com`, or `@` for the domain itself. Names with dots must be full names in the zone. |
| **IPv4 / IPv6** | Which record types to track. |
| **Proxied** | Only applied to records this integration creates. |
| **TTL** | Seconds, or `1` for automatic. Ignored on proxied records. |
| **Check every** | Minutes between checks. Default 5. |

One config entry per record. Add the integration again for another record;
all of them can share the same token.

If the record does not exist, the flow offers to create it pointing at your
current address.

## Entities

Per tracked record, per address family:

| Entity | What it is |
|---|---|
| `sensor.<record>_public_a_address` | Your current public address |
| `sensor.<record>_record_a_address` | What Cloudflare currently has |
| `sensor.<record>_a_last_updated` | When it was last changed |
| `binary_sensor.<record>_a_out_of_sync` | Problem class: on when they differ |
| `button.<record>_update_now` | Checks immediately, same as the `update_now` action |

`AAAA` equivalents appear when IPv6 is enabled.

## Notifications

The integration does not send messages itself — it fires an event and you
automate on it. That way you use whatever you already have: Discord, mobile
push, persistent notification.

```yaml
automation:
  - alias: "Cloudflare DDNS changed"
    triggers:
      - trigger: event
        event_type: cloudflare_ddns_record_updated
    actions:
      - action: notify.persistent_notification
        data:
          message: >-
            {{ trigger.event.data.record_name }}
            ({{ trigger.event.data.record_type }}):
            {{ trigger.event.data.old_ip | default('new record') }}
            -> {{ trigger.event.data.new_ip }}
```

### `cloudflare_ddns_record_updated`

| Field | |
|---|---|
| `entry_id` | The config entry that changed |
| `record_name` | FQDN, e.g. `home.example.com` |
| `record_type` | `A` or `AAAA` |
| `old_ip` | Previous address, or `null` if just created |
| `new_ip` | New address |
| `created` | `true` if the record was created rather than updated |
| `proxied` | Whether the record is proxied |

### `cloudflare_ddns_record_failed`

Fired when an update was attempted and Cloudflare refused. Carries
`record_name`, `record_type`, `current_ip`, `attempted_ip` and `error`.

## Service

`cloudflare_ddns.update_now` forces an immediate check, ignoring the poll
interval. Optional `entry_id` limits it to specific records; omit it for all.

## Notes

**Proxying defeats the point.** A proxied record resolves to Cloudflare's
addresses, not yours, so anything needing your real IP — VPN, game server,
SSH — must be DNS-only. Proxying is off by default.

**Proxied records always use automatic TTL.** That is Cloudflare's rule.

**Private answers are rejected.** If an IP lookup returns a private or
link-local address, the check fails rather than publishing it.

**IPv6 needs working IPv6.** On a DS-Lite connection you have IPv6 but no
usable public IPv4, so track `AAAA` only.

Address lookups use [ipify](https://www.ipify.org/), falling back to
[icanhazip](https://icanhazip.com/).

## YAML alternative

If you would rather not run a custom integration, [`yaml/`](yaml/) holds the
same logic as a Home Assistant package — a `rest` sensor, two `rest_command`s
and an automation, in one drop-in file. It is IPv4-only and needs the record
to exist already. See [`yaml/README.md`](yaml/README.md).

## Issues and contributions

Report bugs and request features in
[GitHub issues](https://github.com/ptrck-sh/cloudflare-ddns-ha/issues).
Attach the integration's diagnostics download; it redacts the token, the
zone ID and every IP address.

Development happens on
[GitLab](https://gitlab.com/ptrck-sh/cloudflare-ddns-ha). GitHub is a
read-only mirror, so pull requests there cannot be merged as they are. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Prior art

Built after the shell-script and add-on approaches to the same problem,
notably [K0p1-Git/cloudflare-ddns-updater][k0p1] and
[silashansen/hass_addons][silas]. The differences: the record ID is resolved
at runtime instead of hardcoded, updates preserve TTL and proxy settings, and
it runs inside Home Assistant with no Supervisor or cron.

[k0p1]: https://github.com/K0p1-Git/cloudflare-ddns-updater
[silas]: https://github.com/silashansen/hass_addons

## License

MIT — see [LICENSE](LICENSE).
