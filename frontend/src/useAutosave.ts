import { useCallback, useEffect, useRef, useState } from 'react'
import { useBlocker } from 'react-router'

export type SaveState = 'idle' | 'saving' | 'error'

const isEmpty = (patch: object) => Object.keys(patch).length === 0

const isMap = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

/**
 * Новая правка поверх старой. Словари сливаются по ключам: две правки типов разных
 * фрагментов, пока идёт запрос, не затирают друг друга. Всё остальное просто заменяется.
 */
export const merge = <P extends object>(older: P, newer: P): P => {
  const out = { ...older } as Record<string, unknown>
  for (const [key, value] of Object.entries(newer)) {
    const before = out[key]
    out[key] = isMap(before) && isMap(value) ? { ...before, ...value } : value
  }
  return out as P
}

/**
 * Сохраняет правки без кнопки «Сохранить». Правки копятся и уходят одним запросом через
 * `wait` мс; следующий запрос — только после ответа на предыдущий, поэтому старое значение
 * не перезапишет новое. Непринятая правка остаётся в очереди и уйдёт со следующей или по
 * flush. flush отправляет всё сразу и отвечает, сохранилось ли.
 *
 * Очередь живёт вместе со страницей, поэтому уйти с неё, пока есть несохранённое, нельзя:
 * переход внутри приложения ждёт сохранения, а если оно не прошло, страница остаётся на
 * месте с ошибкой (leaving) — повторить или уйти без правок решает человек. Закрытие
 * вкладки браузер переспрашивает сам.
 */
export function useAutosave<P extends object>(send: (patch: P) => Promise<unknown>) {
  const [state, setState] = useState<SaveState>('idle')
  const pending = useRef<P>({} as P)
  const running = useRef<Promise<boolean> | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const sendRef = useRef(send)
  useEffect(() => { sendRef.current = send })

  const hasUnsaved = useCallback(() => running.current !== null || !isEmpty(pending.current), [])

  const flush = useCallback((): Promise<boolean> => {
    clearTimeout(timer.current)
    if (running.current !== null) return running.current.then(() => flush())
    if (isEmpty(pending.current)) return Promise.resolve(true)

    const patch = pending.current
    pending.current = {} as P
    setState('saving')
    const run = sendRef.current(patch).then(() => true, () => {
      pending.current = merge(patch, pending.current)  // новые правки важнее упавших
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
    pending.current = merge(pending.current, patch)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => { void flush() }, wait)
  }, [flush])

  const blocker = useBlocker(hasUnsaved)
  const blockerRef = useRef(blocker)
  useEffect(() => { blockerRef.current = blocker })
  const leaving = blocker.state === 'blocked'

  /** Сохранить; если в этот момент ждёт переход — после сохранения пропустить его. */
  const retry = useCallback(() => flush().then(saved => {
    const current = blockerRef.current
    if (saved && current.state === 'blocked') current.proceed()
    return saved
  }), [flush])

  useEffect(() => { if (leaving) void retry() }, [leaving, retry])

  const leaveAnyway = useCallback(() => {
    clearTimeout(timer.current)
    pending.current = {} as P
    const current = blockerRef.current
    if (current.state === 'blocked') current.proceed()
  }, [])

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (hasUnsaved()) event.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => {
      window.removeEventListener('beforeunload', warn)
      void flush()  // последняя попытка, если страницу сняли мимо роутера
    }
  }, [flush, hasUnsaved])

  return { state, schedule, flush, retry, leaving, leaveAnyway }
}

export type Autosave<P extends object> = ReturnType<typeof useAutosave<P>>
