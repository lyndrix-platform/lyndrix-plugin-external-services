import asyncio

from core.api import ModuleManifest
from nicegui import ui

from app.controller.api import build_router
from app.controller.routing import register_all, register_service, set_context
from app.controller.service import ext_service_manager
from app.ui.overview import render_overview_ui as _render_overview_ui
from app.ui.settings import render_settings_ui as _render_settings_ui
from app.ui.widget import render_dashboard_widget as _render_dashboard_widget

try:
    from ui.layout import main_layout
except ImportError:
    def main_layout(title):  # type: ignore
        def decorator(fn):
            return fn
        return decorator


manifest = ModuleManifest(
    id="lyndrix.plugin.external_services",
    name="External Services",
    version="0.1.1",
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


def render_overview_ui(ctx):
    _render_overview_ui(ctx)


def render_settings_ui(ctx):
    _render_settings_ui(ctx)


def render_dashboard_widget(ctx):
    _render_dashboard_widget(ctx)


def setup(ctx):
    ctx.log.info("External Services: starting setup...")

    ext_service_manager.ensure_table()
    set_context(ctx)

    services = ext_service_manager.get_enabled()
    register_all(services)
    ctx.log.info(f"External Services: registered {len(services)} service(s).")

    from main import app as fastapi_app  # noqa: PLC0415
    fastapi_app.include_router(build_router())

    @ui.page("/external")
    @main_layout("External Services")
    async def _external_hub():
        render_overview_ui(ctx)

    @ctx.subscribe("db:connected")
    async def on_db_connected(payload):
        del payload
        svcs = await asyncio.to_thread(ext_service_manager.get_enabled)
        register_all(svcs)
        ctx.log.info("External Services: re-registered routes after db:connected.")

    @ctx.subscribe("external_services:register")
    async def on_register(payload):
        try:
            svc = await asyncio.to_thread(ext_service_manager.register_from_payload, payload)
        except Exception as exc:
            ctx.log.error(f"External Services: failed to register service from event: {exc}")
            return

        if svc is None:
            return

        register_service(svc)
        ctx.log.info(f"External Services: registered '{svc.name}' via event bus.")

    plugin_state["ready"] = True
    ctx.log.info("External Services: setup complete.")


def teardown(ctx):
    plugin_state["ready"] = False
    ctx.log.info("External Services: teardown complete.")
