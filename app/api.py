"""
api.py — FastAPI REST endpoints for External Services CRUD.

The router is mounted by core via ``ctx.register_routes()`` under
``/api/plugins/lyndrix.plugin.external_services/``. The router registry enforces
authentication on every route automatically; we additionally require
``api:read`` on reads and ``api:write`` on every mutation, so neither an
anonymous nor a merely-authenticated caller can create/edit/delete embedded
services (these register live NiceGUI pages + sidebar entries).

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
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from core.api import require_permission

from .logic import routing
from .logic.service import ext_service_manager, validate_url
from .model.models import ExternalService

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
        "type": svc.service_type,
        "open_mode": getattr(svc, "open_mode", "iframe") or "iframe",
        "show_in_nav": svc.show_in_nav,
        "enabled": svc.enabled,
        "route": f"/external/{svc.slug}",
    }


class ServiceCreate(BaseModel):
    """Matches the payload format the IAC orchestrator (and others) send."""

    service: str
    name: str
    icon: str = "open_in_browser"
    url: str
    type: str = "iframe"
    route: Optional[str] = None
    open_mode: str = "iframe"
    show_in_nav: bool = True
    description: str = ""
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return validate_url(v)


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    url: Optional[str] = None
    type: Optional[str] = None
    open_mode: Optional[str] = None
    show_in_nav: Optional[bool] = None
    enabled: Optional[bool] = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: Optional[str]) -> Optional[str]:
        return validate_url(v) if v is not None else v


def build_router() -> APIRouter:
    router = APIRouter(tags=["External Services"])

    @router.get("/", dependencies=[Depends(require_permission("api:read"))])
    def list_services():
        return [_to_dict(s) for s in ext_service_manager.get_all()]

    @router.post(
        "/",
        status_code=201,
        dependencies=[Depends(require_permission("api:write"))],
    )
    def create_service(data: ServiceCreate):
        slug = _slugify(data.route or data.service)
        try:
            svc = ext_service_manager.upsert(
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
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        routing.refresh_service(svc)
        return _to_dict(svc)

    @router.put(
        "/{service_id}",
        dependencies=[Depends(require_permission("api:write"))],
    )
    def update_service(service_id: int, data: ServiceUpdate):
        updates = {k: v for k, v in data.dict().items() if v is not None}
        try:
            updated = ext_service_manager.update(service_id, **updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail="Service not found")

        svc = ext_service_manager.get_by_id(service_id)
        if svc:
            routing.refresh_service(svc)
        return {"ok": True}

    @router.delete(
        "/{service_id}",
        dependencies=[Depends(require_permission("api:write"))],
    )
    def delete_service(service_id: int):
        svc = ext_service_manager.get_by_id(service_id)
        if not svc:
            raise HTTPException(status_code=404, detail="Service not found")
        slug = svc.slug
        if not ext_service_manager.delete(service_id):
            raise HTTPException(status_code=404, detail="Service not found")
        routing.remove_service(slug)
        return {"ok": True}

    @router.post(
        "/reload",
        dependencies=[Depends(require_permission("api:write"))],
    )
    def reload_services():
        services = ext_service_manager.get_enabled()
        routing.register_all(services)
        return {"registered": len(services)}

    return router
