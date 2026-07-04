"""
ui_overview.py — Hub page at /external showing all registered external services
                 as clickable cards.  This is the "External Services" sidebar entry.
"""

from nicegui import ui

from core.api import UIStyles

from ...logic.service import ext_service_manager
from .pages import open_in_new_tab


def render_overview_ui(ctx) -> None:
    del ctx
    services = ext_service_manager.get_all()

    if not services:
        with ui.column().classes("w-full items-center justify-center gap-4 py-16"):
            ui.icon("link_off", size="48px").classes("text-[var(--lx-text-muted)]")
            ui.label("Keine externen Services konfiguriert.").classes(
                "text-[var(--lx-text-muted)] text-sm"
            )
            ui.label(
                "Füge Services über die Einstellungen → Plugins → External Services hinzu "
                "oder sende einen authentifizierten POST (API-Key erforderlich) an "
                "/api/plugins/lyndrix.plugin.external_services/."
            ).classes("text-[var(--lx-text-muted)] text-xs text-center max-w-md")
        return

    enabled = [s for s in services if s.enabled]
    disabled = [s for s in services if not s.enabled]

    if enabled:
        with ui.row().classes("flex-wrap gap-4 w-full"):
            for svc in enabled:
                _render_service_card(svc)

    if disabled:
        ui.label("Deaktiviert").classes(
            "text-[length:var(--lx-text-3xs)] font-bold uppercase tracking-wider "
            "text-[var(--lx-text-muted)] mt-6 mb-2"
        )
        with ui.row().classes("flex-wrap gap-4 w-full opacity-50"):
            for svc in disabled:
                _render_service_card(svc, dimmed=True)


def _render_service_card(svc, dimmed: bool = False) -> None:
    opacity = "opacity-50" if dimmed else ""

    # Shared entity-card chrome + the "info" gradient accent stripe (was a
    # hand-rolled sky->cyan div; the token-mapped gradient is the same hue pair).
    with ui.card().classes(
        f"w-64 cursor-pointer hover:scale-[1.02] "
        f"transition-transform duration-[var(--lx-transition-fast)] ease-[var(--lx-ease)] "
        f"{UIStyles.ENTITY_CARD} {UIStyles.CARD_ACCENT_INFO} {opacity}"
    ):
        with ui.column().classes("gap-3"):
            with ui.row().classes("items-center gap-3"):
                with ui.element("div").classes(
                    "w-10 h-10 rounded-[var(--lx-radius-lg)] bg-[var(--lx-elevated)] "
                    "flex items-center justify-center shrink-0"
                ):
                    ui.icon(svc.icon or "open_in_browser", size="22px").classes(
                        "text-[var(--lx-accent-2)]"
                    )

                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(svc.name).classes(
                        "text-sm font-bold text-[var(--lx-text)] leading-tight truncate"
                    )
                    with ui.row().classes("items-center gap-1"):
                        ui.label(svc.service_type.upper()).classes(
                            "text-[length:var(--lx-text-3xs)] [font-family:var(--lx-font-mono)] "
                            "text-[var(--lx-text-muted)] uppercase"
                        )
                        open_mode = getattr(svc, "open_mode", "iframe") or "iframe"
                        if open_mode == "new_tab":
                            ui.label("NEU TAB").classes(
                                "text-[length:var(--lx-text-3xs)] font-bold "
                                "rounded-[var(--lx-radius)] px-1"
                            ).style(
                                "background: color-mix(in srgb, var(--lx-warning) 20%, transparent); "
                                "color: var(--lx-warning); "
                                "border: 1px solid color-mix(in srgb, var(--lx-warning) 30%, transparent);"
                            )

            if svc.description:
                ui.label(svc.description).classes(
                    "text-xs text-[var(--lx-text-muted)] leading-relaxed line-clamp-2"
                )

            ui.label(svc.url).classes(
                "text-[length:var(--lx-text-3xs)] [font-family:var(--lx-font-mono)] "
                "text-[var(--lx-text-muted)] truncate w-full"
            )

            with ui.row().classes("w-full gap-2 mt-1"):
                open_mode = getattr(svc, "open_mode", "iframe") or "iframe"
                if open_mode == "new_tab":
                    ui.button(
                        "Öffnen",
                        icon="open_in_new",
                        on_click=lambda u=svc.url: open_in_new_tab(u),
                    ).props("unelevated size=sm color=warning").classes("flex-1")
                else:
                    ui.button(
                        "Öffnen",
                        icon="open_in_browser",
                        on_click=lambda u=f"/external/{svc.slug}": ui.navigate.to(u),
                    ).props("unelevated size=sm color=secondary").classes("flex-1")

                ui.button(
                    icon="open_in_new",
                    on_click=lambda url=svc.url: open_in_new_tab(url),
                ).props("flat round dense").classes("text-[var(--lx-text-muted)]").tooltip(
                    "Im Browser öffnen"
                )
