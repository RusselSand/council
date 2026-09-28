import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Council, CouncilPatch, Settings, Slicing } from '../api'
import { App } from '../App'
import { setLanguage } from '../i18n'
import { en } from '../i18n/en'
import { ru } from '../i18n/ru'
import { HomePage } from './HomePage'
import { CouncilPage, POLL_MS, STAGES } from './CouncilPage'

const COUNCIL: Council = {
  id: 'demo-1', name: 'Сервис уведомлений', status: 'structure', brief: 'Хочу воркер',
  participants: ['sol', 'fable'], judge: 'fable', updated_at: '2026-09-17T10:00:00Z', slicing: null,
}
const SETTINGS: Settings = {
  models: [
    { alias: 'sol', short_name: 'Sol', display_name: 'GPT-5.6 Sol', cli: 'codex', available: true },
    { alias: 'fable', short_name: 'Fable', display_name: 'Claude Fable 5.1', cli: 'claude', available: true },
    { alias: 'astra', short_name: 'Astra', display_name: 'Gemini Astra 3', cli: 'gemini', available: false },
  ],
  min_participants: 2, default_participants: ['sol', 'fable'], default_judge: 'fable',
}

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
const networkError = () => Promise.reject(new TypeError('Failed to fetch'))

const run = (model: string, state: 'waiting' | 'running' | 'done' | 'failed', error: string | null = null) =>
  ({ model, state, error })
const SLICED_TEXT = 'Хочу воркер. Состояние держать в файлах, без базы.'
const RUNNING: Slicing = {
  state: 'running', text: SLICED_TEXT, fragments: [], error: null, steps: [
    { name: 'slice', state: 'running', runs: [run('sol', 'running'), run('fable', 'done')] },
    { name: 'slice_judge', state: 'waiting', runs: [run('fable', 'waiting')] },
    { name: 'label', state: 'waiting', runs: [run('sol', 'waiting'), run('fable', 'waiting')] },
    { name: 'label_judge', state: 'waiting', runs: [run('fable', 'waiting')] },
  ],
}
const DONE: Slicing = {
  state: 'done', text: SLICED_TEXT, error: null,
  steps: [
    { name: 'slice', state: 'done', runs: [run('sol', 'failed', 'нет входа в подписку'), run('fable', 'done')] },
    { name: 'slice_judge', state: 'skipped', runs: [] },
    { name: 'label', state: 'done', runs: [run('sol', 'done'), run('fable', 'done')] },
    { name: 'label_judge', state: 'done', runs: [run('fable', 'done')] },
  ],
  fragments: [
    { id: 1, text: 'Хочу воркер.', label: 'idea', reason: 'Желаемый результат.', council_label: 'idea',
      decided_by: 'agreed', slice_note: null,
      votes: [{ model: 'sol', labels: ['idea'] }, { model: 'fable', labels: ['idea'] }] },
    { id: 2, text: 'Состояние держать в файлах, без базы.', label: 'proposal', reason: 'Способ хранения.',
      council_label: 'proposal', decided_by: 'judge', slice_note: 'две мысли',
      votes: [{ model: 'sol', labels: ['constraint'] }, { model: 'fable', labels: ['proposal'] }] },
  ],
}

let fetchMock: ReturnType<typeof vi.fn>
let patches: CouncilPatch[]
let starts: number
beforeEach(async () => {
  await setLanguage('ru')
  fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock)
  patches = []; starts = 0
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

/**
 * Сервер: список, совет, настройки, PATCH и запуск нарезки. Каждый ответ — новый Response:
 * тело читается один раз. council — функция, если совет меняется между запросами.
 */
const server = ({
  council = () => COUNCIL,
  patch = () => json(COUNCIL),
  start = () => json({ ...COUNCIL, status: 'slices', slicing: RUNNING }, 202),
}: { council?: () => Council; patch?: () => Promise<Response>; start?: () => Promise<Response> } = {}) =>
  (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (url === '/api/settings') return json(SETTINGS)
    if (url === '/api/councils') return method === 'POST' ? json({ id: COUNCIL.id }) : json([council()])
    if (url.endsWith('/slicing')) { starts++; return start() }
    if (method === 'PATCH') { patches.push(JSON.parse(String(init?.body))); return patch() }
    return json(council())
  }

const renderAt = (path: string) => render(<RouterProvider router={createMemoryRouter([{
  path: '/', element: <App />, children: [
    { index: true, element: <HomePage /> },
    ...STAGES.map(stage => ({ path: `councils/:id/${stage}`, element: <CouncilPage stage={stage} /> })),
  ],
}], { initialEntries: [path] })} />)

describe('HomePage', () => {
  it('показывает загрузку, пока запрос идёт, а не «Нет проектов»', () => {
    fetchMock.mockReturnValue(new Promise(() => {}))
    renderAt('/')
    expect(screen.getByText(ru['common.loading'])).toBeTruthy()
    expect(screen.queryByText(ru['home.empty'])).toBeNull()
  })

  it('показывает список проектов с судьёй и числом участников', async () => {
    fetchMock.mockImplementation(server())
    renderAt('/')
    expect(await screen.findByText(COUNCIL.name)).toBeTruthy()
    expect(screen.getByText(/Судья: fable · 2 модели/)).toBeTruthy()
    expect(screen.queryByText(ru['home.empty'])).toBeNull()
  })

  it('показывает «Нет проектов» только после успешного пустого ответа', async () => {
    fetchMock.mockReturnValue(json([]))
    renderAt('/')
    expect(await screen.findByText(ru['home.empty'])).toBeTruthy()
  })

  it.each([
    ['ошибка сервера', () => json({ detail: 'boom' }, 500)],
    ['сеть недоступна', networkError],
  ])('%s → ошибка с повтором, без «Нет проектов»', async (_, failure) => {
    fetchMock.mockImplementationOnce(failure).mockImplementation(server())
    renderAt('/')
    expect(await screen.findByText(ru['home.loadFailed'])).toBeTruthy()
    expect(screen.queryByText(ru['home.empty'])).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: ru['common.retry'] }))
    expect(await screen.findByText(COUNCIL.name)).toBeTruthy()
  })
})

describe('CouncilPage', () => {
  it('показывает проект: имя в шапке, пройденные этапы', async () => {
    fetchMock.mockImplementation(server())
    renderAt('/councils/demo-1/brief')
    expect(await screen.findByRole('heading', { name: COUNCIL.name })).toBeTruthy()
    expect(screen.getByRole('banner').textContent).toContain(COUNCIL.name)
    expect(screen.getByRole('link', { name: /Нарезка/ }).textContent).toContain(ru['council.stageDone'])
    expect(screen.getByRole('link', { name: /Структура/ }).textContent).not.toContain(ru['council.stageDone'])
  })

  it('404 → «Проект не найден»', async () => {
    fetchMock.mockImplementation((url: string) =>
      url === '/api/settings' ? json(SETTINGS) : json({ detail: ru['council.notFound'] }, 404))
    renderAt('/councils/missing/brief')
    expect(await screen.findByRole('heading', { name: ru['council.notFound'] })).toBeTruthy()
    expect(screen.queryByRole('button', { name: ru['common.retry'] })).toBeNull()
  })

  it('404 от настроек — ошибка загрузки с повтором: совет-то есть', async () => {
    let settingsMissing = true
    const rest = server()
    fetchMock.mockImplementation((url: string, init?: RequestInit) =>
      url === '/api/settings' && settingsMissing ? json({ detail: 'Not Found' }, 404) : rest(url, init))
    renderAt('/councils/demo-1/brief')
    expect(await screen.findByRole('heading', { name: ru['council.loadFailed'] })).toBeTruthy()
    expect(screen.queryByText(ru['council.notFound'])).toBeNull()

    settingsMissing = false
    fireEvent.click(screen.getByRole('button', { name: ru['common.retry'] }))
    expect(await screen.findByRole('heading', { name: COUNCIL.name })).toBeTruthy()
  })

  it.each([
    ['ошибка сервера', () => json({ detail: 'boom' }, 500)],
    ['сеть недоступна', networkError],
  ])('%s → «Не удалось загрузить», а не «не найден»', async (_, failure) => {
    fetchMock.mockImplementationOnce(failure).mockImplementation(server())
    renderAt('/councils/demo-1/brief')
    expect(await screen.findByRole('heading', { name: ru['council.loadFailed'] })).toBeTruthy()
    expect(screen.queryByText(ru['council.notFound'])).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: ru['common.retry'] }))
    expect(await screen.findByRole('heading', { name: COUNCIL.name })).toBeTruthy()
  })
})

describe('Ввод', () => {
  const open = async (patch?: () => Promise<Response>, start?: () => Promise<Response>) => {
    fetchMock.mockImplementation(server({ patch, start }))
    renderAt('/councils/demo-1/brief')
    return await screen.findByRole('textbox', { name: ru['brief.title'] }) as HTMLTextAreaElement
  }
  const checkbox = (name: RegExp) => screen.getByRole('checkbox', { name }) as HTMLInputElement
  const judge = () => screen.getByRole('combobox', { name: /Судья/ }) as HTMLSelectElement
  const slice = () => screen.getByRole('button', { name: ru['brief.slice'] }) as HTMLButtonElement

  it('показывает текст, название, участников и судью', async () => {
    expect((await open()).value).toBe(COUNCIL.brief)
    expect(screen.getByText('2 слова')).toBeTruthy()
    expect((screen.getByRole('textbox', { name: ru['brief.nameTitle'] }) as HTMLInputElement).value).toBe(COUNCIL.name)
    expect([checkbox(/GPT-5.6 Sol/).checked, checkbox(/Claude Fable/).checked, checkbox(/Gemini Astra/).checked])
      .toEqual([true, true, false])
    expect(screen.getByText('codex cli')).toBeTruthy()
    expect(judge().value).toBe('fable')
    expect([...judge().options].map(o => o.text)).toEqual(['Sol', 'Fable', 'Astra'])
  })

  it('не даёт оставить меньше двух участников', async () => {
    await open()
    const locked = () => [/GPT-5.6 Sol/, /Claude Fable/, /Gemini Astra/]
      .map(name => checkbox(name).getAttribute('aria-disabled') === 'true')
    expect(locked()).toEqual([true, true, false])
    fireEvent.click(checkbox(/GPT-5.6 Sol/))
    expect(checkbox(/GPT-5.6 Sol/).checked).toBe(true)

    fireEvent.click(checkbox(/Gemini Astra/))
    await waitFor(() => expect(patches).toEqual([{ participants: ['sol', 'fable', 'astra'] }]))
    expect(locked()).toEqual([false, false, false])
  })

  it('судью можно выбрать и не из участников, он сохраняется сразу', async () => {
    await open()
    fireEvent.change(judge(), { target: { value: 'astra' } })
    expect(judge().value).toBe('astra')
    await waitFor(() => expect(patches).toEqual([{ judge: 'astra' }]))
  })

  it('текст и название уходят одним запросом, когда человек перестал печатать', async () => {
    const text = await open()
    fireEvent.change(text, { target: { value: 'Хочу воркер для Codex' } })
    fireEvent.change(text, { target: { value: 'Хочу воркер для Codex CLI' } })
    fireEvent.change(screen.getByRole('textbox', { name: ru['brief.nameTitle'] }), { target: { value: 'Воркер' } })
    expect(screen.getByText('5 слов')).toBeTruthy()
    expect(screen.getByRole('banner').textContent).toContain('Воркер')
    expect(patches).toEqual([])

    await waitFor(() => expect(patches).toEqual([{ brief: 'Хочу воркер для Codex CLI', name: 'Воркер' }]))
  })

  it('«Нарезать» сохраняет текст, запускает нарезку и показывает её ход', async () => {
    const text = await open()
    fireEvent.change(text, { target: { value: 'Новый текст' } })
    fireEvent.click(slice())
    expect(await screen.findByRole('heading', { name: ru['slices.runningTitle'] })).toBeTruthy()
    expect(patches).toEqual([{ brief: 'Новый текст' }])
    const calls = fetchMock.mock.calls.map(([url, init]) => `${init?.method ?? 'GET'} ${url}`)
    expect(calls.indexOf('PATCH /api/councils/demo-1')).toBeLessThan(calls.indexOf('POST /api/councils/demo-1/slicing'))
  })

  it('отказ сервера в запуске объясняет, почему, и оставляет на вводе', async () => {
    await open(undefined, () => json({ detail: 'Нет подключения к моделям: Gemini Astra 3' }, 422))
    fireEvent.click(slice())
    expect((await screen.findByRole('alert')).textContent).toBe('Нет подключения к моделям: Gemini Astra 3')
    expect(screen.getByRole('textbox', { name: ru['brief.title'] })).toBeTruthy()
  })

  it('модель без подключения помечена', async () => {
    await open()
    expect(checkbox(/Gemini Astra/).closest('label')?.textContent).toContain(ru['model.offline'])
    expect(checkbox(/GPT-5.6 Sol/).closest('label')?.textContent).not.toContain(ru['model.offline'])
  })

  it('«Нарезать» выключена, пока текста нет', async () => {
    const text = await open()
    fireEvent.change(text, { target: { value: '   ' } })
    expect(slice().disabled).toBe(true)
  })

  it('непринятую правку видно, повтор отправляет её снова', async () => {
    let fail = true
    await open(() => (fail ? json({ detail: 'boom' }, 500) : json(COUNCIL)))
    fireEvent.change(judge(), { target: { value: 'sol' } })
    expect((await screen.findByRole('alert')).textContent).toContain(ru['save.failed'])

    fail = false
    fireEvent.click(screen.getByRole('button', { name: ru['common.retry'] }))
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(patches).toEqual([{ judge: 'sol' }, { judge: 'sol' }])
  })

  it('«Нарезать» при непринятой правке остаётся на месте', async () => {
    const text = await open(() => json({ detail: 'boom' }, 500))
    fireEvent.change(text, { target: { value: 'Новый текст' } })
    fireEvent.click(slice())
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('textbox', { name: ru['brief.title'] })).toBeTruthy()
  })

  const leave = () => fireEvent.click(screen.getByRole('link', { name: 'Spec Council' }))
  const home = () => screen.findByRole('heading', { name: ru['home.title'] })

  it('переход по ссылке сначала сохраняет правку, не дожидаясь паузы', async () => {
    const text = await open()
    fireEvent.change(text, { target: { value: 'Новый текст' } })
    leave()
    expect(await home()).toBeTruthy()
    expect(patches).toEqual([{ brief: 'Новый текст' }])
  })

  it('непринятая правка не пропадает при переходе: страница остаётся, повтор сохраняет и уводит', async () => {
    let fail = true
    const text = await open(() => (fail ? json({ detail: 'boom' }, 500) : json(COUNCIL)))
    fireEvent.change(text, { target: { value: 'Новый текст' } })
    leave()
    expect((await screen.findByRole('alert')).textContent).toContain(ru['save.leaveAnyway'])
    expect((screen.getByRole('textbox', { name: ru['brief.title'] }) as HTMLTextAreaElement).value).toBe('Новый текст')

    fail = false
    fireEvent.click(screen.getByRole('button', { name: ru['common.retry'] }))
    expect(await home()).toBeTruthy()
    expect(patches).toEqual([{ brief: 'Новый текст' }, { brief: 'Новый текст' }])
  })

  it('уйти без непринятой правки можно, но только явно', async () => {
    const text = await open(() => json({ detail: 'boom' }, 500))
    fireEvent.change(text, { target: { value: 'Новый текст' } })
    leave()
    fireEvent.click(await screen.findByRole('button', { name: ru['save.leaveAnyway'] }))
    expect(await home()).toBeTruthy()
    expect(patches).toEqual([{ brief: 'Новый текст' }])
  })
})

describe('Нарезка', () => {
  const openSlices = (council: () => Council, start?: () => Promise<Response>) => {
    fetchMock.mockImplementation(server({ council, start }))
    renderAt('/councils/demo-1/slices')
  }

  it('без нарезки — подсказка и дорога на ввод', async () => {
    openSlices(() => COUNCIL)
    expect(await screen.findByRole('link', { name: ru['slices.toBrief'] })).toBeTruthy()
  })

  it('итог — текст целиком с подсветкой, типы, пометки о спорах; ход работы с ошибками', async () => {
    openSlices(() => ({ ...COUNCIL, slicing: DONE }))
    expect(await screen.findByRole('heading', { name: ru['slices.resultTitle'] })).toBeTruthy()
    expect(document.querySelector('.sliced-text')?.textContent).toBe(SLICED_TEXT)
    expect([...document.querySelectorAll('mark')].map(m => m.textContent)).toEqual(DONE.fragments.map(f => f.text))
    expect(screen.getByText(`${ru['label.proposal']} · 1`)).toBeTruthy()
    expect(screen.getByText(`${ru['label.risk']} · 0`)).toBeTruthy()
    expect(screen.getByText('готово ×2')).toBeTruthy()

    const chosen = (name: string) =>
      within(screen.getByRole('radiogroup', { name })).getByRole('radio', { checked: true }).textContent
    expect([chosen('F1'), chosen('F2')]).toEqual([ru['label.idea'], ru['label.proposal']])
    expect(screen.getByText('модели разошлись (Sol — ограничение, Fable — предложение), '
      + 'решил судья: Способ хранения.')).toBeTruthy()
    expect(screen.getByText('граница — решение судьи нарезки: две мысли')).toBeTruthy()

    expect(screen.getByText(ru['slices.stepState.skipped'])).toBeTruthy()
    expect(screen.getByText('нет входа в подписку')).toBeTruthy()
  })

  it('тип можно поменять: сохраняется сразу, тип совета остаётся виден', async () => {
    openSlices(() => ({ ...COUNCIL, slicing: DONE }))
    const first = await screen.findByRole('radiogroup', { name: 'F1' })
    fireEvent.click(within(first).getByRole('radio', { name: ru['label.risk'] }))
    expect(within(first).getByRole('radio', { checked: true }).textContent).toBe(ru['label.risk'])
    expect(screen.getByText('вы выбрали другой тип, у совета — «идея»')).toBeTruthy()
    expect(screen.getByText(`${ru['label.risk']} · 1`)).toBeTruthy()
    await waitFor(() => expect(patches).toEqual([{ labels: { 1: 'risk', 2: 'proposal' } }]))
  })

  it('пока идёт — спрашивает сервер и сам показывает итог', async () => {
    let current: Council = { ...COUNCIL, slicing: RUNNING }
    openSlices(() => current)
    expect(await screen.findByRole('heading', { name: ru['slices.runningTitle'] })).toBeTruthy()
    current = { ...COUNCIL, slicing: DONE }
    const result = { name: ru['slices.resultTitle'] }
    expect(await screen.findByRole('heading', result, { timeout: POLL_MS + 2000 })).toBeTruthy()
  }, POLL_MS + 5000)

  it('упавшая — причина и повтор', async () => {
    const failed: Slicing = { ...RUNNING, state: 'failed', error: 'ни один участник не справился' }
    openSlices(() => ({ ...COUNCIL, slicing: failed }))
    expect((await screen.findByRole('alert')).textContent).toBe('ни один участник не справился')
    fireEvent.click(screen.getByRole('button', { name: ru['slices.retry'] }))
    expect(await screen.findByRole('heading', { name: ru['slices.runningTitle'] })).toBeTruthy()
    expect(starts).toBe(1)
  })
})

describe('App: «Новый совет»', () => {
  const clickNew = () => fireEvent.click(screen.getByRole('button', { name: ru['header.newCouncil'] }))

  it('блокирует кнопку на время запроса и переходит во ввод', async () => {
    let resolve!: (r: Response) => void
    const rest = server()
    fetchMock.mockImplementation((url: string, init?: RequestInit) =>
      init?.method === 'POST' ? new Promise<Response>(r => { resolve = r }) : rest(url, init))
    renderAt('/')
    clickNew()
    const busy = screen.getByRole('button', { name: ru['header.creating'] }) as HTMLButtonElement
    expect(busy.disabled).toBe(true)

    resolve(new Response(JSON.stringify({ id: 'demo-1' }), { status: 200 }))
    expect(await screen.findByRole('heading', { name: COUNCIL.name })).toBeTruthy()
  })

  it('при ошибке показывает сообщение и снова даёт нажать', async () => {
    fetchMock.mockImplementation((_: string, init?: RequestInit) =>
      init?.method === 'POST' ? networkError() : json([]))
    renderAt('/')
    clickNew()
    expect((await screen.findByRole('alert')).textContent).toBe(ru['header.createFailed'])
    expect((screen.getByRole('button', { name: ru['header.newCouncil'] }) as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('Переключатель языка', () => {
  it('меняет надписи и <html lang>, помня выбор', async () => {
    fetchMock.mockReturnValue(json([]))
    renderAt('/')
    expect(await screen.findByText(ru['home.title'])).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: ru['header.switchLanguage'] }))
    expect(await screen.findByText(en['home.title'])).toBeTruthy()
    expect(document.documentElement.lang).toBe('en')
    expect(localStorage.getItem('lang')).toBe('en')
  })
})
