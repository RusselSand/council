import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, STATUS_LABEL, type Run } from '../api'

export function HomePage() {
  const [runs, setRuns] = useState<Run[]>([])
  useEffect(() => { api.runs().then(setRuns).catch(() => {}) }, [])

  return (
    <>
      <h1 className="page-title">Проекты</h1>
      <p className="page-sub">От брифа до согласованного ТЗ.</p>
      <div className="card-grid">
        {runs.map(r => (
          <Link key={r.id} to={`/runs/${r.id}/brief`} className="card">
            <div className="card-head">
              <span className="card-name">{r.name}</span>
              <span className={`pill ${r.status}`}>{STATUS_LABEL[r.status]}</span>
            </div>
            <div className="muted">Автор: {r.author} · Ревьюер: {r.reviewer} · {r.updated_at}</div>
          </Link>
        ))}
        {runs.length === 0 && <div className="card muted">Нет проектов — нажмите «Новый бриф».</div>}
      </div>
    </>
  )
}
