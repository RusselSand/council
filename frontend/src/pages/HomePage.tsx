import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, councilPath } from '../api'
import { formatDate } from '../i18n'
import { useLoad } from '../useLoad'

export function HomePage() {
  const { t } = useTranslation()
  const { state, retry } = useLoad(api.councils, [])

  return (
    <main className="main">
      <h1 className="page-title">{t('home.title')}</h1>
      <p className="page-sub">{t('home.subtitle')}</p>
      <div className="card-grid">
        {state.kind === 'loading' && <div className="card muted">{t('common.loading')}</div>}
        {state.kind === 'error' && (
          <div className="card muted">
            {t('home.loadFailed')}{' '}
            <button className="btn-primary" onClick={retry}>{t('common.retry')}</button>
          </div>
        )}
        {state.kind === 'ok' && state.data.map(c => (
          <Link key={c.id} to={councilPath(c.id)} className="card">
            <div className="card-head">
              <span className="card-name">{c.name || t('council.untitled')}</span>
              <span className={`pill ${c.status}`}>{t(`status.${c.status}`)}</span>
            </div>
            <div className="muted">
              {t('home.meta', { judge: c.judge, count: c.participants.length, updated: formatDate(c.updated_at) })}
            </div>
          </Link>
        ))}
        {state.kind === 'ok' && state.data.length === 0 && (
          <div className="card muted">{t('home.empty')}</div>
        )}
      </div>
    </main>
  )
}
