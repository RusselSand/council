import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Outlet, useNavigate } from 'react-router'
import { api, councilPath } from './api'
import { setLanguage } from './i18n'

export function App() {
  const { t, i18n } = useTranslation()
  const nav = useNavigate()
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState(false)
  const otherLanguage = i18n.language.startsWith('ru') ? 'en' : 'ru'

  const newCouncil = async () => {
    setCreating(true); setError(false)
    try {
      const { id } = await api.createCouncil()
      nav(councilPath(id))
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
          {error && <span className="error-text" role="alert">{t('header.createFailed')}</span>}
          <button className="btn-lang" onClick={() => setLanguage(otherLanguage)}
                  aria-label={t('header.switchLanguage')} title={t('header.switchLanguage')}>
            {otherLanguage.toUpperCase()}
          </button>
          <button className="btn-primary" onClick={newCouncil} disabled={creating}>
            {creating ? t('header.creating') : t('header.newCouncil')}
          </button>
        </div>
      </header>
      <main className="main"><Outlet /></main>
    </div>
  )
}
