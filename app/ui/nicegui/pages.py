"""
pages.py — NiceGUI page rendering for embedded external services.

A single parameterised route ``/external/{slug}`` is registered once at setup
time. It resolves the service by slug at request time so that disabling,
deleting or editing a service takes effect immediately (no stale per-slug
routes lingering until restart).

All service URLs are validated to be http(s) on write (logic/service.py), and
are additionally output-encoded here as defence in depth before being placed
into HTML attributes / JavaScript string literals.
"""

import asyncio
import json
import logging

from nicegui import ui

from ...logic.service import ext_service_manager

log = logging.getLogger("Plugin:ExternalServices:Pages")

# Restrictive-but-functional sandbox for embedded third-party pages. Embedded
# services run in their *own* origin, so ``allow-same-origin`` does not weaken
# isolation of the Lyndrix origin; it only lets the embedded app talk to itself.
_IFRAME_SANDBOX = (
    "allow-scripts allow-same-origin allow-forms "
    "allow-popups allow-modals allow-downloads"
)


def register_pages() -> None:
    """Register the single slug-resolved external-services page (call once)."""
    try:
        from ui.layout import main_layout
    except ImportError:

        def main_layout(title, **kwargs):  # type: ignore
            def decorator(fn):
                return fn

            return decorator

    @ui.page("/external/{slug}")
    @main_layout("External Service")
    async def _external_service_page(slug: str) -> None:
        # Resolve at request time so enable/disable/edit/delete are live.
        svc = await asyncio.to_thread(ext_service_manager.get_by_slug, slug)
        if svc is None or not svc.enabled:
            _render_unavailable(slug)
            return

        open_mode = getattr(svc, "open_mode", "iframe") or "iframe"
        if open_mode == "new_tab":
            render_new_tab_landing(svc.name, svc.icon, svc.url)
        else:
            render_iframe(svc.name, svc.icon, svc.url)


def _render_unavailable(slug: str) -> None:
    with ui.column().classes("w-full items-center justify-center gap-4 py-24"):
        ui.icon("link_off", size="48px").classes("text-zinc-600")
        ui.label("Dieser Service ist nicht verfügbar.").classes("text-zinc-400 text-sm")
        ui.label(f"/external/{slug}").classes("text-[11px] font-mono text-zinc-600")


def render_iframe(name: str, icon: str, url: str) -> None:
    del name, icon  # rendered chrome comes from main_layout/nav
    # ``url`` is validated http(s) on write; encode the quote defensively so it
    # can never break out of the double-quoted ``src`` attribute.
    safe_src = url.replace('"', "%22")

    ui.element("iframe").props(
        f'src="{safe_src}" sandbox="{_IFRAME_SANDBOX}" '
        'referrerpolicy="no-referrer" allowfullscreen'
    ).style(
        "width: 100%; "
        "flex: 1 1 auto; "
        "min-height: 0; "
        "border: none; "
        "display: block;"
    )

    ui.run_javascript("""
        (function() {
            var qpage = document.querySelector(".q-page");
            if (!qpage) return;
            qpage.style.padding    = "0";
            qpage.style.display    = "flex";
            qpage.style.flexDirection = "column";

            var content = qpage.querySelector(".nicegui-content");
            if (content) {
                content.style.padding       = "0";
                content.style.margin        = "0";
                content.style.width         = "100%";
                content.style.flex          = "1 1 auto";
                content.style.display       = "flex";
                content.style.flexDirection = "column";
                content.style.minHeight     = "0";
            }

            var col = content ? content.querySelector(":scope > .nicegui-column") : null;
            if (col) {
                col.style.maxWidth      = "none";
                col.style.padding       = "0";
                col.style.margin        = "0";
                col.style.width         = "100%";
                col.style.flex          = "1 1 auto";
                col.style.display       = "flex";
                col.style.flexDirection = "column";
                col.style.minHeight     = "0";
            }
        })();
    """)


def render_new_tab_landing(name: str, icon: str, url: str) -> None:
    open_in_new_tab(url)

    with ui.column().classes("w-full items-center justify-center gap-6 py-24"):
        with ui.card().classes(
            "items-center gap-4 p-8 bg-zinc-800/40 border border-zinc-700/30 rounded-2xl"
        ):
            ui.icon(icon or "open_in_browser", size="48px").classes("text-sky-400")
            ui.label(name).classes("text-xl font-bold text-zinc-100")
            ui.label("Dieser Service wird in einem neuen Tab geöffnet.").classes(
                "text-sm text-zinc-400 text-center"
            )
            ui.label(url).classes("text-[11px] font-mono text-zinc-600")
            ui.button(
                "Erneut öffnen",
                icon="open_in_new",
                on_click=lambda u=url: open_in_new_tab(u),
            ).props("unelevated color=sky").classes("mt-2")


def open_in_new_tab(url: str) -> None:
    """Open ``url`` in a new browser tab, JSON-encoding it into the JS literal.

    Using ``json.dumps`` (rather than f-string interpolation) means a URL can
    never break out of the JavaScript string and inject arbitrary code.
    """
    ui.run_javascript(f"window.open({json.dumps(url)}, '_blank');")
