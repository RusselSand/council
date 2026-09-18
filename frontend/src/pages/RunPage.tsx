import { useEffect, useState } from 'react'
import { Link, NavLink, useParams } from 'react-router'
import { api, type Run } from '../api'

export const STAGES = [
  { path: 'brief', label: 'Бриф' },
  { path: 'approaches', label: 'Подходы' },
  { path: 'decisions', label: 'Решения' },
  { path: 'spec', label: 'ТЗ и ревью' },
  { path: 'history', label: 'История' },
]

export function RunPage({ stage }: { stage: string }) {
  const { id = '' } = useParams()
  const [run, setRun] = useState<Run>()
  const [notFound, setNotFound] = useState(false)
  useEffect(() => {
    setRun(undefined); setNotFound(false)
    api.run(id).then(setRun).catch(() => setNotFound(true))
  }, [id])
  const label = STAGES.find(s => s.path === stage)?.label

  if (notFound) return (
    <>
      <h1 className="page-title">Проект не найден</h1>
      <p className="page-sub">Возможно, ссылка устарела. <Link to="/">К списку проектов</Link></p>
    </>
  )

  return (
    <>
      <h1 className="page-title">{run?.name ?? '…'}</h1>
      <nav className="tabs">
        {STAGES.map(s => <NavLink key={s.path} to={`/runs/${id}/${s.path}`} className="tab">{s.label}</NavLink>)}
      </nav>
      <div className="card placeholder">{label} — заглушка</div>
    </>
  )
}
