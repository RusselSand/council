import { useCallback, useEffect, useState } from 'react'

export type Loaded<T> = { kind: 'loading' } | { kind: 'ok'; data: T } | { kind: 'error'; error: unknown }

/**
 * Данные страницы с сервера: загрузка, ошибка, повтор. Ответ на прежний запрос не
 * перезапишет новый. update правит уже загруженное — например, после правки на экране.
 */
export function useLoad<T>(load: () => Promise<T>, deps: readonly unknown[]) {
  const [state, setState] = useState<Loaded<T>>({ kind: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setState({ kind: 'loading' })
    load().then(
      data => active && setState({ kind: 'ok', data }),
      error => active && setState({ kind: 'error', error }),
    )
    return () => { active = false }
    // load пересоздаётся на каждый рендер; перезагрузку задают deps и повтор.
  }, [...deps, attempt])

  const retry = useCallback(() => setAttempt(a => a + 1), [])
  const update = useCallback((change: (data: T) => T) =>
    setState(s => (s.kind === 'ok' ? { kind: 'ok', data: change(s.data) } : s)), [])
  return { state, retry, update }
}
