# Lyndrix External Services

Embed external web services (Home Assistant, Grafana, Netdata, …) directly into the Lyndrix UI as full-screen iframes with sidebar entries.

- **Repository:** [https://github.com/lyndrix-platform/lyndrix-plugin-external-services](https://github.com/lyndrix-platform/lyndrix-plugin-external-services)
- **Platform docs:** [Lyndrix Core](https://docs.lyndrix.eu) · [Plugin ecosystem](https://docs.lyndrix.eu/ecosystem/)

## Features

- iframe-based embedding of external services (or new-tab links for services that forbid embedding)
- One sidebar entry per service in the *Services* section — the plugin has no tab of its own
- React settings page (create / edit / delete / reload) and a tile overview of all active services
- Managed service registry with DB persistence, cluster-aware sidebar sync
- REST API and event-driven service registration

## Installation

Install **External Services** from the Lyndrix **Plugin Manager**, or declare it for
reconciliation on boot via `LYNDRIX_PLUGINS_DESIRED`:

```text
https://github.com/lyndrix-platform/lyndrix-plugin-external-services
```

See the [Plugin Development Guide](https://docs.lyndrix.eu/plugins/) for the plugin model and
lifecycle, and [Usage](usage.md) / [Configuration](configuration.md) for details.
