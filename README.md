# lyndrix-external-services

A Lyndrix plugin that embeds external web services (Home Assistant, Grafana, Netdata, …) into the Lyndrix UI — as full-screen iframes or as new-tab links — with one sidebar entry per service.

---

## Features

- **Sidebar integration** — every enabled service with `show_in_nav` appears in the *Services* section of the sidebar (core API ≥ 1.9 `ctx.register_nav_entries`). Embedded services open at `/ext/lyndrix-plugin-external_services/<slug>`, `new_tab` services as plain links. The plugin itself has **no sidebar tab** — the services are the entries.
- **React UI** (React shell, UI engine `api`):
  - **Settings page** `/apps/lyndrix-plugin-external_services/external/settings` — reached through the gear button on the *Plugins* page. Table of all services with create / edit / delete, Material-icon preview, open mode, "show in sidebar", "active", and a *Reload* action.
  - **Overview** `/apps/lyndrix-plugin-external_services/external/overview` — tile grid of every enabled service. Optionally linked from the sidebar as *Alle Dienste* (plugin setting `show_overview_in_nav`, core ≥ 1.10).
- **NiceGUI engine** — hub page `/external`, slug-resolved page `/external/<slug>`, settings modal and dashboard widget keep working unchanged.
- **REST API** — authenticated full CRUD at `/api/plugins/lyndrix.plugin.external_services/` so other services (e.g. the IaC orchestrator) can register services programmatically.
- **Event bus** — publish `external_services:register` from any plugin to register a service in-process.
- **Cluster-ready** — sidebar entries are per instance; every change is announced as `external_services:changed` (bridged) and peers re-read the shared table.
- **Persistent** — service definitions survive restarts via the `external_services` MariaDB table.

---

## Payload format

Both the REST API and the event bus accept the same fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `service` | string | yes | Internal identifier, used as slug fallback |
| `name` | string | yes | Display name shown in sidebar and tile |
| `icon` | string | no | [Material Icon](https://fonts.google.com/icons) name (default: `open_in_browser`) |
| `url` | string | yes | Full `http(s)://` URL of the external service (no userinfo) |
| `type` | string | no | Integration type — currently `iframe` (default) |
| `route` | string | no | Explicit URL slug; falls back to `service` |
| `open_mode` | string | no | `iframe` (embedded, default) or `new_tab` — use `new_tab` for services that forbid embedding (X-Frame-Options / CSP) |
| `show_in_nav` | bool | no | Whether to add a sidebar entry (default: `true`) |
| `description` | string | no | Short description shown on the overview tile |
| `enabled` | bool | no | Whether the service is active (default: `true`) |

---

## REST API

Base path: `/api/plugins/lyndrix.plugin.external_services/`

> **Authentication required.** The router is mounted by core via
> `ctx.register_routes()` and every route is auth-enforced. Reads need
> `plugin:lyndrix.plugin.external_services:api:read`, mutations
> `…:api:write` (global `api:read` / `api:write` keep working). Send a valid
> Lyndrix API key or bearer token with each request.

### Register or update a service

```http
POST /api/plugins/lyndrix.plugin.external_services/
Content-Type: application/json
X-API-Key: <your-api-key>

{
  "service":     "homeassistant",
  "name":        "Home-Assistant",
  "icon":        "home",
  "url":         "https://smart-home.example.com",
  "type":        "iframe",
  "route":       "smart-home",
  "open_mode":   "iframe",
  "show_in_nav": true
}
```

The call is **idempotent** — if a service with the same slug already exists it is updated in place.

### List all services

```http
GET /api/plugins/lyndrix.plugin.external_services/
```

### Update a service

```http
PUT /api/plugins/lyndrix.plugin.external_services/{id}
Content-Type: application/json

{ "enabled": false }
```

### Delete a service

```http
DELETE /api/plugins/lyndrix.plugin.external_services/{id}
```

### Force re-scan (after manual DB changes)

```http
POST /api/plugins/lyndrix.plugin.external_services/reload
```

Re-reads the enabled services, rebuilds this instance's sidebar entries and tells the peers to do the same.

---

## Event bus

Any Lyndrix plugin can register a service without HTTP by emitting on the bus.

**Topic:** `external_services:register`

The plugin's manifest must include this topic in `permissions.emit`:

```python
manifest = ModuleManifest(
    ...
    permissions={
        "emit": ["external_services:register"],
    },
)
```

Then emit from `setup()` or any bus handler:

```python
ctx.emit("external_services:register", {
    "service": "homeassistant",
    "name":    "Home-Assistant",
    "icon":    "home",
    "url":     "https://smart-home.example.com",
    "type":    "iframe",
    "route":   "smart-home",
})
```

The service is persisted to the DB and the sidebar entry is registered immediately.

---

## IAC Orchestrator integration example

In `lyndrix-iac-orchestrator`, after a deployment completes, post the service URL back to Lyndrix:

```python
import httpx

httpx.post(
    "http://lyndrix-core:8081/api/plugins/lyndrix.plugin.external_services/",
    headers={"X-API-Key": API_KEY},
    json={
        "service":     "homeassistant",
        "name":        "Home-Assistant",
        "icon":        "home",
        "url":         deployment.url,
        "type":        "iframe",
        "route":       "smart-home",
    },
)
```

Or use the event bus directly if both run in the same process.

---

## Plugin settings

Edited in the core's settings dialog (*Plugins → gear*; stored in Vault):

| Key | Kind | Default | Effect |
|---|---|---|---|
| `show_overview_in_nav` | bool | `false` | Publishes an extra sidebar entry *Alle Dienste* (`id: all-services`, group *Services*, first position) that opens the React overview in-shell (`open_mode: "route"`, core API ≥ 1.10). Older cores skip the entry with a warning; the per-service entries are unaffected. Applied at bootstrap and on `plugin:settings_changed` on every instance. |

---

## Project structure

```
lyndrix-plugin-external-services/
├── entrypoint.py            # manifest + lifecycle wiring only
├── package.json             # React UI toolchain (vite build → app/ui/static)
├── vite.ui.config.ts
├── tsconfig.json
├── locales/
│   ├── external_services.en.json   # i18next dialect, source of truth
│   └── external_services.de.json
├── app/
│   ├── api.py               # REST router (API-first; both UIs use only this)
│   ├── model/models.py      # SQLAlchemy model
│   ├── logic/
│   │   ├── service.py       # CRUD manager, URL validation, schema bootstrap
│   │   └── routing.py       # sidebar entries (ctx.register_nav_entries), overview entry
│   └── ui/
│       ├── react/           # federated React UI (settings + overview)
│       │   ├── index.tsx    # registers window.__lyndrix_plugin_lyndrix_plugin_external_services
│       │   ├── PluginApp.tsx
│       │   ├── SettingsView.tsx · ServiceDialog.tsx · OverviewView.tsx · shared.tsx
│       │   └── lib/api.ts
│       ├── static/ui_bundle.js   # built bundle (committed; served by the core)
│       └── nicegui/         # NiceGUI engine pages, settings modal, widget
└── tests/test_service.py
```

### Building the React UI

```bash
npm install
npm run typecheck   # tsc --noEmit
npm run build       # → app/ui/static/ui_bundle.js (commit it)
```

React, `react-dom`, `react-i18next` and `i18next` are provided by the shell at runtime (window globals) and are externalized in `vite.ui.config.ts`.

---

## Routes

| Path | Engine | Description |
|---|---|---|
| `/apps/lyndrix-plugin-external_services/external/settings` | React | Settings page (manage services) |
| `/apps/lyndrix-plugin-external_services/external/overview` | React | Tile overview of enabled services |
| `/ext/lyndrix-plugin-external_services/<slug>` | React shell | Embedded service (sidebar entry, `open_mode: iframe`) |
| `/external` | NiceGUI | Hub page |
| `/external/<slug>` | NiceGUI | Full-screen iframe / new-tab landing |
| `/api/plugins/lyndrix.plugin.external_services/` | — | REST CRUD (authenticated) |

---

## Requirements

- lyndrix-core ≥ 1.7.0 (core API ≥ 1.9 for sidebar entries; ≥ 1.10 for the optional *Alle Dienste* entry)
- No additional Python dependencies — uses only packages already present in lyndrix-core (`nicegui`, `fastapi`, `sqlalchemy`, `pydantic`)
- Node 20 only to rebuild the React bundle
