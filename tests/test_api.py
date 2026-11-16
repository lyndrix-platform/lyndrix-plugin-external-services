"""REST layer: route permissions (ES-01), input validation and conflicts (ES-03),
legacy URL flagging (ES-02) — the real router behind a FastAPI TestClient, with
the core's request authentication replaced by a fixed identity."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.api import ApiIdentity
from core.api import security as core_security

from ext_plugin.app import api as api_mod
from ext_plugin.app.model.models import ExternalService

from .test_service import db, mgr, registry  # noqa: F401  (shared fixtures)

READ = api_mod.PERM_READ
WRITE = api_mod.PERM_WRITE
MANAGE = api_mod.PERM_MANAGE

_GRAFANA = {"service": "grafana", "name": "Grafana", "url": "https://grafana.example.test/"}


@pytest.fixture
def client_as(mgr, registry, monkeypatch):  # noqa: F811
    """``client_as(*permissions)`` → TestClient whose caller holds exactly those."""

    def _make(*permissions, headers=None):
        identity = ApiIdentity(method="session", username="tester", permissions=frozenset(permissions))
        monkeypatch.setattr(core_security, "require_api_auth", lambda request: identity)
        app = FastAPI()
        app.include_router(api_mod.build_router())
        return TestClient(app, headers=headers or {})

    return _make


# --- ES-01: writes need the dedicated manage permission ---------------------------

def test_manage_permission_is_not_an_api_write_alias():
    # The core lets the global api:write (and the INT_USER baseline grant)
    # satisfy every "plugin:<id>:api:write" — the manage id must escape that.
    assert not MANAGE.endswith((":api:read", ":api:write"))


@pytest.mark.parametrize("grants", [(READ,), (READ, WRITE), ("api:read", "api:write")])
def test_api_write_alone_cannot_create_update_or_delete(client_as, mgr, grants):
    existing = mgr.upsert(slug="wiki", name="Wiki", url="https://wiki.example.test/")
    client = client_as(*grants)

    assert client.post("/", json=_GRAFANA).status_code == 403
    assert client.put(f"/{existing.id}", json={"url": "https://evil.example.test/"}).status_code == 403
    assert client.delete(f"/{existing.id}").status_code == 403

    assert client.get("/").status_code == 200
    stored = mgr.get_by_id(existing.id)
    assert stored is not None and stored.url == "https://wiki.example.test/"
    assert mgr.get_by_slug("grafana") is None


def test_manage_permission_allows_the_full_lifecycle(client_as, mgr):
    client = client_as(READ, MANAGE)

    created = client.post("/", json=_GRAFANA)
    assert created.status_code == 201
    sid = created.json()["id"]
    assert client.put(f"/{sid}", json={"name": "Grafana 2"}).status_code == 200
    assert mgr.get_by_id(sid).name == "Grafana 2"
    assert client.delete(f"/{sid}").status_code == 200
    assert mgr.get_by_id(sid) is None


def test_manifest_maps_manage_to_the_admin_role_only():
    from ext_plugin.entrypoint import manifest

    assert [p.id for p in manifest.custom_permissions] == ["external_services:manage"]
    holders = {r.id: (MANAGE in r.permissions, list(r.auto_map_groups)) for r in manifest.roles}
    assert holders["admin"] == (True, ["INT_ADMIN"])
    assert holders["operator"][0] is False and holders["viewer"][0] is False


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "https://lyndrix.example.test"},
        {"host": "lyndrix.example.test"},
        {"host": "core:8080", "x-forwarded-host": "lyndrix.example.test", "x-forwarded-proto": "https"},
    ],
)
def test_url_on_the_lyndrix_origin_is_rejected(client_as, mgr, headers):
    client = client_as(READ, MANAGE, headers=headers)

    own = {"service": "self", "name": "Self", "url": "https://lyndrix.example.test/some/page"}
    assert client.post("/", json=own).status_code == 422
    assert mgr.get_by_slug("self") is None

    other = client.post("/", json=_GRAFANA)
    assert other.status_code == 201
    repoint = client.put(f"/{other.json()['id']}", json={"url": "http://lyndrix.example.test/"})
    assert repoint.status_code == 422
    # Another port on the same host is a different origin and stays allowed.
    assert client.put(f"/{other.json()['id']}", json={"url": "https://lyndrix.example.test:3000/"}).status_code == 200


# --- ES-02: legacy rows are flagged, not hidden, in the admin list ------------------

def test_list_flags_rows_with_an_invalid_stored_url(client_as, db, mgr):  # noqa: F811
    from .test_service import _seed_legacy

    _seed_legacy(db, "legacy", "javascript:alert(1)")
    mgr.upsert(slug="grafana", name="Grafana", url="https://grafana.example.test/")

    rows = {r["slug"]: r for r in client_as(READ).get("/").json()}
    assert rows["legacy"]["url_valid"] is False
    assert rows["grafana"]["url_valid"] is True


# --- ES-03: conflicts and invalid input are client errors, never a 500 --------------

def test_lost_slug_race_is_a_409(client_as, db, mgr, monkeypatch):  # noqa: F811
    """A peer inserts the same slug between our lookup and our insert."""
    from sqlalchemy.orm import sessionmaker

    engine, _ = db

    def _racing_tx(self, **fields):
        with sessionmaker(bind=engine)() as s:
            s.add(ExternalService(slug=fields["slug"], name="Peer", url="https://peer.example.test/"))
            s.commit()
        with sessionmaker(bind=engine)() as s:   # our insert: the lookup saw nothing
            s.add(ExternalService(slug=fields["slug"], name=fields["name"], url=fields["url"]))
            s.commit()

    monkeypatch.setattr(type(mgr), "_upsert_tx", _racing_tx)
    reply = client_as(READ, MANAGE).post("/", json=_GRAFANA)

    assert reply.status_code == 409
    assert "grafana" in reply.json()["detail"]
    assert mgr.get_by_slug("grafana").name == "Peer"


@pytest.mark.parametrize(
    "patch",
    [
        {"name": "n" * 101},
        {"name": ""},
        {"description": "d" * 501},
        {"icon": "i" * 101},
        {"url": "https://example.test/" + "u" * 1000},
        {"type": "t" * 51},
        {"open_mode": "popup"},
        {"service": "s" * 101},
        {"route": "all-services"},
        {"service": "All Services"},      # slugifies to the reserved id
    ],
)
def test_invalid_create_payload_is_a_422(client_as, mgr, patch):
    reply = client_as(READ, MANAGE).post("/", json={**_GRAFANA, **patch})
    assert reply.status_code == 422, reply.text
    assert mgr.get_all() == []


@pytest.mark.parametrize(
    "patch",
    [{"name": "n" * 101}, {"description": "d" * 501}, {"open_mode": "popup"}, {"url": "javascript:alert(1)"}],
)
def test_invalid_update_payload_is_a_422(client_as, mgr, patch):
    svc = mgr.upsert(slug="wiki", name="Wiki", url="https://wiki.example.test/")
    assert client_as(READ, MANAGE).put(f"/{svc.id}", json=patch).status_code == 422
    assert mgr.get_by_id(svc.id).name == "Wiki"


def test_update_maps_type_to_the_service_type_column(client_as, mgr):
    svc = mgr.upsert(slug="wiki", name="Wiki", url="https://wiki.example.test/")
    assert client_as(READ, MANAGE).put(f"/{svc.id}", json={"type": "embed"}).status_code == 200
    assert mgr.get_by_id(svc.id).service_type == "embed"
