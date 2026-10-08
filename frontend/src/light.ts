import {
  councilPath, outcomeReady, seeking, structureIsStale,
  type Council, type DecisionAnalysis, type IdeaDiscovery, type OutcomeDiscovery, type ProposalDiscovery,
  type QuestionDiscovery, type Slicing, type Stream, type Structure,
} from './api'
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
type Run = Slicing | Structure | IdeaDiscovery | QuestionDiscovery | ProposalDiscovery | DecisionAnalysis
  | OutcomeDiscovery

const ofRun = (run: Run | null): Light | null => {
  if (run?.state === 'running') return 'running'
  if (run?.state === 'failed') return 'failed'
  return null
}

/**
 * Где поток: пока нет идеи — на группе, пока не отобраны вопросы — на вопросах, пока не выбраны
 * варианты — на вариантах, пока не зафиксированы решения — на решениях, дальше — итоги.
 */
export const currentStep = (stream: Stream): ChainStep => {
  if (!stream.idea) return 'group'
  if (!stream.scope) return 'questions'
  if (!stream.choices) return 'options'
  return stream.decisions ? 'outcomes' : 'decisions'
}

/**
 * Шаг цепочки потока. Пройденный — зелёный; на текущем — ход совета (идёт или упал) или ваш.
 * Утверждённая идея проходит шаг, и прежний поиск идеи, даже упавший, уже не важен. Итоги —
 * последний шаг: собраны и все готовы — зелёные; какой-то держит открытый вопрос или пробел —
 * ход за вами (решить его), как и если итоги ещё не собирали.
 */
export const chainLight = (stream: Stream, step: ChainStep): Light => {
  if (step === 'group') return stream.idea ? 'done' : ofRun(stream.discovery) ?? 'yours'
  if (step === 'questions' && stream.idea) return stream.scope ? 'done' : ofRun(stream.questions) ?? 'yours'
  if (step === 'options' && stream.scope) return stream.choices ? 'done' : ofRun(stream.proposals) ?? 'yours'
  if (step === 'decisions' && stream.choices) return stream.decisions ? 'done' : ofRun(stream.analysis) ?? 'yours'
  if (step === 'outcomes' && stream.decisions) {
    const outcomes = stream.outcomes
    return ofRun(outcomes) ?? (outcomes?.outcomes.every(outcomeReady) ? 'done' : 'yours')
  }
  return 'idle'
}

/** Поток — цвет его текущего шага. */
export const streamLight = (stream: Stream): Light => chainLight(stream, currentStep(stream))

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
    case 'structure': {
      if (!structure) return 'idle'
      const run = ofRun(structure)
      if (run) return run
      if (!streams) return 'yours'
      // Устарели — разложить заново. Пока ИИ ищет идеи, нельзя (сервер ответит 423): ход не ваш.
      return structureIsStale(council) && !seeking(council) ? 'yours' : 'done'
    }
    case 'streams':
      if (!streams) return 'idle'
      // По устаревшим группам идеи не утверждают и не ищут заново: сначала разложить заново.
      if (structureIsStale(council)) return seeking(council) ? 'running' : 'idle'
      return strongest(streams.map(streamLight))
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
    | 'ideaFailed' | 'ideaWaits' | 'questionsFailed' | 'questionsWait' | 'optionsFailed' | 'optionsWait'
    | 'decisionsFailed' | 'decisionsWait' | 'outcomesFailed' | 'outcomesWait'
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
  // Устаревшие группы идею не утвердят: сначала — разложить заново. А это нельзя, пока ИИ
  // ищет идеи (сервер ответит 423): тогда ждём его и ничего не предлагаем.
  else if (structure?.state === 'done' && structureIsStale(council)) {
    if (!seeking(council)) add('yours', 'groupsStale', councilPath(id, 'structure'))
  } else if (structure?.state === 'done' && !streams) add('yours', 'groupsReady', councilPath(id, 'structure'))
  else if (structure?.state === 'done') {
    for (const stream of streams ?? []) {
      const to = councilPath(id, `streams/${stream.group}`)
      const light = streamLight(stream)
      const step = currentStep(stream)
      const where = step === 'group' ? 'idea' : step
      if (light === 'failed') add('failed', `${where}Failed`, to, stream.group)
      else if (light === 'yours') add('yours', where === 'idea' ? 'ideaWaits' : `${where}Wait`, to, stream.group)
    }
  }
  return items
}
