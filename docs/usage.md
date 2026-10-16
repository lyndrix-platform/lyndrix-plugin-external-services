# Usage

## Managing services (React shell)

Open **Plugins → External Services → gear**. This opens the plugin's settings page
`/apps/lyndrix-plugin-external_services/external/settings`:

- **New service** — name, optional slug (derived from the name when empty), URL,
  description, Material icon (live preview, names from
  [fonts.google.com/icons](https://fonts.google.com/icons)), open mode
  (*Embedded (iframe)* or *New browser tab*), *Show in sidebar*, *Active*.
- **Edit / Delete** — per row; delete asks for confirmation.
- **Reload** — re-reads the services from the database and rebuilds the sidebar
  entries on every instance (`POST /reload`).

Callers without the plugin write permission see the table read-only.

## Opening services

- Every active service with *Show in sidebar* is listed in the **Services**
  section of the sidebar. Embedded services open inside the shell
  (`/ext/lyndrix-plugin-external_services/<slug>`), new-tab services open in a
  new browser tab.
- **All services** (`/apps/lyndrix-plugin-external_services/external/overview`)
  shows every active service as a tile. Enable the plugin setting
  `show_overview_in_nav` to link it from the sidebar as *Alle Dienste*
  (core ≥ 1.10).

Services that block embedding (`X-Frame-Options` / CSP) must use *New browser
tab*.

## NiceGUI engine

The hub page `/external`, the slug page `/external/<slug>`, the settings modal
and the dashboard widget are unchanged.

## REST API and event bus

Base path `/api/plugins/lyndrix.plugin.external_services/` (authenticated):
`GET /` list, `POST /` create or update by slug, `PUT /{id}` partial update,
`DELETE /{id}`, `POST /reload`. In-process registration via the bus topic
`external_services:register` with the same payload. See the
[README](https://github.com/lyndrix-platform/lyndrix-plugin-external-services#readme)
for payload fields and examples.
