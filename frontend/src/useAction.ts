import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, type Council } from './api'

/**
 * Действие с кнопки, которое сервер может отклонить: запуск хода совета или правка групп.
 * Пока идёт — busy, отказ сервера — error словами сервера, иначе — failed. act может вернуть
 * null — делать не стали (например, не сохранился текст). then — что сделать после удачи,
 * например перейти на этап. go отвечает, удалось ли.
 */
export function useAction(onDone: (council: Council) => void,
                          failed: 'start.failed' | 'groups.editFailed' = 'start.failed') {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const go = async (act: () => Promise<Council | null>, then?: () => void): Promise<boolean> => {
    setBusy(true); setError(null)
    try {
      const council = await act()
      if (!council) return false
      onDone(council)
      then?.()
      return true
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t(failed))
      return false
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, go }
}
