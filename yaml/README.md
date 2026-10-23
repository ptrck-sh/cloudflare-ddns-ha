# YAML alternative

The same idea as the integration, in plain Home Assistant YAML: no HACS, no
add-on, no container, no shell script. It runs on every install type.

It is deliberately smaller than the integration:

- IPv4 only (`A` records).
- The record must already exist. It updates a record, it never creates one.
  Create it by hand first, pointing at any address; the first run corrects it.
- It reports through a notify action instead of firing events.
- It checks the address only against an IPv4 pattern. A private answer, for
  example from a captive portal, would be published; the integration rejects
  those.

## Package

[`packages/cloudflare_ddns.yaml`](packages/cloudflare_ddns.yaml) holds a
public IP `rest` sensor, two `rest_command`s and an automation in one file.
It reports to a Discord channel through `notify.home_assistant`; change the
three notify actions if you use something else.

1. Enable packages once, in `configuration.yaml`:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

2. Copy the file to `<config>/packages/cloudflare_ddns.yaml`.
3. Add these to `secrets.yaml`:

   ```yaml
   cloudflare_auth_header: "Bearer <token>"
   cloudflare_zone_id: "<32 hex characters>"
   cloudflare_record_name: "home.example.com"
   discord_ddns_channel_id: "<channel id>"
   ```

4. Restart Home Assistant. A reload does not pick up new top-level keys.

The token needs **Zone → DNS → Edit** on the zone.

**Edit the automation as YAML only.** Opening it in the visual editor makes
Home Assistant rewrite the file and resolve the `!secret` references into it,
which writes your API token to disk in plain text.

The PATCH sends only `type`, `name` and `content`. Cloudflare leaves the
fields it is not sent alone, so the record keeps its TTL and proxy setting.

## Blueprint

[`blueprints/automation/cloudflare_ddns_record.yaml`](blueprints/automation/cloudflare_ddns_record.yaml)
is the automation alone, for keeping several records current: install the
package once, then add one blueprint automation per record. It needs the
package's sensor and `rest_command`s to exist.

Values entered into a blueprint, the token included, are stored in
`automations.yaml` in plain text.

## Moving to the integration

Remove the package (or the equivalent blocks you pasted into
`configuration.yaml` and `automations.yaml`) once the integration tracks the
same record. Both can run side by side while you test, but two copies of the
`rest_command` keys fail the configuration check.
