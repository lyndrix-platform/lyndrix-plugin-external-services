import asyncio
import time

from core.api import ModuleContext, ModuleManifest, PluginHealthStatus, db_instance

from .app.api import build_router
from .app.logic.routing import register_all, register_service, set_context
from .app.logic.service import ext_service_manager
from .app.ui.nicegui.overview import render_overview_ui as _render_overview_ui
from .app.ui.nicegui.pages import register_pages
from .app.ui.nicegui.settings import render_settings_ui as _render_settings_ui
from .app.ui.nicegui.widget import render_dashboard_widget as _render_dashboard_widget

manifest = ModuleManifest(
    id="lyndrix.plugin.external_services",
    name="External Services",
    version="0.2.1",
    description="Embed external web services (Home Assistant, Grafana, …) via iframe.",
    author="Lyndrix",
    icon="public",
    type="PLUGIN",
    min_core_version="0.0.6",
    auto_enable_on_install=True,
    repo_url="https://github.com/lyndrix-platform/lyndrix-plugin-external-services",
    ui_route="/external",
    permissions={
        "subscribe": ["db:connected", "external_services:register"],
        "emit": [],
    },
)

plugin_state: dict = {"ready": False}


def render_overview_ui(ctx: ModuleContext) -> None:
    _render_overview_ui(ctx)


def render_settings_ui(ctx: ModuleContext) -> None:
    _render_settings_ui(ctx)


def render_dashboard_widget(ctx: ModuleContext) -> None:
    _render_dashboard_widget(ctx)


def setup(ctx: ModuleContext) -> None:
    ctx.log.info("External Services: starting setup...")

    set_context(ctx)

    # Mount the REST router through the core registry so it inherits
    # require_api_auth (and the per-route api:read/api:write guards). This
    # replaces the previous ``from main import app`` escape hatch.
    ctx.register_routes(build_router())

    # Register the single slug-resolved page and the overview hub. These do not
    # touch the DB at registration time, so they are safe to register here.
    register_pages()
    _register_overview_page(ctx)

    @ctx.subscribe("db:connected")
    async def on_db_connected(payload) -> None:
        del payload
        # All DB work (table create + migration + read) is guarded behind
        # db:connected and offloaded so it never blocks the event loop.
        await asyncio.to_thread(ext_service_manager.ensure_table)
        svcs = await asyncio.to_thread(ext_service_manager.get_enabled)
        register_all(svcs)
        ctx.log.info(
            f"External Services: registered {len(svcs)} service(s) after db:connected."
        )

    @ctx.subscribe("external_services:register")
    async def on_register(payload) -> None:
        try:
            svc = await asyncio.to_thread(
                ext_service_manager.register_from_payload, payload
            )
        except Exception as exc:
            ctx.log.error(
                f"External Services: failed to register service from event: {exc}"
            )
            return

        if svc is None:
            return

        register_service(svc)
        ctx.log.info(f"External Services: registered '{svc.name}' via event bus.")

    plugin_state["ready"] = True
    ctx.log.info("External Services: setup complete.")


def _register_overview_page(ctx: ModuleContext) -> None:
    from nicegui import ui

    try:
        from ui.layout import main_layout
    except ImportError:

        def main_layout(title, **kwargs):  # type: ignore
            def decorator(fn):
                return fn

            return decorator

    @ui.page("/external")
    @main_layout("External Services")
    async def _external_hub() -> None:
        render_overview_ui(ctx)


async def health(ctx: ModuleContext) -> PluginHealthStatus:
    """Functional health probe.

    Goes beyond "setup ran" by actually exercising the persistence path this
    plugin depends on: it confirms the DB is connected, that the
    ``external_services`` table is reachable, and reports how many services are
    registered/enabled. The sync ORM calls are offloaded to a thread so the
    health check never blocks the event loop.
    """
    start = time.perf_counter()

    if not plugin_state.get("ready"):
        return PluginHealthStatus(
            status="error",
            details={"reason": "setup_incomplete", "ready": False},
        )

    if not db_instance.is_connected:
        return PluginHealthStatus(
            status="error",
            details={"reason": "db_unavailable", "db_connected": False},
        )

    try:
        def _probe() -> tuple[int, int]:
            ext_service_manager.ensure_table()
            return (
                len(ext_service_manager.get_all()),
                len(ext_service_manager.get_enabled()),
            )

        total, enabled = await asyncio.to_thread(_probe)
    except Exception as exc:  # DB query failed → the plugin cannot serve anything
        return PluginHealthStatus(
            status="error",
            details={"reason": "db_query_failed", "error": str(exc)},
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    latency = round((time.perf_counter() - start) * 1000, 1)
    details = {
        "db_connected": True,
        "services_total": total,
        "services_enabled": enabled,
    }
    # DB works but nothing is wired up yet — usable, but not doing its job.
    if enabled == 0:
        return PluginHealthStatus(
            status="degraded",
            details={**details, "reason": "no_enabled_services"},
            latency_ms=latency,
        )
    return PluginHealthStatus(status="ok", details=details, latency_ms=latency)


def teardown(ctx: ModuleContext) -> None:
    plugin_state["ready"] = False
    ctx.log.info("External Services: teardown complete.")
