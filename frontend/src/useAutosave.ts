import { useCallback, useEffect, useRef, useState } from 'react'

export type SaveState = 'idle' | 'saving' | 'error'

const isEmpty = (patch: object) => Object.keys(patch).length === 0

/**
 * Сохраняет правки без кнопки «Сохранить». Правки копятся и уходят одним запросом через
 * `wait` мс; следующий запрос — только после ответа на предыдущий, поэтому старое значение
 * не перезапишет новое. Непринятая правка остаётся в очереди и уйдёт со следующей или по
 * flush. flush отправляет всё сразу и отвечает, сохранилось ли.
 */
export function useAutosave<P extends object>(send: (patch: P) => Promise<unknown>) {
  const [state, setState] = useState<SaveState>('idle')
  const pending = useRef<P>({} as P)
  const running = useRef<Promise<boolean> | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const sendRef = useRef(send)
  useEffect(() => { sendRef.current = send })

  const flush = useCallback((): Promise<boolean> => {
    clearTimeout(timer.current)
    if (running.current) return running.current.then(() => flush())
    if (isEmpty(pending.current)) return Promise.resolve(true)

    const patch = pending.current
    pending.current = {} as P
    setState('saving')
    const run = sendRef.current(patch).then(() => true, () => {
      pending.current = { ...patch, ...pending.current }  // новые правки важнее упавших
      return false
    }).then(saved => {
      running.current = null
      if (!saved) { setState('error'); return false }
      if (!isEmpty(pending.current)) return flush()
      setState('idle')
      return true
    })
    running.current = run
    return run
  }, [])

  const schedule = useCallback((patch: P, wait: number) => {
    pending.current = { ...pending.current, ...patch }
    clearTimeout(timer.current)
    timer.current = setTimeout(() => { void flush() }, wait)
  }, [flush])

  // Уход со страницы: несохранённое отправляем сразу, а закрытие вкладки переспрашиваем.
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (running.current || !isEmpty(pending.current)) event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => {
      window.removeEventListener('beforeunload', warn)
      void flush()
    }
  }, [flush])

  return { state, schedule, flush }
}
