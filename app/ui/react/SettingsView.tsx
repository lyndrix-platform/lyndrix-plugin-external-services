import React, { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { externalServicesApi } from './lib/api'
import type { ExternalServiceOut } from './lib/api'
import ServiceDialog from './ServiceDialog'
import {
  Button, EmptyState, ErrorBox, Icon, IconButton, Modal, NoticeBox, PageHeader, Spinner,
  goOverview, hostOf, useCanWrite, useNotice,
} from './shared'

type Dialog = { kind: 'none' } | { kind: 'create' } | { kind: 'edit'; svc: ExternalServiceOut } | { kind: 'delete'; svc: ExternalServiceOut }

/** /external/settings — the plugin's settings page (manifest.settings_ui_route):
 *  table of every service with create / edit / delete and the reload action. */
export default function SettingsView() {
  const { t } = useTranslation('external_services')
  const canWrite = useCanWrite()
  const [services, setServices] = useState<ExternalServiceOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useNotice()
  const [busy, setBusy] = useState(false)
  const [dialog, setDialog] = useState<Dialog>({ kind: 'none' })

  const load = useCallback(async () => {
    try {
      setServices(await externalServicesApi.list())
      setError(null)
    } catch (err) {
      setError(`${t('msg.loadFailed', { defaultValue: 'Could not load services' })}: ${(err as Error).message}`)
    }
  }, [t])

  useEffect(() => { void load() }, [load])

  async function reload() {
    setBusy(true)
    try {
      const r = await externalServicesApi.reload()
      setNotice(t('msg.reloaded', { defaultValue: '{{count}} services reloaded.', count: r.registered }))
      await load()
    } catch (err) {
      setError(`${t('msg.reloadFailed', { defaultValue: 'Reload failed' })}: ${(err as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  async function remove(svc: ExternalServiceOut) {
    setBusy(true)
    try {
      await externalServicesApi.remove(svc.id)
      setDialog({ kind: 'none' })
      setNotice(t('msg.deleted', { defaultValue: 'Service "{{name}}" deleted.', name: svc.name }))
      await load()
    } catch (err) {
      setError(`${t('msg.deleteFailed', { defaultValue: 'Could not delete' })}: ${(err as Error).message}`)
      setDialog({ kind: 'none' })
    } finally {
      setBusy(false)
    }
  }

  function onSaved(message: string) {
    setDialog({ kind: 'none' })
    setNotice(message)
    void load()
  }

  const count = services?.length ?? 0

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '1.5rem' }}>
      <PageHeader
        title={t('settings.title', { defaultValue: 'External services' })}
        subtitle={t('settings.subtitle', { defaultValue: '{{count}} services configured · embedded in the shell or opened in a new tab.', count })}
        actions={
          <>
            <Button icon="apps" label={t('common.overview', { defaultValue: 'All services' })} onClick={goOverview} variant="ghost" />
            <Button icon="refresh" label={t('common.refresh', { defaultValue: 'Refresh' })} onClick={() => void load()} disabled={busy} />
            <Button icon="sync" label={t('common.reload', { defaultValue: 'Reload' })} onClick={() => void reload()} disabled={busy || !canWrite}
              title={t('settings.reloadHint', { defaultValue: 'Re-read the services from the database and rebuild the sidebar entries on every instance.' })} />
            <Button icon="add" variant="primary" label={t('settings.newService', { defaultValue: 'New service' })}
              onClick={() => setDialog({ kind: 'create' })} disabled={!canWrite} />
          </>
        }
      />

      {error && <ErrorBox msg={error} />}
      {notice && <NoticeBox msg={notice} />}
      {!canWrite && (
        <p style={{ fontSize: '0.78rem', color: 'var(--lx-text-muted)', margin: '0 0 1rem' }}>
          {t('settings.readOnly', { defaultValue: 'You can view the services but not change them (plugin write permission required).' })}
        </p>
      )}

      {services === null && !error && <Spinner label={t('common.loading', { defaultValue: 'Loading…' })} />}

      {services !== null && services.length === 0 && (
        <div className="lx-card">
          <EmptyState
            icon="public"
            title={t('settings.empty', { defaultValue: 'No external services yet.' })}
            hint={t('settings.emptyHint', { defaultValue: 'Add Grafana, Home Assistant, NetBox, … — each enabled service becomes an entry in the Services section of the sidebar.' })}
            action={canWrite ? (
              <Button icon="add" variant="primary" label={t('settings.newService', { defaultValue: 'New service' })} onClick={() => setDialog({ kind: 'create' })} />
            ) : undefined}
          />
        </div>
      )}

      {services !== null && services.length > 0 && (
        <div className="lx-card" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table className="lx-table">
              <thead>
                <tr>
                  <th>{t('settings.colService', { defaultValue: 'Service' })}</th>
                  <th>{t('settings.colUrl', { defaultValue: 'URL' })}</th>
                  <th>{t('settings.colMode', { defaultValue: 'Opens' })}</th>
                  <th>{t('settings.colSidebar', { defaultValue: 'Sidebar' })}</th>
                  <th>{t('settings.colActive', { defaultValue: 'Active' })}</th>
                  <th style={{ textAlign: 'right' }}>{t('settings.colActions', { defaultValue: 'Actions' })}</th>
                </tr>
              </thead>
              <tbody>
                {services.map((s) => (
                  <tr key={s.id} style={{ opacity: s.enabled ? 1 : 0.6 }}>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', minWidth: 180 }}>
                        <Icon name={s.icon || 'open_in_browser'} size={22} style={{ color: 'var(--lx-accent)', flexShrink: 0 }} />
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
                          <span style={{ fontWeight: 600 }}>{s.name}</span>
                          <span style={{ fontSize: '0.7rem', color: 'var(--lx-text-muted)', fontFamily: 'var(--lx-font-mono)' }}>{s.slug}</span>
                          {s.description && <span style={{ fontSize: '0.75rem', color: 'var(--lx-text-muted)' }}>{s.description}</span>}
                        </div>
                      </div>
                    </td>
                    <td>
                      <a href={s.url} target="_blank" rel="noreferrer" title={s.url}
                        style={{ color: 'var(--lx-text)', fontFamily: 'var(--lx-font-mono)', fontSize: '0.75rem', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        {hostOf(s.url)}
                        <Icon name="open_in_new" size={13} style={{ color: 'var(--lx-text-muted)' }} />
                      </a>
                    </td>
                    <td>
                      <span className="lx-badge lx-badge--muted">
                        <Icon name={s.open_mode === 'new_tab' ? 'open_in_new' : 'web_asset'} size={13} />
                        {s.open_mode === 'new_tab'
                          ? t('settings.modeNewTab', { defaultValue: 'new tab' })
                          : t('settings.modeIframe', { defaultValue: 'embedded' })}
                      </span>
                    </td>
                    <td>
                      <Icon name={s.show_in_nav ? 'check' : 'remove'} size={18}
                        style={{ color: s.show_in_nav ? 'var(--lx-state-up)' : 'var(--lx-text-muted)' }} />
                    </td>
                    <td>
                      <span className={s.enabled ? 'lx-badge lx-badge--up' : 'lx-badge lx-badge--muted'}>
                        <span className="lx-dot" />
                        {s.enabled ? t('settings.active', { defaultValue: 'active' }) : t('settings.inactive', { defaultValue: 'inactive' })}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 2 }}>
                        <IconButton icon="edit" title={t('common.edit', { defaultValue: 'Edit' })} disabled={!canWrite || busy}
                          onClick={() => setDialog({ kind: 'edit', svc: s })} />
                        <IconButton icon="delete" danger title={t('common.delete', { defaultValue: 'Delete' })} disabled={!canWrite || busy}
                          onClick={() => setDialog({ kind: 'delete', svc: s })} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(dialog.kind === 'create' || dialog.kind === 'edit') && (
        <ServiceDialog
          initial={dialog.kind === 'edit' ? dialog.svc : null}
          onClose={() => setDialog({ kind: 'none' })}
          onSaved={onSaved}
        />
      )}

      {dialog.kind === 'delete' && (
        <Modal title={t('confirm.deleteTitle', { defaultValue: 'Delete service?' })} onClose={() => setDialog({ kind: 'none' })} width={480}>
          <p style={{ margin: '0 0 1rem', fontSize: '0.85rem', color: 'var(--lx-text)' }}>
            {t('confirm.deleteBody', {
              defaultValue: '"{{name}}" ({{url}}) is removed from the database and its sidebar entry disappears on every instance. This cannot be undone.',
              name: dialog.svc.name, url: dialog.svc.url,
            })}
          </p>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
            <Button label={t('common.cancel', { defaultValue: 'Cancel' })} onClick={() => setDialog({ kind: 'none' })} disabled={busy} />
            <Button variant="danger" icon="delete" label={t('common.delete', { defaultValue: 'Delete' })} disabled={busy}
              onClick={() => void remove(dialog.svc)} />
          </div>
        </Modal>
      )}
    </div>
  )
}
