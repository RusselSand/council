import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, type Council } from './api'

/**
 * Запуск хода совета с кнопки: пока идёт — busy, отказ сервера — error словами сервера.
 * start может вернуть null — запускать не стали (например, не сохранился текст). then —
 * что сделать после удачного запуска, например перейти на этап.
 */
export function useStart(onStart: (started: Council) => void) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const go = async (start: () => Promise<Council | null>, then?: () => void) => {
    setBusy(true); setError(null)
    try {
      const started = await start()
      if (started) {
        onStart(started)
        then?.()
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('start.failed'))
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, go }
}
