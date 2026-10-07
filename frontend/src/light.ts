import { councilPath, structureIsStale, type Council, type IdeaDiscovery, type Slicing, type Stream, type Structure } from './api'
import type { Stage } from './pages/CouncilPage'

/**
 * Светофор: в каком состоянии совет, этап, поток или шаг цепочки. Цвета — как в легенде:
 * зелёный — «идёт / готово» (running, done), жёлтый — ход за вами (yours), красный — ход
 * модели упал (failed), белый — ещё не начато или ждёт следующего шага (idle).
 */
export type Light = 'running' | 'done' | 'yours' | 'failed' | 'idle'

/** Шаги цепочки потока. Работает пока первый — группа и её идея. */
export const CHAIN = ['group', 'questions', 'options', 'decisions', 'outcomes'] as const
export type ChainStep = (typeof CHAIN)[number]

/** Что важнее показать, если состояний несколько: сначала то, что требует человека. */
const ORDER: Light[] = ['failed', 'yours', 'running', 'done', 'idle']
export const strongest = (lights: Light[]): Light => ORDER.find(light => lights.includes(light)) ?? 'idle'

/** Ход модели: идёт — зелёный, упал — красный. Готов или не было — решает этап. */
const ofRun = (run: Slicing | Structure | IdeaDiscovery | null): Light | null => {
  if (run?.state === 'running') return 'running'
  if (run?.state === 'failed') return 'failed'
  return null
}

/** Поток: ищет идею, упал, ждёт утверждения идеи или — утверждена — ждёт следующего шага. */
export const streamLight = (stream: Stream): Light =>
  ofRun(stream.discovery) ?? (stream.idea ? 'idle' : 'yours')

/** Шаг цепочки потока. Дальше идеи шаги пока не готовы — белые. */
export const chainLight = (stream: Stream, step: ChainStep): Light => {
  if (step !== 'group') return 'idle'
  return stream.idea ? 'done' : streamLight(stream)
}

/**
 * Этап совета. Ввод готов, когда текст нарезали; нарезка — когда разложили по группам;
 * группы — когда подтвердили и они не устарели. Готовый ход без следующего — ваш ход.
 */
export function stageLight(council: Council, stage: Stage): Light {
  const { slicing, structure, streams } = council
  switch (stage) {
    case 'brief':
      return slicing ? 'done' : 'idle'
    case 'slices':
      if (!slicing) return 'idle'
      return ofRun(slicing) ?? (structure ? 'done' : 'yours')
    case 'structure':
      if (!structure) return 'idle'
      return ofRun(structure) ?? (streams && !structureIsStale(council) ? 'done' : 'yours')
    case 'streams':
      return streams ? strongest(streams.map(streamLight)) : 'idle'
    case 'history':
      return 'idle'
  }
}

/** Совет целиком: самое важное из состояний его этапов. Нетронутый — белый, черновик. */
export const councilLight = (council: Council): Light =>
  strongest((['brief', 'slices', 'structure', 'streams'] as const).map(stage => stageLight(council, stage)))

/** Что в совете требует человека: его ход или упавший ход модели — и куда за этим идти. */
export interface Attention {
  light: 'yours' | 'failed'
  what: 'slicingFailed' | 'slicesDone' | 'groupingFailed' | 'groupsStale' | 'groupsReady'
    | 'ideaFailed' | 'ideaWaits'
  /** Буква потока — у того, что про поток. */
  group?: string
  to: string
}

export function attention(council: Council): Attention[] {
  const { id, slicing, structure, streams } = council
  const items: Attention[] = []
  const add = (light: Attention['light'], what: Attention['what'], to: string, group?: string) =>
    items.push({ light, what, to, ...(group ? { group } : {}) })

  if (slicing?.state === 'failed') add('failed', 'slicingFailed', councilPath(id, 'slices'))
  else if (slicing?.state === 'done' && !structure) add('yours', 'slicesDone', councilPath(id, 'slices'))

  if (structure?.state === 'failed') add('failed', 'groupingFailed', councilPath(id, 'structure'))
  else if (structure?.state === 'done' && structureIsStale(council)) add('yours', 'groupsStale', councilPath(id, 'structure'))
  else if (structure?.state === 'done' && !streams) add('yours', 'groupsReady', councilPath(id, 'structure'))
  // Устаревшие группы идею не утвердят: сначала — разложить заново.
  else if (structure?.state === 'done') {
    for (const stream of streams ?? []) {
      const to = councilPath(id, `streams/${stream.group}`)
      if (stream.discovery?.state === 'failed') add('failed', 'ideaFailed', to, stream.group)
      else if (streamLight(stream) === 'yours') add('yours', 'ideaWaits', to, stream.group)
    }
  }
  return items
}
