"""Service + cluster readiness (1.2.0) against an in-memory SQLite engine patched
into the core's db_instance: locked/idempotent bootstrap DDL, race tolerance,
COUNT-based health, and the cluster-announced sidebar sync."""
import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ext_plugin.app.logic import routing
from ext_plugin.app.logic import service as service_mod
from ext_plugin.app.model.models import ExternalService


class _FakeCtx:
    """Records cluster announcements and the nav entry sets handed to the core."""

    def __init__(self):
        self.events = []
        self.nav = []          # every register_nav_entries() call (list of entries)

    def emit(self, topic, payload=None, cluster=False):
        self.events.append((topic, payload, cluster))

    def register_nav_entries(self, entries):
        self.nav.append([dict(e) for e in entries])
        return len(entries)

    @property
    def published(self):
        """Slugs of the entry set currently published."""
        return sorted(e["id"] for e in (self.nav[-1] if self.nav else []))


class _FakeCtxNoNav:
    """A core older than API 1.9: no register_nav_entries at all."""

    def emit(self, topic, payload=None, cluster=False):
        pass


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture
def db(monkeypatch):
    engine = _engine()
    taken = []

    @contextmanager
    def _lock(name):
        taken.append(name)
        yield True

    dbi = service_mod.db_instance
    monkeypatch.setattr(dbi, "engine", engine, raising=False)
    monkeypatch.setattr(dbi, "SessionLocal", sessionmaker(bind=engine), raising=False)
    monkeypatch.setattr(dbi, "is_connected", True, raising=False)
    monkeypatch.setattr(dbi, "advisory_lock", _lock, raising=False)
    return engine, taken


@pytest.fixture
def mgr(db):
    m = service_mod.ExternalServiceManager()
    m.ensure_table()
    return m


@pytest.fixture
def registry(monkeypatch):
    """A routing module bound to a fake ctx (core API >= 1.9 nav surface)."""
    ctx = _FakeCtx()
    monkeypatch.setattr(routing, "_ctx", ctx)
    monkeypatch.setattr(routing, "_loop", None)
    monkeypatch.setattr(routing, "_entries", {})
    return ctx.nav, ctx


# --- smoke -----------------------------------------------------------------------

def test_empty_payload_does_not_raise(mgr):
    assert mgr.register_from_payload({}) is None  # no URL → logged + skipped


# --- bootstrap DDL ---------------------------------------------------------------

def test_ensure_table_locked_and_idempotent(db):
    engine, taken = db
    m = service_mod.ExternalServiceManager()
    m.ensure_table()
    m.ensure_table()
    assert taken == ["lyndrix_bootstrap", "lyndrix_bootstrap"]
    tables = inspect(engine).get_table_names()
    assert tables == ["external_services"]  # never touches other core tables


def test_legacy_table_gets_open_mode(db):
    engine, _ = db
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE external_services (id INTEGER PRIMARY KEY, slug VARCHAR(100) NOT NULL UNIQUE, "
            "name VARCHAR(100) NOT NULL, description VARCHAR(500), icon VARCHAR(100), url VARCHAR(1000) NOT NULL, "
            "service_type VARCHAR(50), show_in_nav BOOLEAN, enabled BOOLEAN)"
        ))
    service_mod.ExternalServiceManager().ensure_table()
    cols = {c["name"] for c in inspect(engine).get_columns("external_services")}
    assert "open_mode" in cols


def test_lost_create_race_is_tolerated(db, monkeypatch):
    engine, _ = db
    ExternalService.__table__.create(bind=engine)  # the peer won

    def _racy(*a, **kw):
        raise RuntimeError("(1050, \"Table 'external_services' already exists\")")

    monkeypatch.setattr(ExternalService.__table__, "create", _racy)
    service_mod.ExternalServiceManager().ensure_table()  # must not raise


def test_unexpected_create_error_propagates(db, monkeypatch):
    def _broken(*a, **kw):
        raise RuntimeError("(1142, 'CREATE command denied')")

    monkeypatch.setattr(ExternalService.__table__, "create", _broken)
    with pytest.raises(RuntimeError):
        service_mod.ExternalServiceManager().ensure_table()


def test_ddl_race_detection():
    assert service_mod._is_ddl_race(RuntimeError("(1060, \"Duplicate column name 'open_mode'\")"))
    assert service_mod._is_ddl_race(RuntimeError("(1050, \"Table 'x' already exists\")"))
    assert not service_mod._is_ddl_race(RuntimeError("(1146, \"Table 'x' doesn't exist\")"))


# --- count / health --------------------------------------------------------------

def test_count(mgr):
    assert mgr.count() == (0, 0)
    mgr.upsert(slug="ha", name="HA", url="https://ha.example.com")
    mgr.upsert(slug="graf", name="Grafana", url="https://grafana.example.com", enabled=False)
    assert mgr.count() == (2, 1)


def test_health_runs_no_ddl(mgr, monkeypatch):
    from ext_plugin import entrypoint

    def _no_ddl():
        raise AssertionError("health() must not run DDL")

    monkeypatch.setattr(entrypoint.ext_service_manager, "ensure_table", _no_ddl)
    monkeypatch.setitem(entrypoint.plugin_state, "ready", True)
    mgr.upsert(slug="ha", name="HA", url="https://ha.example.com")
    status = asyncio.run(entrypoint.health(None))
    assert status.status == "ok"
    assert status.details["services_total"] == 1 and status.details["services_enabled"] == 1


def test_manifest_declares_changed_topic_both_ways():
    from ext_plugin import entrypoint

    perms = entrypoint.manifest.permissions
    assert "external_services:changed" in perms.emit
    assert "external_services:changed" in perms.subscribe


# --- sidebar sync across instances -----------------------------------------------

def test_refresh_and_remove_announce_to_cluster(mgr, registry):
    _nav, ctx = registry
    svc = mgr.upsert(slug="ha", name="HA", url="https://ha.example.com", open_mode="new_tab")
    routing.refresh_service(svc)
    assert ctx.published == ["ha"]
    entry = ctx.nav[-1][0]
    assert entry["url"] == "https://ha.example.com" and entry["open_mode"] == "new_tab"
    assert entry["group"] == "Services" and entry["label"] == "HA"
    assert ctx.events[-1] == ("external_services:changed", {"action": "upsert", "slug": "ha"}, True)

    routing.remove_service("ha")
    assert ctx.published == []
    assert ctx.events[-1] == ("external_services:changed", {"action": "delete", "slug": "ha"}, True)
    assert len(ctx.events) == 2  # one announcement per operation


def test_hidden_or_disabled_services_get_no_entry(mgr, registry):
    _nav, ctx = registry
    hidden = mgr.upsert(slug="hid", name="Hidden", url="https://h.example.com", show_in_nav=False)
    routing.refresh_service(hidden, announce_change=False)
    assert ctx.published == []
    shown = mgr.upsert(slug="vis", name="Visible", url="https://v.example.com")
    routing.refresh_service(shown, announce_change=False)
    assert ctx.published == ["vis"]
    mgr.update(shown.id, enabled=False)
    routing.refresh_service(mgr.get_by_id(shown.id), announce_change=False)
    assert ctx.published == []
    assert ctx.events == []


def test_old_core_without_nav_api_is_tolerated(mgr, registry, monkeypatch):
    _nav, ctx = registry
    monkeypatch.setattr(routing, "_ctx", _FakeCtxNoNav(), raising=True)
    svc = mgr.upsert(slug="ha", name="HA", url="https://ha.example.com")
    routing.refresh_service(svc, announce_change=False)   # must not raise
    assert routing.registered_slugs() == ["ha"]


def test_resync_on_peer_change(mgr, registry):
    _nav, ctx = registry
    a = mgr.upsert(slug="ha", name="HA", url="https://ha.example.com")
    b = mgr.upsert(slug="graf", name="Grafana", url="https://grafana.example.com")
    routing.register_all([a, b])
    assert ctx.published == ["graf", "ha"]

    # a peer renamed "ha", disabled "graf" and added "nb"
    mgr.update(a.id, name="Home Assistant")
    mgr.update(b.id, enabled=False)
    mgr.upsert(slug="nb", name="NetBox", url="https://netbox.example.com")
    routing.resync(mgr.get_enabled())

    assert ctx.published == ["ha", "nb"]
    assert {e["id"]: e["label"] for e in ctx.nav[-1]}["ha"] == "Home Assistant"
    assert ctx.events == []  # applying a peer change never re-announces
