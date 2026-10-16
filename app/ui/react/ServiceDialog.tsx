import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { externalServicesApi } from './lib/api'
import type { ExternalServiceOut, OpenMode } from './lib/api'
import { Button, Checkbox, ErrorBox, Icon, Labeled, Modal } from './shared'

const DEFAULT_ICON = 'open_in_browser'

/** Create / edit form for one service. Validation beyond "required" and the
 *  URL scheme is the API's job (validate_url); its 400 detail is shown as-is. */
export default function ServiceDialog({ initial, onClose, onSaved }: {
  initial: ExternalServiceOut | null
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const { t } = useTranslation('external_services')
  const editing = initial !== null

  const [name, setName] = useState(initial?.name ?? '')
  const [slug, setSlug] = useState(initial?.slug ?? '')
  const [url, setUrl] = useState(initial?.url ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [icon, setIcon] = useState(initial?.icon ?? DEFAULT_ICON)
  const [openMode, setOpenMode] = useState<OpenMode>(initial?.open_mode ?? 'iframe')
  const [showInNav, setShowInNav] = useState(initial?.show_in_nav ?? true)
  const [enabled, setEnabled] = useState(initial?.enabled ?? true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const iconName = icon.trim() || DEFAULT_ICON

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const trimmedName = name.trim()
    const trimmedUrl = url.trim()
    if (!trimmedName) { setError(t('form.nameRequired', { defaultValue: 'Please enter a name.' })); return }
    if (!/^https?:\/\/\S+/i.test(trimmedUrl)) {
      setError(t('form.urlInvalid', { defaultValue: 'The URL must start with http:// or https://.' }))
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (editing) {
        await externalServicesApi.update(initial.id, {
          name: trimmedName, url: trimmedUrl, description: description.trim(), icon: iconName,
          open_mode: openMode, show_in_nav: showInNav, enabled,
        })
        onSaved(t('msg.updated', { defaultValue: 'Service "{{name}}" saved.', name: trimmedName }))
      } else {
        const explicitSlug = slug.trim()
        await externalServicesApi.create({
          service: explicitSlug || trimmedName,
          route: explicitSlug || null,
          name: trimmedName, url: trimmedUrl, description: description.trim(), icon: iconName,
          type: 'iframe', open_mode: openMode, show_in_nav: showInNav, enabled,
        })
        onSaved(t('msg.created', { defaultValue: 'Service "{{name}}" created.', name: trimmedName }))
      }
    } catch (err) {
      setError(`${t('msg.saveFailed', { defaultValue: 'Could not save' })}: ${(err as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  const input = { className: 'lx-input', style: { width: '100%' } as React.CSSProperties }

  return (
    <Modal
      title={editing ? t('form.titleEdit', { defaultValue: 'Edit service' }) : t('form.titleCreate', { defaultValue: 'New external service' })}
      onClose={onClose}
    >
      <form onSubmit={(e) => void submit(e)} style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
        {error && <ErrorBox msg={error} />}

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.9rem' }}>
          <Labeled label={t('form.name', { defaultValue: 'Name' })}>
            <input {...input} value={name} autoFocus required maxLength={100}
              placeholder={t('form.namePlaceholder', { defaultValue: 'Grafana' })}
              onChange={(e) => setName(e.target.value)} />
          </Labeled>
          <Labeled
            label={t('form.slug', { defaultValue: 'Slug' })}
            hint={editing
              ? t('form.slugFixed', { defaultValue: 'The slug cannot be changed after creation.' })
              : t('form.slugHint', { defaultValue: 'URL-safe identifier (/external/<slug>, sidebar entry id). Leave empty to derive it from the name; an existing slug is updated in place.' })}
          >
            <input {...input} value={slug} disabled={editing} maxLength={100} pattern="[A-Za-z0-9-]*"
              placeholder={editing ? '' : 'grafana'}
              onChange={(e) => setSlug(e.target.value)} />
          </Labeled>
        </div>

        <Labeled
          label={t('form.url', { defaultValue: 'URL' })}
          hint={t('form.urlHint', { defaultValue: 'Full http(s) address. Services that forbid embedding (X-Frame-Options / CSP) must use "New browser tab".' })}
        >
          <input {...input} type="url" value={url} required maxLength={1000} placeholder="https://grafana.example.com"
            onChange={(e) => setUrl(e.target.value)} />
        </Labeled>

        <Labeled label={t('form.description', { defaultValue: 'Description' })}>
          <input {...input} value={description} maxLength={500}
            placeholder={t('form.descriptionPlaceholder', { defaultValue: 'Shown on the tile in the overview' })}
            onChange={(e) => setDescription(e.target.value)} />
        </Labeled>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.9rem' }}>
          <Labeled
            label={t('form.icon', { defaultValue: 'Icon' })}
            hint={
              <>
                {t('form.iconHint', { defaultValue: 'Material Icons name, e.g. home, insights, dns, hub — browse at' })}{' '}
                <a href="https://fonts.google.com/icons" target="_blank" rel="noreferrer" style={{ color: 'var(--lx-accent)' }}>fonts.google.com/icons</a>.
              </>
            }
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span className="lx-card" title={iconName}
                style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 38, height: 38, flexShrink: 0, color: 'var(--lx-accent)' }}>
                <Icon name={iconName} size={22} />
              </span>
              <input {...input} value={icon} maxLength={100} placeholder={DEFAULT_ICON} spellCheck={false}
                onChange={(e) => setIcon(e.target.value)} />
            </div>
          </Labeled>
          <Labeled label={t('form.openMode', { defaultValue: 'Open as' })}>
            <select className="lx-select" style={{ width: '100%' }} value={openMode} onChange={(e) => setOpenMode(e.target.value as OpenMode)}>
              <option value="iframe">{t('form.openModeIframe', { defaultValue: 'Embedded (iframe)' })}</option>
              <option value="new_tab">{t('form.openModeNewTab', { defaultValue: 'New browser tab' })}</option>
            </select>
          </Labeled>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', paddingTop: '0.2rem' }}>
          <Checkbox checked={showInNav} onChange={setShowInNav}
            label={t('form.showInNav', { defaultValue: 'Show in sidebar' })}
            hint={t('form.showInNavHint', { defaultValue: 'Adds an entry to the Services section. Hidden services stay reachable from the overview.' })} />
          <Checkbox checked={enabled} onChange={setEnabled}
            label={t('form.enabled', { defaultValue: 'Active' })}
            hint={t('form.enabledHint', { defaultValue: 'Inactive services are kept but get no sidebar entry and are not shown in the overview.' })} />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '0.4rem' }}>
          <Button label={t('common.cancel', { defaultValue: 'Cancel' })} onClick={onClose} disabled={busy} />
          <Button type="submit" variant="primary" icon={editing ? 'save' : 'add'} disabled={busy}
            label={editing ? t('common.save', { defaultValue: 'Save' }) : t('common.create', { defaultValue: 'Create' })} />
        </div>
      </form>
    </Modal>
  )
}
