import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useParams } from 'react-router'
import { api, councilPath, isNotFound, type Council } from '../api'

export const STAGES = ['brief', 'approaches', 'decisions', 'spec', 'history'] as const
export type Stage = (typeof STAGES)[number]

type State =
  | { kind: 'loading' } | { kind: 'ok'; council: Council } | { kind: 'not_found' } | { kind: 'error' }

export function CouncilPage({ stage }: { stage: Stage }) {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true  // ответ для предыдущего id не должен перезаписать текущий
    setState({ kind: 'loading' })
    api.council(id)
      .then(council => active && setState({ kind: 'ok', council }))
      .catch(e => active && setState({ kind: isNotFound(e) ? 'not_found' : 'error' }))
    return () => { active = false }
  }, [id, attempt])

  if (state.kind === 'not_found') return (
    <>
      <h1 className="page-title">{t('council.notFound')}</h1>
      <p className="page-sub">
        {t('council.notFoundHint')} <Link to="/">{t('council.backToList')}</Link>
      </p>
    </>
  )

  if (state.kind === 'error') return (
    <>
      <h1 className="page-title">{t('council.loadFailed')}</h1>
      <p className="page-sub">{t('council.loadFailedHint')}</p>
      <button className="btn-primary" style={{ marginTop: 12 }}
              onClick={() => setAttempt(a => a + 1)}>{t('common.retry')}</button>
    </>
  )

  return (
    <>
      <h1 className="page-title">{state.kind === 'ok' ? state.council.name || t('council.untitled') : '…'}</h1>
      <nav className="tabs">
        {STAGES.map(s => (
          <NavLink key={s} to={councilPath(id, s)} className="tab">{t(`stage.${s}`)}</NavLink>
        ))}
      </nav>
      <div className="card placeholder">{t('council.stub', { stage: t(`stage.${stage}`) })}</div>
    </>
  )
}
