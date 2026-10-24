# Repository policy

Shared policy for human and automated contributors. This baseline file
is scaffolded by the ptrck-sh template; extend it with repo-specifics.

## Project

Home Assistant custom integration `cloudflare_ddns`, distributed through
HACS. GitLab is the source of truth; GitHub
(`github.com/ptrck-sh/cloudflare-ddns-ha`) is a push mirror and the public
face: releases, HACS and user issues live there.

`CONTRIBUTING.md` lists the invariants every change must preserve, the
release flow and the compatibility rule. Read it before changing code.

## Working rules

- No third-party runtime dependencies; `manifest.json` `requirements` stays
  empty.
- Keep `translations/en.json` a byte copy of `strings.json`.
- The minimum Home Assistant version is in `hacs.json`. Check when an API
  landed before using it.
- `yaml/` is the standalone no-HACS alternative. It shares no code with the
  integration; keep both behaviours aligned when the update logic changes.

## Validation

```sh
uv sync
uv run pytest
```

pre-commit runs ruff, yamllint, proselint and the policy checks on commit.
hassfest and the HACS action run on the GitHub mirror.
