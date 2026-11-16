"""Service + cluster readiness (1.2.0) against an in-memory SQLite engine patched
into the core's db_instance: locked/idempotent bootstrap DDL, race tolerance,
COUNT-based health, the cluster-announced sidebar sync, and (1.4.0) the
setting-driven "Alle Dienste" overview entry + React UI manifest/locales."""
import asyncio
import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ext_plugin.app.logic import routing
from ext_plugin.app.logic import service as service_mod
from ext_plugin.app.model.models import ExternalService

_REPO = Path(__file__).resolve().parents[1]


class _FakeCtx:
    """Records cluster announcements and the nav entry sets handed to the core."""

    def __init__(self):
        self.events = []
        self.nav = []          # every register_nav_entries() call (list of entries)
        self.settings = {}     # Vault-backed plugin settings (ctx.get_setting)

    def emit(self, topic, payload=None, cluster=False):
        self.events.append((topic, payload, cluster))

    def register_nav_entries(self, entries):
        self.nav.append([dict(e) for e in entries])
        return len(entries)

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

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
    monkeypatch.setattr(routing, "_overview_enabled", False)
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


# --- "Alle Dienste" overview entry (1.4.0, setting show_overview_in_nav) ---------

def test_overview_entry_follows_setting(mgr, registry):
    _nav, ctx = registry
    svc = mgr.upsert(slug="ha", name="HA", url="https://ha.example.com")
    routing.register_all([svc])
    assert ctx.published == ["ha"]

    routing.set_overview_enabled(True)
    assert routing.overview_enabled() is True
    assert ctx.published == ["all-services", "ha"]
    entry = next(e for e in ctx.nav[-1] if e["id"] == "all-services")
    assert entry["url"] == "/apps/lyndrix-plugin-external_services/external/overview"
    assert entry["open_mode"] == "route" and entry["group"] == "Services"
    assert entry["order"] == -1 and entry["icon"] == "apps" and entry["label"] == "Alle Dienste"
    assert routing.registered_slugs() == ["ha"]   # services only — the extra entry is no slug
    assert ctx.events == []                       # a local toggle is never announced to peers

    routing.set_overview_enabled(True)            # unchanged → no republish
    assert len(ctx.nav) == 2

    routing.set_overview_enabled(False)
    assert ctx.published == ["ha"]


def test_overview_entry_survives_resync_and_removals(mgr, registry):
    _nav, ctx = registry
    routing.set_overview_enabled(True)
    a = mgr.upsert(slug="ha", name="HA", url="https://ha.example.com")
    routing.resync([a])                           # peer change rebuilds the service entries
    assert ctx.published == ["all-services", "ha"]
    routing.remove_service("ha", announce_change=False)
    assert ctx.published == ["all-services"]


def test_set_overview_enabled_without_publish_waits_for_register_all(mgr, registry):
    _nav, ctx = registry
    routing.set_overview_enabled(True, publish=False)
    assert ctx.nav == []                          # bootstrap publishes the complete set once
    routing.register_all([])
    assert ctx.published == ["all-services"]


@pytest.mark.parametrize(
    "stored,expected",
    [("true", True), ("True", True), ("1", True), ("on", True), (True, True),
     ("false", False), ("0", False), ("", False), (None, False), (False, False)],
)
def test_read_overview_setting_coerces_bool_and_string(registry, stored, expected):
    _nav, ctx = registry
    ctx.settings["show_overview_in_nav"] = stored
    assert routing.read_overview_setting(ctx) is expected


def test_read_overview_setting_defaults_and_old_core(registry):
    _nav, ctx = registry
    assert routing.read_overview_setting(ctx) is False        # never saved
    assert routing.read_overview_setting() is False           # falls back to the bound ctx
    assert routing.read_overview_setting(_FakeCtxNoNav()) is False   # core without get_setting

    class _VaultDown:
        def get_setting(self, key, default=None):
            raise RuntimeError("vault sealed")

    assert routing.read_overview_setting(_VaultDown()) is False     # never breaks bootstrap


def test_settings_changed_payload_filter():
    from ext_plugin import entrypoint

    pid = entrypoint.manifest.id
    assert entrypoint.settings_changed_for_us({"plugin_id": pid, "keys": ["show_overview_in_nav"], "by": "admin"})
    assert entrypoint.settings_changed_for_us({"plugin_id": pid})            # no keys → re-read
    assert not entrypoint.settings_changed_for_us({"plugin_id": pid, "keys": ["other"]})
    assert not entrypoint.settings_changed_for_us({"plugin_id": "lyndrix.plugin.other", "keys": ["show_overview_in_nav"]})
    assert not entrypoint.settings_changed_for_us("garbage")
    assert "plugin:settings_changed" in entrypoint.manifest.permissions.subscribe


# --- React UI manifest + locales (1.4.0) -------------------------------------------

def test_manifest_react_ui_has_no_sidebar_tab():
    from ext_plugin import entrypoint

    m = entrypoint.manifest
    assert m.version == "1.5.0"
    assert m.react_ui is True and m.i18n_namespace == "external_services"
    paths = [r["path"] for r in m.react_routes]
    assert sorted(paths) == ["/external/overview", "/external/settings"]
    assert all(r["sidebar_visible"] is False for r in m.react_routes)
    assert m.settings_ui_route == "/external/settings" and m.settings_ui_route in paths
    field = next(f for f in m.settings_schema if f.key == "show_overview_in_nav")
    assert field.kind == "bool" and field.default == "false"


def _flatten(tree, prefix=""):
    out = {}
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{path}."))
        else:
            out[path] = value
    return out


def test_locales_en_de_parity_and_i18next_dialect():
    en = _flatten(json.loads((_REPO / "locales" / "external_services.en.json").read_text("utf-8")))
    de = _flatten(json.loads((_REPO / "locales" / "external_services.de.json").read_text("utf-8")))
    assert en, "english locale is the source of truth and must not be empty"
    assert set(en) == set(de)                     # de is complete, no stray keys
    for text_ in list(en.values()) + list(de.values()):
        assert isinstance(text_, str) and text_.strip()
        assert "%{" not in text_                  # core/NiceGUI dialect never reaches i18next


def test_react_bundle_is_committed_with_the_shell_global():
    bundle = _REPO / "app" / "ui" / "static" / "ui_bundle.js"
    assert bundle.exists(), "run `npm run build` — the core serves app/ui/static/ui_bundle.js"
    assert "__lyndrix_plugin_lyndrix_plugin_external_services" in bundle.read_text("utf-8")


# --- ES-02: stored URLs are re-validated when entries are registered ---------------

def _seed_legacy(db, slug, url, **cols):
    """Insert a row the way a pre-0.2.0 release could: bypassing validate_url."""
    engine, _ = db
    with sessionmaker(bind=engine)() as s:
        s.add(ExternalService(slug=slug, name=slug.title(), url=url, **cols))
        s.commit()


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "data:text/html,<script>1</script>", "//evil.example.test/x",
     "https://user:pw@evil.example.test/", "ftp://files.example.test/", ""],
)
def test_legacy_invalid_url_is_never_published(db, mgr, registry, url):
    _, ctx = registry
    _seed_legacy(db, "legacy", url)
    mgr.upsert(slug="grafana", name="Grafana", url="https://grafana.example.test/")

    routing.register_all(mgr.get_enabled())          # bootstrap path
    assert ctx.published == ["grafana"]

    routing.refresh_service(mgr.get_by_slug("legacy"))  # single-service path
    assert ctx.published == ["grafana"]
    assert all(e["url"].startswith("https://") for e in ctx.nav[-1])

    # The row itself is untouched — an admin corrects it, nothing is rewritten.
    assert mgr.get_by_slug("legacy").url == url
    assert service_mod.url_problem(url) is not None


def test_corrected_legacy_row_is_published_again(db, mgr, registry):
    _, ctx = registry
    _seed_legacy(db, "legacy", "javascript:alert(1)")
    routing.register_all(mgr.get_enabled())
    assert ctx.published == []

    mgr.update(mgr.get_by_slug("legacy").id, url="https://ok.example.test/")
    routing.refresh_service(mgr.get_by_slug("legacy"))
    assert ctx.published == ["legacy"]


def test_react_sources_guard_every_service_href():
    """Source-level guard (the bundle is rebuilt separately): no service URL
    reaches an href/src that is not behind the http(s) check."""
    react = _REPO / "app" / "ui" / "react"
    assert "export function isHttpUrl" in (react / "shared.tsx").read_text()
    for name in ("OverviewView.tsx", "SettingsView.tsx"):
        assert "hasSafeUrl(" in (react / name).read_text(), name


# --- ES-03: write robustness -------------------------------------------------------

def test_reserved_slug_matches_the_overview_entry_and_is_rejected(mgr):
    assert routing.OVERVIEW_ENTRY_ID in service_mod.RESERVED_SLUGS
    with pytest.raises(ValueError, match="reserved"):
        mgr.upsert(slug="all-services", name="X", url="https://x.example.test/")
    assert mgr.register_from_payload({"service": "all-services", "url": "https://x.example.test/"}) is None


def test_legacy_row_with_reserved_slug_does_not_shadow_the_overview_entry(db, mgr, registry):
    _, ctx = registry
    _seed_legacy(db, "all-services", "https://x.example.test/")
    routing.set_overview_enabled(True, publish=False)
    routing.register_all(mgr.get_enabled())
    assert [e["url"] for e in ctx.nav[-1] if e["id"] == "all-services"] == [routing.OVERVIEW_ROUTE]


def test_over_long_fields_are_rejected_before_the_database(mgr):
    with pytest.raises(ValueError, match="name"):
        mgr.upsert(slug="a", name="n" * 101, url="https://a.example.test/")
    svc = mgr.upsert(slug="a", name="A", url="https://a.example.test/")
    with pytest.raises(ValueError, match="description"):
        mgr.update(svc.id, description="d" * 501)
    with pytest.raises(ValueError, match="open_mode"):
        mgr.update(svc.id, open_mode="popup")


def test_bus_registration_stays_lenient_and_survives_a_slug_race(mgr, monkeypatch):
    # Unknown open_mode / missing name fall back instead of dropping the payload.
    svc = mgr.register_from_payload({"service": "ha", "url": "https://ha.example.test/", "open_mode": "weird"})
    assert (svc.name, svc.open_mode) == ("ha", "iframe")

    # First pass loses the unique-slug race, the second one updates the peer's row.
    real = mgr.upsert
    calls = []

    def _flaky(**fields):
        calls.append(fields["slug"])
        if len(calls) == 1:
            raise service_mod.SlugConflict("lost the race")
        return real(**fields)

    monkeypatch.setattr(mgr, "upsert", _flaky)
    again = mgr.register_from_payload({"service": "ha", "name": "Home Assistant", "url": "https://ha.example.test/"})
    assert calls == ["ha", "ha"] and again.name == "Home Assistant"


@pytest.mark.parametrize("code", ["1020", "1205", "1213"])
def test_writes_are_retried_on_mariadb_conflicts(monkeypatch, code):
    monkeypatch.setattr(service_mod.time, "sleep", lambda _s: None)
    attempts = []

    def _tx():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError(f"({code}, 'Record has changed since last read')")
        return "done"

    assert service_mod.retry_write(_tx) == "done" and len(attempts) == 3

    def _other():
        raise RuntimeError("(1064, 'syntax')")

    with pytest.raises(RuntimeError, match="1064"):
        service_mod.retry_write(_other)
