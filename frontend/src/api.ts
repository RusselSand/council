export type CouncilStatus = 'brief' | 'slices' | 'structure' | 'review' | 'ready'

export const LABELS = ['idea', 'question', 'proposal', 'constraint', 'risk'] as const
export type Label = (typeof LABELS)[number]
export type RunState = 'waiting' | 'running' | 'done' | 'failed'
export type StepName = 'slice' | 'slice_judge' | 'label' | 'label_judge' | 'structure' | 'structure_judge'
  | 'idea_discovery' | 'idea_judge'
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
/** Поток — подтверждённая группа под той же буквой; discovery — поиск её идеи, если её нет в тексте. */
export interface Stream { group: string; discovery: IdeaDiscovery | null; idea: StreamIdea | null }

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
  /** text null — идея записана в тексте группы, её не правят. */
  approveIdea: (id: string, at: GroupsVersion, group: string, text: string | null) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/idea`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, ...(text === null ? {} : { text }) }),
    }),
  settings: () => request<Settings>('/api/settings'),
}

/**
 * Запустить ход совета (нарезку, группы). Если он уже идёт (409: вторая вкладка, повторный
 * клик, потерянный ответ на прошлый запуск) — вернуть совет с идущим, чтобы экран за ним
 * следил. 409 сервер отдаёт только тогда; временный отказ (503, 423) — ошибка для экрана.
 */
export const startOrFollow = async (start: () => Promise<Council>, id: string): Promise<Council> => {
  try {
    return await start()
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) return api.council(id)
    throw e
  }
}

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

/** Совет ищет идею хоть одного потока. */
export const seeking = (council: Council): boolean =>
  council.streams?.some(stream => stream.discovery?.state === 'running') ?? false

/** Адрес страницы проекта. id всегда кодируется здесь, а не в местах вызова. */
export const councilPath = (id: string, stage = 'brief') => `/councils/${encodeURIComponent(id)}/${stage}`
