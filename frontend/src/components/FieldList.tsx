import type { Dispatch, SetStateAction } from 'react'

/** Поле списка — путь к рабочей копии или ссылка на макет; key — чтобы React не путал поля, когда одно убирают. */
export interface ListField { key: number; value: string }
let fieldKeys = 0
export const listField = (value = ''): ListField => ({ key: fieldKeys++, value })

/** Поля списка: каждое можно поправить или убрать (пока их больше min), добавить — пока их меньше max. */
export function FieldList({ fields, onFields, max, min = 1, locked, placeholder, label, removeLabel, addLabel }: Readonly<{
  fields: ListField[]; onFields: Dispatch<SetStateAction<ListField[]>>; max: number; min?: number; locked: boolean
  placeholder: string; label: (n: number) => string; removeLabel: (n: number) => string; addLabel: string
}>) {
  return (
    <div className="repo-paths">
      {fields.map((field, n) => (
        <div className="repo-path" key={field.key}>
          <input className="text-field" value={field.value} readOnly={locked} placeholder={placeholder}
                 aria-label={label(n + 1)}
                 onChange={e => {
                   const value = e.target.value
                   onFields(current => current.map(f => f.key === field.key ? { ...f, value } : f))
                 }} />
          {fields.length > min && (
            <button type="button" className="btn-link repo-remove" disabled={locked} aria-label={removeLabel(n + 1)}
                    onClick={() => onFields(current => current.filter(f => f.key !== field.key))}>×</button>
          )}
        </div>
      ))}
      {fields.length < max && (
        <button type="button" className="btn-link repo-add" disabled={locked}
                onClick={() => onFields(current => [...current, listField()])}>{addLabel}</button>
      )}
    </div>
  )
}
