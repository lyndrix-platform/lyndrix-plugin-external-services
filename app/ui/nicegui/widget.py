import asyncio

from nicegui import ui

from ...logic.service import ext_service_manager


async def render_dashboard_widget(ctx):
    del ctx
    services = await asyncio.to_thread(ext_service_manager.get_enabled)
    with ui.row().classes("items-center gap-2"):
        ui.icon("public", size="16px").classes("text-[var(--lx-accent-2)]")
        ui.label(f"{len(services)} externe Service(s) aktiv").classes(
            "text-xs text-[var(--lx-text-muted)]"
        )
        if services:
            ui.button(
                "Übersicht",
                icon="arrow_forward",
                on_click=lambda: ui.navigate.to("/external"),
            ).props("flat dense size=xs").classes("text-[var(--lx-accent-2)]")
