---
applyTo: '**/manifest.json,hacs.json,pyproject.toml'
description: HARO manifest, HACS, and version requirements
globs: ['**/manifest.json', hacs.json, pyproject.toml]
alwaysApply: false
---

# Manifest And Release Metadata

The Home Assistant manifest, HACS metadata, and Python project metadata must stay consistent.

## Versioning

The HARO version must match in:

- `pyproject.toml`
- `custom_components/haro/manifest.json`
- release tag without the leading `v`

Release tags use `vX.Y.Z` or `vX.Y.ZrcN`.
Run `uv lock` after changing the project version so `uv.lock` stays current.

## Home Assistant Version

The minimum Home Assistant version must match in:

- `pyproject.toml` dependency constraint for `homeassistant`
- `hacs.json` `homeassistant` field

Do not let Dependabot update Home Assistant automatically unless the HACS minimum is updated in the same change.

## HACS Package

HARO releases upload `haro.zip`.
The HACS `filename` field must stay `haro.zip`, and `zip_release` must stay `true`.

## Manifest Shape

Keep the integration domain `haro`.
HARO is a hub-style integration with a config flow and no Home Assistant platforms unless the integration begins exposing entities.
Do not add runtime Python requirements to `manifest.json` unless Home Assistant must install them for HARO at integration load time.
