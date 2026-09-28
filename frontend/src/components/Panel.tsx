import { useId, type ReactNode } from 'react'

/**
 * Раздел страницы на карточке: заголовок, пояснение, содержимое. С htmlFor заголовок
 * становится подписью поля внутри — отдельный label не нужен.
 */
export function Panel({ title, hint, htmlFor, large, children }: Readonly<{
  title: string; hint?: string; htmlFor?: string; large?: boolean; children: ReactNode
}>) {
  const titleId = useId()
  return (
    <section className="card panel" aria-labelledby={titleId}>
      <h2 id={titleId} className={large ? 'panel-title large' : 'panel-title'}>
        {htmlFor ? <label htmlFor={htmlFor}>{title}</label> : title}
      </h2>
      {hint && <p className="panel-hint">{hint}</p>}
      {children}
    </section>
  )
}
