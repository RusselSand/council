import { describe, expect, it } from 'vitest'
import type { Council, IdeaDiscovery, QuestionDiscovery, Slicing, Stream, Structure } from './api'
import { attention, chainLight, councilLight, stageLight, streamLight } from './light'

const BASE: Council = {
  id: 'c1', name: 'Совет', status: 'brief', brief: 'текст', participants: ['sol', 'fable'], judge: 'fable',
  updated_at: '2026-10-07T10:00:00Z', slicing: null, structure: null, streams: null,
}
const fragment = { id: 1, text: 'Хочу воркер.', label: 'idea' as const, reason: '', council_label: 'idea' as const,
                   decided_by: 'agreed' as const, votes: [], slice_note: null }
const slicing = (state: Slicing['state']): Slicing =>
  ({ state, run: 's1', text: 'Хочу воркер.', steps: [], fragments: [fragment], error: null })
const structure = (state: Structure['state'], labels: Structure['labels'] = { 1: 'idea' }): Structure => ({
  state, run: 'g1', slicing_run: 's1', labels, steps: [], relations: [], decisions: [], proposal: null,
  edited: false, revision: 0, error: null,
  groups: [{ id: 'A', title: 'Воркер', fragment_ids: [1], idea_fragment_ids: [], missing_idea: true, shared_fragment_ids: [] }],
})
const search = (state: IdeaDiscovery['state']): IdeaDiscovery =>
  ({ state, run: 'i1', steps: [], options: [], proposal: null, error: null })
const asked = (state: QuestionDiscovery['state']): QuestionDiscovery =>
  ({ state, run: 'q1', idea: 'Идея', steps: [], questions: [], error: null })
/** Поток: approved — идея утверждена; questions — поиск вопросов; chosen — вопросы отобраны. */
const stream = (discovery: IdeaDiscovery | null, approved = false, questions: QuestionDiscovery | null = null,
                chosen = false): Stream => ({
  group: 'A', discovery, idea: approved ? { text: 'Идея', by: 'human', evidence: [] } : null, questions,
  scope: chosen ? [{ id: 'Q1', text: 'Как?', source: 'discovered', source_question_id: null, proposal_ids: [], reason: null }]
    : null,
})
const at = (council: Partial<Council>): Council => ({ ...BASE, ...council })

describe('светофор', () => {
  it('нетронутый совет — белый черновик', () => {
    expect(councilLight(BASE)).toBe('idle')
    expect(attention(BASE)).toEqual([])
  })

  it('этапы: идёт — зелёный, упал — красный, готово без следующего шага — ваш ход', () => {
    expect(stageLight(at({ slicing: slicing('running') }), 'slices')).toBe('running')
    expect(stageLight(at({ slicing: slicing('failed') }), 'slices')).toBe('failed')
    const sliced = at({ slicing: slicing('done') })
    expect(stageLight(sliced, 'brief')).toBe('done')
    expect(stageLight(sliced, 'slices')).toBe('yours')
    expect(stageLight(at({ slicing: slicing('done'), structure: structure('done') }), 'slices')).toBe('done')
  })

  it('группы готовы, пока их не подтвердили или пока они не устарели, — ваш ход', () => {
    const grouped = at({ slicing: slicing('done'), structure: structure('done') })
    expect(stageLight(grouped, 'structure')).toBe('yours')
    expect(stageLight({ ...grouped, streams: [stream(null, true)] }, 'structure')).toBe('done')
    const stale = { ...grouped, structure: structure('done', { 1: 'risk' }), streams: [stream(null, true)] }
    expect(stageLight(stale, 'structure')).toBe('yours')
    expect(attention(stale).map(a => a.what)).toEqual(['groupsStale'])
  })

  it('поток: ищет идею, упал, ждёт утверждения; утверждённая — шаг готов, дальше белое', () => {
    expect(streamLight(stream(search('running')))).toBe('running')
    expect(streamLight(stream(search('failed')))).toBe('failed')
    expect(streamLight(stream(search('done')))).toBe('yours')
    const chosen = stream(search('done'), true, asked('done'), true)
    expect(streamLight(chosen)).toBe('idle')
    expect(['group', 'questions', 'options'].map(step => chainLight(chosen, step as 'group'))).toEqual(
      ['done', 'done', 'idle'])
  })

  it('своя идея после упавшего поиска: поток прошёл шаг, ошибки больше нет', () => {
    const own = stream(search('failed'), true, asked('done'))
    expect(streamLight(own)).toBe('yours')                   // теперь ход за вами — вопросы
    expect(chainLight(own, 'group')).toBe('done')
    const council = at({ slicing: slicing('done'), structure: structure('done'), streams: [own] })
    expect(councilLight(council)).toBe('yours')
    expect(attention(council).map(a => a.what)).toEqual(['questionsWait'])
  })

  it('вопросы: ищет ИИ, упал поиск, ждут отбора, отобраны', () => {
    const on = (questions: QuestionDiscovery | null, chosen = false) => stream(null, true, questions, chosen)
    expect([on(asked('running')), on(asked('failed')), on(asked('done')), on(null), on(asked('done'), true)]
      .map(streamLight)).toEqual(['running', 'failed', 'yours', 'yours', 'idle'])
    const council = at({ slicing: slicing('done'), structure: structure('done'), streams: [on(asked('failed'))] })
    expect(attention(council)).toEqual([
      { light: 'failed', what: 'questionsFailed', group: 'A', to: '/councils/c1/streams/A' }])
  })

  it('группы устарели, пока ИИ ищет идеи: разложить заново нельзя, совет — в работе', () => {
    const stale = { slicing: slicing('done'), structure: structure('done', { 1: 'risk' }) }
    const seeking = at({ ...stale, streams: [stream(search('running')), { ...stream(search('done')), group: 'B' }] })
    expect(councilLight(seeking)).toBe('running')
    expect(stageLight(seeking, 'structure')).not.toBe('yours')
    expect(attention(seeking)).toEqual([])
    const settled = at({ ...stale, streams: [stream(search('done')), { ...stream(search('done')), group: 'B' }] })
    expect(councilLight(settled)).toBe('yours')
    expect(attention(settled).map(a => a.what)).toEqual(['groupsStale'])
  })

  it('совет — самое важное из его этапов: ошибка, потом ваш ход, потом работа ИИ', () => {
    const confirmed = { slicing: slicing('done'), structure: structure('done') }
    const two = (a: IdeaDiscovery, b: IdeaDiscovery) =>
      at({ ...confirmed, streams: [stream(a), { ...stream(b), group: 'B' }] })
    expect(councilLight(two(search('running'), search('done')))).toBe('yours')
    expect(councilLight(two(search('running'), search('failed')))).toBe('failed')
    expect(councilLight(two(search('running'), search('running')))).toBe('running')
  })

  it('требует внимания: что и куда идти', () => {
    const council = at({ slicing: slicing('done'), structure: structure('done'),
                         streams: [stream(search('failed')), { ...stream(search('done')), group: 'B' }] })
    expect(attention(council)).toEqual([
      { light: 'failed', what: 'ideaFailed', group: 'A', to: '/councils/c1/streams/A' },
      { light: 'yours', what: 'ideaWaits', group: 'B', to: '/councils/c1/streams/B' },
    ])
    expect(attention(at({ slicing: slicing('done') }))).toEqual([
      { light: 'yours', what: 'slicesDone', to: '/councils/c1/slices' }])
    expect(attention(at({ slicing: slicing('done'), structure: structure('failed') }))).toEqual([
      { light: 'failed', what: 'groupingFailed', to: '/councils/c1/structure' }])
  })
})
