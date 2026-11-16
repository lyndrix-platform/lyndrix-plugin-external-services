import React from 'react'
// react-i18next is provided by the host shell (window.__lyndrix_react_i18next);
// strings come from locales/external_services.<locale>.json (namespace
// "external_services"), auto-registered by the core and served via its catalog.
import OverviewView from './OverviewView'
import SettingsView from './SettingsView'
import { useLocation } from './shared'

/** Root component, mounted by the shell for every manifest.react_routes path:
 *  /apps/<id>/external/overview → tile grid, /apps/<id>/external/settings → CRUD. */
export default function PluginApp() {
  const { pathname } = useLocation()
  const isOverview = pathname.replace(/\/+$/, '').endsWith('/overview')
  return isOverview ? <OverviewView /> : <SettingsView />
}
