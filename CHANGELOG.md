# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-10-15
### Fixed
- Sidebar entries finally appear: the plugin now publishes one navigation entry per enabled service through the sanctioned core API `ctx.register_nav_entries()` (core ≥ 1.7 / API 1.9). Up to 1.2.0 it injected virtual manifests through a `core.api.module_manager` export that never existed, so no entry was ever shown — and the virtual entries would have polluted the cluster's plugin fingerprint (`plugin_artifacts` preflight check).

### Changed
- The React shell lists the services under *Services* and opens them embedded at `/ext/<plugin>/<slug>` (`open_mode: iframe`) or in a new tab (`open_mode: new_tab`); the NiceGUI page `/external/{slug}` is unchanged.
- `min_core_version` is 1.7.0. On an older core the plugin still loads and serves its API, but logs one warning and shows no sidebar entries.

## [1.2.0] - 2026-10-15
### Fixed
- `health()` no longer runs DDL (`create_all` + `ALTER TABLE`) on every poll; it
  issues a single `COUNT` query (`ext_service_manager.count()`).
- Cluster-safe schema bootstrap: `ensure_table()` creates only this plugin's
  table (`checkfirst=True`), uses `ADD COLUMN IF NOT EXISTS` on MariaDB, runs
  under `db_instance.advisory_lock("lyndrix_bootstrap")` (getattr-guarded) and
  treats MariaDB 1050/1060 as "a peer did it". A failed or lost bootstrap never
  skips `register_all`.
- The bootstrap now also runs when the plugin is activated after
  `db:connected` already fired (the normal boot order) — before, the table was
  only created as a side effect of the health probe and the nav entries were
  not registered at boot.

### Changed
- Sidebar entries are per process; every create/update/delete/register (REST,
  NiceGUI, `external_services:register`) and `POST /reload` is announced as
  `external_services:changed` with `cluster=True`. Peers re-read the enabled
  services from the database and rebuild their entries (removed/disabled slugs
  disappear). `POST /reload` now also drops stale entries.
- Mutating REST handlers are `async`: DB work runs in `asyncio.to_thread`, the
  in-memory registry is only mutated on the event loop.
- Services pushed via `external_services:register` are refreshed (not only
  added), so a renamed service updates its sidebar entry.

### Known issues
- `core.api` does not export `module_manager`, so sidebar injection logs
  "NAV: Could not inject sidebar entry" and the per-service nav entries do not
  appear (pre-existing; the `/external/<slug>` pages work). Needs a core API
  for virtual nav entries.

## [0.2.0] - 2026-06-27
### Security
- **Critical**: closed the anonymous REST API. The router is now mounted by core
  via `ctx.register_routes()` under `/api/plugins/lyndrix.plugin.external_services/`
  and every route is auth-enforced (`api:read` for reads, `api:write` for
  mutations). The old unauthenticated `/api/external-services/` path is gone.
- **Critical**: fixed stored XSS — service URLs are now validated and embedded via
  a sandboxed iframe, with values rendered through `json.dumps`.

### Changed
- Updated operator-facing help text (REST docs, overview/settings UI) to point at
  the new authenticated path and note that an API key is required (B3). The
  in-process `external_services:register` event remains supported.
- Refactored package layout: `app/controller/` → `app/logic/`, `app/ui/*` →
  `app/ui/nicegui/*`, REST router moved to `app/api.py`.

## [0.1.0] - 2026-05-26
### Changed
- Refactored to the new Lyndrix Core plugin standard (`./app/` sub-package layout).
- `entrypoint.py` is now a pure wiring layer — the `external_services:register` payload processing was moved into the service layer.
- Manifest `repo_url` corrected to the canonical `lyndrix-platform/lyndrix-plugin-external-services`.
- `min_core_version` bumped to `0.0.6`.

### Fixed
- **Critical**: replaced illegal import `from core.components.plugins.logic.models import ModuleManifest` with the stable `from core.api import ModuleManifest`. The previous import reached into internal core modules and would have broken on any future core refactor.
- Removed tracked `__pycache__/` directory from the repository.
- `.gitignore` extended to cover Python cache and tooling artefacts.

### Added
- `CHANGELOG.md`.
- `requirements-dev.txt` with the standard plugin toolchain.
- `tests/test_service.py` smoke test for `ext_service_manager`.
- `app/controller/service.py::ext_service_manager.register_from_payload()` helper consolidating the event-bus registration flow.

## [0.0.1] - earlier
- Initial public release on the legacy flat layout.
