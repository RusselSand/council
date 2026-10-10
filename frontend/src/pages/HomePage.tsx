import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, councilPath, notesOf, type Council, type Settings } from '../api'
import { formatDate, formatToday } from '../i18n'
import { attention, councilLight } from '../light'
import { useLoad } from '../useLoad'

/**
 * Сводка: сколько советов в каком состоянии — светофором, что ждёт вас или упало, и все
 * советы. Состояние совета — самое важное из его этапов. Настройки — ради проектов: каталог заметок совета —
 * папка документации его проекта, и выгрузка в другой каталог потока не завершает.
 */
export function HomePage() {
  const { t } = useTranslation()
  const { state, retry } = useLoad(() => Promise.all([api.councils(), api.settings()]), [])

  return (
    <main className="main">
      <h1 className="page-title">{t('home.title')}</h1>
      <p className="page-sub">{formatToday()}</p>
      {state.kind === 'loading' && <div className="card muted section-gap">{t('common.loading')}</div>}
      {state.kind === 'error' && (
        <div className="card muted section-gap">
          {t('home.loadFailed')}{' '}
          <button className="btn-primary" onClick={retry}>{t('common.retry')}</button>
        </div>
      )}
      {state.kind === 'ok' && state.data[0].length === 0 && (
        <div className="card muted section-gap">{t('home.empty')}</div>
      )}
      {state.kind === 'ok' && state.data[0].length > 0 && <Summary councils={state.data[0]} settings={state.data[1]} />}
    </main>
  )
}

/** Плитки «Общей картины»: зелёная — идёт или готово, белая — черновики, жёлтая, красная. */
const TILES = ['go', 'idle', 'yours', 'failed'] as const

function Summary({ councils, settings }: Readonly<{ councils: Council[]; settings: Settings }>) {
  const { t } = useTranslation()
  const lights = councils.map(council => councilLight(council, notesOf(council, settings)))
  const tile = (kind: (typeof TILES)[number]) =>
    lights.filter(light => (kind === 'go' ? light === 'running' || light === 'done' : light === kind)).length
  const streams = councils.reduce((sum, council) => sum + (council.streams?.length ?? 0), 0)
  const pending = councils.flatMap(council => attention(council, notesOf(council, settings)).map(item => ({ ...item, council })))

  return (
    <>
      <section className="overview" aria-labelledby="overview-title">
        <h2 id="overview-title" className="overview-title">{t('home.overview')}</h2>
        <ul className="totals">
          <li className="total">
            <span className="total-num">{councils.length}</span>
            <span className="total-label">{t('home.councils', { count: councils.length })}</span>
          </li>
          <li className="total">
            <span className="total-num">{streams}</span>
            <span className="total-label">{t('home.streams', { count: streams })}</span>
          </li>
        </ul>
        <ul className="tiles">
          {TILES.map(kind => (
            <li key={kind} className={`tile ${kind === 'go' ? 'running' : kind}`}>
              <span className="tile-num">{tile(kind)}</span>
              <span className="tile-label">{t(`home.tile.${kind}`)}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="attention-title">
        <div className="section-head">
          <h2 id="attention-title" className="section-title">{t('home.attention', { count: pending.length })}</h2>
          <Legend />
        </div>
        {pending.length === 0
          ? <p className="muted">{t('home.calm')}</p>
          : (
            <ul className="attention-grid">
              {pending.map(item => (
                <li key={`${item.council.id}:${item.what}:${item.group ?? ''}`}>
                  <Link to={item.to} className={`attention-card ${item.light}`}>
                    <p className="attention-caps">{t(`attention.${item.what}`, { group: item.group })}</p>
                    <p className="attention-title">{item.council.name || t('council.untitled')}</p>
                    <p className="attention-meta">{t(`attention.${item.what}.hint`)}</p>
                    <span className="corner" aria-hidden="true">{item.light === 'failed' ? '!' : '?'}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
      </section>

      <section aria-labelledby="all-title">
        <div className="section-head">
          <h2 id="all-title" className="section-title">{t('home.all')}</h2>
        </div>
        <div className="card-grid">
          {councils.map((council, i) => (
            <Link key={council.id} to={councilPath(council.id)} className="card">
              <div className="card-head">
                <span className="card-name">{council.name || t('council.untitled')}</span>
              </div>
              <div className="council-light">
                <span className={`light-dot ${lights[i]}`} aria-hidden="true" />
                {t(`home.light.${lights[i]}`)}
              </div>
              <div className="muted">
                {t('home.meta', { judge: council.judge, count: council.participants.length,
                                  updated: formatDate(council.updated_at) })}
              </div>
            </Link>
          ))}
        </div>
      </section>
    </>
  )
}

/** Что значат цвета. Белый — черновики — на плитке подписан, здесь его нет, как и в макете. */
function Legend() {
  const { t } = useTranslation()
  return (
    <ul className="legend" aria-label={t('legend.title')}>
      <li><span className="light-dot running" aria-hidden="true" />{t('legend.go')}</li>
      <li><span className="light-dot yours" aria-hidden="true" />{t('legend.yours')}</li>
      <li><span className="light-dot failed" aria-hidden="true" />{t('legend.failed')}</li>
    </ul>
  )
}
