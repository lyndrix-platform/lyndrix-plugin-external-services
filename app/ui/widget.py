from nicegui import ui

from ..controller.service import ext_service_manager


def render_dashboard_widget(ctx):
    del ctx
    services = ext_service_manager.get_enabled()
    with ui.row().classes("items-center gap-2"):
        ui.icon("public", size="16px").classes("text-sky-400")
        ui.label(f"{len(services)} externe Service(s) aktiv").classes(
            "text-xs text-zinc-400"
        )
        if services:
            ui.button(
                "Übersicht",
                icon="arrow_forward",
                on_click=lambda: ui.navigate.to("/external"),
            ).props("flat dense size=xs").classes("text-sky-400")
