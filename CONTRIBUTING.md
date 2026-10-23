# Contributing

## Where things live

| | Where |
|---|---|
| Source of truth, merge requests, CI | [gitlab.com/ptrck-sh/cloudflare-ddns-ha](https://gitlab.com/ptrck-sh/cloudflare-ddns-ha) |
| Releases, HACS, user issues | [github.com/ptrck-sh/cloudflare-ddns-ha](https://github.com/ptrck-sh/cloudflare-ddns-ha) |

GitHub is a push mirror of GitLab's protected branches and tags. Anything
merged on GitHub is overwritten by the next mirror push.

- **Issues:** open them on GitHub. Maintainers track the work on GitLab and
  link back to the GitHub issue.
- **Changes:** open a merge request on GitLab. A GitHub pull request is fine
  for discussion; a maintainer ports it to GitLab with your authorship kept
  and closes the pull request.

## Development

Tools come from [mise](https://mise.jdx.dev/); Python dependencies from
[uv](https://docs.astral.sh/uv/).

```sh
mise install
uv sync
uv run pytest
```

Tests use
[`pytest-homeassistant-custom-component`](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component),
which loads the integration into a real Home Assistant core. The Cloudflare
API and the IP lookup services are faked in `tests/conftest.py`; no test
touches the network.

pre-commit runs ruff, yamllint and the repository policy checks on every
commit and again in CI.

## Behaviour to preserve

1. Updates PATCH only `type`, `name` and `content`, so a record keeps its TTL
   and proxy setting.
2. TTL is omitted when creating a proxied record; Cloudflare rejects it.
3. Non-global IP answers are rejected, never published.
4. One address family failing does not take the other's entities down.
5. Authentication failures raise `ConfigEntryAuthFailed`, prompting re-auth.
6. Diagnostics redact the token, the zone ID and every IP address.

Each has a test. Keep it that way.

## Compatibility

The minimum Home Assistant version is in `hacs.json`. CI tests against the
Home Assistant version pinned by `pytest-homeassistant-custom-component` in
`uv.lock`. Before raising the minimum or using a newer API, check when that
API landed.

## Releases

Versions follow [SemVer](https://semver.org/), tags carry no `v` prefix.

1. Set `version` in `custom_components/cloudflare_ddns/manifest.json` to the
   new version, in a merge request.
2. After merge, tag the merge commit on GitLab, for example `0.2.0`, or
   `0.2.0-rc.1` for a release candidate.
3. The tag mirrors to GitHub, where the release workflow checks the tag
   matches the manifest and publishes a GitHub release. Release candidates
   become pre-releases, which HACS offers only to users who enable beta
   versions.
