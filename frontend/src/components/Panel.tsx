import { useId, type ReactNode } from 'react'

/**
 * Раздел страницы на карточке: заголовок, пояснение, содержимое. С htmlFor заголовок
 * становится подписью поля внутри — отдельный label не нужен. aside — справа от заголовка
 * (значок, состояние). caps — мелкий заголовок капсом, для списков.
 */
export function Panel({ title, hint, htmlFor, large, caps, aside, children }: Readonly<{
  title: string; hint?: string; htmlFor?: string; large?: boolean; caps?: boolean
  aside?: ReactNode; children: ReactNode
}>) {
  const titleId = useId()
  let size = ''
  if (large) size = ' large'
  else if (caps) size = ' caps'
  return (
    <section className="card panel" aria-labelledby={titleId}>
      <div className="panel-head">
        <h2 id={titleId} className={`panel-title${size}`}>
          {htmlFor ? <label htmlFor={htmlFor}>{title}</label> : title}
        </h2>
        {aside}
      </div>
      {hint && <p className="panel-hint">{hint}</p>}
      {children}
    </section>
  )
}
