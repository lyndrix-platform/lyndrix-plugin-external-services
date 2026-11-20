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

Reads need `plugin:lyndrix.plugin.external_services:api:read`; `POST /reload`
needs `…:api:write`. Creating, changing and deleting a service requires the
custom permission `external_services:manage`
(`plugin:lyndrix.plugin.external_services:external_services:manage`). The core
grants `…:api:write` to every user by baseline, so `manage` deliberately has no
such baseline grant and no global `api:write` fallback: the service list is
published as trusted sidebar links to everyone.

The manifest ships the roles *Viewer* (read), *Operator* (read + write: can
reload the sidebar entries, cannot create or repoint services) and
*Administrator* (read + write + manage; auto-mapped to `INT_ADMIN`). Grant
`external_services:manage` to whoever maintains the service list. Global
`api:read` keeps working through the core's fallback.

## URL validation

- Only `http(s)://` URLs without userinfo are accepted.
- A URL on the origin the request arrived on (Lyndrix itself) is refused with
  422, because the shell would frame it same-origin.
- Stored URLs are validated again before they are published or rendered. An
  invalid legacy row gets no sidebar entry, `GET /` marks it with
  `url_valid: false`, and both UIs show it as inert text. Check for such rows
  after an upgrade with
  `SELECT id, url FROM external_services WHERE url NOT LIKE 'http%'`.

## Cluster mode

Sidebar entries are per instance. Every change is announced as
`external_services:changed` (cluster-bridged) and the peers rebuild their
entries from the shared table. The schema bootstrap runs under the core's
`lyndrix_bootstrap` advisory lock and tolerates a lost race.

## Compatibility

- lyndrix-core ≥ 1.7.0 (`min_core_version`), core API ≥ 1.9 for sidebar entries.
- The React bundle (`app/ui/static/ui_bundle.js`) is only used by the React
  shell; the NiceGUI engine keeps its own pages.
