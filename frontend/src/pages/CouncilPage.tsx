import { useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useOutletContext, useParams } from 'react-router'
import { api, councilPath, isNotFound, type Council, type CouncilPatch, type CouncilStatus } from '../api'
import type { Layout } from '../App'
import { useAutosave } from '../useAutosave'
import { useInterval } from '../useInterval'
import { useLoad } from '../useLoad'
import { BriefStage } from './BriefStage'
import { SlicesStage } from './SlicesStage'

export const STAGES = ['brief', 'slices', 'structure', 'spec', 'history'] as const

/** Как часто спрашивать сервер, пока идёт нарезка: ходы моделей длятся минутами. */
export const POLL_MS = 2000
export type Stage = (typeof STAGES)[number]

/** Этап i пройден, если статус совета ушёл дальше него. «История» пройденной не бывает. */
const STATUS_ORDER: CouncilStatus[] = ['brief', 'slices', 'structure', 'review', 'ready']
const isDone = (stageIndex: number, status: CouncilStatus) => stageIndex < STATUS_ORDER.indexOf(status)

/** 404 на сам совет. 404 от настроек — обычная ошибка загрузки: совет-то есть, и повтор уместен. */
class CouncilMissing extends Error {}

const loadCouncil = (id: string) => Promise.all([
  api.council(id).catch((e: unknown) => Promise.reject(isNotFound(e) ? new CouncilMissing() : e)),
  api.settings(),
])

export function CouncilPage({ stage }: Readonly<{ stage: Stage }>) {
  const { id = '' } = useParams()
  // Свой экземпляр на каждый совет: очередь сохранения не перенесёт правки в чужой.
  return <CouncilView key={id} id={id} stage={stage} />
}

function CouncilView({ id, stage }: Readonly<{ id: string; stage: Stage }>) {
  const { t } = useTranslation()
  const { state, retry, update } = useLoad(() => loadCouncil(id), [id])
  const saver = useAutosave((patch: CouncilPatch) => api.updateCouncil(id, patch))
  const { schedule } = saver

  const council = state.kind === 'ok' ? state.data[0] : null
  const title = council && (council.name || t('council.untitled'))
  const setCrumb = useOutletContext<Layout | undefined>()?.setCrumb
  useEffect(() => {
    setCrumb?.(title)
    return () => setCrumb?.(null)
  }, [setCrumb, title])

  // Экран показывает правку сразу, сервер получает её чуть позже.
  const change = useCallback((patch: CouncilPatch, wait: number) => {
    update(([c, settings]) => [{ ...c, ...patch }, settings])
    schedule(patch, wait)
  }, [update, schedule])

  // С сервера берём только нарезку и статус: текст и название могут быть ещё не сохранены.
  const sliced = useCallback((fresh: Council) =>
    update(([c, settings]) => [{ ...c, status: fresh.status, slicing: fresh.slicing }, settings]), [update])
  useInterval(() => { api.council(id).then(sliced, () => { /* следующий опрос */ }) },
              council?.slicing?.state === 'running' ? POLL_MS : null)

  if (state.kind === 'error' && state.error instanceof CouncilMissing) return (
    <main className="main">
      <h1 className="page-title">{t('council.notFound')}</h1>
      <p className="page-sub">
        {t('council.notFoundHint')} <Link to="/">{t('council.backToList')}</Link>
      </p>
    </main>
  )

  if (state.kind === 'error') return (
    <main className="main">
      <h1 className="page-title">{t('council.loadFailed')}</h1>
      <p className="page-sub">{t('council.loadFailedHint')}</p>
      <button className="btn-primary" style={{ marginTop: 12 }} onClick={retry}>{t('common.retry')}</button>
    </main>
  )

  return (
    <>
      <nav className="stage-bar" aria-label={t('council.stages')}>
        {STAGES.map((s, i) => {
          const done = council !== null && isDone(i, council.status)
          return (
            <NavLink key={s} to={councilPath(id, s)} className={done ? 'tab done' : 'tab'}>
              {({ isActive }) => (
                <>
                  <span className="tab-num" aria-hidden="true">{done && !isActive ? '✓' : i + 1}</span>
                  {t(`stage.${s}`)}
                  {done && <span className="sr-only"> ({t('council.stageDone')})</span>}
                </>
              )}
            </NavLink>
          )
        })}
      </nav>
      <main className="main">
        <h1 className="sr-only">{title ?? t('common.loading')}</h1>
        {state.kind === 'loading' && <div className="card muted">{t('common.loading')}</div>}
        {state.kind === 'ok' && stage === 'brief' && (
          <BriefStage council={state.data[0]} settings={state.data[1]} onChange={change}
                      onStart={sliced} saver={saver} />
        )}
        {state.kind === 'ok' && stage === 'slices' && (
          <SlicesStage council={state.data[0]} settings={state.data[1]} onStart={sliced} />
        )}
        {state.kind === 'ok' && stage !== 'brief' && stage !== 'slices' && (
          <div className="card placeholder">{t('council.stub', { stage: t(`stage.${stage}`) })}</div>
        )}
      </main>
    </>
  )
}
