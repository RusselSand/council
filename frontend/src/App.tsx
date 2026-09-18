import { Link, Outlet, useNavigate } from 'react-router'
import { api } from './api'

export function App() {
  const nav = useNavigate()
  const newRun = async () => { const { id } = await api.createRun(); nav(`/runs/${id}/brief`) }
  return (
    <div className="app">
      <header className="header">
        <Link to="/" className="brand"><span className="brand-mark" />Spec Council</Link>
        <button className="btn-primary" onClick={newRun}>+ Новый бриф</button>
      </header>
      <main className="main"><Outlet /></main>
    </div>
  )
}
