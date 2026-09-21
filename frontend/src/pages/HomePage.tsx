import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, councilPath, type Council } from '../api'
import { formatDate } from '../i18n'

type State = { kind: 'loading' } | { kind: 'ok'; councils: Council[] } | { kind: 'error' }

export function HomePage() {
  const { t } = useTranslation()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setState({ kind: 'loading' })
    api.councils()
      .then(councils => active && setState({ kind: 'ok', councils }))
      .catch(() => active && setState({ kind: 'error' }))
    return () => { active = false }
  }, [attempt])

  return (
    <>
      <h1 className="page-title">{t('home.title')}</h1>
      <p className="page-sub">{t('home.subtitle')}</p>
      <div className="card-grid">
        {state.kind === 'loading' && <div className="card muted">{t('common.loading')}</div>}
        {state.kind === 'error' && (
          <div className="card muted">
            {t('home.loadFailed')}{' '}
            <button className="btn-primary" onClick={() => setAttempt(a => a + 1)}>{t('common.retry')}</button>
          </div>
        )}
        {state.kind === 'ok' && state.councils.map(c => (
          <Link key={c.id} to={councilPath(c.id)} className="card">
            <div className="card-head">
              <span className="card-name">{c.name || t('council.untitled')}</span>
              <span className={`pill ${c.status}`}>{t(`status.${c.status}`)}</span>
            </div>
            <div className="muted">
              {t('home.meta', { author: c.author, reviewer: c.reviewer, updated: formatDate(c.updated_at) })}
            </div>
          </Link>
        ))}
        {state.kind === 'ok' && state.councils.length === 0 && (
          <div className="card muted">{t('home.empty')}</div>
        )}
      </div>
    </>
  )
}
