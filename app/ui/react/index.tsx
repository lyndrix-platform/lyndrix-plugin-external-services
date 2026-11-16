import PluginApp from './PluginApp'

// Explicit global assignment — the shell (lyndrix-ui usePluginModules) reads
// window.__lyndrix_plugin_<safe id>, safe id = plugin id with [.-] → "_".
;(window as unknown as Record<string, unknown>)['__lyndrix_plugin_lyndrix_plugin_external_services'] = {
  PluginApp,
  // Mirrors manifest.react_routes. No sidebar tab on purpose: the managed
  // services ARE the sidebar entries (group "Services"); the settings page is
  // reached through the gear on the Plugins page, the overview through the
  // optional "Alle Dienste" nav entry (plugin setting show_overview_in_nav).
  pluginRoutes: [
    { path: '/external/overview', label: 'Alle Dienste', icon: 'apps', sidebar_visible: false },
    { path: '/external/settings', label: 'Externe Dienste – Einstellungen', icon: 'settings', sidebar_visible: false },
  ],
}
