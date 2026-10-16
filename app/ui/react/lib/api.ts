/**
 * Typed client for the plugin's own REST API (app/api.py), mounted by the core
 * at /api/plugins/lyndrix.plugin.external_services/. The UI holds no business
 * logic — every capability goes through these calls.
 */

export const PLUGIN_ID = 'lyndrix.plugin.external_services'
/** Shell-side URL-safe id ("." → "-"): /apps/<id>/… plugin routes, /ext/<id>/… embeds. */
export const SHELL_PLUGIN_ID = 'lyndrix-plugin-external_services'
const TOKEN_KEY = 'lyndrix_token'
const REQUEST_TIMEOUT_MS = 15_000

// ─── Types (mirror app/api.py _to_dict / ServiceCreate / ServiceUpdate) ───────

export type OpenMode = 'iframe' | 'new_tab'

export interface ExternalServiceOut {
  id: number
  slug: string
  name: string
  description: string
  icon: string
  url: string
  type: string
  open_mode: OpenMode
  show_in_nav: boolean
  enabled: boolean
  /** NiceGUI engine page, /external/<slug> */
  route: string
}

export interface ServiceCreate {
  /** Internal identifier; slug fallback when `route` is empty. */
  service: string
  name: string
  icon: string
  url: string
  type: string
  /** Explicit slug (upsert key). */
  route: string | null
  open_mode: OpenMode
  show_in_nav: boolean
  description: string
  enabled: boolean
}

export type ServiceUpdate = Partial<
  Pick<ExternalServiceOut, 'name' | 'description' | 'icon' | 'url' | 'type' | 'open_mode' | 'show_in_nav' | 'enabled'>
>

/** Core: GET /api/me/access — server-derived effective permissions. */
export interface AccessView {
  is_superadmin: boolean
  plugins: Record<string, { visible: boolean; can_read: boolean; can_write: boolean; routes: string[] }>
}

// ─── Fetch wrapper ──────────────────────────────────────────────────────────

/** In-SPA navigation the shell's BrowserRouter picks up — never a full reload
 *  (a cold load would run before the dynamic plugin routes are registered). */
export function spaNavigate(path: string) {
  window.history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY)
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init.headers as Record<string, string> | undefined),
  }

  // Bound every request so a hung backend cannot leave promises pending forever.
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(path, { ...init, headers, signal: controller.signal })
  } finally {
    clearTimeout(timeout)
  }

  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY)
    spaNavigate('/login')
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') msg = body.detail
      else if (body.detail) msg = JSON.stringify(body.detail)
    } catch { /* non-JSON error body */ }
    throw new Error(msg)
  }

  return res.json() as Promise<T>
}

const base = (subpath: string) => `/api/plugins/${PLUGIN_ID}/${subpath}`

export const pluginApi = {
  get: <T>(subpath: string) => apiFetch<T>(base(subpath)),
  post: <T>(subpath: string, body?: unknown) =>
    apiFetch<T>(base(subpath), { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(subpath: string, body?: unknown) =>
    apiFetch<T>(base(subpath), { method: 'PUT', body: body !== undefined ? JSON.stringify(body) : undefined }),
  del: <T>(subpath: string) => apiFetch<T>(base(subpath), { method: 'DELETE' }),
}

// ─── External Services surface ──────────────────────────────────────────────

export const externalServicesApi = {
  /** GET / — every service (enabled or not), ordered by name. */
  list: () => pluginApi.get<ExternalServiceOut[]>(''),
  /** POST / — create, or update in place when the slug exists. */
  create: (data: ServiceCreate) => pluginApi.post<ExternalServiceOut>('', data),
  /** PUT /{id} — partial update. */
  update: (id: number, data: ServiceUpdate) => pluginApi.put<{ ok: boolean }>(String(id), data),
  /** DELETE /{id} */
  remove: (id: number) => pluginApi.del<{ ok: boolean }>(String(id)),
  /** POST /reload — re-read the DB, rebuild sidebar entries on every instance. */
  reload: () => pluginApi.post<{ registered: number }>('reload'),
  /** Core access view — used only to hide write controls the API would reject anyway. */
  access: () => apiFetch<AccessView>('/api/me/access'),
}
