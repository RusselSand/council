/** Общие мелочи текста для этапов совета. */

/** Текст без лишних пробелов — так его сравнивает и сервер. */
export const squash = (text: string) => text.trim().split(/\s+/).join(' ')

/** Коммит коротко; нет коммитов — прочерк. */
export const shortSha = (sha: string) => sha.slice(0, 8) || '—'

/** Номера фрагментов коротко: F1–F3, F5. */
export function fragmentRange(ids: number[]): string {
  const sorted = [...new Set(ids)].sort((a, b) => a - b)
  const parts: string[] = []
  let start = 0
  while (start < sorted.length) {
    let end = start
    while (end + 1 < sorted.length && sorted[end + 1] === sorted[end] + 1) end++
    parts.push(end - start >= 2
      ? `F${sorted[start]}–F${sorted[end]}`
      : sorted.slice(start, end + 1).map(id => `F${id}`).join(', '))
    start = end + 1
  }
  return parts.join(', ')
}
