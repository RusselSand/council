import { useState } from 'react'
import { Link, Outlet, useNavigate } from 'react-router'
import { api, runPath } from './api'

export function App() {
  const nav = useNavigate()
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState(false)

  const newRun = async () => {
    setCreating(true); setError(false)
    try {
      const { id } = await api.createRun()
      nav(runPath(id))
    } catch {
      setError(true)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <Link to="/" className="brand"><span className="brand-mark" />Spec Council</Link>
        <div className="header-actions">
          {error && <span className="error-text" role="alert">Не удалось создать бриф</span>}
          <button className="btn-primary" onClick={newRun} disabled={creating}>
            {creating ? 'Создаём…' : '+ Новый бриф'}
          </button>
        </div>
      </header>
      <main className="main"><Outlet /></main>
    </div>
  )
}
