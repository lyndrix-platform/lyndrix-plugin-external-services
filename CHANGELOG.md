# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
