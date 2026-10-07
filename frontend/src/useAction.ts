import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, type Council } from './api'

/** Чем объяснить отказ, если сервер своих слов не дал. */
type Failed = 'start.failed' | 'groups.editFailed' | 'idea.approveFailed' | 'questions.approveFailed'
  | 'options.approveFailed'

/**
 * Действие с кнопки, которое сервер может отклонить: запуск хода совета, правка групп,
 * утверждение идеи или вопросов. Пока идёт — busy, отказ сервера — error словами сервера,
 * иначе — failed. act может вернуть null — делать не стали (например, не сохранился текст).
 * then — что сделать после удачи, например перейти на этап. go отвечает, удалось ли. Второе
 * действие, пока идёт первое, не начинается: ответы пришли бы не по порядку, и экран
 * показал бы промежуточный.
 */
export function useAction(onDone: (council: Council) => void, failed: Failed = 'start.failed') {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const running = useRef(false)  // busy доходит до кнопок только с отрисовкой, а это — сразу

  const go = async (act: () => Promise<Council | null>, then?: () => void): Promise<boolean> => {
    if (running.current) return false
    running.current = true
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
      running.current = false
      setBusy(false)
    }
  }
  return { busy, error, go }
}
