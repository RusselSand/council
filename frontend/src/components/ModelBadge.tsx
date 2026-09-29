import { useTranslation } from 'react-i18next'
import type { Model } from '../api'

/** Модель: плашка с буквой, полное имя и CLI, через которую она работает, — или что её не запустить. */
export function ModelBadge({ model, compact }: Readonly<{ model: Model; compact?: boolean }>) {
  const { t } = useTranslation()
  // Для узких колонок: плашка и короткое имя.
  if (compact) return (
    <span className="model-badge">
      <span className={`model-tile ${model.cli}`} aria-hidden="true">{model.short_name.charAt(0)}</span>
      <span className="model-name">{model.short_name}</span>
    </span>
  )
  return (
    <span className="model-badge">
      <span className={`model-tile ${model.cli}`} aria-hidden="true">{model.short_name.charAt(0)}</span>
      <span className="model-text">
        <span className="model-name">{model.display_name}</span>
        <span className="model-cli">
          {model.cli} cli{!model.available && <span className="model-offline"> · {t('model.offline')}</span>}
        </span>
      </span>
    </span>
  )
}

/**
 * Модель в списке выбора: вся строка — подпись чекбокса. Невыбранная приглушена.
 * locked — сейчас не переключить (например, участников и так минимум), но выглядит как
 * обычный чекбокс: серая галочка читалась бы как «модель недоступна».
 */
export function ModelCheckbox({ model, checked, locked, onChange }: Readonly<{
  model: Model; checked: boolean; locked?: boolean; onChange: (checked: boolean) => void
}>) {
  return (
    <label className={checked ? 'model-option' : 'model-option off'}>
      <ModelBadge model={model} />
      <input type="checkbox" checked={checked} aria-disabled={locked || undefined}
             onChange={e => { if (!locked) onChange(e.target.checked) }} />
    </label>
  )
}
