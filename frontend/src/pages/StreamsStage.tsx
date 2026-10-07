import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import {
  api, ApiError, councilPath, groupsConfirmed, startOrFollow, streamOf, structureIsStale,
  type Council, type Group, type IdeaDiscovery, type LabeledFragment, type Model, type OpenQuestion,
  type Settings, type Stream, type Structure,
} from '../api'
import { LabelPill } from '../components/Labels'
import { modelOf } from '../components/ModelBadge'
import { Panel } from '../components/Panel'
import { Progress } from '../components/Progress'
import { CHAIN, chainLight, currentStep, streamLight, type ChainStep } from '../light'
import { useAction } from '../useAction'

type T = ReturnType<typeof useTranslation>['t']

/**
 * Потоки: каждая подтверждённая группа — отдельный поток со своей цепочкой шагов. Слева —
 * потоки и цепочка открытого, по центру — его шаг, справа — ход работы совета. Открытый
 * поток — в адресе, по букве группы.
 */
export function StreamsStage({ council, settings, onChange }: Readonly<{
  council: Council; settings: Settings; onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const { stream: wanted } = useParams()
  const { structure, streams } = council
  // Буквы в адресе нет или такого потока уже нет (группы поменяли) — открыт первый.
  const stream = streams?.find(s => s.group === wanted) ?? streams?.[0]

  if (!structure || !stream || !groupsConfirmed(council)) return (
    <div className="card placeholder">
      {t('streams.none')} <Link to={councilPath(council.id, 'structure')}>{t('streams.toGroups')}</Link>
    </div>
  )
  // Свой экземпляр на поток: открытый шаг и черновик идеи — у каждого потока свои.
  return <StreamPage key={stream.group} council={council} structure={structure} stream={stream}
                     models={settings.models} onChange={onChange} />
}

function StreamPage({ council, structure, stream, models, onChange }: Readonly<{
  council: Council; structure: Structure; stream: Stream; models: Model[]
  onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const [chosen, setView] = useState<ChainStep>(currentStep(stream))
  // Утверждение отбора — здесь, а не в шаге: отказ (409) приносит новый поиск, шаг рисуется
  // заново, а ошибка должна остаться видна.
  const choosing = useAction(onChange, 'questions.approveFailed')
  const group = structure.groups.find(g => g.id === stream.group)
  if (!group) return null  // поток без группы не бывает: состав меняют, только сняв подтверждение
  // Открыть можно пройденный шаг и текущий: дальше — нечего.
  const view = CHAIN.indexOf(chosen) <= CHAIN.indexOf(currentStep(stream)) ? chosen : currentStep(stream)
  const search = stream.discovery
  const run = view === 'group' ? search : stream.questions

  return (
    <div className="streams-layout">
      <aside className="streams-nav">
        <StreamList council={council} structure={structure} open={stream.group} />
        <Chain stream={stream} group={group} view={view} onView={setView} />
      </aside>
      <div className="streams-main">
        <Now stream={stream} group={group} />
        {structureIsStale(council) && (
          <p className="fragment-note">
            {t('streams.stale')}{' '}
            <Link className="btn-link" to={councilPath(council.id, 'structure')}>{t('streams.toGroups')}</Link>
          </p>
        )}
        {view === 'group' && (
          // Поиск закончился — черновик заново, из предложения совета.
          <GroupStep key={`${search?.run}:${search?.state}`} council={council} structure={structure}
                     stream={stream} group={group} models={models} onChange={onChange}
                     onApproved={() => setView('questions')} />
        )}
        {view === 'questions' && (
          // Новый поиск вопросов — и отбор заново, к его вопросам.
          <QuestionsStep key={stream.questions?.run ?? ''} council={council} structure={structure}
                         stream={stream} group={group} onChange={onChange} approve={choosing}
                         onBack={() => setView('group')} onApproved={() => setView('options')} />
        )}
        {view === 'options' && <OptionsStep stream={stream} onBack={() => setView('questions')} />}
      </div>
      <aside className="streams-side">
        {run && <Progress steps={run.steps} models={models} />}
      </aside>
    </div>
  )
}

function StreamList({ council, structure, open }: Readonly<{
  council: Council; structure: Structure; open: string
}>) {
  const { t } = useTranslation()
  const streams = council.streams ?? []
  return (
    <nav aria-label={t('streams.list')}>
      <p className="side-caps">{t('streams.title', { count: streams.length })}</p>
      <ul className="stream-nav">
        {streams.map(stream => (
          <li key={stream.group}>
            <Link to={councilPath(council.id, `streams/${stream.group}`)} className="stream-link"
                  aria-current={stream.group === open ? 'page' : undefined}>
              <span className="group-letter" aria-hidden="true">{stream.group}</span>
              <span className="stream-text">
                <span className="stream-title">
                  {structure.groups.find(g => g.id === stream.group)?.title ?? stream.group}
                </span>
                <span className="stream-meta">
                  <span className={`light-dot ${streamLight(stream)}`} aria-hidden="true" />{whereIs(stream, t)}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/** Где поток и чей ход. */
function whereIs(stream: Stream, t: T): string {
  const step = currentStep(stream)
  if (step === 'options') return t('streams.atOptions')
  const run = step === 'group' ? stream.discovery : stream.questions
  const where = step === 'group' ? 'group' : 'questions'
  if (run?.state === 'running') return t(`streams.${where}.seeking`)
  if (run?.state === 'failed') return t(`streams.${where}.failed`)
  return t(`streams.${where}.yours`)
}

/** «Сейчас»: где поток и чей ход — и вся его цепочка сегментами в цветах светофора. */
function Now({ stream, group }: Readonly<{ stream: Stream; group: Group }>) {
  const { t } = useTranslation()
  const light = streamLight(stream)
  return (
    <section className="now" aria-labelledby="now-title">
      <p className={`now-caps ${light}`}>{t('now.caps', { group: stream.group, state: t(`now.${light}`) })}</p>
      <h2 id="now-title" className="now-title">{group.title}</h2>
      <ol className="segments">
        {CHAIN.map(step => {
          const state = chainLight(stream, step)
          return (
            <li key={step} className={`segment ${state}`}>
              <span className="segment-name">
                {t(`chain.${step}`)}
                <span className="sr-only"> ({t(`light.${state}`)})</span>
              </span>
              {step === 'group' && <span className="segment-sub">{ideaStatus(stream, group, t)}</span>}
              {step === 'questions' && stream.idea && (
                <span className="segment-sub">{questionsStatus(stream, t)}</span>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

/** Цепочка шагов потока: пройденные и текущий открываются, дальше — что будет. */
function Chain({ stream, group, view, onView }: Readonly<{
  stream: Stream; group: Group; view: ChainStep; onView: (step: ChainStep) => void
}>) {
  const { t } = useTranslation()
  const reached = CHAIN.indexOf(currentStep(stream))
  const status = (step: ChainStep, i: number) => {
    if (step === 'group') return groupStatus(stream, group, t)
    if (step === 'questions' && stream.idea) return questionsStatus(stream, t)
    return t(i === reached ? 'chain.soon' : 'chain.notStarted')
  }
  return (
    <section className="card panel chain" aria-labelledby="chain-title">
      <h2 id="chain-title" className="panel-title caps">
        {t('chain.title')} <span className="chain-of">{t('chain.of', { group: stream.group })}</span>
      </h2>
      <ol className="chain-steps">
        {CHAIN.map((step, i) => {
          const light = chainLight(stream, step)
          const state = i === reached ? 'current' : 'later'
          const body = (
            <>
              <span className={`chain-num ${light}`} aria-hidden="true">{light === 'done' ? '✓' : i + 1}</span>
              <span className="chain-body">
                <span className="chain-name">{t(`chain.${step}`)}</span>
                <span className={`chain-status ${light}`}>
                  {status(step, i)}
                </span>
                <span className="chain-role"><span className="role-tag ai">{t('chain.ai')}</span>{t(`chain.${step}.ai`)}</span>
                {step !== 'outcomes' && (
                  <span className="chain-role"><span className="role-tag">{t('chain.you')}</span>{t(`chain.${step}.you`)}</span>
                )}
              </span>
            </>
          )
          const className = `chain-step ${i < reached ? 'done' : state}${view === step ? ' open' : ''}`
          return (
            <li key={step}>
              {i <= reached
                ? <button className={className} aria-current={view === step ? 'step' : undefined}
                          onClick={() => onView(step)}>{body}</button>
                : <div className={className}>{body}</div>}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function groupStatus(stream: Stream, group: Group, t: T): string {
  return `${t('chain.fragments', { count: group.fragment_ids.length })} · ${ideaStatus(stream, group, t)}`
}

/** Что с вопросами потока: ищутся, упали, найдены, отобраны или ещё не искались. */
function questionsStatus(stream: Stream, t: T): string {
  const search = stream.questions
  if (stream.scope) return t('chain.questionsChosen', { count: stream.scope.length })
  if (search?.state === 'running') return t('chain.questionsSeeking')
  if (search?.state === 'failed') return t('chain.questionsFailed')
  if (search) return t('chain.questionsFound', { count: search.questions.length })
  return t('chain.questionsNone')
}

/** Что с идеей потока: утверждена, записана в тексте, ищется, упала, найдена или за вами. */
function ideaStatus(stream: Stream, group: Group, t: T): string {
  const search = stream.discovery
  if (stream.idea) return t('chain.ideaApproved')
  if (!group.missing_idea) return t('chain.ideaText')
  if (search?.state === 'running') return t('chain.ideaSeeking')
  if (search?.state === 'failed') return t('chain.ideaFailed')
  if (search?.proposal?.idea) return t('chain.ideaFound')
  return t('chain.ideaNone')
}

/**
 * Шаг «Группа»: фрагменты группы и её идея. Записана в тексте — её только утверждают. Нет —
 * её ищет совет; человек берёт предложение или другой вариант, правит формулировку или пишет
 * свою и утверждает. Утверждённая ведёт к вопросам.
 */
function GroupStep({ council, structure, stream, group, models, onChange, onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group; models: Model[]
  onChange: (council: Council) => void; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const search = stream.discovery
  const [draft, setDraft] = useState(stream.idea?.text ?? search?.proposal?.idea ?? '')
  const approve = useAction(onChange, 'idea.approveFailed')
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = search?.state === 'running'
  const text = group.missing_idea ? squash(draft) : null
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  // Пока ИИ ищет вопросы к идее, её не поменять: сервер ответит 423.
  const asking = stream.questions?.state === 'running'
  const canApprove = !busy && !sought && !asking && text !== '' && !structureIsStale(council)

  const submit = () => void approve.go(async () => {
    try {
      return await api.approveIdea(council.id, { run: structure.run, revision: structure.revision }, group.id, text)
    } catch (e) {
      // Группы уже другие (поправили в другой вкладке) — показываем нынешние.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, onApproved)
  const seekAgain = () => void retry.go(() => startOrFollow(
    () => api.seekIdea(council.id, group.id), council.id, c => streamOf(c, group.id)?.discovery))
  // Устаревшие группы заново не ищут: сервер откажет, пока их не разложат заново.

  let idea
  if (!group.missing_idea) idea = <TextIdea group={group} fragments={fragments} />
  else if (sought) idea = <p className="muted">{t('idea.seeking')} {t('run.note')}</p>
  else idea = (
    <>
      {search?.state === 'failed' && !stream.idea && (
        <>
          <p className="error-text" role="alert">{search.error}</p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
          <p className="fragment-note">
            {t('idea.failedNote')}{' '}
            <button className="btn-link" disabled={busy || structureIsStale(council)} onClick={seekAgain}>
              {t('run.retry')}
            </button>
          </p>
        </>
      )}
      <IdeaEditor group={group} search={search} draft={draft} busy={busy} onDraft={setDraft} />
      {search && <IdeaOptions search={search} draft={draft} models={models} busy={busy} onTake={setDraft} />}
    </>
  )

  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t(sought ? 'idea.capsAi' : 'idea.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('idea.title')}</h2>
        <p className="panel-hint">{t('idea.hint')}</p>
      </section>
      <section className="card panel" aria-label={t('idea.section')}>
        <h3 className="panel-title caps">{t('idea.section')}</h3>
        {idea}
        <h3 className="panel-title caps section-gap">{t('idea.fragments')}</h3>
        <ol className="group-fragments">
          {group.fragment_ids.map(id => {
            const fragment = fragments.get(id)
            const others = structure.groups.filter(g => g.id !== group.id && g.fragment_ids.includes(id)).map(g => g.id)
            return (
              <li key={id} className="group-fragment">
                <span className="fragment-id">F{id}</span>
                {fragment && <LabelPill label={fragment.label} />}
                <span className="group-fragment-text">{fragment?.text ?? '—'}</span>
                {others.length > 0 && <span className="shared-chip">{t('groups.shared', { groups: others.join(', ') })}</span>}
              </li>
            )
          })}
        </ol>
        {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
        {asking && <p className="fragment-note">{t('idea.questionsRunning')}</p>}
        <div className="stream-actions">
          <button className="btn-primary large" disabled={!canApprove} onClick={submit}>{t('idea.approve')}</button>
        </div>
      </section>
    </>
  )
}

/** Идея, записанная в тексте: фрагменты-идеи группы, их не правят. */
function TextIdea({ group, fragments }: Readonly<{ group: Group; fragments: Map<number, LabeledFragment> }>) {
  const { t } = useTranslation()
  return (
    <>
      <div className="idea-box">
        {group.idea_fragment_ids.map((id, n) => (
          <div key={id} className="idea-line">
            <div className="idea-head">
              <span className="fragment-id">I{n + 1}</span>
              <LabelPill label="idea" />
              <span className="source-tag">{t('idea.fromText')} · F{id}</span>
            </div>
            <p className="idea-fixed">{fragments.get(id)?.text ?? '—'}</p>
          </div>
        ))}
      </div>
      <p className="fragment-note">{t('idea.textNote')}</p>
    </>
  )
}

/** Формулировка идеи: предложение совета, взятый вариант или своя. Откуда она — по тексту. */
function IdeaEditor({ group, search, draft, busy, onDraft }: Readonly<{
  group: Group; search: IdeaDiscovery | null; draft: string; busy: boolean; onDraft: (text: string) => void
}>) {
  const { t } = useTranslation()
  const offered = offeredBy(search).find(o => squash(o.idea) === squash(draft))
  const proposal = search?.proposal
  let note = null
  if (proposal?.idea) note = t('idea.foundNote')
  else if (proposal) note = t('idea.noneNote', { reason: proposal.reason })
  return (
    <>
      <div className="idea-box">
        <div className="idea-head">
          <span className="fragment-id">I1</span>
          <LabelPill label="idea" />
          <span className={offered ? 'source-tag ai' : 'source-tag'}>{t(offered ? 'idea.byAi' : 'idea.byYou')}</span>
        </div>
        <textarea className="idea-text" aria-label={t('idea.field', { group: group.id })} value={draft}
                  maxLength={1000} readOnly={busy} onChange={e => onDraft(e.target.value)} />
        {offered && (
          <p className="idea-why">{t('idea.why', { evidence: fragmentRange(offered.evidence), reason: offered.reason })}</p>
        )}
      </div>
      {note && <p className="fragment-note">{note}</p>}
    </>
  )
}

/** Варианты участников — когда есть из чего выбирать: их несколько или судья не взял ни один как есть. */
function IdeaOptions({ search, draft, models, busy, onTake }: Readonly<{
  search: IdeaDiscovery; draft: string; models: Model[]; busy: boolean; onTake: (text: string) => void
}>) {
  const { t } = useTranslation()
  const { options, proposal } = search
  if (options.length === 0 || (options.length === 1 && proposal?.option === 0)) return null
  return (
    <>
      <h3 className="panel-title caps section-gap">{t('idea.options')}</h3>
      <ul className="idea-options">
        {options.map((option, i) => (
          <li key={option.idea} className="idea-option">
            <span className="idea-option-text">
              {option.idea}
              {proposal?.decided_by === 'judge' && proposal.option === i && (
                <span className="pill idea-pick">{t('idea.judgePick')}</span>
              )}
            </span>
            <span className="idea-option-meta">
              {t('idea.optionMeta', {
                models: option.models.map(m => modelOf(models, m).short_name).join(', '),
                evidence: fragmentRange(option.evidence),
              })}
              {option.reason && ` — ${option.reason}`}
            </span>
            <button className="btn-secondary" disabled={busy || squash(option.idea) === squash(draft)}
                    onClick={() => onTake(option.idea)}>
              {t('idea.take')}
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

/**
 * Шаг «Вопросы»: совет ищет открытые вопросы к утверждённой идее, а человек оставляет нужные,
 * убирает лишние, добавляет свои и утверждает, какие вопросы потоку решать. Ответы здесь не
 * выбирают. Черновик отбора — к нынешнему поиску; утверждённый отбор — его начало.
 */
function QuestionsStep({ council, structure, stream, group, onChange, approve, onBack, onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>
  onBack: () => void; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const search = stream.questions
  const found = search?.questions ?? []
  const scope = stream.scope
  const [removed, setRemoved] = useState<ReadonlySet<string>>(
    () => new Set(scope ? found.filter(q => !scope.some(s => s.id === q.id)).map(q => q.id) : []))
  const [added, setAdded] = useState<string[]>(
    () => scope?.filter(q => q.source === 'added').map(q => q.text) ?? [])
  const [draft, setDraft] = useState('')
  const [twice, setTwice] = useState(false)   // свой вопрос совпал с тем, что уже в отборе
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = search?.state === 'running'
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const kept = found.filter(q => !removed.has(q.id))
  const chosen = kept.length + added.length
  const locked = busy || sought
  const canApprove = !locked && search !== null && chosen > 0 && !structureIsStale(council)
  const idea = stream.idea
  if (!idea) return null

  const toggle = (id: string) => setRemoved(before => {
    const next = new Set(before)
    if (!next.delete(id)) next.add(id)
    return next
  })
  const add = (event: FormEvent) => {
    event.preventDefault()
    const text = squash(draft)
    if (!text) return
    // Сравнение — как на сервере: совпавший с оставленным или своим вопрос он всё равно бы выкинул.
    const there = [...kept.map(q => q.text), ...added].some(own => sameQuestion(own) === sameQuestion(text))
    setTwice(there)
    if (!there) {
      setAdded([...added, text])
      setDraft('')
    }
  }
  const seek = () => void retry.go(() => startOrFollow(
    () => api.seekQuestions(council.id, group.id), council.id, c => streamOf(c, group.id)?.questions))
  // Устаревшие группы заново не ищут: сервер откажет, пока их не разложат заново.
  const stale = structureIsStale(council)
  const submit = () => void approve.go(async () => {
    try {
      return await api.approveScope(council.id, { run: structure.run, revision: structure.revision },
                                    group.id, search?.run ?? '', kept.map(q => q.id), added)
    } catch (e) {
      // Группы уже другие (поправили в другой вкладке) — показываем нынешние.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, onApproved)

  let list
  if (!search) list = (
    <p className="muted">
      {t('questions.notSought')}{' '}
      <button className="btn-link" disabled={busy || stale} onClick={seek}>{t('questions.seek')}</button>
    </p>
  )
  else if (sought) list = <p className="muted">{t('questions.seeking')} {t('run.note')}</p>
  else list = (
    <>
      {search.state === 'failed' && (
        <>
          <p className="error-text" role="alert">{search.error}</p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
          <p className="fragment-note">
            {t('questions.failedNote')}{' '}
            <button className="btn-link" disabled={busy || stale} onClick={seek}>{t('run.retry')}</button>
          </p>
        </>
      )}
      {search.state === 'done' && found.length === 0 && <p className="muted">{t('questions.none')}</p>}
      <ol className="questions" aria-label={t('questions.found')}>
        {found.map(question => (
          <QuestionItem key={question.id} question={question} fragments={fragments}
                        removed={removed.has(question.id)} busy={locked} onToggle={() => toggle(question.id)} />
        ))}
        {added.map(text => (
          <li key={text} className="question">
            <div className="question-head">
              <span className="source-tag">{t('questions.source.added')}</span>
              <span className="question-text">{text}</span>
              <button className="btn-secondary" disabled={locked}
                      onClick={() => setAdded(added.filter(own => own !== text))}>
                {t('questions.remove')}
              </button>
            </div>
          </li>
        ))}
      </ol>
      <form className="question-add" onSubmit={add}>
        <input className="text-field" aria-label={t('questions.own')} placeholder={t('questions.own')}
               value={draft} maxLength={500} readOnly={locked}
               onChange={e => { setDraft(e.target.value); setTwice(false) }} />
        <button type="submit" className="btn-secondary" disabled={locked || squash(draft) === ''}>
          {t('questions.add')}
        </button>
      </form>
      {twice && <p className="fragment-note question-twice">{t('questions.twice')}</p>}
    </>
  )

  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t(sought ? 'questions.capsAi' : 'questions.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('questions.title')}</h2>
        <p className="panel-hint">{t('questions.hint')}</p>
      </section>
      <section className="card panel" aria-label={t('questions.title')}>
        <div className="idea-box">
          <div className="idea-head">
            <span className="fragment-id">I1</span>
            <LabelPill label="idea" />
            <span className={idea.by === 'human' ? 'source-tag' : 'source-tag ai'}>{t(`questions.by.${idea.by}`)}</span>
            <button className="btn-link idea-change" onClick={onBack}>{t('questions.change')}</button>
          </div>
          <p className="idea-fixed">{idea.text}</p>
        </div>
        {list}
        {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
        <div className="stream-actions spread">
          <span className="muted">{t('questions.count', { count: chosen, total: found.length + added.length })}</span>
          <button className="btn-primary large" disabled={!canApprove} onClick={submit}>{t('questions.approve')}</button>
        </div>
      </section>
    </>
  )
}

/** Найденный вопрос: откуда он, почему и на него какие предложения группы отвечают. */
function QuestionItem({ question, fragments, removed, busy, onToggle }: Readonly<{
  question: OpenQuestion; fragments: Map<number, LabeledFragment>; removed: boolean; busy: boolean
  onToggle: () => void
}>) {
  const { t } = useTranslation()
  const fromModels = question.source === 'inferred' || question.source === 'discovered'
  return (
    <li className={removed ? 'question removed' : 'question'}>
      <div className="question-head">
        <span className="fragment-id">{question.id}</span>
        <span className={fromModels ? 'source-tag ai' : 'source-tag'}>{t(`questions.source.${question.source}`)}</span>
        <span className="question-text">{question.text}</span>
        {removed && <span className="group-tag">{t('questions.removedTag')}</span>}
        <button className="btn-secondary" disabled={busy} onClick={onToggle}>
          {t(removed ? 'questions.restore' : 'questions.remove')}
        </button>
      </div>
      {question.reason && <p className="question-why">{t('questions.why', { reason: question.reason })}</p>}
      {question.proposal_ids.length > 0 && (
        <details className="question-proposals">
          <summary>{t('questions.proposals', { count: question.proposal_ids.length })}</summary>
          <ul>
            {question.proposal_ids.map(id => (
              <li key={id}><span className="fragment-id">F{id}</span> {fragments.get(id)?.text ?? '—'}</li>
            ))}
          </ul>
        </details>
      )}
    </li>
  )
}

/** Шаг «Варианты» пока не готов: здесь отобранные вопросы и дорога назад, к отбору. */
function OptionsStep({ stream, onBack }: Readonly<{ stream: Stream; onBack: () => void }>) {
  const { t } = useTranslation()
  const scope = stream.scope
  if (!scope) return null
  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t('options.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('options.title')}</h2>
        <p className="panel-hint">{t('options.hint')}</p>
      </section>
      <Panel title={t('options.scope')} caps aside={<button className="btn-link" onClick={onBack}>{t('options.change')}</button>}>
        <ol className="questions">
          {scope.map(question => (
            <li key={question.id} className="question">
              <div className="question-head">
                <span className="fragment-id">{question.id}</span>
                <span className="question-text">{question.text}</span>
              </div>
            </li>
          ))}
        </ol>
      </Panel>
      <div className="card placeholder">{t('options.stub')}</div>
    </>
  )
}

/** Что предлагал совет: его предложение и варианты участников. */
function offeredBy(search: IdeaDiscovery | null): { idea: string; evidence: number[]; reason: string }[] {
  if (!search) return []
  const proposal = search.proposal?.idea ? [{ ...search.proposal, idea: search.proposal.idea }] : []
  return [...proposal, ...search.options]
}

/** Текст идеи без лишних пробелов — так его сравнивает и сервер. */
const squash = (text: string) => text.trim().split(/\s+/).join(' ')

/** Один и тот же вопрос — как считает сервер: без лишних пробелов, регистра и знака в конце. */
const sameQuestion = (text: string) => squash(text).replace(/[.?!]+$/, '').toLowerCase()

/** Номера фрагментов коротко: F1–F3, F5. */
export function fragmentRange(ids: number[]): string {
  const sorted = [...new Set(ids)].sort((a, b) => a - b)
  const parts: string[] = []
  let start = 0
  while (start < sorted.length) {
    let end = start
    while (end + 1 < sorted.length && sorted[end + 1] === sorted[end] + 1) end++
    parts.push(end - start >= 2
      ? `F${sorted[start]}–F${sorted[end]}`
      : sorted.slice(start, end + 1).map(id => `F${id}`).join(', '))
    start = end + 1
  }
  return parts.join(', ')
}
