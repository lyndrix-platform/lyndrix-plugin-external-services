"""
routing.py — Sidebar-nav injection for ExternalService entries.

The page itself is served by a single parameterised NiceGUI route at
``/external/{slug}`` (see ``app/ui/nicegui/pages.py``) which resolves the
service at request time, so enable/disable/edit/delete take effect immediately
without a process restart.

This module only manages the *navigation* side: it injects/removes a virtual
manifest entry in ``module_manager.registry`` so each service shows up in the
main sidebar under "Services". It is the single orchestration point used by both
the REST API and the NiceGUI settings form.
"""

import logging
from typing import Iterable, Optional

from ..model.models import ExternalService

log = logging.getLogger("Plugin:ExternalServices:Routing")

_ctx: Optional[object] = None


def set_context(ctx: object) -> None:
    global _ctx
    _ctx = ctx


def register_all(services: Iterable[ExternalService]) -> None:
    """Inject sidebar nav for every enabled service (called at startup)."""
    for svc in services:
        register_service(svc)


def register_service(svc: ExternalService) -> None:
    """Inject a single service's sidebar entry (idempotent)."""
    if svc.enabled and svc.show_in_nav:
        _inject_nav_entry(svc)


def refresh_service(svc: ExternalService) -> None:
    """Re-sync a service's sidebar entry after a create/update.

    Shared by the REST API and the settings form so there is exactly one code
    path for the operation. The page route is global and slug-resolved, so only
    the nav entry needs reconciling here.
    """
    remove_service(svc.slug)
    register_service(svc)


def remove_service(slug: str) -> None:
    """Remove a service's sidebar nav entry."""
    virtual_id = f"external.service.{slug}"
    try:
        from core.api import module_manager

        if virtual_id in module_manager.registry:
            del module_manager.registry[virtual_id]
            log.info(f"NAV: Removed sidebar entry for '{slug}'.")
    except Exception as exc:
        log.warning(f"NAV: Could not remove entry for '{slug}': {exc}")


def _inject_nav_entry(svc: ExternalService) -> None:
    """Add a virtual manifest entry to module_manager so the sidebar shows this service."""
    try:
        from core.api import ModuleManifest, ModulePermissions, module_manager

        virtual_id = f"external.service.{svc.slug}"
        if virtual_id in module_manager.registry:
            return

        virtual_manifest = ModuleManifest(
            id=virtual_id,
            name=svc.name,
            icon=svc.icon or "open_in_browser",
            type="PLUGIN",
            ui_route=f"/external/{svc.slug}",
            version="1.0.0",
            description=svc.description or f"External service: {svc.name}",
            permissions=ModulePermissions(),
        )
        module_manager.registry[virtual_id] = {
            "manifest": virtual_manifest,
            "module": None,
            "context": _ctx,
            "status": "active",
        }
        log.info(f"NAV: Injected sidebar entry for '{svc.slug}'.")
    except Exception as exc:
        log.warning(f"NAV: Could not inject sidebar entry for '{svc.slug}': {exc}")
