import { describe, expect, it } from 'vitest'
import type {
  Folders, Issue, IssueDiscovery,
  Council, DecisionAnalysis, DesignScan, IdeaDiscovery, Outcome, OutcomeDiscovery, ProposalDiscovery, QuestionDiscovery,
  RepositoryScan, Research, Slicing, Stream, Structure,
} from './api'
import { attention, CHAIN, chainLight, councilLight, currentStep, reachable, stageLight, streamLight } from './light'

/** Каталог заметок из настроек: выгрузки в тестах — в него; папки задач у проекта нет. */
const ROOT = '/notes'
const NOTES: Folders = { notes: ROOT, issues: null }

const BASE: Council = {
  id: 'c1', name: 'Совет', status: 'brief', brief: 'текст', participants: ['sol', 'fable'], judge: 'fable',
  updated_at: '2026-10-07T10:00:00Z', project: '', slicing: null, structure: null, streams: null, research: null,
}
/** Исследование пройдено пропуском обоих шагов: потоки можно начинать. */
const RESEARCHED: Research = {
  scan: null, repository: { by: 'skipped', scan_run: '' }, design_scan: null, design: { by: 'skipped', scan_run: '' } }
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
  ({ state, run: 'q1', idea: 'Идея', repository: 'skipped', design: 'skipped', decisions: [], decisions_seen: '', notes: '', steps: [], questions: [], error: null })
const offered = (state: ProposalDiscovery['state']): ProposalDiscovery =>
  ({ state, run: 'p1', scope: [], steps: [], options: [], error: null })
const checked = (state: DecisionAnalysis['state']): DecisionAnalysis =>
  ({ state, run: 'd1', choices: [], steps: [], analyses: [], error: null })
const result = (more: Partial<Outcome> = {}): Outcome => ({
  id: 'O1', title: 'Итог', behavior: 'Так работает.', adr_ids: [], constraint_ids: [], risk_ids: [],
  acceptance_criteria: ['Видно сразу.'], blocked_by: [], gaps: [], ...more })
const assembled = (state: OutcomeDiscovery['state'], outcomes: Outcome[] = []): OutcomeDiscovery =>
  ({ state, run: 'o1', decisions: [], steps: [], outcomes, kept: [], touched: [], uncovered_adr_ids: [], approved: false, error: null })
const task = (more: Partial<Issue> = {}): Issue => ({
  id: 'I1', title: 'Задача', user_story: 'As a member, I want it.', main_entry_points: [], current_state: '',
  scope: ['Сделать.'], outcome_ids: ['O1'], adr_ids: [], constraint_ids: [], risk_ids: [], depends_on: [],
  blocked_by: [], acceptance_criteria: [], ...more })
const cut = (state: IssueDiscovery['state'], issues: Issue[] = []): IssueDiscovery =>
  ({ state, run: 'i1', outcomes: 'o1', code: false, sources: [], steps: [], issues, gaps: [], kept: [], cut: {},
     uncovered_outcome_ids: [], error: null })
/**
 * Поток: approved — идея утверждена; questions — поиск вопросов; chosen — вопросы отобраны;
 * proposals — поиск вариантов; picked — выбор по ним утверждён; analysis — его проверка;
 * decided — решения зафиксированы; outcomes — итоги из них; issues — их нарезка на задачи.
 */
const stream = (discovery: IdeaDiscovery | null, approved = false, questions: QuestionDiscovery | null = null,
                chosen = false, proposals: ProposalDiscovery | null = null, picked = false,
                analysis: DecisionAnalysis | null = null, decided = false,
                outcomes: OutcomeDiscovery | null = null, issues: IssueDiscovery | null = null): Stream => ({
  group: 'A', discovery, idea: approved ? { text: 'Идея', by: 'human', evidence: [] } : null, questions, earlier: [], earlier_outcomes: null, earlier_issues: null,
  saved_outcomes: [], saved_issues: [],
  // Утверждённая идея — шаги «Репозиторий» и «Дизайн» пропущены: их проверяют свои тесты.
  scan: null, repository: approved ? { by: 'skipped', scan_run: '' } : null,
  design_scan: null, design: approved ? { by: 'skipped', scan_run: '' } : null,
  decisions_search: null, project_decisions: null, notes_draft: null, notes: null,
  scope: chosen ? [{ id: 'Q1', text: 'Как?', source: 'discovered', source_question_id: null, proposal_ids: [], reason: null, note: null, revisits: null }]
    : null,
  proposals, choices: picked ? [{ question_id: 'Q1', proposal: null }] : null,
  analysis, decisions: decided ? [{ question_id: 'Q1', proposal: null, rationale: null, rationale_by: null }] : null,
  // Итоги, которые уже режут на задачи, утверждены.
  outcomes: outcomes && issues ? { ...outcomes, approved: true } : outcomes, issues,
})
/** Совет; с потоками — исследование по умолчанию пройдено: потоки проверяют свои шаги. */
const at = (council: Partial<Council>): Council => ({ ...BASE, research: council.streams ? RESEARCHED : null, ...council })

describe('светофор', () => {
  it('нетронутый совет — белый черновик', () => {
    expect(councilLight(BASE, NOTES)).toBe('idle')
    expect(attention(BASE, NOTES)).toEqual([])
  })

  it('этапы: идёт — зелёный, упал — красный, готово без следующего шага — ваш ход', () => {
    expect(stageLight(at({ slicing: slicing('running') }), 'slices', NOTES)).toBe('running')
    expect(stageLight(at({ slicing: slicing('failed') }), 'slices', NOTES)).toBe('failed')
    const sliced = at({ slicing: slicing('done') })
    expect(stageLight(sliced, 'brief', NOTES)).toBe('done')
    expect(stageLight(sliced, 'slices', NOTES)).toBe('yours')
    expect(stageLight(at({ slicing: slicing('done'), structure: structure('done') }), 'slices', NOTES)).toBe('done')
  })

  it('группы готовы, пока их не подтвердили или пока они не устарели, — ваш ход', () => {
    const grouped = at({ slicing: slicing('done'), structure: structure('done') })
    expect(stageLight(grouped, 'structure', NOTES)).toBe('yours')
    expect(stageLight({ ...grouped, streams: [stream(null, true)] }, 'structure', NOTES)).toBe('done')
    const stale = { ...grouped, structure: structure('done', { 1: 'risk' }), streams: [stream(null, true)] }
    expect(stageLight(stale, 'structure', NOTES)).toBe('yours')
    expect(attention(stale, NOTES).map(a => a.what)).toEqual(['groupsStale'])
  })

  it('идеи — на этапе «Группы»: ищет ИИ, упал, ждёт утверждения; поток до идеи ждёт', () => {
    const grouped = (s: Stream) => at({ slicing: slicing('done'), structure: structure('done'), streams: [s] })
    expect([search('running'), search('failed'), search('done')].map(found => stageLight(grouped(stream(found)), 'structure', NOTES)))
      .toEqual(['running', 'failed', 'yours'])
    expect(attention(grouped(stream(search('failed'))), NOTES)).toEqual([
      { light: 'failed', what: 'ideaFailed', group: 'A', to: '/councils/c1/structure' }])
    expect(attention(grouped(stream(search('done'))), NOTES).map(a => a.what)).toEqual(['ideaWaits'])
    expect([streamLight(stream(search('done')), NOTES), currentStep(stream(search('done')))]).toEqual(['idle', 'start'])
    const picked = stream(search('done'), true, asked('done'), true, offered('done'), true)
    expect(streamLight(picked, NOTES)).toBe('yours')
    expect(CHAIN.map(step => chainLight(picked, step, NOTES))).toEqual(['done', 'done', 'done', 'yours', 'idle', 'idle', 'idle'])
  })

  it('своя идея после упавшего поиска: поток прошёл шаг, ошибки больше нет', () => {
    const own = stream(search('failed'), true, asked('done'))
    expect(streamLight(own, NOTES)).toBe('yours')                   // теперь ход за вами — вопросы
    expect(chainLight(own, 'start', NOTES)).toBe('done')
    const council = at({ slicing: slicing('done'), structure: structure('done'), streams: [own] })
    expect(councilLight(council, NOTES)).toBe('yours')
    expect(attention(council, NOTES).map(a => a.what)).toEqual(['questionsWait'])
  })

  it('вопросы: ищет ИИ, упал поиск, ждут отбора, отобраны', () => {
    const on = (questions: QuestionDiscovery | null, chosen = false) => stream(null, true, questions, chosen)
    expect([on(asked('running')), on(asked('failed')), on(asked('done')), on(null)]
      .map(s => streamLight(s, NOTES))).toEqual(['running', 'failed', 'yours', 'yours'])
    const council = at({ slicing: slicing('done'), structure: structure('done'), streams: [on(asked('failed'))] })
    expect(attention(council, NOTES)).toEqual([
      { light: 'failed', what: 'questionsFailed', group: 'A', to: '/councils/c1/streams/A' }])
  })

  it('группы устарели, пока ИИ ищет идеи: разложить заново нельзя, совет — в работе', () => {
    const stale = { slicing: slicing('done'), structure: structure('done', { 1: 'risk' }) }
    const seeking = at({ ...stale, streams: [stream(search('running')), { ...stream(search('done')), group: 'B' }] })
    expect(councilLight(seeking, NOTES)).toBe('running')
    expect(stageLight(seeking, 'structure', NOTES)).not.toBe('yours')
    expect(attention(seeking, NOTES)).toEqual([])
    const settled = at({ ...stale, streams: [stream(search('done')), { ...stream(search('done')), group: 'B' }] })
    expect(councilLight(settled, NOTES)).toBe('yours')
    expect(attention(settled, NOTES).map(a => a.what)).toEqual(['groupsStale'])
  })

  it('варианты: ищет ИИ, упал поиск, ждут выбора, выбор утверждён', () => {
    const on = (proposals: ProposalDiscovery | null, picked = false) =>
      stream(null, true, asked('done'), true, proposals, picked)
    expect([on(offered('running')), on(offered('failed')), on(offered('done')), on(null)]
      .map(s => streamLight(s, NOTES))).toEqual(['running', 'failed', 'yours', 'yours'])
    expect(chainLight(on(offered('done'), true), 'options', NOTES)).toBe('done')
    const council = at({ slicing: slicing('done'), structure: structure('done'), streams: [on(offered('done'))] })
    expect(attention(council, NOTES)).toEqual([
      { light: 'yours', what: 'optionsWait', group: 'A', to: '/councils/c1/streams/A' }])
  })

  it('исследование: когда идеи утверждены; сканирует ИИ, скан упал, ждёт вас; пройдено — потоки можно начинать', () => {
    const scanned = (state: RepositoryScan['state']): RepositoryScan => ({
      state, run: 's1', idea: 'Идея', rounds: 1,
      repositories: [{ name: '', path: 'project', root: '/repos/project', commit_sha: 'abc', dirty: false, files: 1, outside: 0, omitted: [], omitted_count: 0 }],
      steps: [], complete: true, result: null, follow_up: [], error: null })
    const designed = (state: DesignScan['state']): DesignScan => ({
      state, run: 'd1', idea: 'Идея', links: ['https://www.figma.com/design/K/x'], source: null, rounds: 1,
      steps: [], complete: true, result: null, follow_up: [], error: null })
    const waiting = { ...stream(null, true), repository: null, design: null, scan: null }
    const on = (research: Research | null) =>
      at({ slicing: slicing('done'), structure: structure('done'), streams: [waiting], research })
    const none: Research = { scan: null, repository: null, design_scan: null, design: null }
    expect([on({ ...none, scan: scanned('running') }), on({ ...none, scan: scanned('failed') }), on(none), on(null)]
      .map(council => stageLight(council, 'research', NOTES))).toEqual(['running', 'failed', 'yours', 'yours'])
    expect(attention(on({ ...none, scan: scanned('failed') }), NOTES)).toEqual([
      { light: 'failed', what: 'repositoryFailed', to: '/councils/c1/research' }])
    expect(attention(on(null), NOTES).map(a => a.what)).toEqual(['repositoryWait'])
    const repository = { ...none, repository: RESEARCHED.repository }
    expect(stageLight(on({ ...repository, design_scan: designed('failed') }), 'research', NOTES)).toBe('failed')
    expect(attention(on(repository), NOTES).map(a => a.what)).toEqual(['designWait'])
    // Пока исследование не пройдено, поток ждёт его, а не вас.
    expect([streamLight(waiting, NOTES), currentStep(waiting), chainLight(waiting, 'start', NOTES)])
      .toEqual(['idle', 'start', 'idle'])
    // Пройдено — поток можно начинать: ход за вами.
    expect(stageLight(on(RESEARCHED), 'research', NOTES)).toBe('done')
    expect(attention(on(RESEARCHED), NOTES)).toEqual([
      { light: 'yours', what: 'startWait', group: 'A', to: '/councils/c1/streams/A' }])
    expect(chainLight(waiting, 'start', NOTES, true)).toBe('yours')
    // Пока идеи не утверждены, исследование ждёт их.
    const unideaed = at({ slicing: slicing('done'), structure: structure('done'), streams: [stream(search('done'))] })
    expect(stageLight(unideaed, 'research', NOTES)).toBe('idle')
  })

  it('решения: проверяет ИИ, проверка упала, ждут фиксации; зафиксированные ведут к итогам', () => {
    const on = (analysis: DecisionAnalysis | null, decided = false) =>
      stream(null, true, asked('done'), true, offered('done'), true, analysis, decided)
    expect([on(checked('running')), on(checked('failed')), on(checked('done')), on(null)].map(s => streamLight(s, NOTES)))
      .toEqual(['running', 'failed', 'yours', 'yours'])
    const done = on(checked('done'), true)
    expect([currentStep(done), chainLight(done, 'decisions', NOTES)]).toEqual(['outcomes', 'done'])
    const council = (s: Stream) => at({ slicing: slicing('done'), structure: structure('done'), streams: [s] })
    expect(attention(council(on(checked('failed'))), NOTES)).toEqual([
      { light: 'failed', what: 'decisionsFailed', group: 'A', to: '/councils/c1/streams/A' }])
    expect(attention(council(on(checked('done'))), NOTES).map(a => a.what)).toEqual(['decisionsWait'])
  })

  it('итоги: собирает ИИ, сборка упала; собраны — ход за вами, пока их не утвердили', () => {
    const on = (outcomes: OutcomeDiscovery | null, issues: IssueDiscovery | null = null) =>
      stream(null, true, asked('done'), true, offered('done'), true, checked('done'), true, outcomes, issues)
    const ready = on(assembled('done', [result()]))
    const blocked = on(assembled('done', [result({ blocked_by: ['Q1'] })]))
    expect([on(assembled('running')), on(assembled('failed')), ready, blocked, on(null)].map(s => streamLight(s, NOTES)))
      .toEqual(['running', 'failed', 'yours', 'yours', 'yours'])
    expect(currentStep(ready)).toBe('outcomes')
    const council = (s: Stream) => at({ slicing: slicing('done'), structure: structure('done'), streams: [s] })
    expect(attention(council(ready), NOTES)).toEqual([
      { light: 'yours', what: 'outcomesWait', group: 'A', to: '/councils/c1/streams/A' }])
    expect(attention(council(on(assembled('failed'))), NOTES).map(a => a.what)).toEqual(['outcomesFailed'])
    // Утверждены — шаг пройден, и с блокировками тоже: дальше задачи, а выгрузить можно уже сейчас.
    const approved = on(assembled('done', [result({ blocked_by: ['Q1'] })]), cut('running'))
    expect(currentStep(approved)).toBe('issues')
    expect(CHAIN.map(step => chainLight(approved, step, NOTES)))
      .toEqual(['done', 'done', 'done', 'done', 'done', 'running', 'yours'])
  })

  it('задачи: нарезает ИИ, нарезка упала; все готовы и каждый итог в задаче — поток готов', () => {
    const on = (issues: IssueDiscovery) =>
      stream(null, true, asked('done'), true, offered('done'), true, checked('done'), true,
             assembled('done', [result()]), issues)
    const ready = on(cut('done', [task()]))
    const blocked = on(cut('done', [task(), task({ id: 'I2', blocked_by: ['G1'] })]))
    const gaps = on({ ...cut('done', [task()]), gaps: [{ id: 'G1', question: 'Где отчёт?', reason: '', outcome_ids: [] }] })
    const lost = on({ ...cut('done', [task()]), uncovered_outcome_ids: ['O2'] })
    const none = on(cut('done'))
    // Все задачи готовы — дальше документация: поток готов, когда выгружен к этим задачам.
    expect([on(cut('running')), on(cut('failed')), ready, blocked, gaps, lost, none].map(s => streamLight(s, NOTES)))
      .toEqual(['running', 'failed', 'yours', 'yours', 'yours', 'yours', 'yours'])
    expect([currentStep(ready), currentStep(blocked), reachable(blocked)]).toEqual(['notes', 'issues', 'notes'])
    expect(CHAIN.map(step => chainLight(ready, step, NOTES)))
      .toEqual(['done', 'done', 'done', 'done', 'done', 'done', 'yours'])
    const written = { ...ready, notes: { run: 'n1', outcomes: 'o1', language: 'Russian', root: '/notes', notes: [] } }
    expect(streamLight(written, NOTES)).toBe('done')
    expect(streamLight({ ...written, notes: { ...written.notes, outcomes: 'o0' } }, NOTES)).toBe('yours')   // к прежним итогам
    expect(chainLight({ ...ready, notes_draft: { state: 'running', run: 'n2', outcomes: 'o1', language: 'English', root: ROOT,
      steps: [], notes: [], vanished: [], skipped: [], error: null } }, 'notes', NOTES)).toBe('running')
    const council = (s: Stream) => at({ slicing: slicing('done'), structure: structure('done'), streams: [s] })
    expect(attention(council(blocked), NOTES).map(a => a.what)).toEqual(['issuesWait'])
    expect(attention(council(on(cut('failed'))), NOTES).map(a => a.what)).toEqual(['issuesFailed'])
    expect(attention(council(ready), NOTES).map(a => a.what)).toEqual(['notesWait'])
    expect(attention(council(written), NOTES)).toEqual([])
    // Каталог сменили (проект или его папку): выгрузка в прежний — не выгрузка, поток снова ждёт её.
    expect(streamLight(written, { ...NOTES, notes: '/other' })).toBe('yours')
    expect(attention(council(written), { ...NOTES, notes: '/other' }).map(a => a.what)).toEqual(['notesWait'])
    // Поверх выгрузки собрали новый черновик: его ход важнее прежней выгрузки.
    const redrafted = (state: 'running' | 'failed') => ({ ...written, notes_draft: { state, run: 'n2', outcomes: 'o1',
      language: 'English', root: ROOT, steps: [], notes: [], vanished: [], skipped: [], error: null } })
    expect(chainLight(redrafted('running'), 'notes', NOTES)).toBe('running')
    expect(attention(council(redrafted('failed')), NOTES).map(a => a.what)).toEqual(['notesFailed'])
    // Задачи не все готовы, а документацию уже собирают: её ход виден, а не «задачи ждут».
    const drafting = (state: 'running' | 'failed') => ({ ...blocked, notes_draft: { state, run: 'n1', outcomes: 'o1',
      language: 'English', root: ROOT, steps: [], notes: [], vanished: [], skipped: [], error: null } })
    expect([currentStep(drafting('running')), streamLight(drafting('running'), NOTES)]).toEqual(['notes', 'running'])
    expect(attention(council(drafting('failed')), NOTES).map(a => a.what)).toEqual(['notesFailed'])
    expect(chainLight(drafting('running'), 'issues', NOTES)).toBe('yours')       // задачи всё так же ждут вас
    // Решение, не вошедшее ни в один итог, нет и в задачах: спецификация его потеряла — не зелёный.
    const unplaced = stream(null, true, asked('done'), true, offered('done'), true, checked('done'), true,
                            { ...assembled('done', [result()]), uncovered_adr_ids: ['ADR-1'] }, cut('done', [task()]))
    expect(streamLight(unplaced, NOTES)).toBe('yours')
    // Итог без критериев готовности: задачу по нему не проверить — тоже не зелёный.
    const vague = stream(null, true, asked('done'), true, offered('done'), true, checked('done'), true,
                         assembled('done', [result({ acceptance_criteria: [] })]), cut('done', [task()]))
    expect(streamLight(vague, NOTES)).toBe('yours')
  })

  it('совет — самое важное из его этапов: ошибка, потом ваш ход, потом работа ИИ', () => {
    const confirmed = { slicing: slicing('done'), structure: structure('done') }
    const two = (a: IdeaDiscovery, b: IdeaDiscovery) =>
      at({ ...confirmed, streams: [stream(a), { ...stream(b), group: 'B' }] })
    expect(councilLight(two(search('running'), search('done')), NOTES)).toBe('yours')
    expect(councilLight(two(search('running'), search('failed')), NOTES)).toBe('failed')
    expect(councilLight(two(search('running'), search('running')), NOTES)).toBe('running')
  })

  it('требует внимания: что и куда идти', () => {
    const council = at({ slicing: slicing('done'), structure: structure('done'),
                         streams: [stream(search('failed')), { ...stream(search('done')), group: 'B' }] })
    expect(attention(council, NOTES)).toEqual([
      { light: 'failed', what: 'ideaFailed', group: 'A', to: '/councils/c1/structure' },
      { light: 'yours', what: 'ideaWaits', group: 'B', to: '/councils/c1/structure' },
    ])
    expect(attention(at({ slicing: slicing('done') }), NOTES)).toEqual([
      { light: 'yours', what: 'slicesDone', to: '/councils/c1/slices' }])
    expect(attention(at({ slicing: slicing('done'), structure: structure('failed') }), NOTES)).toEqual([
      { light: 'failed', what: 'groupingFailed', to: '/councils/c1/structure' }])
  })
})
