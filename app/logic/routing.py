"""
routing.py — sidebar entries for ExternalService rows (core API ≥ 1.9).

Every enabled service with ``show_in_nav`` becomes one navigation entry that
this plugin publishes through ``ctx.register_nav_entries()``. The React shell
lists the entries under *Services* and opens them embedded (``open_mode``
``iframe`` → ``/ext/<plugin>/<slug>``) or in a new tab; the NiceGUI engine
keeps serving its own slug-resolved page at ``/external/{slug}`` (see
``app/ui/nicegui/pages.py``), which resolves the service at request time, so
enable/disable/edit/delete take effect immediately without a process restart.

This module is the single orchestration point used by the REST API, the NiceGUI
settings form and the ``external_services:register`` bus topic.

Cluster mode: nav entries are per process. Every local change is announced as
``external_services:changed`` with ``cluster=True``; peers receive the relayed
copy (``payload["_origin"]`` set) and call :func:`resync` with the enabled
services from the shared database.

History: up to 1.2.0 this module injected virtual manifests into the module
registry through a ``core.api.module_manager`` export that never existed — the
entries never appeared, and had they, they would have polluted the cluster's
plugin fingerprint. 1.3.0 uses the sanctioned API instead (core ≥ 1.7).
"""

import asyncio
import functools
import logging
from typing import Dict, Iterable, Optional

from ..model.models import ExternalService

log = logging.getLogger("Plugin:ExternalServices:Routing")

CHANGED_TOPIC = "external_services:changed"
NAV_GROUP = "Services"
_DEFAULT_ICON = "open_in_browser"

_ctx: Optional[object] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
# slug → nav entry currently published by this process.
_entries: Dict[str, dict] = {}
_api_warned = False


def set_context(ctx: object) -> None:
    global _ctx, _loop
    _ctx = ctx
    # setup() runs on the core loop; remember it so announce() can hop back
    # onto it when a caller runs in a worker thread.
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None
    _entries.clear()


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


def nav_entry(svc: ExternalService) -> dict:
    """The sidebar entry for one service (``ctx.register_nav_entries`` shape)."""
    return {
        "id": svc.slug,
        "label": svc.name,
        "url": svc.url,
        "icon": svc.icon or _DEFAULT_ICON,
        "open_mode": "new_tab" if svc.open_mode == "new_tab" else "iframe",
        "group": NAV_GROUP,
        "description": svc.description or None,
    }


def registered_slugs() -> list:
    """Slugs currently published by this process (diagnostics / tests)."""
    return sorted(_entries)


def _publish() -> None:
    """Hand the complete entry set to the core (replaces the previous set)."""
    global _api_warned
    register = getattr(_ctx, "register_nav_entries", None)
    if not callable(register):
        if not _api_warned:
            log.warning("NAV: this core has no ctx.register_nav_entries (API < 1.9) — services get no sidebar entries.")
            _api_warned = True
        return
    try:
        register(list(_entries.values()))
    except Exception as exc:
        log.warning(f"NAV: could not publish {len(_entries)} sidebar entr(y/ies): {exc}")


def resync(services: Iterable[ExternalService]) -> None:
    """Rebuild every sidebar entry from ``services`` (the enabled rows).

    Used when a peer instance changed the services: entries of removed or
    disabled services disappear, changed ones are re-published. Never announces.
    """
    _entries.clear()
    for svc in services:
        if svc.enabled and svc.show_in_nav:
            _entries[svc.slug] = nav_entry(svc)
    _publish()
    log.info(f"NAV: {len(_entries)} sidebar entr{'y' if len(_entries) == 1 else 'ies'} published.")


def register_all(services: Iterable[ExternalService]) -> None:
    """Publish sidebar entries for every enabled service (called at startup)."""
    resync(services)


def register_service(svc: ExternalService) -> None:
    """Publish a single service's sidebar entry (idempotent)."""
    if svc.enabled and svc.show_in_nav:
        _entries[svc.slug] = nav_entry(svc)
    else:
        _entries.pop(svc.slug, None)
    _publish()


def refresh_service(svc: ExternalService, *, announce_change: bool = True) -> None:
    """Re-sync a service's sidebar entry after a create/update.

    Shared by the REST API, the settings form and the bus topic so there is
    exactly one code path for the operation. The page route is global and
    slug-resolved, so only the nav entry needs reconciling here.
    """
    register_service(svc)
    if announce_change:
        announce("upsert", svc.slug)


def remove_service(slug: str, *, announce_change: bool = True) -> None:
    """Remove a service's sidebar entry (announced to peers by default)."""
    if _entries.pop(slug, None) is not None:
        _publish()
        log.info(f"NAV: Removed sidebar entry for '{slug}'.")
    if announce_change:
        announce("delete", slug)
