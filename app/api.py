"""
api.py — FastAPI REST endpoints for External Services CRUD.

The router is mounted by core via ``ctx.register_routes()`` under
``/api/plugins/lyndrix.plugin.external_services/``. The router registry enforces
authentication on every route automatically; we additionally require
``api:read`` on reads and the dedicated ``external_services:manage`` permission
on every mutation of a service record. The core grants ``…:api:write`` to every
INT_USER (and lets the global ``api:write`` satisfy it), so it cannot protect
entries that *all* users open as trusted sidebar links — ``manage`` has no such
fallback and is mapped to the plugin's admin role only (audit ES-01).

Endpoints (relative to the mount prefix above):
  GET    /            — list all
  POST   /            — create / upsert by slug
  PUT    /{id}        — update fields
  DELETE /{id}        — remove
  POST   /reload      — re-scan DB and refresh nav

Note: the public path moved from the old unauthenticated /api/external-services/
to the core-managed plugin namespace above and now requires authentication.
External callers (e.g. the IAC orchestrator) must update their target URL + send
an API key, or use the in-process ``external_services:register`` event instead.

Mutating handlers are ``async``: the blocking DB work runs in
``asyncio.to_thread`` while the (per-process) sidebar registry is only touched
on the event loop. Every mutation is announced to peer instances
(``external_services:changed``, cluster-bridged) by ``routing``.
"""

import asyncio
import logging
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from core.api import require_permission

from .logic import routing
from .logic.service import (
    FIELD_LIMITS,
    SlugConflict,
    ext_service_manager,
    origin_key,
    url_problem,
    validate_slug,
    validate_url,
)
from .model.models import ExternalService

# Plugin-scoped permission ids. Gating routes on the fully-qualified
# plugin:<id>:api:* (rather than bare api:read/api:write) makes the manifest's
# scoped viewer/operator roles actually unlock routes, while global api:read/
# api:write holders keep working via the core's one-directional fallback.
PLUGIN_ID = "lyndrix.plugin.external_services"
PERM_READ = f"plugin:{PLUGIN_ID}:api:read"
PERM_WRITE = f"plugin:{PLUGIN_ID}:api:write"
# Creating/repointing/deleting a service changes where a sidebar entry that every
# user trusts leads to. The id must NOT end in ``:api:read``/``:api:write``:
# only then the core's baseline grants and the global api:write fallback do not
# satisfy it. Declared in the manifest (``custom_permissions``).
PERM_MANAGE = f"plugin:{PLUGIN_ID}:external_services:manage"

log = logging.getLogger("Plugin:ExternalServices:API")


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9-]", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "service"


def _to_dict(svc: ExternalService) -> dict:
    return {
        "id": svc.id,
        "slug": svc.slug,
        "name": svc.name,
        "description": svc.description,
        "icon": svc.icon,
        "url": svc.url,
        # False for a legacy row whose stored URL fails today's validation: it
        # is not published and clients must not render it as a link (ES-02).
        "url_valid": url_problem(svc.url) is None,
        "type": svc.service_type,
        "open_mode": getattr(svc, "open_mode", "iframe") or "iframe",
        "show_in_nav": svc.show_in_nav,
        "enabled": svc.enabled,
        "route": f"/external/{svc.slug}",
    }


class ServiceCreate(BaseModel):
    """Matches the payload format the IAC orchestrator (and others) send."""

    # Limits mirror the column widths (FIELD_LIMITS): an over-long value is a
    # 422 with the field name instead of a database error (ES-03).
    service: str = Field(min_length=1, max_length=FIELD_LIMITS["slug"])
    name: str = Field(min_length=1, max_length=FIELD_LIMITS["name"])
    icon: str = Field(default="open_in_browser", max_length=FIELD_LIMITS["icon"])
    url: str = Field(max_length=FIELD_LIMITS["url"])
    type: str = Field(default="iframe", max_length=FIELD_LIMITS["service_type"])
    route: Optional[str] = Field(default=None, max_length=FIELD_LIMITS["slug"])
    open_mode: Literal["iframe", "new_tab"] = "iframe"
    show_in_nav: bool = True
    description: str = Field(default="", max_length=FIELD_LIMITS["description"])
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return validate_url(v)


class ServiceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=FIELD_LIMITS["name"])
    description: Optional[str] = Field(default=None, max_length=FIELD_LIMITS["description"])
    icon: Optional[str] = Field(default=None, max_length=FIELD_LIMITS["icon"])
    url: Optional[str] = Field(default=None, max_length=FIELD_LIMITS["url"])
    type: Optional[str] = Field(default=None, max_length=FIELD_LIMITS["service_type"])
    open_mode: Optional[Literal["iframe", "new_tab"]] = None
    show_in_nav: Optional[bool] = None
    enabled: Optional[bool] = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: Optional[str]) -> Optional[str]:
        return validate_url(v) if v is not None else v


def _own_origins(request: Request) -> set:
    """Host[:port] keys under which the caller reached Lyndrix itself.

    A service URL on the Lyndrix origin would be framed same-origin by the shell
    (full access to the session token), so the write routes refuse it. The core
    has no configured public URL; the browser's ``Origin`` and the (forwarded)
    ``Host`` of this very request are the best available evidence.
    """
    headers = request.headers
    proto = (headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    candidates = [headers.get("origin") or ""]
    for name in ("x-forwarded-host", "host"):
        for host in (headers.get(name) or "").split(","):
            if host.strip():
                candidates.append(f"{proto}://{host.strip()}")
    return {key for key in (origin_key(c) for c in candidates) if key}


def _reject_own_origin(url: Optional[str], request: Request) -> None:
    if url is not None and origin_key(url) in _own_origins(request):
        raise HTTPException(
            status_code=422,
            detail="The service URL must not point at Lyndrix itself (same origin as this request).",
        )


def build_router() -> APIRouter:
    router = APIRouter(tags=["External Services"])

    @router.get("/", dependencies=[Depends(require_permission(PERM_READ))])
    def list_services():
        return [_to_dict(s) for s in ext_service_manager.get_all()]

    @router.post(
        "/",
        status_code=201,
        dependencies=[Depends(require_permission(PERM_MANAGE))],
    )
    async def create_service(data: ServiceCreate, request: Request):
        _reject_own_origin(data.url, request)
        try:
            slug = validate_slug(_slugify(data.route or data.service))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            svc = await asyncio.to_thread(
                ext_service_manager.upsert,
                slug=slug,
                name=data.name,
                url=data.url,
                icon=data.icon,
                service_type=data.type,
                open_mode=data.open_mode,
                show_in_nav=data.show_in_nav,
                description=data.description,
                enabled=data.enabled,
            )
        except SlugConflict as exc:
            # Lost the unique-slug race against another instance: a clean,
            # retryable conflict instead of an IntegrityError → 500.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        routing.refresh_service(svc)
        return _to_dict(svc)

    @router.put(
        "/{service_id}",
        dependencies=[Depends(require_permission(PERM_MANAGE))],
    )
    async def update_service(service_id: int, data: ServiceUpdate, request: Request):
        _reject_own_origin(data.url, request)
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if "type" in updates:
            # The API field is "type", the column "service_type" — without the
            # mapping a PUT silently dropped the value.
            updates["service_type"] = updates.pop("type")
        try:
            updated = await asyncio.to_thread(ext_service_manager.update, service_id, **updates)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Service not found")

        svc = await asyncio.to_thread(ext_service_manager.get_by_id, service_id)
        if svc:
            routing.refresh_service(svc)
        return {"ok": True}

    @router.delete(
        "/{service_id}",
        dependencies=[Depends(require_permission(PERM_MANAGE))],
    )
    async def delete_service(service_id: int):
        svc = await asyncio.to_thread(ext_service_manager.get_by_id, service_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Service not found")
        slug = svc.slug
        if not await asyncio.to_thread(ext_service_manager.delete, service_id):
            raise HTTPException(status_code=404, detail="Service not found")
        routing.remove_service(slug)
        return {"ok": True}

    @router.post(
        "/reload",
        dependencies=[Depends(require_permission(PERM_WRITE))],
    )
    async def reload_services():
        services = await asyncio.to_thread(ext_service_manager.get_enabled)
        routing.resync(services)
        routing.announce("reload")
        return {"registered": len(services)}

    return router
