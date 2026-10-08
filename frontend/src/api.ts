export type CouncilStatus = 'brief' | 'slices' | 'structure' | 'review' | 'ready'

export const LABELS = ['idea', 'question', 'proposal', 'constraint', 'risk'] as const
export type Label = (typeof LABELS)[number]
export type RunState = 'waiting' | 'running' | 'done' | 'failed'
export type StepName = 'slice' | 'slice_judge' | 'label' | 'label_judge' | 'structure' | 'structure_judge'
  | 'idea_discovery' | 'idea_judge' | 'question_discovery' | 'question_judge'
  | 'proposal_discovery' | 'proposal_judge' | 'decision_analysis' | 'decision_judge'
  | 'outcome_discovery' | 'outcome_judge'
export interface ModelRun { model: string; state: RunState; error: string | null }
/** skipped — судья не понадобился: участники сошлись. */
export interface Step { name: StepName; state: RunState | 'skipped'; runs: ModelRun[] }
/** Что предложил участник; вариантов несколько, если он видит неоднозначность. */
export interface Vote { model: string; labels: Label[] }
export interface LabeledFragment {
  id: number; text: string
  /** Итоговый тип; council_label — что сказал совет, если человек выбрал другой. */
  label: Label; reason: string; council_label: Label
  /** agreed — участники сошлись, judge — разошлись и решил судья. */
  decided_by: 'agreed' | 'judge'; votes: Vote[]
  /** Пояснение судьи нарезки о границе этого фрагмента. */
  slice_note: string | null
}
/** Нарезка и разметка текста советом: идёт в фоне минутами, фронт опрашивает совет. */
export interface Slicing {
  state: 'running' | 'done' | 'failed'; steps: Step[]; fragments: LabeledFragment[]; error: string | null
  /** Свой у каждого запуска: правка типа несёт его, чтобы не лечь на фрагменты новой нарезки. */
  run: string
  /** Текст, который нарезали: исходник мог поменяться после запуска. */
  text: string
}
export interface Council {
  id: string; name: string; status: CouncilStatus; brief: string
  /** Каждый участник предлагает свой вариант, не видя чужих; судья выбирает лучший. */
  participants: string[]; judge: string
  updated_at: string
  slicing: Slicing | null
  structure: Structure | null
  /** Потоки подтверждённых групп; null — группы ещё не подтверждены. */
  streams: Stream[] | null
}

/** Фрагменты вокруг одной задумки. Общий фрагмент стоит в нескольких группах тем же номером. */
export interface Group {
  id: string; title: string; fragment_ids: number[]; idea_fragment_ids: number[]
  /** Идеи в тексте нет: её восстановит следующий этап. */
  missing_idea: boolean
  /** Какие из fragment_ids есть и в других группах. */
  shared_fragment_ids: number[]
}
/** depends_on — source требует результата target; related — связаны без зависимости. */
export interface GroupRelation { source: string; target: string; type: 'depends_on' | 'related'; reason: string }
export interface StructureDecision { issue: string; decision: string; reason: string }
/** Раскладка готовой нарезки по группам; slicing_run и labels — из какой нарезки и с какими типами. */
export interface Structure {
  state: 'running' | 'done' | 'failed'; run: string; slicing_run: string; labels: Record<number, Label>
  steps: Step[]; groups: Group[]; relations: GroupRelation[]; decisions: StructureDecision[]
  /** Как предложил совет; groups и relations — с правками человека, edited — они различаются. */
  proposal: { groups: Group[]; relations: GroupRelation[] } | null; edited: boolean
  /** Сколько раз группы правили: правка несёт версию, к которой сделана. */
  revision: number
  error: string | null
}
/** Формулировка идеи, как её восстановили по фрагментам группы; models — кто предложил. */
export interface IdeaOption { idea: string; evidence: number[]; reason: string; models: string[] }
/**
 * Что предлагает совет. idea null — не предлагает (никто не взялся или судья не принял ни
 * один вариант), reason — почему. option — какой из вариантов предложен как есть; null —
 * судья свёл формулировки.
 */
export interface IdeaProposal {
  idea: string | null; evidence: number[]; reason: string; decided_by: 'agreed' | 'judge'; option: number | null
}
/** Поиск идеи группы, в тексте которой её нет: идёт в фоне минутами, фронт опрашивает совет. */
export interface IdeaDiscovery {
  state: 'running' | 'done' | 'failed'; run: string; steps: Step[]
  options: IdeaOption[]; proposal: IdeaProposal | null; error: string | null
}
/** Идея потока, утверждённая человеком: записана в тексте, вариант совета как есть или своя. */
export interface StreamIdea { text: string; by: 'text' | 'council' | 'human'; evidence: number[] }
/**
 * Открытый вопрос: что ещё неизвестно. user — из текста, дословно; inferred — незаписанный,
 * на него отвечают предложения группы; discovered — недостающий; added — добавлен при отборе.
 */
export interface OpenQuestion {
  id: string; text: string; source: 'user' | 'inferred' | 'discovered' | 'added'
  source_question_id: number | null; proposal_ids: number[]; reason: string | null
}
/** Поиск вопросов к утверждённой идее (idea — к какой): идёт в фоне, фронт опрашивает совет. */
export interface QuestionDiscovery {
  state: 'running' | 'done' | 'failed'; run: string; idea: string; steps: Step[]
  questions: OpenQuestion[]; error: string | null
}
/**
 * Новый вариант ответа на вопрос, найденный советом (P1, P2… сквозь поток). Варианты из текста —
 * фрагменты группы в OpenQuestion.proposal_ids. Ссылки — на ограничения и риски группы и на
 * другие вопросы, от которых он зависит; recommended — судья счёл его предпочтительным.
 */
export interface Proposal {
  id: string; text: string; reason: string; constraint_ids: number[]; risk_ids: number[]
  depends_on: string[]; recommended: boolean
}
/** Что совет нашёл к вопросу: recommended — один предпочтительный, alternatives — равноправные, none — ничего нового. */
export interface QuestionOptions {
  question_id: string; proposals: Proposal[]; verdict: 'recommended' | 'alternatives' | 'none'; reason: string | null
}
/** Поиск вариантов к отобранным вопросам: по вопросу за раз, готовые — в options по мере поиска. */
export interface ProposalDiscovery {
  state: 'running' | 'done' | 'failed'; run: string; scope: string[]; steps: Step[]
  options: QuestionOptions[]; error: string | null
}
/** Выбор по вопросу: Fn — вариант из текста, Pn — найденный советом, null — пока не решает (unresolved). */
export interface Choice { question_id: string; proposal: string | null }
/**
 * Что совет сказал по вопросу перед решением. validated — выбор человека проверен, проблем нет;
 * conflict — с ним проблема (решать всё равно человеку); recommended — для unresolved совет
 * предлагает вариант из тех, что есть; none — обоснованно выбрать нельзя. proposal — проверенный
 * или рекомендованный вариант; rationale — обоснование совета: в ADR — если человек его оставит.
 */
export interface QuestionAnalysis {
  question_id: string; verdict: 'validated' | 'conflict' | 'recommended' | 'none'; proposal: string | null
  constraint_conflicts: number[]; risk_ids: number[]; depends_on: string[]
  reason: string | null; rationale: string | null
}
/** Проверка выбора: по вопросу за раз, готовые — в analyses по мере проверки; choices — к какому выбору. */
export interface DecisionAnalysis {
  state: 'running' | 'done' | 'failed'; run: string; choices: string[]; steps: Step[]
  analyses: QuestionAnalysis[]; error: string | null
}
/**
 * Решение человека по вопросу — ADR: вариант и почему он; proposal null — вопрос оставлен открытым.
 * rationale_by: ai — обоснование совета, подтверждённое как есть; human — своё или поправленное.
 */
export interface Decision {
  question_id: string; proposal: string | null; rationale: string | null; rationale_by: 'ai' | 'human' | null
}
/** Решение, как его фиксирует человек: у открытого вопроса proposal и rationale — null. */
export interface DecisionDraft { question_id: string; proposal: string | null; rationale: string | null }
/** Неопределённость, которой нет среди вопросов потока: материал для нового поиска вопросов. */
export interface OutcomeGap { question: string; reason: string }
/**
 * Итог — законченное изменение системы после принятых решений (O1, O2…). adr_ids — на каких
 * решениях стоит (ADR-n — решение по n-му вопросу отбора); blocked_by — открытые вопросы, без
 * решения которых его поведение не определить: недостающее не додумывается.
 */
export interface Outcome {
  id: string; title: string; behavior: string; adr_ids: string[]; constraint_ids: number[]; risk_ids: number[]
  acceptance_criteria: string[]; blocked_by: string[]; gaps: OutcomeGap[]
}
/** Сборка итогов из решений (decisions — к каким); uncovered_adr_ids — решения, не вошедшие ни в один итог. */
export interface OutcomeDiscovery {
  state: 'running' | 'done' | 'failed'; run: string; decisions: string[]; steps: Step[]
  outcomes: Outcome[]; uncovered_adr_ids: string[]; error: string | null
}
/**
 * Поток — подтверждённая группа под той же буквой. discovery — поиск её идеи, если её нет в
 * тексте; questions — поиск вопросов к утверждённой идее; scope — какие из них решать;
 * proposals — поиск вариантов к ним; choices — выбор по каждому; analysis — его проверка;
 * decisions — решения, которые зафиксировал человек; outcomes — итоги, собранные из них.
 */
export interface Stream {
  group: string; discovery: IdeaDiscovery | null; idea: StreamIdea | null
  questions: QuestionDiscovery | null; scope: OpenQuestion[] | null
  proposals: ProposalDiscovery | null; choices: Choice[] | null
  analysis: DecisionAnalysis | null; decisions: Decision[] | null
  outcomes: OutcomeDiscovery | null
}

/** Правка с экрана: меняются только присланные поля. */
export type CouncilPatch = Partial<Pick<Council, 'name' | 'brief' | 'participants' | 'judge'>> & {
  /** Типы фрагментов готовой нарезки, {id: тип}: только изменённые, остальные не трогаются. */
  labels?: Record<number, Label>
  /** К какой нарезке относятся labels: Slicing.run. */
  slicing_run?: string
}

/** available — есть подключение к CLI: без него модель видна, но не запускается. */
export interface Model { alias: string; short_name: string; display_name: string; cli: string; available: boolean }
export interface Settings {
  models: Model[]; min_participants: number; default_participants: string[]; default_judge: string
}

/** Ответ сервера не 2xx. Сетевые сбои бросают обычный TypeError от fetch. */
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export const isNotFound = (e: unknown) => e instanceof ApiError && e.status === 404

/** Текст ошибки: `detail` из ответа FastAPI, иначе statusText (в HTTP/2 он часто пустой), иначе код. */
const errorMessage = async (res: Response) => {
  try {
    const { detail } = await res.json()
    if (typeof detail === 'string' && detail) return detail
  } catch { /* тело не JSON */ }
  return res.statusText || `HTTP ${res.status}`
}

const request = async <T,>(url: string, init?: RequestInit): Promise<T> => {
  const res = await fetch(url, init)
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  return res.json()
}

const councilUrl = (id: string) => `/api/councils/${encodeURIComponent(id)}`

/** К какой раскладке и версии её групп правка: Structure.run и revision. Не та — 409. */
export interface GroupsVersion { run: string; revision: number }

const editGroups = (id: string, action: 'merge' | 'split' | 'rename' | 'restore' | 'confirm',
                    at: GroupsVersion, body: object = {}) =>
  request<Council>(`${councilUrl(id)}/structure/${action}`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ run: at.run, revision: at.revision, ...body }),
  })

export const api = {
  councils: () => request<Council[]>('/api/councils'),
  council: (id: string) => request<Council>(councilUrl(id)),
  createCouncil: () => request<{ id: string }>('/api/councils', { method: 'POST' }),
  updateCouncil: (id: string, patch: CouncilPatch) => request<Council>(councilUrl(id), {
    method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(patch),
  }),
  startSlicing: (id: string) => request<Council>(`${councilUrl(id)}/slicing`, { method: 'POST' }),
  startStructure: (id: string) => request<Council>(`${councilUrl(id)}/structure`, { method: 'POST' }),
  /** group — где нажали: её буква и название остаются. */
  mergeGroups: (id: string, at: GroupsVersion, group: string, other: string) =>
    editGroups(id, 'merge', at, { group, other }),
  splitGroup: (id: string, at: GroupsVersion, group: string, fragmentIds: number[], title: string) =>
    editGroups(id, 'split', at, { group, fragment_ids: fragmentIds, title }),
  renameGroup: (id: string, at: GroupsVersion, group: string, title: string) =>
    editGroups(id, 'rename', at, { group, title }),
  restoreGroups: (id: string, at: GroupsVersion) => editGroups(id, 'restore', at),
  /** Группы на экране становятся потоками; у групп без идеи совет сразу её ищет. */
  confirmGroups: (id: string, at: GroupsVersion) => editGroups(id, 'confirm', at),
  /** Искать идею потока заново: после сбоя или без подключения к моделям. */
  seekIdea: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/discovery`, { method: 'POST' }),
  /** Искать вопросы к идее потока заново: после сбоя или без подключения к моделям. */
  seekQuestions: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/questions/discovery`, { method: 'POST' }),
  /**
   * Какие вопросы потоку решать: оставленные из найденных (их id) и свои (тексты). questionsRun —
   * к какому поиску отбор: каждый нумерует вопросы с Q1, и отбор к прежнему сервер отклонит (409).
   */
  approveScope: (id: string, at: GroupsVersion, group: string, questionsRun: string, keep: string[], added: string[]) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/questions`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, questions_run: questionsRun, keep, added }),
    }),
  /** Искать варианты к отобранным вопросам заново: после сбоя или без подключения к моделям. */
  seekProposals: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/proposals/discovery`, { method: 'POST' }),
  /**
   * Выбор по каждому отобранному вопросу; совет сразу его проверяет. proposalsRun — к какому
   * поиску: у каждого свои номера Pn.
   */
  approveChoices: (id: string, at: GroupsVersion, group: string, proposalsRun: string, choices: Choice[]) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/choices`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, proposals_run: proposalsRun, choices }),
    }),
  /** Проверить выбор заново: после сбоя или без подключения к моделям. */
  checkChoices: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/analysis`, { method: 'POST' }),
  /** Решения по каждому отобранному вопросу; совет сразу собирает из них итоги. analysisRun — к какой проверке выбора. */
  approveDecisions: (id: string, at: GroupsVersion, group: string, analysisRun: string, decisions: DecisionDraft[]) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/decisions`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, analysis_run: analysisRun, decisions }),
    }),
  /** Собрать итоги заново: после сбоя или без подключения к моделям. */
  seekOutcomes: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/outcomes/discovery`, { method: 'POST' }),
  /** text null — идея записана в тексте группы, её не правят. */
  approveIdea: (id: string, at: GroupsVersion, group: string, text: string | null) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/idea`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, ...(text === null ? {} : { text }) }),
    }),
  settings: () => request<Settings>('/api/settings'),
}

/**
 * Запустить ход совета (нарезку, группы, поиск идеи или вопросов). Если его уже запустили
 * (409: вторая вкладка, повторный клик, потерянный ответ на прошлый запуск) — вернуть совет с
 * ним, чтобы экран за ним следил: он идёт или на месте уже не тот ход, что был на экране, —
 * пусть даже успел закончиться. run — где этот ход в совете, onScreen — совет на экране.
 * 409 бывает и не про это: группы устарели, идея уже утверждена, — тогда ход на месте прежний
 * и не идёт, и это отказ словами сервера, как и временный (503, 423).
 */
export const startOrFollow = async (start: () => Promise<Council>, onScreen: Council,
                                    run: (council: Council) => { state: string; run: string } | null | undefined,
): Promise<Council> => {
  const shown = run(onScreen)?.run
  try {
    return await start()
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      const council = await api.council(onScreen.id)
      const now = run(council)
      if (now && (now.state === 'running' || now.run !== shown)) return council
    }
    throw e
  }
}

/** Поток группы в совете: где искать его ходы. */
export const streamOf = (council: Council, group: string) => council.streams?.find(s => s.group === group)

/**
 * Группы разложены по другим типам, чем сейчас у фрагментов: человек поправил тип после
 * раскладки. Группы могли устареть — стоит разложить заново.
 */
export const structureIsStale = (council: Council): boolean => {
  const { structure, slicing } = council
  if (!structure || structure.state !== 'done' || !slicing) return false
  if (structure.slicing_run !== slicing.run) return true
  return slicing.fragments.some(f => structure.labels[f.id] !== f.label)
}

/**
 * Группы подтверждены: каждая стала потоком. Новый состав групп или новая раскладка
 * подтверждение снимают, переименование — нет.
 */
export const groupsConfirmed = (council: Council): boolean =>
  council.streams !== null && council.structure?.state === 'done'

/** Ходы потока: поиск идеи, вопросов, вариантов, проверка выбора и сборка итогов. */
export const searchesOf = (stream: Stream) =>
  [stream.discovery, stream.questions, stream.proposals, stream.analysis, stream.outcomes]

/** Совет работает хоть над одним потоком: ищет, проверяет или собирает. */
export const seeking = (council: Council): boolean =>
  council.streams?.some(stream => searchesOf(stream).some(run => run?.state === 'running')) ?? false

/** Итог готов к разработке: его не держит ни открытый вопрос, ни пробел. */
export const outcomeReady = (outcome: Outcome): boolean => outcome.blocked_by.length === 0 && outcome.gaps.length === 0

/** Адрес страницы проекта. id всегда кодируется здесь, а не в местах вызова. */
export const councilPath = (id: string, stage = 'brief') => `/councils/${encodeURIComponent(id)}/${stage}`
