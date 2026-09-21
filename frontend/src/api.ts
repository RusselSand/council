export type CouncilStatus = 'brief' | 'approaches' | 'decisions' | 'review' | 'ready'
export interface Council { id: string; name: string; status: CouncilStatus; author: string; reviewer: string; updated_at: string }

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

export const api = {
  councils: () => request<Council[]>('/api/councils'),
  council: (id: string) => request<Council>(`/api/councils/${encodeURIComponent(id)}`),
  createCouncil: () => request<{ id: string }>('/api/councils', { method: 'POST' }),
}

/** Адрес страницы проекта. id всегда кодируется здесь, а не в местах вызова. */
export const councilPath = (id: string, stage = 'brief') => `/councils/${encodeURIComponent(id)}/${stage}`
