import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  Council, CouncilPatch, IdeaDiscovery, Label, QuestionDiscovery, Settings, Slicing, Stream, StreamIdea, Structure,
} from '../api'
import { App } from '../App'
import { setLanguage } from '../i18n'
import { en } from '../i18n/en'
import { ru } from '../i18n/ru'
import { HomePage } from './HomePage'
import { CouncilPage, POLL_MS, STAGES, stagePath } from './CouncilPage'

const COUNCIL: Council = {
  id: 'demo-1', name: 'Сервис уведомлений', status: 'structure', brief: 'Хочу воркер',
  participants: ['sol', 'fable'], judge: 'fable', updated_at: '2026-09-17T10:00:00Z', slicing: null,
  structure: null, streams: null,
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
  state: 'running', run: 'r1', text: SLICED_TEXT, fragments: [], error: null, steps: [
    { name: 'slice', state: 'running', runs: [run('sol', 'running'), run('fable', 'done')] },
    { name: 'slice_judge', state: 'waiting', runs: [run('fable', 'waiting')] },
    { name: 'label', state: 'waiting', runs: [run('sol', 'waiting'), run('fable', 'waiting')] },
    { name: 'label_judge', state: 'waiting', runs: [run('fable', 'waiting')] },
  ],
}
const DONE: Slicing = {
  state: 'done', run: 'r1', text: SLICED_TEXT, error: null,
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

const GROUPING: Structure = {
  state: 'running', run: 'g1', slicing_run: 'r1', labels: { 1: 'idea', 2: 'proposal' },
  steps: [
    { name: 'structure', state: 'running', runs: [run('sol', 'running'), run('fable', 'done')] },
    { name: 'structure_judge', state: 'waiting', runs: [run('fable', 'waiting')] },
  ],
  groups: [], relations: [], decisions: [], proposal: null, edited: false, revision: 0, error: null,
}
const GROUPED: Structure = {
  ...GROUPING, state: 'done',
  steps: [
    { name: 'structure', state: 'done', runs: [run('sol', 'done'), run('fable', 'done')] },
    { name: 'structure_judge', state: 'done', runs: [run('fable', 'done')] },
  ],
  groups: [
    { id: 'A', title: 'Воркер', fragment_ids: [1, 2], idea_fragment_ids: [1], missing_idea: false,
      shared_fragment_ids: [2] },
    { id: 'B', title: 'Хранение', fragment_ids: [2], idea_fragment_ids: [], missing_idea: true,
      shared_fragment_ids: [2] },
  ],
  relations: [{ source: 'B', target: 'A', type: 'related', reason: 'Пишет туда же, что и A.' }],
  decisions: [{ issue: 'F2: A или A+B', decision: 'A+B', reason: 'Касается обеих.' }],
}

const SEEKING: IdeaDiscovery = {
  state: 'running', run: 'i1', options: [], proposal: null, error: null, steps: [
    { name: 'idea_discovery', state: 'running', runs: [run('sol', 'running'), run('fable', 'done')] },
    { name: 'idea_judge', state: 'waiting', runs: [run('fable', 'waiting')] },
  ],
}
const FOUND: IdeaDiscovery = {
  ...SEEKING, state: 'done',
  steps: [
    { name: 'idea_discovery', state: 'done', runs: [run('sol', 'done'), run('fable', 'done')] },
    { name: 'idea_judge', state: 'done', runs: [run('fable', 'done')] },
  ],
  options: [
    { idea: 'Состояние не теряется', evidence: [2], reason: 'про хранение', models: ['sol'] },
    { idea: 'Результат переживает сбой', evidence: [2], reason: 'про надёжность', models: ['fable'] },
  ],
  proposal: { idea: 'Результат переживает сбой', evidence: [2], reason: 'шире', decided_by: 'judge', option: 1 },
}
/** Идея группы A — из текста: F1. */
const TEXT_IDEA: StreamIdea = { text: 'Хочу воркер.', by: 'text', evidence: [1] }
const QUESTIONS_SEEKING: QuestionDiscovery = {
  state: 'running', run: 'q1', idea: 'Хочу воркер.', questions: [], error: null, steps: [
    { name: 'question_discovery', state: 'running', runs: [run('sol', 'running'), run('fable', 'done')] },
    { name: 'question_judge', state: 'waiting', runs: [run('fable', 'waiting')] },
  ],
}
const QUESTIONS_FOUND: QuestionDiscovery = {
  ...QUESTIONS_SEEKING, state: 'done',
  steps: [
    { name: 'question_discovery', state: 'done', runs: [run('sol', 'done'), run('fable', 'done')] },
    { name: 'question_judge', state: 'done', runs: [run('fable', 'done')] },
  ],
  questions: [
    { id: 'Q1', text: 'Где хранить состояние?', source: 'inferred', source_question_id: null, proposal_ids: [2],
      reason: 'F2 отвечает на незаписанный вопрос' },
    { id: 'Q2', text: 'Как понять, что воркер не теряет результат?', source: 'discovered', source_question_id: null,
      proposal_ids: [], reason: 'без меры идею не проверить' },
  ],
}
/**
 * Совет с подтверждёнными группами: у A идея записана в тексте, у B её ищет совет. more —
 * что ещё у потоков: вопросы, отбор.
 */
const confirmed = (search: IdeaDiscovery = FOUND, structure: Structure = GROUPED,
                   ideas: Partial<Record<'A' | 'B', StreamIdea>> = {},
                   more: Partial<Record<'A' | 'B', Partial<Stream>>> = {}): Council => ({
  ...COUNCIL, status: 'review', slicing: DONE, structure,
  streams: [{ group: 'A', discovery: null, idea: ideas.A ?? null, questions: null, scope: null, ...more.A },
            { group: 'B', discovery: search, idea: ideas.B ?? null, questions: null, scope: null, ...more.B },
  ] satisfies Stream[],
})

/** Совет с другими типами фрагментов — как их сохранил бы сервер. */
const relabeled = (c: Council, labels: Record<number, Label> = {}): Council => ({
  ...c,
  slicing: c.slicing && {
    ...c.slicing, fragments: c.slicing.fragments.map(f => ({ ...f, label: labels[f.id] ?? f.label })),
  },
})

let fetchMock: ReturnType<typeof vi.fn>
let patches: CouncilPatch[]
let starts: number
let groupStarts: number
let edits: { action: string; body: unknown }[]
let streamCalls: { group: string; action: string; body: unknown }[]
beforeEach(async () => {
  await setLanguage('ru')
  fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock)
  patches = []; starts = 0; groupStarts = 0; edits = []; streamCalls = []
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

/**
 * Сервер: список, совет, настройки, PATCH, запуски, правки групп и действия с потоками. Каждый
 * ответ — новый Response: тело читается один раз. council — функция, если совет меняется
 * между запросами.
 */
const server = ({
  council = () => COUNCIL,
  patch = () => json(COUNCIL),
  start = () => json({ ...COUNCIL, status: 'slices', slicing: RUNNING }, 202),
  group = () => json({ ...COUNCIL, status: 'structure', slicing: DONE, structure: GROUPING }, 202),
  edit = () => json(council()),
  stream = () => json(council()),
}: {
  council?: () => Council; patch?: () => Promise<Response>
  start?: () => Promise<Response>; group?: () => Promise<Response>; edit?: () => Promise<Response>
  stream?: () => Promise<Response>
} = {}) =>
  (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    if (url === '/api/settings') return json(SETTINGS)
    if (url === '/api/councils') return method === 'POST' ? json({ id: COUNCIL.id }) : json([council()])
    if (url.endsWith('/slicing')) { starts++; return start() }
    if (url.endsWith('/structure')) { groupStarts++; return group() }
    const editAction = /\/structure\/(\w+)$/.exec(url)?.[1]
    if (editAction) { edits.push({ action: editAction, body: JSON.parse(String(init?.body)) }); return edit() }
    const streamAction = /\/streams\/(\w+)\/(idea|discovery|questions(?:\/discovery)?)$/.exec(url)
    if (streamAction) {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      streamCalls.push({ group: streamAction[1], action: streamAction[2], body })
      return stream()
    }
    if (method === 'PATCH') { patches.push(JSON.parse(String(init?.body))); return patch() }
    return json(council())
  }

const renderAt = (path: string) => render(<RouterProvider router={createMemoryRouter([{
  path: '/', element: <App />, children: [
    { index: true, element: <HomePage /> },
    ...STAGES.map(stage => ({ path: `councils/:id/${stagePath(stage)}`, element: <CouncilPage stage={stage} /> })),
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

  it('сводка: советы светофором, что требует внимания и куда идти', async () => {
    const councils: Council[] = [
      { ...COUNCIL, id: 'c1', name: 'Черновик' },
      { ...COUNCIL, id: 'c2', name: 'Нарезан', slicing: DONE },
      { ...COUNCIL, id: 'c3', name: 'Раскладывают', slicing: DONE, structure: GROUPING },
      { ...confirmed(FOUND), id: 'c4', name: 'С потоками' },
      { ...COUNCIL, id: 'c5', name: 'Упал', slicing: { ...RUNNING, state: 'failed', error: 'нет входа' } },
    ]
    fetchMock.mockImplementation((url: string) => (url === '/api/councils' ? json(councils) : server()(url)))
    renderAt('/')
    const overview = await screen.findByRole('region', { name: ru['home.overview'] })
    expect(within(overview).getAllByRole('listitem').map(li => li.textContent)).toEqual([
      '5советов', '2потока',
      `1${ru['home.tile.go']}`, `1${ru['home.tile.idle']}`, `2${ru['home.tile.yours']}`, `1${ru['home.tile.failed']}`,
    ])

    const pending = screen.getByRole('region', { name: 'Требует внимания (4)' })
    const cards = within(pending).getAllByRole('link')
    expect(cards.map(card => [card.getAttribute('href'), card.querySelector('.corner')?.textContent])).toEqual([
      ['/councils/c2/slices', '?'],
      ['/councils/c4/streams/A', '?'], ['/councils/c4/streams/B', '?'],
      ['/councils/c5/slices', '!'],
    ])
    expect(within(cards[2]).getByText('Поток B · идея')).toBeTruthy()
    expect(within(cards[3]).getByText(ru['attention.slicingFailed'])).toBeTruthy()

    const all = screen.getByRole('region', { name: ru['home.all'] })
    expect(within(within(all).getByRole('link', { name: /Раскладывают/ })).getByText(ru['home.light.running'])).toBeTruthy()
    expect(within(within(all).getByRole('link', { name: /Черновик/ })).getByText(ru['home.light.idle'])).toBeTruthy()
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

describe('Подтверждение групп и потоки', () => {
  const grouped = (status: Council['status'] = 'structure', structure: Structure = GROUPED): Council =>
    ({ ...COUNCIL, status, slicing: DONE, structure })
  const confirmCard = () => screen.findByRole('region', { name: ru['confirm.title'] })
  const confirmButton = async () =>
    within(await confirmCard()).getByRole('button', { name: ru['confirm.confirm'] }) as HTMLButtonElement
  const streamNav = () => screen.findByRole('navigation', { name: ru['streams.list'] })

  it('«Подтвердить»: группы становятся потоками, экран уходит к первому', async () => {
    let current = grouped()
    fetchMock.mockImplementation(server({
      council: () => current,
      edit: () => { current = confirmed(SEEKING); return json(current) },
    }))
    renderAt('/councils/demo-1/structure')
    fireEvent.click(await confirmButton())
    const nav = await streamNav()
    expect(edits).toEqual([{ action: 'confirm', body: { run: 'g1', revision: 0 } }])
    expect(within(nav).getByText('Потоки · 2')).toBeTruthy()
    const links = within(nav).getAllByRole('link')
    expect(links.map(link => link.textContent)).toEqual([
      `AВоркер${ru['streams.group.yours']}`, `BХранение${ru['streams.group.seeking']}`])
    expect(links[0].getAttribute('aria-current')).toBe('page')
    expect(screen.getByText(ru['idea.textNote'])).toBeTruthy()
    expect(screen.getByRole('link', { name: /Группы/ }).textContent).toContain(ru['light.done'])
  })

  it('подтверждённые — ссылка «К потокам», а не кнопка', async () => {
    fetchMock.mockImplementation(server({ council: () => confirmed() }))
    renderAt('/councils/demo-1/structure')
    const card = await confirmCard()
    expect(within(card).getByText(ru['confirm.done'])).toBeTruthy()
    fireEvent.click(within(card).getByRole('link', { name: ru['confirm.open'] }))
    expect(await streamNav()).toBeTruthy()
    expect(edits).toEqual([])
  })

  it('устаревшие после смены типов группы не подтвердить', async () => {
    const stale = { ...GROUPED, labels: { 1: 'idea' as const, 2: 'risk' as const } }
    fetchMock.mockImplementation(server({ council: () => grouped('structure', stale) }))
    renderAt('/councils/demo-1/structure')
    expect((await confirmButton()).disabled).toBe(true)
    expect(within(await confirmCard()).getByText(ru['confirm.stale'])).toBeTruthy()
  })

  it('группы поменяли в другой вкладке (409) — ошибка у кнопки, видны нынешние, экран на месте', async () => {
    let current = grouped()
    fetchMock.mockImplementation(server({
      council: () => current,
      edit: () => {
        current = grouped('structure', { ...GROUPED, revision: 1, groups: [
          { ...GROUPED.groups[0], title: 'Воркер Codex' }, GROUPED.groups[1]] })
        return json({ detail: 'Группы уже поменяли — правка была к прежним' }, 409)
      },
    }))
    renderAt('/councils/demo-1/structure')
    fireEvent.click(await confirmButton())
    const alert = await within(await confirmCard()).findByRole('alert')
    expect(alert.textContent).toBe('Группы уже поменяли — правка была к прежним')
    expect(await screen.findByRole('region', { name: 'Воркер Codex' })).toBeTruthy()
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.queryByRole('navigation', { name: ru['streams.list'] })).toBeNull()
  })

  it('пока сохраняется правка группы, подтвердить нельзя', async () => {
    let release!: () => void
    fetchMock.mockImplementation(server({
      council: () => grouped(),
      edit: () => new Promise<Response>(r => { release = () => r(new Response(JSON.stringify(grouped()))) }),
    }))
    renderAt('/councils/demo-1/structure')
    fireEvent.click(within(await screen.findByRole('region', { name: 'Воркер' })).getByRole('button', { name: ru['groups.merge'] }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'B Хранение' }))
    await waitFor(async () => expect((await confirmButton()).disabled).toBe(true))
    release()
    await waitFor(async () => expect((await confirmButton()).disabled).toBe(false))
    expect(edits.map(e => e.action)).toEqual(['merge'])
  })

  it('объединение после подтверждения снимает его: снова кнопка «Подтвердить»', async () => {
    let current = confirmed()
    fetchMock.mockImplementation(server({
      council: () => current,
      edit: () => {
        current = grouped('structure', { ...GROUPED, edited: true, relations: [],
                                         groups: [{ ...GROUPED.groups[0], shared_fragment_ids: [] }] })
        return json(current)
      },
    }))
    renderAt('/councils/demo-1/structure')
    expect(within(await confirmCard()).getByRole('link', { name: ru['confirm.open'] })).toBeTruthy()
    fireEvent.click(within(await screen.findByRole('region', { name: 'Воркер' })).getByRole('button', { name: ru['groups.merge'] }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'B Хранение' }))
    expect((await confirmButton()).disabled).toBe(false)
    expect(screen.getByRole('link', { name: /Группы/ }).textContent).not.toContain(ru['light.done'])
  })

  it.each([
    ['группы не подтверждены', grouped()],
    ['групп нет', { ...COUNCIL, status: 'review' as const }],
  ])('потоки, когда %s, — дорога к группам', async (_, council) => {
    fetchMock.mockImplementation(server({ council: () => council }))
    renderAt('/councils/demo-1/streams')
    const link = await screen.findByRole('link', { name: ru['streams.toGroups'] })
    expect(link.getAttribute('href')).toBe('/councils/demo-1/structure')
    expect(screen.queryByRole('navigation', { name: ru['streams.list'] })).toBeNull()
  })

  it('потоки по устаревшим группам — предупреждение', async () => {
    const stale = { ...GROUPED, labels: { 1: 'idea' as const, 2: 'risk' as const } }
    fetchMock.mockImplementation(server({ council: () => confirmed(FOUND, stale) }))
    renderAt('/councils/demo-1/streams')
    expect(await screen.findByText(ru['streams.stale'], { exact: false })).toBeTruthy()
    expect((screen.getByRole('button', { name: ru['idea.approve'] }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('Поток: группа и идея', () => {
  const streamNav = () => screen.findByRole('navigation', { name: ru['streams.list'] })
  const ideaField = () => screen.findByRole('textbox', { name: 'Идея потока B' }) as Promise<HTMLTextAreaElement>
  const approveButton = () => screen.getByRole('button', { name: ru['idea.approve'] }) as HTMLButtonElement
  const openStream = (group: string, council: () => Council, stream?: () => Promise<Response>) => {
    fetchMock.mockImplementation(server({ council, stream }))
    renderAt(`/councils/demo-1/streams/${group}`)
  }

  it('идея из текста: её только утверждают, и поток уходит к вопросам — их ищет ИИ', async () => {
    openStream('A', () => confirmed(),
               () => json(confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: QUESTIONS_SEEKING } })))
    expect(await screen.findByText(ru['idea.textNote'])).toBeTruthy()
    expect(screen.queryByRole('textbox')).toBeNull()
    fireEvent.click(approveButton())
    expect(await screen.findByRole('heading', { name: ru['questions.title'] })).toBeTruthy()
    expect(streamCalls).toEqual([{ group: 'A', action: 'idea', body: { run: 'g1', revision: 0 } }])
    expect(screen.getByText(ru['questions.by.text'])).toBeTruthy()
    expect(screen.getByText(ru['questions.seeking'], { exact: false })).toBeTruthy()
    expect((screen.getByRole('button', { name: ru['questions.approve'] }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText(ru['step.question_discovery'])).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: ru['questions.change'] }))
    expect(await screen.findByRole('heading', { name: ru['idea.title'] })).toBeTruthy()
  })

  it('идеи нет: в поле — выбор судьи, другой вариант можно взять и поправить', async () => {
    const mine = 'Результат переживает падение воркера'
    openStream('B', () => confirmed(), () => json(confirmed(FOUND, GROUPED, { B: { text: mine, by: 'human', evidence: [] } })))
    const field = await ideaField()
    expect(field.value).toBe('Результат переживает сбой')
    expect(screen.getByText('почему: F2 — шире')).toBeTruthy()
    expect(screen.getByText(ru['idea.foundNote'])).toBeTruthy()
    const options = screen.getAllByRole('listitem').filter(li => li.classList.contains('idea-option'))
    expect(options).toHaveLength(2)
    expect(within(options[1]).getByText(ru['idea.judgePick'])).toBeTruthy()
    expect(within(options[0]).getByText('Sol · F2 — про хранение')).toBeTruthy()
    expect((within(options[1]).getByRole('button', { name: ru['idea.take'] }) as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(within(options[0]).getByRole('button', { name: ru['idea.take'] }))
    expect(field.value).toBe('Состояние не теряется')
    expect(screen.getByText('почему: F2 — про хранение')).toBeTruthy()
    fireEvent.change(field, { target: { value: mine } })
    expect(screen.queryByText(/почему:/)).toBeNull()
    expect(screen.getByText(ru['idea.byYou'], { selector: '.source-tag' })).toBeTruthy()
    fireEvent.click(approveButton())
    expect(await screen.findByRole('heading', { name: ru['questions.title'] })).toBeTruthy()
    expect(streamCalls).toEqual([{ group: 'B', action: 'idea', body: { run: 'g1', revision: 0, text: mine } }])
  })

  it('ИИ не предложил идею — поле пустое, утвердить можно, только написав свою', async () => {
    const none: IdeaDiscovery = { ...FOUND, options: [],
                                  proposal: { idea: null, evidence: [], reason: 'цели нет', decided_by: 'agreed', option: null } }
    openStream('B', () => confirmed(none))
    const field = await ideaField()
    expect(field.value).toBe('')
    expect(screen.getByText(ru['idea.noneNote'].replace('{{reason}}', 'цели нет'))).toBeTruthy()
    expect(approveButton().disabled).toBe(true)
    fireEvent.change(field, { target: { value: '   ' } })
    expect(approveButton().disabled).toBe(true)
    fireEvent.change(field, { target: { value: 'Своя идея' } })
    expect(approveButton().disabled).toBe(false)
  })

  it('«Сейчас»: где поток и чей ход, цепочка сегментами', async () => {
    openStream('B', () => confirmed(SEEKING))
    const now = await screen.findByRole('region', { name: 'Хранение' })
    expect(within(now).getByText(`Сейчас · поток B · ${ru['now.running']}`)).toBeTruthy()
    const segments = within(now).getAllByRole('listitem')
    expect(segments.map(segment => segment.className)).toEqual([
      'segment running', 'segment idle', 'segment idle', 'segment idle', 'segment idle'])
    expect(segments[0].textContent).toContain(ru['chain.ideaSeeking'])
    expect(segments.map(segment => segment.querySelector('.sr-only')?.textContent)).toEqual([
      ` (${ru['light.running']})`, ...Array(4).fill(` (${ru['light.idle']})`)])
  })

  it('пока ИИ ищет идею — утвердить нельзя, виден ход работы', async () => {
    openStream('B', () => confirmed(SEEKING))
    expect(await screen.findByText(ru['idea.seeking'], { exact: false })).toBeTruthy()
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(approveButton().disabled).toBe(true)
    expect(screen.getByText(ru['step.idea_discovery'])).toBeTruthy()
    expect(screen.getByText(ru['idea.capsAi'])).toBeTruthy()
  })

  it('поиск упал — причина и повтор; написать идею самому тоже можно', async () => {
    const failed: IdeaDiscovery = { ...SEEKING, state: 'failed', error: 'Нет подключения к моделям: GPT-5.6 Sol' }
    openStream('B', () => confirmed(failed), () => json(confirmed(SEEKING), 202))
    expect((await screen.findByRole('alert')).textContent).toBe('Нет подключения к моделям: GPT-5.6 Sol')
    expect(await ideaField()).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: ru['run.retry'] }))
    expect(await screen.findByText(ru['idea.seeking'], { exact: false })).toBeTruthy()
    expect(streamCalls).toEqual([{ group: 'B', action: 'discovery', body: undefined }])
  })

  it('своя идея после упавшего поиска: поток прошёл шаг, повтора поиска больше нет', async () => {
    const failed: IdeaDiscovery = { ...SEEKING, state: 'failed', error: 'Нет подключения к моделям: GPT-5.6 Sol' }
    const own: StreamIdea = { text: 'Своя идея', by: 'human', evidence: [] }
    openStream('B', () => confirmed(failed, GROUPED, { B: own }))
    expect(await screen.findByRole('heading', { name: ru['questions.title'] })).toBeTruthy()
    expect(screen.getByText(`Сейчас · поток B · ${ru['now.yours']}`)).toBeTruthy()
    expect(screen.getByText(ru['questions.notSought'], { exact: false })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: ru['questions.change'] }))
    expect(await screen.findByRole('heading', { name: ru['idea.title'] })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByRole('button', { name: ru['run.retry'] })).toBeNull()
  })

  it('опрос, ушедший до утверждения идеи, его не стирает; следующий подхватывает найденное', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      const pending: ((council: Council) => void)[] = []
      let first = true
      fetchMock.mockImplementation((url: string, init?: RequestInit) => {
        if (url === '/api/councils/demo-1' && !init?.method) {
          if (first) { first = false; return json(confirmed(SEEKING)) }
          return new Promise<Response>(r => pending.push(c => r(new Response(JSON.stringify(c)))))
        }
        // Утвердили идею A — и совет сразу ищет к ней вопросы.
        return server({ stream: () => json(confirmed(SEEKING, GROUPED, { A: TEXT_IDEA },
                                                      { A: { questions: QUESTIONS_SEEKING } })) })(url, init)
      })
      renderAt('/councils/demo-1/streams/A')
      const nav = await streamNav()
      const link = (name: RegExp) => within(nav).getByRole('link', { name })
      vi.advanceTimersByTime(POLL_MS)               // опрос ушёл до утверждения, ответа пока нет
      expect(pending).toHaveLength(1)
      fireEvent.click(approveButton())
      expect(await screen.findByText(ru['questions.seeking'], { exact: false })).toBeTruthy()

      pending[0](confirmed(FOUND))                  // в нём A ещё без идеи и без поиска вопросов
      await waitFor(() => expect(link(/Воркер/).textContent).toContain(ru['streams.questions.seeking']))
      expect(link(/Хранение/).textContent).toContain(ru['streams.group.seeking'])   // и B — как было

      vi.advanceTimersByTime(POLL_MS)               // следующий опрос — уже после утверждения
      await waitFor(() => expect(pending).toHaveLength(2))
      pending[1](confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: QUESTIONS_FOUND } }))
      await waitFor(() => expect(link(/Хранение/).textContent).toContain(ru['streams.group.yours']))
      expect(link(/Воркер/).textContent).toContain(ru['streams.questions.yours'])
      expect(await screen.findByText('Где хранить состояние?')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it('пока ИИ ищет вопросы к идее, её не поменять', async () => {
    openStream('A', () => confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: QUESTIONS_SEEKING } }))
    fireEvent.click(await screen.findByRole('button', { name: ru['questions.change'] }))
    expect(await screen.findByText(ru['idea.questionsRunning'])).toBeTruthy()
    expect(approveButton().disabled).toBe(true)
  })

  it('вопросы: происхождение, причина, предложения; убрать, вернуть, свой — и отбор уходит на сервер', async () => {
    const chosen = { questions: QUESTIONS_FOUND, scope: [QUESTIONS_FOUND.questions[0],
      { id: 'Q3', text: 'Кто платит за хостинг?', source: 'added' as const, source_question_id: null, proposal_ids: [], reason: null }] }
    openStream('A', () => confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: QUESTIONS_FOUND } }),
               () => json(confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: chosen })))
    const list = await screen.findByRole('list', { name: ru['questions.found'] })
    const item = (n: number) => list.children[n] as HTMLElement   // вопросы, без вложенных предложений
    const first = item(0)
    expect(within(first).getByText('Где хранить состояние?')).toBeTruthy()
    expect(within(first).getByText('почему: F2 отвечает на незаписанный вопрос')).toBeTruthy()
    expect(within(first).getByText('Состояние держать в файлах, без базы.', { exact: false })).toBeTruthy()
    expect(screen.getByText('Решать 2 из 2')).toBeTruthy()

    const second = item(1)
    fireEvent.click(within(second).getByRole('button', { name: ru['questions.remove'] }))
    expect(within(second).getByText(ru['questions.removedTag'])).toBeTruthy()
    expect(screen.getByText('Решать 1 из 2')).toBeTruthy()
    fireEvent.click(within(second).getByRole('button', { name: ru['questions.restore'] }))
    fireEvent.click(within(second).getByRole('button', { name: ru['questions.remove'] }))

    const own = screen.getByRole('textbox', { name: ru['questions.own'] })
    fireEvent.change(own, { target: { value: '  Кто платит за хостинг? ' } })
    fireEvent.click(screen.getByRole('button', { name: ru['questions.add'] }))
    expect(within(list).getByText('Кто платит за хостинг?')).toBeTruthy()
    expect(screen.getByText('Решать 2 из 3')).toBeTruthy()
    // Тот же вопрос, что оставленный, — иначе только знак в конце и регистр: не добавляется.
    for (const twice of ['где хранить состояние', 'кто платит за хостинг!']) {
      fireEvent.change(own, { target: { value: twice } })
      fireEvent.click(screen.getByRole('button', { name: ru['questions.add'] }))
      expect(screen.getByText(ru['questions.twice'])).toBeTruthy()
      expect(screen.getByText('Решать 2 из 3')).toBeTruthy()
    }
    fireEvent.change(own, { target: { value: '' } })

    fireEvent.click(screen.getByRole('button', { name: ru['questions.approve'] }))
    expect(await screen.findByRole('heading', { name: ru['options.title'] })).toBeTruthy()
    expect(streamCalls).toEqual([{ group: 'A', action: 'questions',
                                   body: { run: 'g1', revision: 0, questions_run: 'q1', keep: ['Q1'],
                                           added: ['Кто платит за хостинг?'] } }])
    expect(screen.getByText(ru['options.stub'])).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: ru['options.change'] }))
    expect(await screen.findByText('Решать 2 из 3')).toBeTruthy()      // черновик — от утверждённого отбора
  })

  it('поиск вопросов упал — причина, повтор; своими вопросами отбор всё равно возможен', async () => {
    const failed: QuestionDiscovery = { ...QUESTIONS_SEEKING, state: 'failed', error: 'Нет подключения к моделям: GPT-5.6 Sol' }
    openStream('A', () => confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: failed } }),
               () => json(confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: QUESTIONS_SEEKING } }), 202))
    expect((await screen.findByRole('alert')).textContent).toBe('Нет подключения к моделям: GPT-5.6 Sol')
    const approve = screen.getByRole('button', { name: ru['questions.approve'] }) as HTMLButtonElement
    expect(approve.disabled).toBe(true)
    fireEvent.change(screen.getByRole('textbox', { name: ru['questions.own'] }), { target: { value: 'Свой' } })
    fireEvent.click(screen.getByRole('button', { name: ru['questions.add'] }))
    expect(approve.disabled).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: ru['run.retry'] }))
    expect(await screen.findByText(ru['questions.seeking'], { exact: false })).toBeTruthy()
    expect(streamCalls).toEqual([{ group: 'A', action: 'questions/discovery', body: undefined }])
  })

  it('повтор поиска, которому сервер отказал не потому, что он уже идёт, — отказ виден', async () => {
    const failed: QuestionDiscovery = { ...QUESTIONS_SEEKING, state: 'failed', error: 'Нет подключения к моделям: GPT-5.6 Sol' }
    openStream('A', () => confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: failed } }),
               () => json({ detail: 'Вопросы потока уже утверждены' }, 409))
    fireEvent.click(await screen.findByRole('button', { name: ru['run.retry'] }))
    expect(await screen.findByText('Вопросы потока уже утверждены')).toBeTruthy()
    expect(screen.queryByText(ru['questions.seeking'], { exact: false })).toBeNull()
  })

  it('повтор, который другая вкладка уже запустила и даже довела до конца, — показан её итог', async () => {
    const failed: QuestionDiscovery = { ...QUESTIONS_SEEKING, state: 'failed', error: 'Нет подключения к моделям: GPT-5.6 Sol' }
    let current = confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: failed } })
    openStream('A', () => current, () => {
      current = confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: { ...QUESTIONS_FOUND, run: 'q2' } } })
      return json({ detail: 'Этот ход уже запустили' }, 409)
    })
    fireEvent.click(await screen.findByRole('button', { name: ru['run.retry'] }))
    expect(await screen.findByText('Где хранить состояние?')).toBeTruthy()
    expect(screen.queryByText('Этот ход уже запустили')).toBeNull()
  })

  it('по устаревшим группам вопросы заново не ищут', async () => {
    const failed: QuestionDiscovery = { ...QUESTIONS_SEEKING, state: 'failed', error: 'Нет подключения к моделям: GPT-5.6 Sol' }
    const stale = { ...GROUPED, labels: { 1: 'idea' as const, 2: 'risk' as const } }
    openStream('A', () => confirmed(FOUND, stale, { A: TEXT_IDEA }, { A: { questions: failed } }))
    expect((await screen.findByRole('button', { name: ru['run.retry'] }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('свои вопросы, разные для экрана, — разные и для сервера: Straße и STRASSE', async () => {
    openStream('A', () => confirmed(FOUND, GROUPED, { A: TEXT_IDEA }, { A: { questions: QUESTIONS_FOUND } }))
    const own = await screen.findByRole('textbox', { name: ru['questions.own'] })
    for (const text of ['Straße?', 'STRASSE']) {
      fireEvent.change(own, { target: { value: text } })
      fireEvent.click(screen.getByRole('button', { name: ru['questions.add'] }))
    }
    expect(screen.getByText('Решать 4 из 4')).toBeTruthy()
    expect(screen.queryByText(ru['questions.twice'])).toBeNull()
  })

  it('утвердить к прежним группам нельзя (409) — ошибка и нынешние группы', async () => {
    let current = confirmed()
    openStream('B', () => current, () => {
      current = confirmed(FOUND, { ...GROUPED, revision: 1,
                                   groups: [GROUPED.groups[0], { ...GROUPED.groups[1], title: 'Хранилище' }] })
      return json({ detail: 'Группы уже поменяли — правка была к прежним' }, 409)
    })
    await ideaField()
    fireEvent.click(approveButton())
    expect((await screen.findByRole('alert')).textContent).toBe('Группы уже поменяли — правка была к прежним')
    expect(await within(await streamNav()).findByRole('link', { name: /Хранилище/ })).toBeTruthy()
  })
})


describe('CouncilPage', () => {
  it('показывает проект: имя в шапке, этапы светофором', async () => {
    fetchMock.mockImplementation(server({ council: () => ({ ...COUNCIL, slicing: DONE, structure: GROUPING }) }))
    renderAt('/councils/demo-1/brief')
    expect(await screen.findByRole('heading', { name: COUNCIL.name })).toBeTruthy()
    // Имя в шапку ставит эффект страницы — он может отработать чуть позже заголовка.
    await waitFor(() => expect(screen.getByRole('banner').textContent).toContain(COUNCIL.name))
    const tab = (name: RegExp) => screen.getByRole('link', { name })
    expect(tab(/Нарезка/).textContent).toContain(ru['light.done'])
    expect(tab(/Нарезка/).querySelector('.tab-num')?.textContent).toBe('✓')
    expect(tab(/Группы/).textContent).toContain(ru['light.running'])
    expect(tab(/Группы/).querySelector('.tab-num')?.className).toContain('running')
    expect(tab(/Потоки/).textContent).toContain(ru['light.idle'])   // и «не начат» — словами
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

  it('нарезка уже идёт (409) — «Нарезать» ведёт к ней, а не к ошибке', async () => {
    let started = false
    fetchMock.mockImplementation(server({
      council: () => (started ? { ...COUNCIL, slicing: RUNNING } : COUNCIL),
      start: () => { started = true; return json({ detail: 'Нарезка уже идёт' }, 409) },
    }))
    renderAt('/councils/demo-1/brief')
    fireEvent.click(await screen.findByRole('button', { name: ru['brief.slice'] }))
    expect(await screen.findByRole('heading', { name: ru['slices.runningTitle'] })).toBeTruthy()
  })

  it('отказ сервера в запуске объясняет, почему, и оставляет на вводе', async () => {
    await open(undefined, () => json({ detail: 'Нет подключения к моделям: Gemini Astra 3' }, 422))
    fireEvent.click(slice())
    expect((await screen.findByRole('alert')).textContent).toBe('Нет подключения к моделям: Gemini Astra 3')
    expect(screen.getByRole('textbox', { name: ru['brief.title'] })).toBeTruthy()
  })

  it('временный отказ (503) — это ошибка на месте, а не переход к пустой нарезке', async () => {
    await open(undefined, () => json({ detail: 'Состав совета меняется прямо сейчас — попробуйте ещё раз' }, 503))
    fireEvent.click(slice())
    expect((await screen.findByRole('alert')).textContent).toBe('Состав совета меняется прямо сейчас — попробуйте ещё раз')
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

    expect(screen.getByText(ru['progress.stepState.skipped'])).toBeTruthy()
    expect(screen.getByText('нет входа в подписку')).toBeTruthy()
  })

  it('тип можно поменять: сохраняется сразу, тип совета остаётся виден', async () => {
    openSlices(() => ({ ...COUNCIL, slicing: DONE }))
    const first = await screen.findByRole('radiogroup', { name: 'F1' })
    fireEvent.click(within(first).getByRole('radio', { name: ru['label.risk'] }))
    expect(within(first).getByRole('radio', { checked: true }).textContent).toBe(ru['label.risk'])
    expect(screen.getByText('вы выбрали другой тип, у совета — «идея»')).toBeTruthy()
    expect(screen.getByText(`${ru['label.risk']} · 1`)).toBeTruthy()
    await waitFor(() => expect(patches).toEqual([{ labels: { 1: 'risk' }, slicing_run: 'r1' }]))
  })

  it('нарезку переделали в другой вкладке — прежние типы не ложатся на новую, экран её показывает', async () => {
    const redone: Slicing = {
      ...DONE, run: 'r2', text: 'Совсем другой текст.',
      fragments: [{ ...DONE.fragments[0], text: 'Совсем другой текст.' }],
    }
    let current: Council = { ...COUNCIL, slicing: DONE }
    openSlices(() => current)
    fetchMock.mockImplementation(server({
      council: () => current,
      patch: () => { current = { ...COUNCIL, slicing: redone }; return json({ detail: 'Нарезку уже переделали' }, 409) },
    }))
    const first = await screen.findByRole('radiogroup', { name: 'F1' })
    fireEvent.click(within(first).getByRole('radio', { name: ru['label.risk'] }))
    expect(await screen.findByText('Совсем другой текст.', { selector: '.fragment-text' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(patches).toEqual([{ labels: { 1: 'risk' }, slicing_run: 'r1' }])
  })

  it('правки типов, пока идёт сохранение, уходят следом вместе и не затирают друг друга', async () => {
    let release!: () => void
    let first = true
    openSlices(() => ({ ...COUNCIL, slicing: DONE }))
    fetchMock.mockImplementation(server({
      council: () => ({ ...COUNCIL, slicing: DONE }),
      patch: () => {
        if (!first) return json(COUNCIL)
        first = false
        return new Promise<Response>(r => { release = () => r(new Response(JSON.stringify(COUNCIL))) })
      },
    }))
    const pick = (fragment: string, label: string) => fireEvent.click(
      within(screen.getByRole('radiogroup', { name: fragment })).getByRole('radio', { name: label }))
    await screen.findByRole('radiogroup', { name: 'F1' })

    pick('F1', ru['label.risk'])
    await waitFor(() => expect(patches).toHaveLength(1))   // первый запрос ушёл и висит
    pick('F2', ru['label.idea'])
    pick('F1', ru['label.question'])
    release()
    await waitFor(() => expect(patches).toHaveLength(2))
    expect(patches).toEqual([
      { labels: { 1: 'risk' }, slicing_run: 'r1' },
      { labels: { 1: 'question', 2: 'idea' }, slicing_run: 'r1' },
    ])
  })

  it('пока идёт — спрашивает сервер и сам показывает итог', async () => {
    let current: Council = { ...COUNCIL, slicing: RUNNING }
    openSlices(() => current)
    expect(await screen.findByRole('heading', { name: ru['slices.runningTitle'] })).toBeTruthy()
    current = { ...COUNCIL, slicing: DONE }
    const result = { name: ru['slices.resultTitle'] }
    expect(await screen.findByRole('heading', result, { timeout: POLL_MS + 2000 })).toBeTruthy()
  }, POLL_MS + 5000)

  it('повтор, когда нарезку уже запустили (409), подхватывает идущую', async () => {
    const failed: Slicing = { ...RUNNING, state: 'failed', error: 'ни один участник не справился' }
    let current: Council = { ...COUNCIL, slicing: failed }
    openSlices(() => current, () => {
      current = { ...COUNCIL, slicing: RUNNING }   // её уже запустили в другой вкладке
      return json({ detail: 'Нарезка уже идёт' }, 409)
    })
    fireEvent.click(await screen.findByRole('button', { name: ru['run.retry'] }))
    expect(await screen.findByRole('heading', { name: ru['slices.runningTitle'] })).toBeTruthy()
    expect(screen.queryByText('Нарезка уже идёт')).toBeNull()
  })

  it('опрос не копит запросы, а запоздалый ответ не затирает правку типа', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      const pending: ((council: Council) => void)[] = []
      let first = true
      fetchMock.mockImplementation((url: string, init?: RequestInit) => {
        if (url === '/api/councils/demo-1' && !init?.method) {
          if (first) { first = false; return json({ ...COUNCIL, slicing: RUNNING }) }
          return new Promise<Response>(r => pending.push(c => r(new Response(JSON.stringify(c)))))
        }
        return server()(url, init)
      })
      renderAt('/councils/demo-1/slices')
      expect(await screen.findByRole('heading', { name: ru['slices.runningTitle'] })).toBeTruthy()

      vi.advanceTimersByTime(POLL_MS * 3)          // три такта, а ответа всё нет
      expect(pending).toHaveLength(1)

      pending[0]({ ...COUNCIL, slicing: DONE })
      const first1 = await screen.findByRole('radiogroup', { name: 'F1' })
      fireEvent.click(within(first1).getByRole('radio', { name: ru['label.risk'] }))
      vi.advanceTimersByTime(POLL_MS * 3)          // нарезка готова — больше не спрашиваем
      expect(pending).toHaveLength(1)
      expect(within(first1).getByRole('radio', { checked: true }).textContent).toBe(ru['label.risk'])
    } finally {
      vi.useRealTimers()
    }
  })

  it('упавшая — причина и повтор', async () => {
    const failed: Slicing = { ...RUNNING, state: 'failed', error: 'ни один участник не справился' }
    openSlices(() => ({ ...COUNCIL, slicing: failed }))
    expect((await screen.findByRole('alert')).textContent).toBe('ни один участник не справился')
    fireEvent.click(screen.getByRole('button', { name: ru['run.retry'] }))
    expect(await screen.findByRole('heading', { name: ru['slices.runningTitle'] })).toBeTruthy()
    expect(starts).toBe(1)
  })
})

describe('Группы', () => {
  const openAt = (stage: string, council: () => Council) => {
    fetchMock.mockImplementation(server({ council }))
    renderAt(`/councils/demo-1/${stage}`)
  }

  it('после нарезки — «Дальше»: предложить группы и перейти к ним', async () => {
    let current: Council = { ...COUNCIL, slicing: DONE }
    fetchMock.mockImplementation(server({
      council: () => current,
      group: () => { current = { ...COUNCIL, status: 'structure', slicing: DONE, structure: GROUPING }
                     return json(current, 202) },
    }))
    renderAt('/councils/demo-1/slices')
    fireEvent.click(await screen.findByRole('button', { name: ru['next.propose'] }))
    expect(await screen.findByRole('heading', { name: ru['groups.runningTitle'] })).toBeTruthy()
    expect(groupStarts).toBe(1)
    expect(screen.getByText(ru['step.structure'])).toBeTruthy()
  })

  it('тип поменяли и сразу «Предложить группы» — сперва сохраняется тип, правка во время запуска не откатывается', async () => {
    let current: Council = { ...COUNCIL, slicing: DONE }
    let savedBeforeStart = -1
    let answer!: () => void
    fetchMock.mockImplementation(server({
      council: () => current,
      patch: () => { current = relabeled(current, patches.at(-1)?.labels); return json(current) },
      group: () => {
        savedBeforeStart = patches.length
        const started = JSON.stringify({ ...current, status: 'structure', structure: GROUPING })
        return new Promise<Response>(r => { answer = () => r(new Response(started, { status: 202 })) })
      },
    }))
    renderAt('/councils/demo-1/slices')
    const pick = (label: string) => fireEvent.click(
      within(screen.getByRole('radiogroup', { name: 'F1' })).getByRole('radio', { name: label }))
    await screen.findByRole('radiogroup', { name: 'F1' })
    pick(ru['label.risk'])
    fireEvent.click(screen.getByRole('button', { name: ru['next.propose'] }))
    await waitFor(() => expect(groupStarts).toBe(1))
    expect(savedBeforeStart).toBe(1)
    pick(ru['label.question'])                      // запуск ещё в пути, ответ её не знает
    await waitFor(() => expect(patches).toHaveLength(2))
    answer()
    expect(await screen.findByRole('heading', { name: ru['groups.runningTitle'] })).toBeTruthy()

    fireEvent.click(screen.getByRole('link', { name: /Нарезка/ }))
    const again = await screen.findByRole('radiogroup', { name: 'F1' })
    expect(within(again).getByRole('radio', { checked: true }).textContent).toBe(ru['label.question'])
  })

  it('правку типа из другой вкладки видно после запуска, и свежие группы не устарели', async () => {
    let current: Council = { ...COUNCIL, slicing: DONE }
    fetchMock.mockImplementation(server({
      council: () => current,
      group: () => {
        current = { ...current, status: 'structure', structure: { ...GROUPED, labels: { 1: 'idea', 2: 'risk' } } }
        return json(current, 202)
      },
    }))
    renderAt('/councils/demo-1/slices')
    await screen.findByRole('radiogroup', { name: 'F2' })
    current = relabeled(current, { 2: 'risk' })         // другая вкладка
    fireEvent.click(screen.getByRole('button', { name: ru['next.propose'] }))
    expect(await screen.findByRole('heading', { name: 'ИИ предлагает 2 группы' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: ru['groups.again'] })).toBeNull()

    fireEvent.click(screen.getByRole('link', { name: /Нарезка/ }))
    const second = await screen.findByRole('radiogroup', { name: 'F2' })
    expect(within(second).getByRole('radio', { checked: true }).textContent).toBe(ru['label.risk'])
  })

  it('разложенные — ссылка «К группам», а не новый запуск', async () => {
    openAt('slices', () => ({ ...COUNCIL, slicing: DONE, structure: GROUPED }))
    expect(await screen.findByRole('link', { name: ru['next.open'] })).toBeTruthy()
    expect(screen.queryByRole('button', { name: ru['next.propose'] })).toBeNull()
  })

  it('группы: буквы, названия, связи, общий фрагмент, решение судьи', async () => {
    openAt('structure', () => ({ ...COUNCIL, status: 'structure', slicing: DONE, structure: GROUPED }))
    expect(await screen.findByRole('heading', { name: 'ИИ предлагает 2 группы' })).toBeTruthy()
    const a = screen.getByRole('region', { name: 'Воркер' })
    const b = screen.getByRole('region', { name: 'Хранение' })
    expect(within(a).getByText('связана с B')).toBeTruthy()
    expect(within(b).getByText(ru['groups.missingIdea'])).toBeTruthy()
    expect(within(b).getByText('Пишет туда же, что и A.')).toBeTruthy()
    expect(within(a).queryByText('Пишет туда же, что и A.')).toBeNull()
    expect(within(a).getByText('копия · общий с B')).toBeTruthy()
    expect(within(b).getByText('копия · общий с A')).toBeTruthy()
    expect(within(a).getAllByText(ru['label.proposal'])).toHaveLength(1)
    expect(screen.getByText('Судья: F2: A или A+B → A+B. Касается обеих.')).toBeTruthy()
    expect(screen.getByText('готово ×2')).toBeTruthy()
  })

  it('типы поменяли после раскладки — предупреждение и «Разложить заново»', async () => {
    const stale = { ...GROUPED, labels: { 1: 'idea' as const, 2: 'risk' as const } }
    openAt('structure', () => ({ ...COUNCIL, status: 'structure', slicing: DONE, structure: stale }))
    fireEvent.click(await screen.findByRole('button', { name: ru['groups.again'] }))
    await waitFor(() => expect(groupStarts).toBe(1))
  })

  it('без раскладки — дорога к нарезке', async () => {
    openAt('structure', () => ({ ...COUNCIL, slicing: DONE }))
    expect(await screen.findByRole('link', { name: ru['groups.toSlices'] })).toBeTruthy()
  })
})

describe('Правка групп', () => {
  const grouped = (structure: Structure = GROUPED): Council =>
    ({ ...COUNCIL, status: 'structure', slicing: DONE, structure })
  const MERGED: Structure = {
    ...GROUPED, edited: true, relations: [],
    groups: [{ ...GROUPED.groups[0], fragment_ids: [1, 2], shared_fragment_ids: [] }],
  }
  const openWith = (edit: () => Promise<Response>, council = grouped()) => {
    fetchMock.mockImplementation(server({ council: () => council, edit }))
    renderAt('/councils/demo-1/structure')
  }
  const card = (title: string) => screen.findByRole('region', { name: title })

  it('«Объединить с…»: выбор группы в меню объединяет, итог — с вашими правками', async () => {
    openWith(() => json(grouped(MERGED)))
    fireEvent.click(within(await card('Воркер')).getByRole('button', { name: ru['groups.merge'] }))
    const menu = screen.getByRole('menu', { name: ru['groups.mergeMenu'] })
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'B Хранение' }))
    expect(await screen.findByRole('heading', { name: '1 группа — с вашими правками' })).toBeTruthy()
    expect(edits).toEqual([{ action: 'merge', body: { run: 'g1', revision: 0, group: 'A', other: 'B' } }])
    expect(screen.queryByRole('region', { name: 'Хранение' })).toBeNull()
    expect(screen.getByRole('button', { name: ru['groups.restore'] })).toBeTruthy()
  })

  it('меню закрывается по Escape и ничего не меняет', async () => {
    openWith(() => json(grouped(MERGED)))
    fireEvent.click(within(await card('Воркер')).getByRole('button', { name: ru['groups.merge'] }))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(edits).toEqual([])
  })

  it('«Разделить»: галочки и название новой группы; без них — нельзя', async () => {
    const split: Structure = {
      ...GROUPED, edited: true,
      groups: [{ ...GROUPED.groups[0], fragment_ids: [1], shared_fragment_ids: [] },
               { ...GROUPED.groups[1], id: 'C', title: 'Факты', shared_fragment_ids: [2] },
               { ...GROUPED.groups[1], shared_fragment_ids: [2] }],
    }
    openWith(() => json(grouped(split)))
    const a = await card('Воркер')
    fireEvent.click(within(a).getByRole('button', { name: ru['groups.split'] }))
    const form = within(a).getByRole('form', { name: ru['groups.split'] })
    const submit = within(form).getByRole('button', { name: ru['groups.split'] }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.click(within(a).getByRole('checkbox', { name: 'F2' }))
    expect(submit.disabled).toBe(true)                  // без названия
    fireEvent.change(within(form).getByRole('textbox', { name: ru['groups.newTitle'] }), { target: { value: 'Факты' } })
    expect(submit.disabled).toBe(false)
    fireEvent.click(within(a).getByRole('checkbox', { name: 'F1' }))
    expect(submit.disabled).toBe(true)                  // всё уходить не может
    fireEvent.click(within(a).getByRole('checkbox', { name: 'F1' }))
    fireEvent.click(submit)
    expect(await screen.findByRole('region', { name: 'Факты' })).toBeTruthy()
    expect(edits).toEqual([{ action: 'split', body: { run: 'g1', revision: 0, group: 'A', fragment_ids: [2], title: 'Факты' } }])
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('разделение можно отменить', async () => {
    openWith(() => json(grouped()))
    const a = await card('Воркер')
    fireEvent.click(within(a).getByRole('button', { name: ru['groups.split'] }))
    fireEvent.click(within(a).getByRole('button', { name: ru['groups.cancel'] }))
    expect(within(a).queryByRole('checkbox')).toBeNull()
    expect(edits).toEqual([])
  })

  it('название правится щелчком: Escape — отмена, Enter — сохранить', async () => {
    const renamed: Structure = { ...GROUPED, edited: true,
      groups: [{ ...GROUPED.groups[0], title: 'Воркер Codex' }, GROUPED.groups[1]] }
    openWith(() => json(grouped(renamed)))
    fireEvent.click(within(await card('Воркер')).getByRole('button', { name: 'Воркер' }))
    const field = () => screen.getByRole('textbox', { name: 'Название группы A' })
    fireEvent.change(field(), { target: { value: 'Что-то' } })
    fireEvent.keyDown(field(), { key: 'Escape' })
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(edits).toEqual([])

    fireEvent.click(within(await card('Воркер')).getByRole('button', { name: 'Воркер' }))
    fireEvent.change(field(), { target: { value: '  Воркер Codex ' } })
    fireEvent.keyDown(field(), { key: 'Enter' })
    expect(await screen.findByRole('region', { name: 'Воркер Codex' })).toBeTruthy()
    expect(edits).toEqual([{ action: 'rename', body: { run: 'g1', revision: 0, group: 'A', title: 'Воркер Codex' } }])
  })

  it('«Вернуть как предложил совет» отменяет правки', async () => {
    openWith(() => json(grouped()), grouped(MERGED))
    fireEvent.click(await screen.findByRole('button', { name: ru['groups.restore'] }))
    expect(await screen.findByRole('heading', { name: 'ИИ предлагает 2 группы' })).toBeTruthy()
    expect(edits).toEqual([{ action: 'restore', body: { run: 'g1', revision: 0 } }])
  })

  it('отказ сервера — у той группы, где правили', async () => {
    openWith(() => json({ detail: 'Группы A и B совпали бы по составу' }, 422))
    fireEvent.click(within(await card('Хранение')).getByRole('button', { name: ru['groups.merge'] }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'A Воркер' }))
    const alert = await within(await card('Хранение')).findByRole('alert')
    expect(alert.textContent).toBe('Группы A и B совпали бы по составу')
    expect(within(await card('Воркер')).queryByRole('alert')).toBeNull()
  })

  it('состав группы поменялся, пока открыто разделение, — черновик сброшен', async () => {
    // Откат возвращает A = {F1}, B = {F2}: отмеченное к прежнему составу уже не относится.
    const proposal: Structure = { ...GROUPED, relations: [],
      groups: [{ ...GROUPED.groups[0], fragment_ids: [1], shared_fragment_ids: [] },
               { ...GROUPED.groups[1], shared_fragment_ids: [] }] }
    openWith(() => json(grouped(proposal)), grouped(MERGED))
    const a = await card('Воркер')
    fireEvent.click(within(a).getByRole('button', { name: ru['groups.split'] }))
    fireEvent.click(within(a).getByRole('checkbox', { name: 'F2' }))
    fireEvent.click(screen.getByRole('button', { name: ru['groups.restore'] }))
    expect(await screen.findByRole('region', { name: 'Хранение' })).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByRole('form')).toBeNull()
  })

  it('типы поменялись после раскладки — группы не правятся, пока их не разложат заново', async () => {
    openWith(() => json(grouped()), grouped({ ...MERGED, labels: { 1: 'idea', 2: 'risk' } }))
    const a = await card('Воркер')
    for (const name of [ru['groups.merge'], ru['groups.split'], 'Воркер']) {
      expect((within(a).getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true)
    }
    expect((screen.getByRole('button', { name: ru['groups.restore'] }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: ru['groups.again'] }))
    await waitFor(() => expect(groupStarts).toBe(1))
    expect(edits).toEqual([])
  })

  it('группы, где правили, больше нет (409) — ошибка в шапке', async () => {
    let current = grouped()
    fetchMock.mockImplementation(server({
      council: () => current,
      edit: () => {
        current = grouped({ ...GROUPED, run: 'g2', relations: [], groups: [{ ...GROUPED.groups[0], shared_fragment_ids: [] }] })
        return json({ detail: 'Группы уже разложили заново — правка была к прежним' }, 409)
      },
    }))
    renderAt('/councils/demo-1/structure')
    fireEvent.click(within(await card('Хранение')).getByRole('button', { name: ru['groups.merge'] }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'A Воркер' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Группы уже разложили заново — правка была к прежним')
    expect(screen.queryByRole('region', { name: 'Хранение' })).toBeNull()
  })

  /** Ответ на правку, который приходит, только когда тест его отпустит. */
  const held = () => {
    let release!: (council: Council) => void
    const response = new Promise<Response>(r => { release = c => r(new Response(JSON.stringify(c))) })
    return { edit: () => response, release }
  }

  it('пока разделение сохраняется, его не отменить и не поменять', async () => {
    const { edit, release } = held()
    openWith(edit)
    const a = await card('Воркер')
    fireEvent.click(within(a).getByRole('button', { name: ru['groups.split'] }))
    fireEvent.click(within(a).getByRole('checkbox', { name: 'F2' }))
    const form = within(a).getByRole('form', { name: ru['groups.split'] })
    fireEvent.change(within(form).getByRole('textbox'), { target: { value: 'Факты' } })
    fireEvent.click(within(form).getByRole('button', { name: ru['groups.split'] }))
    await waitFor(() => expect(edits).toHaveLength(1))
    expect((within(form).getByRole('button', { name: ru['groups.cancel'] }) as HTMLButtonElement).disabled).toBe(true)
    expect((within(a).getByRole('checkbox', { name: 'F2' }) as HTMLInputElement).disabled).toBe(true)
    expect((within(form).getByRole('textbox') as HTMLInputElement).readOnly).toBe(true)
    release(grouped({ ...GROUPED, edited: true, groups: [
      { ...GROUPED.groups[0], fragment_ids: [1], shared_fragment_ids: [] },
      { ...GROUPED.groups[1], id: 'C', title: 'Факты' }, GROUPED.groups[1]] }))
    expect(await screen.findByRole('region', { name: 'Факты' })).toBeTruthy()
    expect(screen.queryByRole('form')).toBeNull()
  })

  it('пока название сохраняется, поле не правится и Escape его не закрывает', async () => {
    const { edit, release } = held()
    openWith(edit)
    fireEvent.click(within(await card('Воркер')).getByRole('button', { name: 'Воркер' }))
    const field = screen.getByRole('textbox', { name: 'Название группы A' }) as HTMLInputElement
    fireEvent.change(field, { target: { value: 'Воркер Codex' } })
    fireEvent.keyDown(field, { key: 'Enter' })
    await waitFor(() => expect(field.readOnly).toBe(true))
    fireEvent.keyDown(field, { key: 'Escape' })
    expect(screen.getByRole('textbox', { name: 'Название группы A' })).toBeTruthy()
    release(grouped({ ...GROUPED, edited: true,
      groups: [{ ...GROUPED.groups[0], title: 'Воркер Codex' }, GROUPED.groups[1]] }))
    expect(await screen.findByRole('region', { name: 'Воркер Codex' })).toBeTruthy()
    expect(edits).toHaveLength(1)
  })

  it('открытое меню объединения не работает, пока сохраняется другая правка', async () => {
    const { edit, release } = held()
    openWith(edit)
    fireEvent.click(within(await card('Воркер')).getByRole('button', { name: ru['groups.merge'] }))
    const item = screen.getByRole('menuitem', { name: 'B Хранение' }) as HTMLButtonElement
    // Клавиатурой меню остаётся открытым: переименовываем другую группу.
    fireEvent.click(within(await card('Хранение')).getByRole('button', { name: 'Хранение' }))
    const field = screen.getByRole('textbox', { name: 'Название группы B' })
    fireEvent.change(field, { target: { value: 'Хранилище' } })
    fireEvent.keyDown(field, { key: 'Enter' })
    await waitFor(() => expect(item.disabled).toBe(true))
    fireEvent.click(item)
    release(grouped())
    await waitFor(() => expect(item.disabled).toBe(false))
    expect(edits.map(e => e.action)).toEqual(['rename'])
  })

  it('откат названия сбрасывает открытый черновик', async () => {
    const renamed = grouped({ ...GROUPED, edited: true,
      groups: [{ ...GROUPED.groups[0], title: 'Воркер Codex' }, GROUPED.groups[1]] })
    openWith(() => json(grouped()), renamed)
    fireEvent.click(within(await card('Воркер Codex')).getByRole('button', { name: 'Воркер Codex' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Название группы A' }), { target: { value: 'Что-то' } })
    fireEvent.click(screen.getByRole('button', { name: ru['groups.restore'] }))
    expect(await screen.findByRole('button', { name: 'Воркер' })).toBeTruthy()
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it.each([
    ['группы раскладывают заново', GROUPING, ru['groups.runningTitle']],
    ['новая нарезка стёрла группы', null, null],
  ])('409, а %s, — ошибка правки видна', async (_, fresh, heading) => {
    let current = grouped()
    fetchMock.mockImplementation(server({
      council: () => current,
      edit: () => {
        current = { ...grouped(), structure: fresh }
        return json({ detail: 'Группы уже разложили заново — правка была к прежним' }, 409)
      },
    }))
    renderAt('/councils/demo-1/structure')
    fireEvent.click(within(await card('Воркер')).getByRole('button', { name: ru['groups.merge'] }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'B Хранение' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Группы уже разложили заново — правка была к прежним')
    if (heading) expect(screen.getByRole('heading', { name: heading })).toBeTruthy()
    else expect(screen.getByRole('link', { name: ru['groups.toSlices'] })).toBeTruthy()
  })

  it('группы уже разложили заново (409) — видны нынешние', async () => {
    let current = grouped()
    fetchMock.mockImplementation(server({
      council: () => current,
      edit: () => {
        current = grouped({ ...GROUPED, run: 'g2', groups: [{ ...GROUPED.groups[0], title: 'Новый воркер' },
                                                           GROUPED.groups[1]] })
        return json({ detail: 'Группы уже разложили заново — правка была к прежним' }, 409)
      },
    }))
    renderAt('/councils/demo-1/structure')
    fireEvent.click(within(await card('Воркер')).getByRole('button', { name: ru['groups.merge'] }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'B Хранение' }))
    const fresh = await card('Новый воркер')
    expect((await within(fresh).findByRole('alert')).textContent).toBe('Группы уже разложили заново — правка была к прежним')
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
