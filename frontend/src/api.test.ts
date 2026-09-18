import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, runPath } from './api'

afterEach(() => { vi.unstubAllGlobals() })

const stubResponse = (body: BodyInit | null, init: ResponseInit) =>
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(body, init))))

const failure = () => api.run('x').then(() => { throw new Error('ожидалась ошибка') }, (e: ApiError) => e)

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

describe('runPath', () => {
  it('кодирует id', () => {
    expect(runPath('a/b c')).toBe('/runs/a%2Fb%20c/brief')
    expect(runPath('demo-1', 'spec')).toBe('/runs/demo-1/spec')
  })
})
