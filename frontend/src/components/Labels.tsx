import { Fragment } from 'react'
import { useTranslation } from 'react-i18next'
import { LABELS, type Label, type LabeledFragment } from '../api'

/** Один тип из пяти; выбранный — в цвете своего типа. */
export function LabelChips({ value, onChange, name }: Readonly<{
  value: Label; onChange: (label: Label) => void; name: string
}>) {
  const { t } = useTranslation()
  return (
    <div className="label-chips" role="radiogroup" aria-label={name}>
      {LABELS.map(option => (
        <button key={option} type="button" role="radio" aria-checked={option === value}
                className={option === value ? `label-chip label-${option} selected` : 'label-chip'}
                onClick={() => { if (option !== value) onChange(option) }}>
          {t(`label.${option}`)}
        </button>
      ))}
    </div>
  )
}

/** Цвета типов и сколько фрагментов каждого. */
export function LabelLegend({ fragments }: Readonly<{ fragments: LabeledFragment[] }>) {
  const { t } = useTranslation()
  return (
    <ul className="label-legend">
      {LABELS.map(label => (
        <li key={label} className={`label-${label}`}>
          <span className="label-swatch" aria-hidden="true" />
          {t(`label.${label}`)} · {fragments.filter(f => f.label === label).length}
        </li>
      ))}
    </ul>
  )
}

/**
 * Исходный текст целиком, фрагменты подсвечены цветом своего типа. Промежутки между ними —
 * как в исходнике: текст не меняется, только разрезан и помечен.
 */
export function SlicedText({ text, fragments }: Readonly<{ text: string; fragments: LabeledFragment[] }>) {
  const { t } = useTranslation()
  let position = 0
  return (
    <p className="sliced-text">
      {fragments.map(fragment => {
        const at = text.indexOf(fragment.text, position)
        // Не нашёлся (текст правили вручную) — просто следом, через пробел.
        const gap = at < 0 ? ' ' : text.slice(position, at)
        if (at >= 0) position = at + fragment.text.length
        return (
          <Fragment key={fragment.id}>
            {gap}
            <mark className={`fragment-mark label-${fragment.label}`}
                  title={`F${fragment.id} · ${t(`label.${fragment.label}`)}`}>{fragment.text}</mark>
          </Fragment>
        )
      })}
      {text.slice(position)}
    </p>
  )
}
