"""
service.py — CRUD manager for ExternalService records.
"""
import logging
import re
from typing import List, Optional

from core.api import Base, db_instance

from app.model.models import ExternalService

log = logging.getLogger("Plugin:ExternalServices")


def _slugify(text: str) -> str:
    """Convert arbitrary text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9-]", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "service"


class ExternalServiceManager:

    def ensure_table(self) -> None:
        """Idempotently create the external_services table and apply any column migrations."""
        Base.metadata.create_all(bind=db_instance.engine)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add new columns to existing external_services table without dropping it."""
        import sqlalchemy
        migrations = [
            ("external_services", "open_mode", "VARCHAR(20) NOT NULL DEFAULT 'iframe'"),
        ]
        with db_instance.engine.connect() as conn:
            for table, column, col_def in migrations:
                try:
                    conn.execute(sqlalchemy.text(
                        f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_def}"
                    ))
                    conn.commit()
                    log.info(f"MIGRATE: Added column `{table}.{column}`.")
                except Exception as e:
                    err = str(e)
                    if "Duplicate column name" in err or "already exists" in err:
                        pass  # already present
                    else:
                        log.warning(f"MIGRATE: Could not add `{table}.{column}`: {e}")

    def get_all(self) -> List[ExternalService]:
        with db_instance.SessionLocal() as s:
            rows = s.query(ExternalService).order_by(ExternalService.name).all()
            s.expunge_all()
            return rows

    def get_enabled(self) -> List[ExternalService]:
        with db_instance.SessionLocal() as s:
            rows = (
                s.query(ExternalService)
                .filter(ExternalService.enabled == True)
                .order_by(ExternalService.name)
                .all()
            )
            s.expunge_all()
            return rows

    def get_by_id(self, service_id: int) -> Optional[ExternalService]:
        with db_instance.SessionLocal() as s:
            row = s.query(ExternalService).filter(ExternalService.id == service_id).first()
            if row:
                s.expunge(row)
            return row

    def get_by_slug(self, slug: str) -> Optional[ExternalService]:
        with db_instance.SessionLocal() as s:
            row = s.query(ExternalService).filter(ExternalService.slug == slug).first()
            if row:
                s.expunge(row)
            return row

    def upsert(
        self,
        slug: str,
        name: str,
        url: str,
        icon: str = "open_in_browser",
        service_type: str = "iframe",
        open_mode: str = "iframe",
        show_in_nav: bool = True,
        description: str = "",
        enabled: bool = True,
    ) -> ExternalService:
        """Create or update a service by slug (idempotent)."""
        slug = _slugify(slug)
        with db_instance.SessionLocal() as s:
            existing = s.query(ExternalService).filter(ExternalService.slug == slug).first()
            if existing:
                existing.name = name
                existing.url = url
                existing.icon = icon
                existing.service_type = service_type
                existing.open_mode = open_mode
                existing.show_in_nav = show_in_nav
                existing.description = description
                existing.enabled = enabled
                s.commit()
                s.refresh(existing)
                s.expunge(existing)
                log.info(f"UPSERT: Updated external service '{slug}'.")
                return existing
            else:
                svc = ExternalService(
                    slug=slug,
                    name=name,
                    url=url,
                    icon=icon,
                    service_type=service_type,
                    open_mode=open_mode,
                    show_in_nav=show_in_nav,
                    description=description,
                    enabled=enabled,
                )
                s.add(svc)
                s.commit()
                s.refresh(svc)
                s.expunge(svc)
                log.info(f"UPSERT: Created external service '{slug}'.")
                return svc

    def register_from_payload(self, payload) -> Optional[ExternalService]:
        if not isinstance(payload, dict):
            log.warning("external_services:register received non-dict payload, ignoring.")
            return None

        raw_slug = payload.get("route") or payload.get("service", "service")
        slug = _slugify(str(raw_slug))

        return self.upsert(
            slug=slug,
            name=payload.get("name", slug),
            url=payload.get("url", ""),
            icon=payload.get("icon", "open_in_browser"),
            service_type=payload.get("type", "iframe"),
            open_mode=payload.get("open_mode", "iframe"),
            show_in_nav=bool(payload.get("show_in_nav", True)),
            description=payload.get("description", ""),
            enabled=bool(payload.get("enabled", True)),
        )

    def update(self, service_id: int, **kwargs) -> bool:
        with db_instance.SessionLocal() as s:
            svc = s.query(ExternalService).filter(ExternalService.id == service_id).first()
            if not svc:
                return False
            for key, value in kwargs.items():
                if hasattr(svc, key) and value is not None:
                    setattr(svc, key, value)
            s.commit()
            return True

    def delete(self, service_id: int) -> bool:
        with db_instance.SessionLocal() as s:
            svc = s.query(ExternalService).filter(ExternalService.id == service_id).first()
            if not svc:
                return False
            s.delete(svc)
            s.commit()
            log.info(f"DELETE: Removed external service id={service_id}.")
            return True


ext_service_manager = ExternalServiceManager()
