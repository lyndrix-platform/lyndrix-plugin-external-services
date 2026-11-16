# Configuration

The plugin needs no environment variables. Service definitions live in the
`external_services` table of the shared MariaDB and are managed through the
React settings page, the REST API or the `external_services:register` bus topic
(see [Usage](usage.md)).

## Plugin settings

Edited in the core's settings dialog (*Plugins → External Services → gear*,
section *Navigation*) and stored in Vault under `plugins/<id>/settings`:

| Key | Kind | Default | Effect |
|---|---|---|---|
| `show_overview_in_nav` | bool | `false` | Adds the sidebar entry *Alle Dienste* (first entry of the *Services* section) that opens the overview of all active services inside the shell. Needs core API ≥ 1.10 (`open_mode: "route"`); older cores skip the entry with a warning. Applied immediately on every instance (`plugin:settings_changed`). |

## Permissions

Routes are gated per plugin: `plugin:lyndrix.plugin.external_services:api:read`
for reads, `…:api:write` for every mutation (create, update, delete, reload).
The manifest ships the roles *Viewer* (read), *Operator* and *Administrator*
(read + write; *Administrator* is auto-mapped to `INT_ADMIN`). Global
`api:read` / `api:write` grants keep working through the core's fallback.

## Cluster mode

Sidebar entries are per instance. Every change is announced as
`external_services:changed` (cluster-bridged) and the peers rebuild their
entries from the shared table. The schema bootstrap runs under the core's
`lyndrix_bootstrap` advisory lock and tolerates a lost race.

## Compatibility

- lyndrix-core ≥ 1.7.0 (`min_core_version`), core API ≥ 1.9 for sidebar entries.
- The React bundle (`app/ui/static/ui_bundle.js`) is only used by the React
  shell; the NiceGUI engine keeps its own pages.
