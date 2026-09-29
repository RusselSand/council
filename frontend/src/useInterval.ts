import { useEffect, useRef } from 'react'

/** Вызывает callback каждые delay мс, пока delay не null. Всегда свежий callback, без перезапуска таймера. */
export function useInterval(callback: () => void, delay: number | null) {
  const saved = useRef(callback)
  useEffect(() => { saved.current = callback })
  useEffect(() => {
    if (delay === null) return
    const id = setInterval(() => saved.current(), delay)
    return () => clearInterval(id)
  }, [delay])
}
