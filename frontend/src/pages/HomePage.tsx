import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, runPath, STATUS_LABEL, type Run } from '../api'

type State = { kind: 'loading' } | { kind: 'ok'; runs: Run[] } | { kind: 'error' }

export function HomePage() {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setState({ kind: 'loading' })
    api.runs()
      .then(runs => active && setState({ kind: 'ok', runs }))
      .catch(() => active && setState({ kind: 'error' }))
    return () => { active = false }
  }, [attempt])

  return (
    <>
      <h1 className="page-title">Проекты</h1>
      <p className="page-sub">От брифа до согласованного ТЗ.</p>
      <div className="card-grid">
        {state.kind === 'loading' && <div className="card muted">Загрузка…</div>}
        {state.kind === 'error' && (
          <div className="card muted">
            Не удалось загрузить проекты: сервер недоступен или ответил ошибкой.{' '}
            <button className="btn-primary" onClick={() => setAttempt(a => a + 1)}>Повторить</button>
          </div>
        )}
        {state.kind === 'ok' && state.runs.map(r => (
          <Link key={r.id} to={runPath(r.id)} className="card">
            <div className="card-head">
              <span className="card-name">{r.name}</span>
              <span className={`pill ${r.status}`}>{STATUS_LABEL[r.status]}</span>
            </div>
            <div className="muted">Автор: {r.author} · Ревьюер: {r.reviewer} · {r.updated_at}</div>
          </Link>
        ))}
        {state.kind === 'ok' && state.runs.length === 0 && (
          <div className="card muted">Нет проектов — нажмите «Новый бриф».</div>
        )}
      </div>
    </>
  )
}
