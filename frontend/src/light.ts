import {
  councilPath, researched, seeking, structureIsStale, tasksExported, tasksStale, tasksWaitFor,
  type Council, type DecisionAnalysis, type Folders, type DecisionsSearch, type DesignScan, type IdeaDiscovery,
  type NotesDraft, type OutcomeDiscovery, type TaskPlan, type TasksDraft,
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
export const CHAIN = ['start', 'questions', 'options', 'decisions', 'outcomes', 'notes'] as const
export type ChainStep = (typeof CHAIN)[number]

/** Что важнее показать, если состояний несколько: сначала то, что требует человека. */
const ORDER: Light[] = ['failed', 'yours', 'running', 'done', 'idle']
export const strongest = (lights: Light[]): Light => ORDER.find(light => lights.includes(light)) ?? 'idle'

/** Ход модели: идёт — зелёный, упал — красный. Готов или не было — решает этап. */
type Run = Slicing | Structure | IdeaDiscovery | RepositoryScan | DesignScan | DecisionsSearch | QuestionDiscovery
  | ProposalDiscovery | DecisionAnalysis | OutcomeDiscovery | NotesDraft | TaskPlan | TasksDraft

const ofRun = (run: Run | null): Light | null => {
  if (run?.state === 'running') return 'running'
  if (run?.state === 'failed') return 'failed'
  return null
}

/**
 * Где поток: пока его не начали — в начале (идея и исследование), пока не отобраны вопросы — на вопросах, пока не выбраны
 * варианты — на вариантах, пока не зафиксированы решения — на решениях, пока итоги не утверждены —
 * на итогах, дальше — документация. Задачи режут не в потоке, а на этапе «Задачи» — на весь совет.
 */
export const currentStep = (stream: Stream): ChainStep => {
  if (!stream.idea || !stream.design) return 'start'
  if (!stream.scope) return 'questions'
  if (!stream.choices) return 'options'
  if (!stream.decisions) return 'decisions'
  if (!stream.outcomes?.approved) return 'outcomes'
  return 'notes'
}

/** Шаг можно открыть: пройденный и текущий, а итоги — и раньше, если есть сохранённые: их видно. */
export const openable = (stream: Stream, step: ChainStep): boolean =>
  CHAIN.indexOf(step) <= CHAIN.indexOf(currentStep(stream))
  || (step === 'outcomes' && stream.saved_outcomes.length > 0)

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

/** Сколько заметок выгружено: оставленные в каталоге исчезнувшие и файлы задач прежних выгрузок — не в счёт. */
export const exportedCount = (stream: Stream): number =>
  stream.notes?.notes.filter(note => !note.kept && note.type !== 'issue').length ?? 0

/**
 * Шаг цепочки потока. Пройденный — зелёный; на текущем — ход совета (идёт или упал) или ваш.
 * Утверждённая идея проходит шаг, и прежний поиск идеи, даже упавший, уже не важен. Итоги
 * проходит их утверждение: до него ход за вами. Документация — последний шаг: выгружена к утверждённым итогам
 * в каталог folders (путь из настроек) — зелёная; выгрузка в другой каталог не в счёт.
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
  if (step === 'notes' && stream.outcomes?.approved) {
    // Черновик новее выгрузки — его ход важнее прежней выгрузки: переводится, упал или ждёт записи.
    const draft = stream.notes_draft
    if (draft && draft.run !== stream.notes?.run) return ofRun(draft) ?? 'yours'
    return exported(stream, folders) ? 'done' : ofRun(draft) ?? 'yours'
  }
  return 'idle'
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

/**
 * Задачи: план строится или его выгрузка переводится — зелёный, упали — красный. Плана нет — ход за вами, когда все
 * потоки утверждены и выгружены, иначе ждём их. План устарел (поток поменяли после него) или не выгружен в нынешнюю
 * папку задач — ход за вами; выгружен — готово.
 */
const tasksLight = (council: Council, folders: Folders): Light => {
  if (!council.streams) return 'idle'
  const { tasks: plan, tasks_draft: draft } = council
  const run = ofRun(plan) ?? ofRun(draft)
  if (run) return run
  if (!plan) return tasksWaitFor(council, folders.notes).length === 0 ? 'yours' : 'idle'
  if (tasksStale(council)) return 'yours'
  return tasksExported(council, folders.issues) ? 'done' : 'yours'
}

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
    case 'tasks':
      return tasksLight(council, folders)
  }
}

/** Совет целиком: самое важное из состояний его этапов. Нетронутый — белый, черновик. */
export const councilLight = (council: Council, folders: Folders): Light =>
  strongest((['brief', 'slices', 'structure', 'research', 'streams', 'tasks'] as const).map(stage => stageLight(council, stage, folders)))

/** Что в совете требует человека: его ход или упавший ход модели — и куда за этим идти. */
export interface Attention {
  light: 'yours' | 'failed'
  what: 'slicingFailed' | 'slicesDone' | 'groupingFailed' | 'groupsStale' | 'groupsReady'
    | 'ideaFailed' | 'ideaWaits' | 'repositoryFailed' | 'repositoryWait' | 'designFailed' | 'designWait'
    | 'startWait' | 'questionsFailed' | 'questionsWait' | 'optionsFailed' | 'optionsWait'
    | 'decisionsFailed' | 'decisionsWait' | 'outcomesFailed' | 'outcomesWait'
    | 'notesFailed' | 'notesWait' | 'tasksFailed' | 'tasksWait' | 'tasksStale'
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
    // Задачи — когда все потоки утверждены и выгружены, а дальше — пока план не выгружен.
    const tasks = tasksLight(council, folders)
    const to = councilPath(id, 'tasks')
    if (tasks === 'failed') add('failed', 'tasksFailed', to)
    else if (tasks === 'yours') add('yours', tasksStale(council) ? 'tasksStale' : 'tasksWait', to)
  }
  return items
}
