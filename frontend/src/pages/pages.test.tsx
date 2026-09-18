import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Run } from '../api'
import { App } from '../App'
import { HomePage } from './HomePage'
import { RunPage } from './RunPage'

const RUN: Run = { id: 'demo-1', name: 'Сервис уведомлений', status: 'review', author: 'sol', reviewer: 'fable', updated_at: '2026-09-17' }

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
const networkError = () => Promise.reject(new TypeError('Failed to fetch'))

let fetchMock: ReturnType<typeof vi.fn>
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const renderAt = (path: string) => render(<RouterProvider router={createMemoryRouter([{
  path: '/', element: <App />, children: [
    { index: true, element: <HomePage /> },
    { path: 'runs/:id/brief', element: <RunPage stage="brief" /> },
  ],
}], { initialEntries: [path] })} />)

describe('HomePage', () => {
  it('показывает загрузку, пока запрос идёт, а не «Нет проектов»', () => {
    fetchMock.mockReturnValue(new Promise(() => {}))
    renderAt('/')
    expect(screen.getByText('Загрузка…')).toBeTruthy()
    expect(screen.queryByText(/Нет проектов/)).toBeNull()
  })

  it('показывает список проектов', async () => {
    fetchMock.mockReturnValue(json([RUN]))
    renderAt('/')
    expect(await screen.findByText(RUN.name)).toBeTruthy()
    expect(screen.queryByText(/Нет проектов/)).toBeNull()
  })

  it('показывает «Нет проектов» только после успешного пустого ответа', async () => {
    fetchMock.mockReturnValue(json([]))
    renderAt('/')
    expect(await screen.findByText(/Нет проектов/)).toBeTruthy()
  })

  it.each([
    ['ошибка сервера', () => json({ detail: 'boom' }, 500)],
    ['сеть недоступна', networkError],
  ])('%s → ошибка с повтором, без «Нет проектов»', async (_, failure) => {
    fetchMock.mockImplementationOnce(failure).mockReturnValue(json([RUN]))
    renderAt('/')
    expect(await screen.findByText(/Не удалось загрузить проекты/)).toBeTruthy()
    expect(screen.queryByText(/Нет проектов/)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByText(RUN.name)).toBeTruthy()
  })
})

describe('RunPage', () => {
  it('показывает проект', async () => {
    fetchMock.mockReturnValue(json(RUN))
    renderAt('/runs/demo-1/brief')
    expect(await screen.findByRole('heading', { name: RUN.name })).toBeTruthy()
  })

  it('404 → «Проект не найден»', async () => {
    fetchMock.mockReturnValue(json({ detail: 'Проект не найден' }, 404))
    renderAt('/runs/missing/brief')
    expect(await screen.findByRole('heading', { name: 'Проект не найден' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Повторить' })).toBeNull()
  })

  it.each([
    ['ошибка сервера', () => json({ detail: 'boom' }, 500)],
    ['сеть недоступна', networkError],
  ])('%s → «Не удалось загрузить», а не «не найден»', async (_, failure) => {
    fetchMock.mockImplementationOnce(failure).mockReturnValue(json(RUN))
    renderAt('/runs/demo-1/brief')
    expect(await screen.findByRole('heading', { name: 'Не удалось загрузить проект' })).toBeTruthy()
    expect(screen.queryByText('Проект не найден')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(await screen.findByRole('heading', { name: RUN.name })).toBeTruthy()
  })
})

describe('App: «Новый бриф»', () => {
  const clickNew = () => fireEvent.click(screen.getByRole('button', { name: '+ Новый бриф' }))

  it('блокирует кнопку на время запроса и переходит в бриф', async () => {
    let resolve!: (r: Response) => void
    fetchMock.mockImplementation((url: string, init?: RequestInit) =>
      init?.method === 'POST' ? new Promise<Response>(r => { resolve = r })
        : url === '/api/runs' ? json([]) : json(RUN))
    renderAt('/')
    clickNew()
    const busy = screen.getByRole('button', { name: 'Создаём…' }) as HTMLButtonElement
    expect(busy.disabled).toBe(true)

    resolve(new Response(JSON.stringify({ id: 'demo-1' }), { status: 200 }))
    expect(await screen.findByRole('heading', { name: RUN.name })).toBeTruthy()
  })

  it('при ошибке показывает сообщение и снова даёт нажать', async () => {
    fetchMock.mockImplementation((_: string, init?: RequestInit) =>
      init?.method === 'POST' ? networkError() : json([]))
    renderAt('/')
    clickNew()
    expect((await screen.findByRole('alert')).textContent).toBe('Не удалось создать бриф')
    expect((screen.getByRole('button', { name: '+ Новый бриф' }) as HTMLButtonElement).disabled).toBe(false)
  })
})
