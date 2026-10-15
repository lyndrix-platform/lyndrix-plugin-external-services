"""
routing.py — Sidebar-nav injection for ExternalService entries.

The page itself is served by a single parameterised NiceGUI route at
``/external/{slug}`` (see ``app/ui/nicegui/pages.py``) which resolves the
service at request time, so enable/disable/edit/delete take effect immediately
without a process restart.

This module only manages the *navigation* side: it injects/removes a virtual
manifest entry in ``module_manager.registry`` so each service shows up in the
main sidebar under "Services". It is the single orchestration point used by the
REST API, the NiceGUI settings form and the ``external_services:register`` bus
topic.

Cluster mode: the registry is per process. Every local change is announced as
``external_services:changed`` with ``cluster=True``; peers receive the relayed
copy (``payload["_origin"]`` set) and call :func:`resync` with the enabled
services from the shared database.
"""

import asyncio
import functools
import logging
from typing import Iterable, Optional

from ..model.models import ExternalService

log = logging.getLogger("Plugin:ExternalServices:Routing")

CHANGED_TOPIC = "external_services:changed"
_VIRTUAL_PREFIX = "external.service."

_ctx: Optional[object] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def set_context(ctx: object) -> None:
    global _ctx, _loop
    _ctx = ctx
    # setup() runs on the core loop; remember it so announce() can hop back
    # onto it when a caller runs in a worker thread.
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None


def announce(action: str, slug: Optional[str] = None) -> None:
    """Tell every other core instance to re-sync its sidebar entries."""
    if _ctx is None:
        return
    payload = {"action": action, "slug": slug}
    emit = functools.partial(_ctx.emit, cluster=True)  # type: ignore[attr-defined]
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    try:
        if running is None and _loop is not None and _loop.is_running():
            _loop.call_soon_threadsafe(emit, CHANGED_TOPIC, payload)
        else:
            emit(CHANGED_TOPIC, payload)
    except Exception as exc:  # a lost announcement must never fail the write
        log.warning(f"NAV: could not announce '{action}' for '{slug}': {exc}")


def resync(services: Iterable[ExternalService]) -> None:
    """Rebuild every sidebar entry from ``services`` (the enabled rows).

    Used when a peer instance changed the services: entries of removed or
    disabled services disappear, changed ones are re-injected. Never announces.
    """
    wanted = list(services)
    try:
        from core.api import module_manager

        stale = [k for k in list(module_manager.registry) if k.startswith(_VIRTUAL_PREFIX)]
    except Exception as exc:
        log.warning(f"NAV: resync could not read the registry: {exc}")
        stale = []
    for virtual_id in stale:
        remove_service(virtual_id[len(_VIRTUAL_PREFIX):], announce_change=False)
    register_all(wanted)


def register_all(services: Iterable[ExternalService]) -> None:
    """Inject sidebar nav for every enabled service (called at startup)."""
    for svc in services:
        register_service(svc)


def register_service(svc: ExternalService) -> None:
    """Inject a single service's sidebar entry (idempotent)."""
    if svc.enabled and svc.show_in_nav:
        _inject_nav_entry(svc)


def refresh_service(svc: ExternalService, *, announce_change: bool = True) -> None:
    """Re-sync a service's sidebar entry after a create/update.

    Shared by the REST API, the settings form and the bus topic so there is
    exactly one code path for the operation. The page route is global and
    slug-resolved, so only the nav entry needs reconciling here.
    """
    remove_service(svc.slug, announce_change=False)
    register_service(svc)
    if announce_change:
        announce("upsert", svc.slug)


def remove_service(slug: str, *, announce_change: bool = True) -> None:
    """Remove a service's sidebar nav entry (announced to peers by default)."""
    virtual_id = f"{_VIRTUAL_PREFIX}{slug}"
    try:
        from core.api import module_manager

        if virtual_id in module_manager.registry:
            del module_manager.registry[virtual_id]
            log.info(f"NAV: Removed sidebar entry for '{slug}'.")
    except Exception as exc:
        log.warning(f"NAV: Could not remove entry for '{slug}': {exc}")
    if announce_change:
        announce("delete", slug)


def _inject_nav_entry(svc: ExternalService) -> None:
    """Add a virtual manifest entry to module_manager so the sidebar shows this service."""
    try:
        from core.api import ModuleManifest, ModulePermissions, module_manager

        virtual_id = f"{_VIRTUAL_PREFIX}{svc.slug}"
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
