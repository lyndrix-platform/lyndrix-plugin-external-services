import React, { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { externalServicesApi, spaNavigate } from './lib/api'
import type { ExternalServiceOut } from './lib/api'
import {
  Button, EmptyState, ErrorBox, Icon, PageHeader, Spinner,
  extFramePath, goSettings, hostOf, useLocation,
} from './shared'

// Same sandbox the NiceGUI page uses (app/ui/nicegui/pages.py). The embedded
// service runs in its own origin, so allow-same-origin only lets it talk to itself.
const IFRAME_SANDBOX = 'allow-scripts allow-same-origin allow-forms allow-popups allow-modals allow-downloads'

/** How a tile opens its service. Embedded services that have a sidebar entry
 *  use the shell's frame page (/ext/…); embedded services hidden from the
 *  sidebar have no such entry, so the overview frames them itself (?open=slug). */
function openService(svc: ExternalServiceOut, pathname: string) {
  if (svc.open_mode === 'new_tab') return // rendered as a plain <a target=_blank>
  if (svc.show_in_nav) spaNavigate(extFramePath(svc.slug))
  else spaNavigate(`${pathname}?open=${encodeURIComponent(svc.slug)}`)
}

function Tile({ svc, pathname }: { svc: ExternalServiceOut; pathname: string }) {
  const { t } = useTranslation('external_services')
  const newTab = svc.open_mode === 'new_tab'
  const body = (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
        <span className="lx-card" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 44, height: 44, color: 'var(--lx-accent)', flexShrink: 0 }}>
          <Icon name={svc.icon || 'open_in_browser'} size={26} />
        </span>
        <Icon name={newTab ? 'open_in_new' : 'web_asset'} size={16} style={{ color: 'var(--lx-text-muted)' }} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
        <span style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--lx-text)' }}>{svc.name}</span>
        {svc.description && (
          <span style={{ fontSize: '0.78rem', color: 'var(--lx-text-muted)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
            {svc.description}
          </span>
        )}
      </div>
      <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', fontSize: '0.7rem', color: 'var(--lx-text-muted)' }}>
        <span style={{ fontFamily: 'var(--lx-font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{hostOf(svc.url)}</span>
        <span style={{ flexShrink: 0 }}>
          {newTab
            ? t('overview.newTab', { defaultValue: 'new tab' })
            : svc.show_in_nav
              ? t('overview.embedded', { defaultValue: 'embedded' })
              : t('overview.notInSidebar', { defaultValue: 'not in the sidebar' })}
        </span>
      </div>
    </>
  )
  const style: React.CSSProperties = {
    display: 'flex', flexDirection: 'column', gap: '0.75rem', padding: '1rem', minHeight: 150,
    textAlign: 'left', textDecoration: 'none', color: 'inherit', cursor: 'pointer', font: 'inherit', width: '100%',
  }
  if (newTab) {
    return <a className="lx-card lx-card-hover" href={svc.url} target="_blank" rel="noreferrer" title={svc.url} style={style}>{body}</a>
  }
  return (
    <button type="button" className="lx-card lx-card-hover" title={svc.url} style={style} onClick={() => openService(svc, pathname)}>
      {body}
    </button>
  )
}

/** In-plugin frame for an embedded service that is hidden from the sidebar. */
function EmbeddedService({ svc, onBack }: { svc: ExternalServiceOut; onBack: () => void }) {
  const { t } = useTranslation('external_services')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 7.5rem)', minHeight: 480 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.6rem 1rem', borderBottom: '1px solid var(--lx-border-soft)' }}>
        <Button icon="arrow_back" variant="ghost" label={t('overview.backToOverview', { defaultValue: 'All services' })} onClick={onBack} />
        <Icon name={svc.icon || 'open_in_browser'} size={18} style={{ color: 'var(--lx-accent)' }} />
        <span style={{ fontWeight: 600, color: 'var(--lx-text)' }}>{svc.name}</span>
        <span style={{ fontSize: '0.72rem', color: 'var(--lx-text-muted)' }}>
          {t('overview.frameHint', { defaultValue: 'Embedded here because the service is hidden from the sidebar.' })}
        </span>
        <a href={svc.url} target="_blank" rel="noreferrer" className="lx-btn lx-btn--secondary lx-btn--sm" style={{ marginLeft: 'auto', textDecoration: 'none' }}>
          <Icon name="open_in_new" size={16} />
          {t('common.openNewTab', { defaultValue: 'Open in new tab' })}
        </a>
      </div>
      <iframe
        src={svc.url}
        title={svc.name}
        sandbox={IFRAME_SANDBOX}
        referrerPolicy="no-referrer"
        allowFullScreen
        style={{ flex: '1 1 auto', width: '100%', border: 'none', display: 'block', minHeight: 0 }}
      />
    </div>
  )
}

/** /external/overview — tile grid of every enabled service. */
export default function OverviewView() {
  const { t } = useTranslation('external_services')
  const { pathname, search } = useLocation()
  const [services, setServices] = useState<ExternalServiceOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setServices((await externalServicesApi.list()).filter((s) => s.enabled))
      setError(null)
    } catch (err) {
      setError(`${t('msg.loadFailed', { defaultValue: 'Could not load services' })}: ${(err as Error).message}`)
    }
  }, [t])

  useEffect(() => { void load() }, [load])

  const openSlug = new URLSearchParams(search).get('open')
  const embedded = openSlug && services ? services.find((s) => s.slug === openSlug && s.open_mode !== 'new_tab') : undefined
  if (embedded) {
    return <EmbeddedService svc={embedded} onBack={() => spaNavigate(pathname)} />
  }

  const count = services?.length ?? 0

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '1.5rem' }}>
      <PageHeader
        title={t('overview.title', { defaultValue: 'All services' })}
        subtitle={t('overview.subtitle', { defaultValue: '{{count}} enabled services', count })}
        actions={
          <>
            <Button icon="refresh" label={t('common.refresh', { defaultValue: 'Refresh' })} onClick={() => void load()} />
            <Button icon="settings" label={t('common.settings', { defaultValue: 'Settings' })} onClick={goSettings} />
          </>
        }
      />

      {error && <ErrorBox msg={error} />}
      {services === null && !error && <Spinner label={t('common.loading', { defaultValue: 'Loading…' })} />}

      {services !== null && services.length === 0 && (
        <div className="lx-card">
          <EmptyState
            icon="public"
            title={t('overview.empty', { defaultValue: 'No enabled services.' })}
            hint={t('overview.emptyHint', { defaultValue: 'Enable or add services on the settings page.' })}
            action={<Button icon="settings" label={t('common.settings', { defaultValue: 'Settings' })} onClick={goSettings} />}
          />
        </div>
      )}

      {services !== null && services.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: '1rem' }}>
          {services.map((s) => <Tile key={s.id} svc={s} pathname={pathname} />)}
        </div>
      )}
    </div>
  )
}
