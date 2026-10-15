import {
  councilPath, issueReady, researched, seeking, structureIsStale,
  type Council, type DecisionAnalysis, type Folders, type DecisionsSearch, type DesignScan, type IdeaDiscovery, type IssueDiscovery,
  type NotesDraft, type OutcomeDiscovery,
  type ProposalDiscovery, type QuestionDiscovery, type RepositoryScan, type Slicing, type Stream, type Structure,
} from './api'
import type { Stage } from './pages/CouncilPage'

/**
 * Светофор: в каком состоянии совет, этап, поток или шаг цепочки. Цвета — как в легенде:
 * зелёный — «идёт / готово» (running, done), жёлтый — ход за вами (yours), красный — ход
 * модели упал (failed), белый — ещё не начато или ждёт следующего шага (idle).
 */
export type Light = 'running' | 'done' | 'yours' | 'failed' | 'idle'

/**
 * Шаги цепочки потока. Первый — начало: идею утверждают ещё на этапе «Группы», исследование — на своём этапе, а
 * поток берёт его себе копией, когда его начинают.
 */
export const CHAIN = ['start', 'questions', 'options', 'decisions', 'outcomes', 'issues', 'notes'] as const
export type ChainStep = (typeof CHAIN)[number]

/** Что важнее показать, если состояний несколько: сначала то, что требует человека. */
const ORDER: Light[] = ['failed', 'yours', 'running', 'done', 'idle']
export const strongest = (lights: Light[]): Light => ORDER.find(light => lights.includes(light)) ?? 'idle'

/** Ход модели: идёт — зелёный, упал — красный. Готов или не было — решает этап. */
type Run = Slicing | Structure | IdeaDiscovery | RepositoryScan | DesignScan | DecisionsSearch | QuestionDiscovery
  | ProposalDiscovery | DecisionAnalysis | OutcomeDiscovery | IssueDiscovery | NotesDraft

const ofRun = (run: Run | null): Light | null => {
  if (run?.state === 'running') return 'running'
  if (run?.state === 'failed') return 'failed'
  return null
}

/**
 * Где поток: пока его не начали — в начале (идея и исследование), пока не отобраны вопросы — на вопросах, пока не выбраны
 * варианты — на вариантах, пока не зафиксированы решения — на решениях, пока итоги не утверждены —
 * на итогах, пока задачи не нарезаны и не готовы — на задачах, дальше — документация. Выгрузить
 * можно сразу после утверждения итогов: черновик документации уже переводится или упал — поток на ней.
 */
export const currentStep = (stream: Stream): ChainStep => {
  if (!stream.idea || !stream.design) return 'start'
  if (!stream.scope) return 'questions'
  if (!stream.choices) return 'options'
  if (!stream.decisions) return 'decisions'
  if (!stream.outcomes?.approved) return 'outcomes'
  if (ofRun(stream.notes_draft)) return 'notes'
  if (!stream.issues || stream.issues.state !== 'done') return 'issues'
  return issuesLight(stream.issues, stream) === 'done' ? 'notes' : 'issues'
}

/** Докуда цепочку можно открыть: до текущего шага, а с утверждёнными итогами — и документацию. */
export const reachable = (stream: Stream): ChainStep => stream.outcomes?.approved ? 'notes' : currentStep(stream)

/** Шаг можно открыть: пройденный и текущий, а итоги и задачи — и раньше, если есть сохранённые: их видно. */
export const openable = (stream: Stream, step: ChainStep): boolean =>
  CHAIN.indexOf(step) <= CHAIN.indexOf(reachable(stream))
  || (step === 'outcomes' && stream.saved_outcomes.length > 0)
  || (step === 'issues' && stream.saved_issues.length > 0)

/**
 * Поток выгружен — заметки к нынешним утверждённым итогам и в нынешний каталог (folders — пути из настроек):
 * собрали и утвердили другие итоги или каталог сменили — выгружать снова.
 */
export const exported = (stream: Stream, folders: Folders): boolean => exportedNotes(stream, folders.notes)

/** Заметки потока выгружены к нынешним утверждённым итогам и в нынешний каталог (notes — его путь из настроек). */
export const exportedNotes = (stream: Stream, notes: string | null): boolean =>
  exportedTo(stream, notes) && !!stream.outcomes?.approved && stream.notes?.outcomes === stream.outcomes.run

/** Поток выгружали в нынешний каталог (к каким итогам — неважно): каталог сменили — его выгрузка не там. */
export const exportedTo = (stream: Stream, notes: string | null): boolean =>
  !!stream.notes && notes !== null && stream.notes.root === notes

/** Сколько заметок выгружено: оставленные в каталоге исчезнувшие — не в счёт. */
export const exportedCount = (stream: Stream): number =>
  stream.notes?.notes.filter(note => !note.kept && note.type !== 'issue').length ?? 0

/**
 * Шаг цепочки потока. Пройденный — зелёный; на текущем — ход совета (идёт или упал) или ваш.
 * Утверждённая идея проходит шаг, и прежний поиск идеи, даже упавший, уже не важен. Итоги
 * проходит их утверждение: до него ход за вами. Задачи — последний шаг: нарезаны, ни одну не
 * держит пробел или открытый вопрос, пробелов нет, каждый итог вошёл в задачу и каждое решение —
 * в итог, а у каждого итога есть критерии готовности — зелёные; иначе ход за вами, как и если не
 * нарезалось ни одной. Документация — выгружена к утверждённым итогам в каталог folders (путь из настроек):
 * выгрузка в другой каталог не в счёт.
 */
export const chainLight = (stream: Stream, step: ChainStep, folders: Folders, ready = false): Light => {
  // Начать можно, когда идея утверждена и исследование совета пройдено (ready): до того ждём их — на их этапах.
  if (step === 'start') return stream.design ? 'done' : stream.idea && ready ? 'yours' : 'idle'
  // До вопросов — отбор решений проекта, если в каталоге заметок они есть.
  if (step === 'questions' && stream.design) {
    return stream.scope ? 'done' : ofRun(stream.questions ?? stream.decisions_search) ?? 'yours'
  }
  if (step === 'options' && stream.scope) return stream.choices ? 'done' : ofRun(stream.proposals) ?? 'yours'
  if (step === 'decisions' && stream.choices) return stream.decisions ? 'done' : ofRun(stream.analysis) ?? 'yours'
  if (step === 'outcomes' && stream.decisions) return stream.outcomes?.approved ? 'done' : ofRun(stream.outcomes) ?? 'yours'
  if (step === 'issues' && stream.issues) return issuesLight(stream.issues, stream)
  if (step === 'notes' && stream.outcomes?.approved) {
    // Черновик новее выгрузки — его ход важнее прежней выгрузки: переводится, упал или ждёт записи.
    const draft = stream.notes_draft
    if (draft && draft.run !== stream.notes?.run) return ofRun(draft) ?? 'yours'
    return exported(stream, folders) ? 'done' : ofRun(draft) ?? 'yours'
  }
  return 'idle'
}

/** Шаг «Задачи»: см. chainLight. */
const issuesLight = (issues: IssueDiscovery, stream: Stream): Light => {
  // Решение, не вошедшее ни в один итог, нет и в задачах: спецификация его потеряла.
  const lost = stream.outcomes?.uncovered_adr_ids.length ?? 0
  // Итог без критериев готовности: задачи по нему не проверить.
  const vague = stream.outcomes?.outcomes.some(outcome => outcome.acceptance_criteria.length === 0) ?? false
  const ready = issues.issues.length > 0 && issues.issues.every(issueReady) && issues.gaps.length === 0
    && issues.uncovered_outcome_ids.length === 0 && lost === 0 && !vague
  return ofRun(issues) ?? (ready ? 'done' : 'yours')
}

/**
 * Поток — цвет его текущего шага. folders — пути каталога заметок и папки задач из настроек; ready — исследование
 * совета пройдено: поток можно начинать.
 */
export const streamLight = (stream: Stream, folders: Folders, ready = false): Light =>
  chainLight(stream, currentStep(stream), folders, ready)

/** Идеи групп — на этапе «Группы» после подтверждения: ищутся, упали, ждут вас или утверждены. */
const ideasLight = (streams: Stream[]): Light => strongest(streams.map(stream =>
  stream.idea ? 'done' : ofRun(stream.discovery) ?? 'yours'))

/** Исследование: сканы идут или упали, шаги ждут вас или пройдены. Пока идеи не утверждены — ждёт их. */
const researchLight = (council: Council): Light => {
  const { streams, research } = council
  if (!streams || streams.some(stream => !stream.idea)) return 'idle'
  if (researched(council)) return 'done'
  const scan = research?.repository ? research.design_scan : research?.scan
  return ofRun(scan ?? null) ?? 'yours'
}

/**
 * Этап совета. Ввод готов, когда текст нарезали; нарезка — когда разложили по группам; группы — когда
 * подтвердили, они не устарели и идеи всех утверждены; исследование — когда оба шага пройдены. Готовый ход без
 * следующего — ваш ход.
 */
export function stageLight(council: Council, stage: Stage, folders: Folders): Light {
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
      if (structureIsStale(council)) return seeking(council) ? 'running' : 'yours'
      return ideasLight(streams)
    }
    case 'research':
      if (structureIsStale(council)) return 'idle'
      return researchLight(council)
    case 'streams':
      if (!streams) return 'idle'
      // По устаревшим группам идеи не утверждают и не ищут заново: сначала разложить заново.
      if (structureIsStale(council)) return seeking(council) ? 'running' : 'idle'
      return strongest(streams.map(stream => streamLight(stream, folders, researched(council))))
    case 'history':
      return 'idle'
  }
}

/** Совет целиком: самое важное из состояний его этапов. Нетронутый — белый, черновик. */
export const councilLight = (council: Council, folders: Folders): Light =>
  strongest((['brief', 'slices', 'structure', 'research', 'streams'] as const).map(stage => stageLight(council, stage, folders)))

/** Что в совете требует человека: его ход или упавший ход модели — и куда за этим идти. */
export interface Attention {
  light: 'yours' | 'failed'
  what: 'slicingFailed' | 'slicesDone' | 'groupingFailed' | 'groupsStale' | 'groupsReady'
    | 'ideaFailed' | 'ideaWaits' | 'repositoryFailed' | 'repositoryWait' | 'designFailed' | 'designWait'
    | 'startWait' | 'questionsFailed' | 'questionsWait' | 'optionsFailed' | 'optionsWait'
    | 'decisionsFailed' | 'decisionsWait' | 'outcomesFailed' | 'outcomesWait' | 'issuesFailed' | 'issuesWait'
    | 'notesFailed' | 'notesWait'
  /** Буква потока — у того, что про поток. */
  group?: string
  to: string
}

export function attention(council: Council, folders: Folders): Attention[] {
  const { id, slicing, structure, streams, research } = council
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
    // Идеи — на этапе «Группы».
    for (const stream of streams ?? []) {
      if (stream.idea) continue
      const light = ofRun(stream.discovery)
      if (light === 'failed') add('failed', 'ideaFailed', councilPath(id, 'structure'), stream.group)
      else if (light === null) add('yours', 'ideaWaits', councilPath(id, 'structure'), stream.group)
    }
    // Исследование — когда идеи всех утверждены.
    const step = research?.repository ? 'design' : 'repository'
    const light = researchLight(council)
    if (light === 'failed') add('failed', `${step}Failed`, councilPath(id, 'research'))
    else if (light === 'yours') add('yours', `${step}Wait`, councilPath(id, 'research'))
    const ready = researched(council)
    for (const stream of streams ?? []) {
      if (!stream.idea) continue
      const to = councilPath(id, `streams/${stream.group}`)
      const lit = streamLight(stream, folders, ready)
      const where = currentStep(stream)
      if (lit === 'failed') add('failed', `${where === 'start' ? 'questions' : where}Failed`, to, stream.group)
      else if (lit === 'yours') add('yours', `${where}Wait`, to, stream.group)
    }
  }
  return items
}
