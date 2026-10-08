import { describe, expect, it } from 'vitest'
import css from './styles.css?raw'

/**
 * Контраст текста в палитре (WCAG 2.1): мелкий текст — не меньше 4.5:1 к своему фону. Цвета
 * берутся из :root в styles.css, так что правка токена, которая уронит контраст, упадёт здесь.
 * Настоящее содержимое styles.css тестам отдаёт test.css.include в vite.config.ts: без него
 * Vitest подменяет CSS пустой строкой, даже ?raw.
 */
const root = css.slice(css.indexOf(':root {'), css.indexOf('}', css.indexOf(':root {')))
const tokens = new Map([...root.matchAll(/--([\w-]+):\s*(#[0-9a-f]{3,6})\b/gi)].map(m => [m[1], m[2]]))

const hex = (value: string) => {
  const full = value.length === 4 ? `#${[...value.slice(1)].map(c => c + c).join('')}` : value
  return [1, 3, 5].map(i => parseInt(full.slice(i, i + 2), 16) / 255)
}
const luminance = (value: string) => {
  const [r, g, b] = hex(value).map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const color = (name: string) => (name.startsWith('#') ? name : tokens.get(name) ?? '')
const ratio = (text: string, background: string) => {
  const [a, b] = [luminance(color(text)), luminance(color(background))].sort((x, y) => y - x)
  return (a + 0.05) / (b + 0.05)
}

describe('контраст текста', () => {
  it.each([
    ...['fg', 'fg-soft', 'fg-muted', 'wait-text', 'stop-text', 'go-text']
      .flatMap(text => ['surface', 'bg', 'surface-sunken'].map(background => [text, background])),
    ['#ffffff', 'go'], ['#ffffff', 'stop'], ['wait-ink', 'wait'], ['fg', 'surface'],
    ['wait-text', 'wait-soft'], ['go-text', 'go-soft'], ['stop-text', 'stop-soft'],
    ['ink-muted', 'ink'], ['go-bright', 'ink'], ['wait-bright', 'ink'], ['stop-bright', 'ink'],
  ])('%s на %s — не меньше 4.5:1', (text, background) => {
    expect(tokens.size).toBeGreaterThan(10)
    expect(ratio(text, background)).toBeGreaterThanOrEqual(4.5)
  })
})
