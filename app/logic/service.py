"""
service.py — CRUD manager for ExternalService records.
"""

import logging
import re
from typing import List, Optional
from urllib.parse import urlparse

from contextlib import nullcontext

from core.api import db_instance

from ..model.models import ExternalService

log = logging.getLogger("Plugin:ExternalServices")

# Only these URL schemes may be persisted/embedded. This blocks dangerous
# schemes such as ``javascript:`` (which would execute when handed to
# ``window.open``) and is the single choke point every write path goes through.
_ALLOWED_URL_SCHEMES = ("http", "https")

_TABLE = "external_services"
# Columns added after the initial release: (name, DDL definition).
_MIGRATIONS = (("open_mode", "VARCHAR(20) NOT NULL DEFAULT 'iframe'"),)

# A lost bootstrap race on MariaDB: 1050 table exists / 1060 duplicate column.
_DDL_RACE_CODES = ("1050", "1060")
_DDL_RACE_TEXT = ("already exists", "duplicate column")


def _is_ddl_race(exc: Exception) -> bool:
    msg = str(getattr(exc, "orig", exc))
    return any(c in msg for c in _DDL_RACE_CODES) or any(t in msg.lower() for t in _DDL_RACE_TEXT)


def _is_mariadb(engine) -> bool:
    dialect = engine.dialect
    return dialect.name == "mariadb" or bool(getattr(dialect, "is_mariadb", False))


def _bootstrap_lock():
    """``db_instance.advisory_lock("lyndrix_bootstrap")`` on cores that have it."""
    lock = getattr(db_instance, "advisory_lock", None)
    return lock("lyndrix_bootstrap") if callable(lock) else nullcontext()


def _slugify(text: str) -> str:
    """Convert arbitrary text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9-]", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "service"


def validate_url(url: str) -> str:
    """Normalise and validate a service URL, raising ValueError if unsafe.

    Restricts the scheme to http/https and requires a host, so every write
    path (REST API, event bus, NiceGUI form) rejects ``javascript:`` and
    other non-web schemes before they can be rendered.
    """
    candidate = (url or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES or not parsed.netloc:
        raise ValueError(
            f"Invalid service URL (must be http(s):// with a host): {candidate!r}"
        )
    if parsed.username or parsed.password:
        raise ValueError(
            f"Invalid service URL (must not embed userinfo credentials): {candidate!r}"
        )
    return candidate


class ExternalServiceManager:

    def ensure_table(self) -> None:
        """Idempotently create the external_services table and apply column migrations.

        Cluster-safe: serialized across booting instances by the core's
        ``lyndrix_bootstrap`` advisory lock (when the core provides it), only
        touches this plugin's own table (``checkfirst``), uses ``ADD COLUMN IF
        NOT EXISTS`` on MariaDB, and treats a lost race (1050 table exists /
        1060 duplicate column) as "a peer did it". Blocking — call it via
        ``asyncio.to_thread``. Never call it from ``health()``.
        """
        engine = db_instance.engine
        with _bootstrap_lock():
            try:
                ExternalService.__table__.create(bind=engine, checkfirst=True)
            except Exception as exc:
                if not _is_ddl_race(exc):
                    raise
                log.info(f"BOOTSTRAP: table created by a peer ({exc!s:.120})")
            self._migrate_schema(engine)

    def _migrate_schema(self, engine) -> None:
        """Add new columns to an existing external_services table without dropping it."""
        import sqlalchemy

        existing = {c["name"] for c in sqlalchemy.inspect(engine).get_columns(_TABLE)}
        if_not_exists = "IF NOT EXISTS " if _is_mariadb(engine) else ""
        # NOTE: every identifier below is a hardcoded constant. The f-string DDL
        # is only safe because none of these values is ever user-derived — never
        # interpolate request/payload data into this statement.
        for column, col_def in _MIGRATIONS:
            if column in existing:
                continue
            try:
                with engine.begin() as conn:
                    conn.execute(
                        sqlalchemy.text(
                            f"ALTER TABLE `{_TABLE}` ADD COLUMN {if_not_exists}`{column}` {col_def}"
                        )
                    )
                log.info(f"MIGRATE: Added column `{_TABLE}.{column}`.")
            except Exception as exc:
                if _is_ddl_race(exc):
                    continue  # a peer added it between inspect and ALTER
                log.warning(f"MIGRATE: Could not add `{_TABLE}.{column}`: {exc}")

    def count(self) -> tuple[int, int]:
        """``(total, enabled)`` in one ``COUNT`` query — cheap enough for health()."""
        from sqlalchemy import case, func

        with db_instance.SessionLocal() as s:
            total, enabled = s.query(
                func.count(ExternalService.id),
                func.coalesce(
                    func.sum(case((ExternalService.enabled.is_(True), 1), else_=0)), 0
                ),
            ).one()
            return int(total or 0), int(enabled or 0)

    def get_all(self) -> List[ExternalService]:
        with db_instance.SessionLocal() as s:
            rows = s.query(ExternalService).order_by(ExternalService.name).all()
            s.expunge_all()
            return rows

    def get_enabled(self) -> List[ExternalService]:
        with db_instance.SessionLocal() as s:
            rows = (
                s.query(ExternalService)
                .filter(ExternalService.enabled.is_(True))
                .order_by(ExternalService.name)
                .all()
            )
            s.expunge_all()
            return rows

    def get_by_id(self, service_id: int) -> Optional[ExternalService]:
        with db_instance.SessionLocal() as s:
            row = (
                s.query(ExternalService)
                .filter(ExternalService.id == service_id)
                .first()
            )
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
        url = validate_url(url)
        with db_instance.SessionLocal() as s:
            existing = (
                s.query(ExternalService).filter(ExternalService.slug == slug).first()
            )
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
            log.warning(
                "external_services:register received non-dict payload, ignoring."
            )
            return None

        raw_slug = payload.get("route") or payload.get("service", "service")
        slug = _slugify(str(raw_slug))

        # The event-bus path is lenient: a malformed/empty URL is logged and
        # skipped rather than raised, so one bad payload can't crash the bus.
        try:
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
        except ValueError as exc:
            log.warning(f"external_services:register ignored invalid payload: {exc}")
            return None

    def update(self, service_id: int, **kwargs) -> bool:
        # Re-validate the URL on partial updates so the same guard applies as on
        # create — the PUT route does not go through ``upsert``.
        if kwargs.get("url") is not None:
            kwargs["url"] = validate_url(kwargs["url"])
        with db_instance.SessionLocal() as s:
            svc = (
                s.query(ExternalService)
                .filter(ExternalService.id == service_id)
                .first()
            )
            if not svc:
                return False
            for key, value in kwargs.items():
                if hasattr(svc, key) and value is not None:
                    setattr(svc, key, value)
            s.commit()
            return True

    def delete(self, service_id: int) -> bool:
        with db_instance.SessionLocal() as s:
            svc = (
                s.query(ExternalService)
                .filter(ExternalService.id == service_id)
                .first()
            )
            if not svc:
                return False
            s.delete(svc)
            s.commit()
            log.info(f"DELETE: Removed external service id={service_id}.")
            return True


ext_service_manager = ExternalServiceManager()
