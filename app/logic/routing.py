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

Besides the per-service entries the plugin can publish one extra entry, *Alle
Dienste*, that opens the React overview page in-shell (``open_mode: "route"``,
core API ≥ 1.10 — older cores skip it with a warning). It is switched on by the
``show_overview_in_nav`` plugin setting (see :func:`read_overview_setting`),
which every instance re-reads on ``plugin:settings_changed``.

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
from .service import url_problem

log = logging.getLogger("Plugin:ExternalServices:Routing")

CHANGED_TOPIC = "external_services:changed"
NAV_GROUP = "Services"
_DEFAULT_ICON = "open_in_browser"

# Plugin setting (manifest ``settings_schema``) that adds the "Alle Dienste"
# sidebar entry; stored by the core in Vault, read via ``ctx.get_setting``.
OVERVIEW_SETTING_KEY = "show_overview_in_nav"
OVERVIEW_ENTRY_ID = "all-services"
# In-shell path of the React overview page: ``/apps/<plugin id with "." → "-">``
# is the shell's convention for plugin React routes.
OVERVIEW_ROUTE = "/apps/lyndrix-plugin-external_services/external/overview"

_ctx: Optional[object] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
# slug → nav entry currently published by this process.
_entries: Dict[str, dict] = {}
# Whether the extra "Alle Dienste" entry is published (plugin setting).
_overview_enabled = False
_api_warned = False
# slug → URL already reported as invalid, so a legacy row is logged once and
# not on every resync.
_invalid_reported: Dict[str, str] = {}


def set_context(ctx: object) -> None:
    global _ctx, _loop, _overview_enabled
    _ctx = ctx
    # setup() runs on the core loop; remember it so announce() can hop back
    # onto it when a caller runs in a worker thread.
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = None
    _entries.clear()
    _invalid_reported.clear()
    _overview_enabled = False  # re-read from the plugin settings at bootstrap


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


def is_publishable(svc: ExternalService) -> bool:
    """Whether ``svc`` may get a sidebar entry: enabled, listed, and a valid URL.

    The URL is validated again here — at registration time, not only on write —
    because the table can hold rows that predate the write-side validation
    (audit ES-02). An invalid row stays in the DB and is flagged in the admin
    list; it is just never published.
    """
    if not (svc.enabled and svc.show_in_nav):
        return False
    problem = url_problem(svc.url)
    if problem is None:
        _invalid_reported.pop(svc.slug, None)
        return True
    if _invalid_reported.get(svc.slug) != svc.url:
        _invalid_reported[svc.slug] = svc.url
        log.warning(f"NAV: service '{svc.slug}' is not published — {problem}")
    return False


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


def overview_entry() -> dict:
    """The optional *Alle Dienste* entry that opens the React overview in-shell."""
    return {
        "id": OVERVIEW_ENTRY_ID,
        "label": "Alle Dienste",
        "url": OVERVIEW_ROUTE,
        "icon": "apps",
        # Core API 1.10: an in-shell path. Older cores reject the mode and skip
        # just this entry (warning) — the per-service entries are unaffected.
        "open_mode": "route",
        "group": NAV_GROUP,
        "order": -1,
    }


def registered_slugs() -> list:
    """Slugs currently published by this process (diagnostics / tests)."""
    return sorted(_entries)


def overview_enabled() -> bool:
    """Whether the *Alle Dienste* entry is currently published."""
    return _overview_enabled


def set_overview_enabled(enabled: bool, *, publish: bool = True) -> None:
    """Switch the *Alle Dienste* entry on/off and republish when it changed.

    ``publish=False`` only records the flag — used at bootstrap right before
    :func:`register_all` publishes the complete set anyway. Never announces to
    peers: the setting lives in Vault and every instance re-reads it on
    ``plugin:settings_changed`` (a bridged core topic).
    """
    global _overview_enabled
    enabled = bool(enabled)
    if enabled == _overview_enabled:
        return
    _overview_enabled = enabled
    if publish:
        _publish()
    log.info(f"NAV: 'Alle Dienste' overview entry {'enabled' if enabled else 'disabled'}.")


def _as_bool(value) -> bool:
    """Settings arrive as bool (coerced by the core) or as the string default."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def read_overview_setting(ctx: Optional[object] = None) -> bool:
    """Read ``show_overview_in_nav`` from the plugin settings (blocking: Vault).

    Call it via ``asyncio.to_thread``. Returns ``False`` on cores without
    ``ctx.get_setting``, when nothing was saved yet, or when Vault is unreachable
    — the entry is an opt-in extra and must never break the bootstrap.
    """
    target = ctx if ctx is not None else _ctx
    getter = getattr(target, "get_setting", None)
    if not callable(getter):
        return False
    try:
        return _as_bool(getter(OVERVIEW_SETTING_KEY, False))
    except Exception as exc:
        log.warning(f"NAV: could not read setting '{OVERVIEW_SETTING_KEY}': {exc}")
        return False


def _publish() -> None:
    """Hand the complete entry set to the core (replaces the previous set)."""
    global _api_warned
    register = getattr(_ctx, "register_nav_entries", None)
    if not callable(register):
        if not _api_warned:
            log.warning("NAV: this core has no ctx.register_nav_entries (API < 1.9) — services get no sidebar entries.")
            _api_warned = True
        return
    entries = list(_entries.values())
    if _overview_enabled:
        entries.insert(0, overview_entry())
    try:
        register(entries)
    except Exception as exc:
        log.warning(f"NAV: could not publish {len(entries)} sidebar entr(y/ies): {exc}")


def resync(services: Iterable[ExternalService]) -> None:
    """Rebuild every sidebar entry from ``services`` (the enabled rows).

    Used when a peer instance changed the services: entries of removed or
    disabled services disappear, changed ones are re-published. Never announces.
    """
    _entries.clear()
    for svc in services:
        if is_publishable(svc):
            _entries[svc.slug] = nav_entry(svc)
    _publish()
    log.info(f"NAV: {len(_entries)} sidebar entr{'y' if len(_entries) == 1 else 'ies'} published.")


def register_all(services: Iterable[ExternalService]) -> None:
    """Publish sidebar entries for every enabled service (called at startup)."""
    resync(services)


def register_service(svc: ExternalService) -> None:
    """Publish a single service's sidebar entry (idempotent)."""
    if is_publishable(svc):
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
