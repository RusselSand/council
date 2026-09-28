/** Выпадающий список в рамке с мелкой подписью сверху. */
export function SelectField({ label, value, options, onChange }: Readonly<{
  label: string; value: string; options: readonly { value: string; label: string }[]
  onChange: (value: string) => void
}>) {
  return (
    <label className="select-field">
      <span className="select-label">{label}</span>
      <select value={value} onChange={e => onChange(e.target.value)}>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  )
}
