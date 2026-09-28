import type { Model } from '../api'

/** Модель: плашка с буквой, полное имя и CLI, через которую она работает. */
export function ModelBadge({ model }: Readonly<{ model: Model }>) {
  return (
    <span className="model-badge">
      <span className={`model-tile ${model.cli}`} aria-hidden="true">{model.short_name.charAt(0)}</span>
      <span className="model-text">
        <span className="model-name">{model.display_name}</span>
        <span className="model-cli">{model.cli} cli</span>
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
