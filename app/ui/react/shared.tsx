import React, { useEffect, useState } from 'react'
import { externalServicesApi, PLUGIN_ID, SHELL_PLUGIN_ID, spaNavigate } from './lib/api'

// Small presentational pieces + navigation helpers shared by both pages.
// Everything renders into the host DOM, so the host's .lx-* classes and
// --lx-* tokens apply — the plugin ships no CSS of its own.

// ─── Location / navigation ──────────────────────────────────────────────────

/** Current pathname + search; re-renders on history navigation (spaNavigate
 *  dispatches popstate, so in-plugin links update the view without a reload). */
export function useLocation(): { pathname: string; search: string } {
  const read = () => ({ pathname: window.location.pathname, search: window.location.search })
  const [loc, setLoc] = useState(read)
  useEffect(() => {
    const onChange = () => setLoc(read())
    window.addEventListener('popstate', onChange)
    return () => window.removeEventListener('popstate', onChange)
  }, [])
  return loc
}

/** Base of this plugin's routes in the shell: /apps/<id>/external */
export function pluginBase(): string {
  const p = window.location.pathname.replace(/\/+$/, '')
  const i = p.indexOf('/external/')
  return i >= 0 ? p.slice(0, i + '/external'.length) : `/apps/${SHELL_PLUGIN_ID}/external`
}

export const goOverview = () => spaNavigate(`${pluginBase()}/overview`)
export const goSettings = () => spaNavigate(`${pluginBase()}/settings`)

/** In-shell embed of a sidebar-listed service (shell route /ext/:pluginId/:entryId,
 *  entry id = slug). Only services with show_in_nav have such an entry. */
export const extFramePath = (slug: string) => `/ext/${SHELL_PLUGIN_ID}/${encodeURIComponent(slug)}`

// ─── Permissions ────────────────────────────────────────────────────────────

/** Whether the caller may create/edit/delete (plugin:<id>:api:write or global
 *  api:write). Display hygiene only — the API enforces regardless; unknown → true. */
export function useCanWrite(): boolean {
  const [canWrite, setCanWrite] = useState(true)
  useEffect(() => {
    let alive = true
    externalServicesApi.access()
      .then((a) => {
        if (!alive) return
        const p = a.plugins?.[PLUGIN_ID]
        setCanWrite(a.is_superadmin || !p || p.can_write)
      })
      .catch(() => { /* keep optimistic default; API still gates writes */ })
    return () => { alive = false }
  }, [])
  return canWrite
}

// ─── Presentational ─────────────────────────────────────────────────────────

export function Icon({ name, size = 18, style }: { name: string; size?: number; style?: React.CSSProperties }) {
  return <span className="material-icons" aria-hidden style={{ fontSize: size, lineHeight: 1, ...style }}>{name}</span>
}

export function Button({
  label, onClick, disabled, variant = 'default', icon, title, type = 'button',
}: {
  label: string
  onClick?: () => void
  disabled?: boolean
  variant?: 'default' | 'danger' | 'primary' | 'ghost'
  icon?: string
  title?: string
  type?: 'button' | 'submit'
}) {
  const cls =
    variant === 'primary' ? 'lx-btn lx-btn--primary lx-btn--sm'
    : variant === 'danger' ? 'lx-btn lx-btn--danger lx-btn--sm'
    : variant === 'ghost' ? 'lx-btn lx-btn--ghost lx-btn--sm'
    : 'lx-btn lx-btn--secondary lx-btn--sm'
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={cls} title={title}>
      {icon && <Icon name={icon} size={16} />}
      {label}
    </button>
  )
}

export function IconButton({ icon, onClick, title, disabled, danger }: {
  icon: string
  onClick: () => void
  title: string
  disabled?: boolean
  danger?: boolean
}) {
  return (
    <button
      type="button"
      className={danger ? 'lx-icon-btn lx-icon-btn--danger' : 'lx-icon-btn'}
      onClick={onClick}
      title={title}
      aria-label={title}
      disabled={disabled}
    >
      <Icon name={icon} />
    </button>
  )
}

export function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="lx-card lx-card-accent lx-card-accent--danger" role="alert"
      style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0.7rem 1rem', marginBottom: '1rem', color: 'var(--lx-state-down)', fontSize: '0.8rem' }}>
      <Icon name="error_outline" />
      <span>{msg}</span>
    </div>
  )
}

export function NoticeBox({ msg }: { msg: string }) {
  return (
    <div className="lx-card lx-card-accent lx-card-accent--success" role="status"
      style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0.7rem 1rem', marginBottom: '1rem', color: 'var(--lx-state-up)', fontSize: '0.8rem' }}>
      <Icon name="check_circle" />
      <span>{msg}</span>
    </div>
  )
}

/** A success notice that clears itself. */
export function useNotice(ttlMs = 4000): [string | null, (msg: string | null) => void] {
  const [notice, setNotice] = useState<string | null>(null)
  useEffect(() => {
    if (!notice) return
    const t = window.setTimeout(() => setNotice(null), ttlMs)
    return () => window.clearTimeout(t)
  }, [notice, ttlMs])
  return [notice, setNotice]
}

export function Spinner({ label }: { label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '2rem 0', color: 'var(--lx-text-muted)', fontSize: '0.85rem' }}>
      <div className="animate-spin" style={{ width: 18, height: 18, borderRadius: '50%', border: '2px solid var(--lx-accent)', borderTopColor: 'transparent' }} />
      {label}
    </div>
  )
}

export function EmptyState({ icon, title, hint, action }: { icon: string; title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="lx-empty">
      <Icon name={icon} size={34} />
      <p style={{ margin: 0, fontWeight: 600, color: 'var(--lx-text)' }}>{title}</p>
      {hint && <p style={{ margin: 0, fontSize: '0.8rem', maxWidth: 460 }}>{hint}</p>}
      {action}
    </div>
  )
}

export function Labeled({ label, children, hint }: { label: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
      <span className="lx-label" style={{ marginBottom: 0 }}>{label}</span>
      {children}
      {hint && <span style={{ fontSize: '0.7rem', color: 'var(--lx-text-muted)' }}>{hint}</span>}
    </label>
  )
}

export function Checkbox({ checked, onChange, label, hint, disabled }: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  hint?: string
  disabled?: boolean
}) {
  return (
    <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem', cursor: disabled ? 'not-allowed' : 'pointer' }}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} style={{ marginTop: 3, accentColor: 'var(--lx-accent)' }} />
      <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{ fontSize: '0.85rem', color: 'var(--lx-text)' }}>{label}</span>
        {hint && <span style={{ fontSize: '0.7rem', color: 'var(--lx-text-muted)' }}>{hint}</span>}
      </span>
    </label>
  )
}

export function Modal({ title, onClose, children, width = 640 }: { title: string; onClose: () => void; children: React.ReactNode; width?: number }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="lx-modal-overlay" onClick={onClose} style={{ position: 'fixed', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60 }}>
      <div className="lx-modal lx-card" role="dialog" aria-modal aria-label={title} onClick={(e) => e.stopPropagation()}
        style={{ width: `min(${width}px, 94vw)`, maxHeight: '90vh', overflow: 'auto', padding: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.9rem' }}>
          <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: 'var(--lx-text)' }}>{title}</h3>
          <button type="button" className="lx-icon-btn" onClick={onClose} aria-label="close"><Icon name="close" /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
      <div>
        <h1 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: 'var(--lx-text)' }}>{title}</h1>
        {subtitle && <p style={{ margin: '0.25rem 0 0', fontSize: '0.85rem', color: 'var(--lx-text-muted)' }}>{subtitle}</p>}
      </div>
      {actions && <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>{actions}</div>}
    </div>
  )
}

/** Host of a URL for compact display; falls back to the raw string. */
export function hostOf(url: string): string {
  try { return new URL(url).host } catch { return url }
}
