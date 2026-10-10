import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Light } from '../light'

/** Карточка слайдера: номер на фишке, её формулировка в подсказке и состояние светофором. */
export interface Slide { id: string; title: string; light: Light }

/**
 * Карточки по одной: вопрос, решение, итог, задача. Над ними — фишки всех карточек с состоянием
 * (цвет и слово для скринридера) и счёт готовых, по фишке — переход; ← → — соседние. Фишки — вкладки:
 * в их ряду стрелки, Home и End переводят и карточку, и фокус. start — с какой открыть: обычно первая,
 * где ещё нет ответа.
 */
export function Slider({ slides, label, start = 0, children }: Readonly<{
  slides: Slide[]; label: string; start?: number; children: (index: number) => ReactNode
}>) {
  const { t } = useTranslation()
  const id = useId()
  const tabs = useRef<(HTMLButtonElement | null)[]>([])
  const [chosen, setChosen] = useState(start)
  if (slides.length === 0) return null
  const last = slides.length - 1
  const index = Math.min(Math.max(chosen, 0), last)
  const done = slides.filter(slide => slide.light === 'done').length
  const go = (next: number) => setChosen(Math.min(Math.max(next, 0), last))
  // Как у вкладок WAI-ARIA: по кругу, и фокус — на открытую фишку, чтобы скринридер её назвал.
  const keys = (event: KeyboardEvent) => {
    const moves: Record<string, number> = { ArrowLeft: index === 0 ? last : index - 1,
                                            ArrowRight: index === last ? 0 : index + 1, Home: 0, End: last }
    const next = moves[event.key]
    if (next === undefined) return
    event.preventDefault()
    go(next)
    tabs.current[next]?.focus()
  }

  return (
    <section className="slider" aria-label={label}>
      <div className="slider-head">
        <div className="slider-chips" role="tablist" aria-label={label}>
          {slides.map((slide, n) => (
            <button key={slide.id} type="button" role="tab" id={`${id}-tab-${n}`} aria-controls={`${id}-panel`}
                    ref={tab => { tabs.current[n] = tab }} onKeyDown={keys}
                    aria-selected={n === index} tabIndex={n === index ? 0 : -1}
                    className={`slider-chip ${slide.light}${n === index ? ' active' : ''}`}
                    title={slide.title} onClick={() => go(n)}>
              <span className={`light-dot ${slide.light}`} aria-hidden="true" />
              {slide.id}
              <span className="sr-only">, {t(`slider.${slide.light}`)}</span>
            </button>
          ))}
        </div>
        <span className="slider-count">{t('slider.count', { done, total: slides.length })}</span>
        <span className="slider-nav">
          <button type="button" className="btn-secondary" disabled={index === 0} onClick={() => go(index - 1)}
                  aria-label={t('slider.previous')}>←</button>
          <button type="button" className="btn-secondary" disabled={index === last}
                  onClick={() => go(index + 1)} aria-label={t('slider.next')}>→</button>
        </span>
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${index}`} className="slider-panel">
        {children(index)}
      </div>
    </section>
  )
}

/** С какой карточки открыть: первая, где ещё нет ответа (ход за человеком), иначе — где ИИ работает, иначе первая. */
export const firstOpen = (slides: Slide[]): number => {
  const yours = slides.findIndex(slide => slide.light === 'yours' || slide.light === 'failed')
  if (yours >= 0) return yours
  const running = slides.findIndex(slide => slide.light === 'running')
  return Math.max(running, 0)
}
