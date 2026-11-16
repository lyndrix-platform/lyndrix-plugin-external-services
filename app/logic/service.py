"""
service.py — CRUD manager for ExternalService records.
"""

import logging
import re
import time
from contextlib import contextmanager
from typing import Callable, List, Optional, TypeVar
from urllib.parse import urlparse

from contextlib import nullcontext

from sqlalchemy.exc import IntegrityError

from core.api import db_instance

from ..model.models import ExternalService

log = logging.getLogger("Plugin:ExternalServices")

# Only these URL schemes may be persisted/embedded. This blocks dangerous
# schemes such as ``javascript:`` (which would execute when handed to
# ``window.open``) and is the single choke point every write path goes through.
_ALLOWED_URL_SCHEMES = ("http", "https")

_TABLE = "external_services"

T = TypeVar("T")

# Column widths of the model. MariaDB (strict mode) answers an over-long value
# with a DataError → HTTP 500; validating up front turns that into a clear 422.
FIELD_LIMITS = {
    "slug": 100,
    "name": 100,
    "description": 500,
    "icon": 100,
    "url": 1000,
    "service_type": 50,
    "open_mode": 20,
}
OPEN_MODES = ("iframe", "new_tab")

# Slugs the plugin publishes itself. A service with one of these ids would
# replace that sidebar entry (the core keeps the last duplicate id) — here the
# "Alle Dienste" overview entry (routing.OVERVIEW_ENTRY_ID).
RESERVED_SLUGS = frozenset({"all-services"})

# MariaDB >= 11.6 (innodb_snapshot_isolation=ON) raises 1020 when a row changed
# since the transaction's first read; 1205 = lock wait timeout, 1213 = deadlock.
_RETRY_CODES = ("1020", "1205", "1213")


class SlugConflict(ValueError):
    """Another writer created the same slug at the same time (unique index)."""


def _is_retryable(exc: Exception) -> bool:
    return any(code in str(getattr(exc, "orig", exc)) for code in _RETRY_CODES)


def retry_write(fn: Callable[[], T], *, attempts: int = 4, pause: float = 0.05) -> T:
    """Run ``fn()`` — one complete short transaction — again on 1020/1205/1213.

    ``fn`` must open its own session per attempt. Blocking (sleeps between
    attempts): only call it from worker threads.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if attempt + 1 < attempts and _is_retryable(exc):
                log.debug(f"DB: retrying write after {exc!s:.120}")
                time.sleep(pause * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")  # pragma: no cover


@contextmanager
def _write_session():
    """A READ COMMITTED session (no-op on SQLite) that rolls back on error.

    READ COMMITTED keeps a write next to a concurrent writer on another instance
    from failing with 1020 more often than necessary; the remaining conflicts
    are retried by :func:`retry_write`.
    """
    session = db_instance.SessionLocal()
    try:
        try:
            bind = session.get_bind()
            if bind is not None and bind.dialect.name in ("mysql", "mariadb"):
                session.connection(execution_options={"isolation_level": "READ COMMITTED"})
        except Exception as exc:  # isolation is an optimisation, never a reason to fail
            log.debug(f"DB: READ COMMITTED not applied: {exc}")
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def validate_fields(**fields) -> None:
    """Raise ``ValueError`` for a value that does not fit the model.

    Shared by every write path (REST, bus topic, NiceGUI form). ``None`` values
    are skipped so partial updates can pass their kwargs straight through.
    """
    for key, value in fields.items():
        limit = FIELD_LIMITS.get(key)
        if value is None or limit is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"Invalid {key}: expected text")
        if len(value) > limit:
            raise ValueError(f"Invalid {key}: at most {limit} characters allowed (got {len(value)})")
    open_mode = fields.get("open_mode")
    if open_mode is not None and open_mode not in OPEN_MODES:
        raise ValueError(f"Invalid open_mode {open_mode!r}: expected one of {', '.join(OPEN_MODES)}")
    name = fields.get("name")
    if name is not None and not name.strip():
        raise ValueError("Invalid name: must not be empty")


def validate_slug(slug: str) -> str:
    """The slug as stored, or ``ValueError`` when it is reserved or too long."""
    if slug in RESERVED_SLUGS:
        raise ValueError(f"The slug {slug!r} is reserved by the plugin itself — choose another one")
    validate_fields(slug=slug)
    return slug
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


def url_problem(url: Optional[str]) -> Optional[str]:
    """Why a *stored* URL must not be rendered or published — ``None`` when fine.

    Rows written before the 0.2.0 fix (anonymous API, no validation) can still
    carry ``javascript:`` or other non-web URLs. They are never rewritten here:
    read paths call this to keep such a row out of the sidebar, out of every
    link/iframe, and flagged in the admin list until an admin corrects it.
    """
    try:
        validate_url(url or "")
    except ValueError as exc:
        return str(exc)
    return None


def origin_key(url: str) -> Optional[str]:
    """``host[:port]`` of an http(s) URL with the default ports folded away.

    The scheme is deliberately ignored: ``http://lyndrix`` usually redirects to
    ``https://lyndrix``, so both count as the same place for the "do not embed
    Lyndrix in itself" check. ``None`` for anything that is not an http(s) URL.
    """
    try:
        parsed = urlparse((url or "").strip())
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES or not host:
        return None
    return host.lower() if port in (None, 80, 443) else f"{host.lower()}:{port}"


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
        """Create or update a service by slug (idempotent).

        Raises ``ValueError`` for invalid input and :class:`SlugConflict` when a
        concurrent writer (another instance) created the same slug between our
        lookup and our insert — the caller decides whether to report (REST: 409)
        or to repeat the call, which then updates the peer's row (bus topic).
        """
        slug = validate_slug(_slugify(slug))
        url = validate_url(url)
        if not isinstance(name, str):
            raise ValueError("Invalid name: expected text")
        validate_fields(
            name=name, url=url, icon=icon, service_type=service_type,
            open_mode=open_mode, description=description,
        )

        def _tx() -> ExternalService:
            try:
                return self._upsert_tx(
                    slug=slug, name=name, url=url, icon=icon, service_type=service_type,
                    open_mode=open_mode, show_in_nav=show_in_nav,
                    description=description, enabled=enabled,
                )
            except IntegrityError as exc:
                raise SlugConflict(
                    f"A service with the slug {slug!r} was created at the same time — retry to update it"
                ) from exc

        return retry_write(_tx)

    def _upsert_tx(
        self, *, slug, name, url, icon, service_type, open_mode, show_in_nav, description, enabled
    ) -> ExternalService:
        with _write_session() as s:
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
        # The bus contract predates the strict field validation: an empty name
        # or an unknown open_mode keeps falling back to a sane value instead of
        # dropping the registration (the REST API answers 422 for those).
        open_mode = payload.get("open_mode", "iframe")
        fields = dict(
            slug=slug,
            name=str(payload.get("name") or slug),
            url=payload.get("url", ""),
            icon=payload.get("icon", "open_in_browser"),
            service_type=payload.get("type", "iframe"),
            open_mode=open_mode if open_mode in OPEN_MODES else "iframe",
            show_in_nav=bool(payload.get("show_in_nav", True)),
            description=payload.get("description", ""),
            enabled=bool(payload.get("enabled", True)),
        )
        try:
            try:
                return self.upsert(**fields)
            except SlugConflict:
                # Two instances handled the same registration: the peer's row
                # exists now, so the second pass is a plain update.
                return self.upsert(**fields)
        except ValueError as exc:
            log.warning(f"external_services:register ignored invalid payload: {exc}")
            return None

    def update(self, service_id: int, **kwargs) -> bool:
        # Re-validate the URL on partial updates so the same guard applies as on
        # create — the PUT route does not go through ``upsert``.
        if kwargs.get("url") is not None:
            kwargs["url"] = validate_url(kwargs["url"])
        validate_fields(**kwargs)

        def _tx() -> bool:
            with _write_session() as s:
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

        return retry_write(_tx)

    def delete(self, service_id: int) -> bool:
        def _tx() -> bool:
            with _write_session() as s:
                svc = (
                    s.query(ExternalService)
                    .filter(ExternalService.id == service_id)
                    .first()
                )
                if not svc:
                    return False
                s.delete(svc)
                s.commit()
                return True

        deleted = retry_write(_tx)
        if deleted:
            log.info(f"DELETE: Removed external service id={service_id}.")
        return deleted


ext_service_manager = ExternalServiceManager()
