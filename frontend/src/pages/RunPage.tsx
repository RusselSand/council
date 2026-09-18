import { useEffect, useState } from 'react'
import { Link, NavLink, useParams } from 'react-router'
import { api, isNotFound, runPath, type Run } from '../api'

export const STAGES = [
  { path: 'brief', label: 'Бриф' },
  { path: 'approaches', label: 'Подходы' },
  { path: 'decisions', label: 'Решения' },
  { path: 'spec', label: 'ТЗ и ревью' },
  { path: 'history', label: 'История' },
]

type State = { kind: 'loading' } | { kind: 'ok'; run: Run } | { kind: 'not_found' } | { kind: 'error' }

export function RunPage({ stage }: { stage: string }) {
  const { id = '' } = useParams()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true  // ответ для предыдущего id не должен перезаписать текущий
    setState({ kind: 'loading' })
    api.run(id)
      .then(run => active && setState({ kind: 'ok', run }))
      .catch(e => active && setState({ kind: isNotFound(e) ? 'not_found' : 'error' }))
    return () => { active = false }
  }, [id, attempt])
  const label = STAGES.find(s => s.path === stage)?.label

  if (state.kind === 'not_found') return (
    <>
      <h1 className="page-title">Проект не найден</h1>
      <p className="page-sub">Возможно, ссылка устарела. <Link to="/">К списку проектов</Link></p>
    </>
  )

  if (state.kind === 'error') return (
    <>
      <h1 className="page-title">Не удалось загрузить проект</h1>
      <p className="page-sub">Сервер недоступен или ответил ошибкой.</p>
      <button className="btn-primary" style={{ marginTop: 12 }} onClick={() => setAttempt(a => a + 1)}>Повторить</button>
    </>
  )

  return (
    <>
      <h1 className="page-title">{state.kind === 'ok' ? state.run.name : '…'}</h1>
      <nav className="tabs">
        {STAGES.map(s => <NavLink key={s.path} to={runPath(id, s.path)} className="tab">{s.label}</NavLink>)}
      </nav>
      <div className="card placeholder">{label} — заглушка</div>
    </>
  )
}
