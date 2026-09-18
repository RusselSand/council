export type RunStatus = 'brief' | 'approaches' | 'decisions' | 'review' | 'ready'
export interface Run { id: string; name: string; status: RunStatus; author: string; reviewer: string; updated_at: string }

const get = async <T,>(url: string, init?: RequestInit): Promise<T> => {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(res.statusText)
  return res.json()
}

export const api = {
  runs: () => get<Run[]>('/api/runs'),
  run: (id: string) => get<Run>(`/api/runs/${id}`),
  createRun: () => get<{ id: string }>('/api/runs', { method: 'POST' }),
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  brief: 'Бриф', approaches: 'Подходы', decisions: 'Решения', review: 'Ревью', ready: 'ТЗ согласовано',
}
