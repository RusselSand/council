export type CouncilStatus = 'brief' | 'slices' | 'structure' | 'review' | 'ready'

export const LABELS = ['idea', 'question', 'proposal', 'constraint', 'risk'] as const
export type Label = (typeof LABELS)[number]
export type RunState = 'waiting' | 'running' | 'done' | 'failed'
export type SlicingStepName = 'slice' | 'slice_judge' | 'label' | 'label_judge'
export interface ModelRun { model: string; state: RunState; error: string | null }
/** skipped — судья не понадобился: участники сошлись. */
export interface SlicingStep { name: SlicingStepName; state: RunState | 'skipped'; runs: ModelRun[] }
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
  state: 'running' | 'done' | 'failed'; steps: SlicingStep[]; fragments: LabeledFragment[]; error: string | null
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

export const api = {
  councils: () => request<Council[]>('/api/councils'),
  council: (id: string) => request<Council>(councilUrl(id)),
  createCouncil: () => request<{ id: string }>('/api/councils', { method: 'POST' }),
  updateCouncil: (id: string, patch: CouncilPatch) => request<Council>(councilUrl(id), {
    method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(patch),
  }),
  startSlicing: (id: string) => request<Council>(`${councilUrl(id)}/slicing`, { method: 'POST' }),
  settings: () => request<Settings>('/api/settings'),
}

/**
 * Запустить нарезку. Если она уже идёт (409: вторая вкладка, повторный клик, потерянный
 * ответ на прошлый запуск) — вернуть совет с идущей, чтобы экран за ней следил.
 */
export const startOrFollowSlicing = async (id: string): Promise<Council> => {
  try {
    return await api.startSlicing(id)
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) return api.council(id)
    throw e
  }
}

/** Адрес страницы проекта. id всегда кодируется здесь, а не в местах вызова. */
export const councilPath = (id: string, stage = 'brief') => `/councils/${encodeURIComponent(id)}/${stage}`
