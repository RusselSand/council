import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, councilPath, seeking, type Council } from './api'

afterEach(() => { vi.unstubAllGlobals() })

const stubResponse = (body: BodyInit | null, init: ResponseInit) =>
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(body, init))))

const failure = () => api.council('x').then(() => { throw new Error('ожидалась ошибка') }, (e: ApiError) => e)

describe('ApiError', () => {
  it('берёт текст из detail ответа FastAPI', async () => {
    stubResponse(JSON.stringify({ detail: 'Проект не найден' }), { status: 404, statusText: 'Not Found' })
    const e = await failure()
    expect(e).toBeInstanceOf(ApiError)
    expect([e.status, e.message]).toEqual([404, 'Проект не найден'])
  })

  it('без detail и statusText (HTTP/2) подставляет код', async () => {
    stubResponse('<html>oops</html>', { status: 502, statusText: '' })
    expect((await failure()).message).toBe('HTTP 502')
  })
})

describe('councilPath', () => {
  it('кодирует id', () => {
    expect(councilPath('a/b c')).toBe('/councils/a%2Fb%20c/brief')
    expect(councilPath('demo-1', 'spec')).toBe('/councils/demo-1/spec')
  })
})

describe('seeking', () => {
  it('опрос идёт, пока работает любой ход потока: скан макета, отбор решений, перевод заметок', () => {
    for (const run of ['design_scan', 'decisions_search', 'notes_draft'] as const) {
      const council = { streams: [{ group: 'A', [run]: { state: 'running', run: 'r1' } }] } as unknown as Council
      expect(seeking(council)).toBe(true)
    }
  })
})
