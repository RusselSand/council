import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import {
  api, ApiError, councilPath, groupsConfirmed, outcomeReady, startOrFollow, streamOf, structureIsStale,
  type Council, type Group, type IdeaDiscovery, type LabeledFragment, type Model, type OpenQuestion, type Outcome,
  type QuestionAnalysis, type QuestionOptions, type RepositoryScan, type Settings, type Stream, type Structure,
} from '../api'
import { LabelPill } from '../components/Labels'
import { modelOf } from '../components/ModelBadge'
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
                     models={settings.models} repositories={settings.repositories} onChange={onChange} />
}

function StreamPage({ council, structure, stream, models, repositories, onChange }: Readonly<{
  council: Council; structure: Structure; stream: Stream; models: Model[]; repositories: string | null
  onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const [chosen, setView] = useState<ChainStep>(currentStep(stream))
  // Утверждение отбора — здесь, а не в шаге: отказ (409) приносит новый поиск, шаг рисуется
  // заново, а ошибка должна остаться видна.
  const passing = useAction(onChange, 'repository.approveFailed')
  const choosing = useAction(onChange, 'questions.approveFailed')
  const picking = useAction(onChange, 'options.approveFailed')
  const fixing = useAction(onChange, 'decisions.approveFailed')
  // Открытый вопрос, к которому вернулись из итогов: шаг «Решения» прокрутит к нему.
  const [focus, setFocus] = useState<string | null>(null)
  // Пробел из итога, который человек понёс в вопросы: шаг «Вопросы» добавит его в отбор.
  const [gap, setGap] = useState<string | null>(null)
  const group = structure.groups.find(g => g.id === stream.group)
  if (!group) return null  // поток без группы не бывает: состав меняют, только сняв подтверждение
  // Открыть можно пройденный шаг и текущий: дальше — нечего.
  const view = CHAIN.indexOf(chosen) <= CHAIN.indexOf(currentStep(stream)) ? chosen : currentStep(stream)
  const search = stream.discovery
  const runs = { group: search, repository: stream.scan, questions: stream.questions, options: stream.proposals,
                 decisions: stream.analysis, outcomes: stream.outcomes }
  const run = runs[view]
  const open = (step: ChainStep) => {
    setFocus(null)
    setGap(null)
    setView(step)
  }

  return (
    <div className="streams-layout">
      <aside className="streams-nav">
        <StreamList council={council} structure={structure} open={stream.group} />
        <Chain stream={stream} group={group} view={view} onView={open} />
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
                     onApproved={() => open('repository')} />
        )}
        {view === 'repository' && (
          // Новый скан — и путь заново, из него.
          <RepositoryStep key={stream.scan?.run ?? ''} council={council} structure={structure} stream={stream}
                          group={group} repositories={repositories} onChange={onChange} approve={passing}
                          onApproved={() => open('questions')} />
        )}
        {view === 'questions' && (
          // Новый поиск вопросов — и отбор заново, к его вопросам.
          <QuestionsStep key={stream.questions?.run ?? ''} council={council} structure={structure}
                         stream={stream} group={group} onChange={onChange} approve={choosing} proposed={gap}
                         onBack={() => open('group')} onApproved={() => open('options')} />
        )}
        {view === 'options' && (
          // Новый поиск вариантов — и выбор заново, к его вариантам.
          <OptionsStep key={stream.proposals?.run ?? ''} council={council} structure={structure}
                       stream={stream} group={group} onChange={onChange} approve={picking}
                       onBack={() => setView('questions')} onApproved={() => setView('decisions')} />
        )}
        {view === 'decisions' && (
          // Новая проверка выбора — и решения заново, к её итогам.
          <DecisionsStep key={stream.analysis?.run ?? ''} council={council} structure={structure}
                         stream={stream} group={group} onChange={onChange} approve={fixing} focus={focus}
                         onBack={() => open('options')} onApproved={() => open('outcomes')} />
        )}
        {view === 'outcomes' && (
          <OutcomesStep council={council} stream={stream} group={group} onChange={onChange}
                        onBack={() => open('decisions')}
                        onQuestion={question => { setFocus(question); setView('decisions') }}
                        onGap={question => { setGap(question); setView('questions') }} />
        )}
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
  const run = { group: stream.discovery, repository: stream.scan, questions: stream.questions,
                options: stream.proposals, decisions: stream.analysis, outcomes: stream.outcomes }[step]
  if (run?.state === 'running') return t(`streams.${step}.seeking`)
  if (run?.state === 'failed') return t(`streams.${step}.failed`)
  if (step === 'outcomes' && streamLight(stream) === 'done') return t('streams.outcomes.done')
  return t(`streams.${step}.yours`)
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
              {step === 'repository' && stream.idea && (
                <span className="segment-sub">{repositoryStatus(stream, t)}</span>
              )}
              {step === 'questions' && stream.repository && (
                <span className="segment-sub">{questionsStatus(stream, t)}</span>
              )}
              {step === 'options' && stream.scope && <span className="segment-sub">{optionsStatus(stream, t)}</span>}
              {step === 'decisions' && stream.choices && (
                <span className="segment-sub">{decisionsStatus(stream, t)}</span>
              )}
              {step === 'outcomes' && stream.decisions && (
                <span className="segment-sub">{outcomesStatus(stream, t)}</span>
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
    if (step === 'repository' && stream.idea) return repositoryStatus(stream, t)
    if (step === 'questions' && stream.repository) return questionsStatus(stream, t)
    if (step === 'options' && stream.scope) return optionsStatus(stream, t)
    if (step === 'decisions' && stream.choices) return decisionsStatus(stream, t)
    if (step === 'outcomes' && stream.decisions) return outcomesStatus(stream, t)
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

/**
 * Что с итогами потока: собираются, сборка упала, сколько держат открытые вопросы, сколько ещё не
 * готово, какие решения не вошли ни в один, сколько готово.
 */
function outcomesStatus(stream: Stream, t: T): string {
  const run = stream.outcomes
  if (run?.state === 'running') return t('chain.outcomesAssembling')
  if (run?.state === 'failed') return t('chain.outcomesFailed')
  if (!run) return t('chain.outcomesNone')
  const total = run.outcomes.length
  if (total === 0) return t('chain.outcomesEmpty')
  const blocked = run.outcomes.filter(o => o.blocked_by.length > 0).length
  if (blocked > 0) return t('chain.outcomesBlocked', { count: blocked, total })
  const unready = run.outcomes.filter(o => !outcomeReady(o)).length
  if (unready > 0) return t('chain.outcomesNotReady', { count: unready, total })
  if (run.uncovered_adr_ids.length > 0) return t('chain.outcomesUncovered', { ids: run.uncovered_adr_ids.join(', ') })
  return t('chain.outcomesReady', { count: total, total })
}

/** Что с решениями потока: зафиксированы, выбор проверяется, проверка упала, прошла или не шла. */
function decisionsStatus(stream: Stream, t: T): string {
  const analysis = stream.analysis
  if (stream.decisions) {
    return t('chain.decisionsMade', {
      count: stream.decisions.filter(d => d.proposal).length, total: stream.decisions.length })
  }
  if (analysis?.state === 'running') return t('chain.decisionsChecking')
  if (analysis?.state === 'failed') return t('chain.decisionsFailed')
  if (analysis) return t('chain.decisionsChecked')
  return t('chain.decisionsNone')
}

/** Что с вариантами потока: ищутся, упали, найдены, сколько выбрано или ещё не искались. */
function optionsStatus(stream: Stream, t: T): string {
  const search = stream.proposals
  if (stream.choices) {
    return t('chain.optionsChosen', {
      count: stream.choices.filter(c => c.proposal).length, total: stream.choices.length })
  }
  if (search?.state === 'running') return t('chain.optionsSeeking')
  if (search?.state === 'failed') return t('chain.optionsFailed')
  if (search) return t('chain.optionsFound', { count: search.options.reduce((n, o) => n + o.proposals.length, 0) })
  return t('chain.optionsNone')
}

/** Что с шагом «Репозиторий»: пройден (с картой или без), скан идёт, упал, готов или его не было. */
function repositoryStatus(stream: Stream, t: T): string {
  const scan = stream.scan
  if (stream.repository) return t(stream.repository.by === 'scan' ? 'chain.repositoryTaken' : 'chain.repositorySkipped')
  if (scan?.state === 'running') return t('chain.repositoryScanning')
  if (scan?.state === 'failed') return t('chain.repositoryFailed')
  if (scan) return t('chain.repositoryScanned')
  return t('chain.repositoryNone')
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
  // Пока ИИ работает ниже по цепочке, идею не поменять: сервер ответит 423.
  const asking = [stream.scan, stream.questions, stream.proposals, stream.analysis, stream.outcomes]
    .some(run => run?.state === 'running')
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
    () => api.seekIdea(council.id, group.id), council, c => streamOf(c, group.id)?.discovery))
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
        {asking && <p className="fragment-note">{t('idea.belowRunning')}</p>}
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
 * Шаг «Репозиторий» — необязательный. Совет сканирует рабочую копию под идею: inventory — список
 * файлов, участники и судья читают код и составляют карту того, как система устроена сейчас. Человек
 * утверждает карту или пропускает шаг — и совет сразу ищет вопросы; карта идёт во все следующие шаги.
 */
function RepositoryStep({ council, structure, stream, group, repositories, onChange, approve, onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group; repositories: string | null
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const scan = stream.scan
  const [path, setPath] = useState(scan?.path ?? '')
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = scan?.state === 'running'
  const stale = structureIsStale(council)
  // Пока ИИ работает ниже по цепочке, шаг не поменять: сервер ответит 423.
  const below = [stream.questions, stream.proposals, stream.analysis, stream.outcomes].some(run => run?.state === 'running')
  const idea = stream.idea
  if (!idea) return null
  const at = { run: structure.run, revision: structure.revision }

  const start = (event: FormEvent) => {
    event.preventDefault()
    void retry.go(async () => {
      try {
        return await startOrFollow(() => api.scanRepository(council.id, at, group.id, path, idea.text), council,
                                   c => streamOf(c, group.id)?.scan)
      } catch (e) {
        // Идею поменяли в другой вкладке — показываем нынешнюю: скан пойдёт уже к ней.
        if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
        throw e
      }
    })
  }
  const pass = (scanRun: string | null) => void approve.go(async () => {
    try {
      return await api.approveRepository(council.id, at, group.id, scanRun, idea.text)
    } catch (e) {
      // Группы уже другие или скан уже другой (другая вкладка) — показываем нынешнее.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, onApproved)
  const taken = stream.repository
  const ready = scan?.state === 'done' && scan.result !== null

  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t(sought ? 'repository.capsAi' : 'repository.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('repository.title')}</h2>
        <p className="panel-hint">{t('repository.hint')}</p>
        <p className="fragment-note">{t('repository.trust')}</p>
      </section>
      <p className="options-idea"><span className="fragment-id">I1</span> {idea.text}</p>
      <section className="card panel" aria-label={t('repository.title')}>
        <form className="repo-scan" onSubmit={start}>
          <input className="text-field" aria-label={t('repository.path')} value={path}
                 readOnly={busy || sought} onChange={e => setPath(e.target.value)}
                 placeholder={repositories ? t('repository.pathRoot', { root: repositories }) : t('repository.pathAbsolute')} />
          <button type="submit" className="btn-secondary" disabled={busy || sought || below || stale || path.trim() === ''}>
            {t('repository.scan')}
          </button>
        </form>
        {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
        {stream.questions && !sought && <p className="fragment-note">{t('repository.rescanNote')}</p>}
        {sought && (
          <p className="muted">{t('repository.scanning', { round: Math.min(scan.rounds + 1, 3) })} {t('run.note')}</p>
        )}
        {scan?.state === 'failed' && (
          <>
            <p className="error-text" role="alert">{scan.error}</p>
            <p className="fragment-note">{t('repository.failedNote')}</p>
          </>
        )}
        {scan?.result && <RepositoryMapView scan={scan} />}
        {taken && <p className="fragment-note">{t(taken.by === 'scan' ? 'repository.taken' : 'repository.skipped')}</p>}
        {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
        {below && <p className="fragment-note">{t('repository.belowRunning')}</p>}
        <div className="stream-actions spread">
          <button className="btn-secondary" disabled={busy || sought || below || stale} onClick={() => pass(null)}>
            {t('repository.skip')}
          </button>
          {ready && (
            <button className="btn-primary large" disabled={busy || below || stale} onClick={() => pass(scan.run)}>
              {t('repository.approve')}
            </button>
          )}
        </div>
      </section>
    </>
  )
}

const FINDING_PILL = { verified: 'pill ready', inferred: 'pill open', unknown: 'pill' } as const
const COVERAGE_PILL = { covered: 'pill ready', partial: 'pill open', not_investigated: 'pill blocked', not_applicable: 'pill' } as const

/** Карта скана: находки с подтверждениями, как идёт выполнение, покрытие, неизвестное и расхождения. */
function RepositoryMapView({ scan }: Readonly<{ scan: RepositoryScan }>) {
  const { t } = useTranslation()
  const result = scan.result
  if (!result) return null
  return (
    <>
      <p className="repo-summary">
        {t('repository.summary', {
          path: scan.path, sha: scan.commit_sha.slice(0, 8) || '—', files: scan.files, rounds: scan.rounds })}
      </p>
      {scan.dirty && <p className="fragment-note">{t('repository.dirty')}</p>}
      {scan.outside > 0 && <p className="fragment-note">{t('repository.outside', { count: scan.outside })}</p>}
      {scan.omitted_count > 0 && <p className="fragment-note">{t('repository.omitted', {
        count: scan.omitted_count, items: scan.omitted.join('; ') + (scan.omitted_count > scan.omitted.length ? '; …' : '') })}</p>}
      {scan.state === 'done' && scan.complete && <p className="check ok">{t('repository.complete')}</p>}
      {scan.state === 'done' && !scan.complete && (
        <div className="check problem">
          <p>{t('repository.incomplete')}</p>
          <ul>{scan.follow_up.map(item => (
            <li key={item.objective}>{item.targets.length > 0 ? `${item.objective} — ${item.targets.join(', ')}` : item.objective}</li>
          ))}</ul>
        </div>
      )}
      {result.findings.length === 0 && <p className="muted">{t('repository.empty')}</p>}
      <dl className="outcome-rows">
        {result.findings.length > 0 && (
          <>
            <dt>{t('repository.findings')}</dt>
            <dd>
              <ul className="repo-list">{result.findings.map(finding => (
                <li key={finding.id} className="repo-finding">
                  <span className="repo-finding-head">
                    <span className="fragment-id">{finding.id}</span>
                    <span className={FINDING_PILL[finding.status]}>{t(`repository.status.${finding.status}`)}</span>
                    <span className="repo-statement">{finding.statement}</span>
                  </span>
                  {finding.evidence.length > 0 && (
                    <span className="repo-evidence">
                      {finding.evidence.map(e => [e.path, e.lines, e.symbol].filter(Boolean).join(' · ')).join('; ')}
                    </span>
                  )}
                  {finding.relevance && <span className="option-note">{finding.relevance}</span>}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.flows.length > 0 && (
          <>
            <dt>{t('repository.flows')}</dt>
            <dd>
              <ul className="repo-list">{result.flows.map(flow => (
                <li key={flow.name}>
                  <strong>{flow.name}</strong>
                  {flow.entry_point && <span className="repo-evidence"> · {t('repository.entry', { path: flow.entry_point })}</span>}
                  <ol className="repo-steps">{flow.steps.map(step => (
                    <li key={step.description}>
                      {step.description}{step.finding_ids.length > 0 && ` (${step.finding_ids.join(', ')})`}
                    </li>
                  ))}</ol>
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.coverage.length > 0 && (
          <>
            <dt>{t('repository.coverage')}</dt>
            <dd>
              <ul className="repo-list">{result.coverage.map(area => (
                <li key={area.area} className="repo-finding-head">
                  <span>{area.area}</span>
                  <span className={COVERAGE_PILL[area.status]}>{t(`repository.coverage.${area.status}`)}</span>
                  {area.reason && <span className="option-note">{area.reason}</span>}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.unknowns.length > 0 && (
          <>
            <dt>{t('repository.unknowns')}</dt>
            <dd>
              <ul className="repo-list">{result.unknowns.map(unknown => (
                <li key={unknown.question} className="repo-finding">
                  <span>{unknown.reason ? `${unknown.question} — ${unknown.reason}` : unknown.question}</span>
                  {unknown.investigate.length > 0 && (
                    <span className="option-note">{t('repository.investigate', { targets: unknown.investigate.join(', ') })}</span>
                  )}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.documentation_conflicts.length > 0 && (
          <>
            <dt>{t('repository.conflicts')}</dt>
            <dd><ul className="repo-list">{result.documentation_conflicts.map(text => <li key={text}>{text}</li>)}</ul></dd>
          </>
        )}
      </dl>
    </>
  )
}

/**
 * Шаг «Вопросы»: совет ищет открытые вопросы к утверждённой идее, а человек оставляет нужные,
 * убирает лишние, добавляет свои и утверждает, какие вопросы потоку решать. Ответы здесь не
 * выбирают. Черновик отбора — к нынешнему поиску; утверждённый отбор — его начало.
 */
function QuestionsStep({ council, structure, stream, group, onChange, approve, proposed, onBack, onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>
  /** Пробел из итогов: его добавить в отбор своим вопросом, если такого там ещё нет. */
  proposed: string | null
  onBack: () => void; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const search = stream.questions
  const found = search?.questions ?? []
  const scope = stream.scope
  const [removed, setRemoved] = useState<ReadonlySet<string>>(
    () => new Set(scope ? found.filter(q => !scope.some(s => s.id === q.id)).map(q => q.id) : []))
  const [added, setAdded] = useState<string[]>(() => {
    const own = scope?.filter(q => q.source === 'added').map(q => q.text) ?? []
    const there = [...found.filter(q => !scope || scope.some(s => s.id === q.id)).map(q => q.text), ...own]
    const gap = squash(proposed ?? '')
    return gap && !there.some(text => sameQuestion(text) === sameQuestion(gap)) ? [...own, gap] : own
  })
  const [draft, setDraft] = useState('')
  const [twice, setTwice] = useState(false)   // свой вопрос совпал с тем, что уже в отборе
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = search?.state === 'running'
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const kept = found.filter(q => !removed.has(q.id))
  const chosen = kept.length + added.length
  const locked = busy || sought
  // Пока ИИ работает с утверждённым отбором (ищет варианты, проверяет выбор), отбор не поменять: 423.
  const offering = [stream.proposals, stream.analysis, stream.outcomes].some(run => run?.state === 'running')
  const canApprove = !locked && !offering && search !== null && chosen > 0 && !structureIsStale(council)
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
    () => api.seekQuestions(council.id, group.id), council, c => streamOf(c, group.id)?.questions))
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
    <>
      <p className="muted">
        {t('questions.notSought')}{' '}
        <button className="btn-link" disabled={busy || stale} onClick={seek}>{t('questions.seek')}</button>
      </p>
      {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
    </>
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
      {proposed && added.includes(squash(proposed)) && <p className="fragment-note">{t('questions.fromGap')}</p>}
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
        {offering && <p className="fragment-note">{t('questions.belowRunning')}</p>}
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

/**
 * Шаг «Варианты»: к каждому отобранному вопросу совет ищет новые варианты ответа, а человек
 * выбирает один — из текста группы или найденный — либо оставляет вопрос unresolved: его
 * разберёт следующий шаг. Найденное к вопросу видно, как только готово. Черновик выбора — к
 * нынешнему поиску; утверждённый выбор — его начало.
 */
function OptionsStep({ council, structure, stream, group, onChange, approve, onBack, onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>
  onBack: () => void; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const search = stream.proposals
  const scope = stream.scope ?? []
  // Выбор по вопросу: id варианта, null — unresolved; нет ключа — ещё не выбран.
  const [picked, setPicked] = useState<ReadonlyMap<string, string | null>>(
    () => new Map(stream.choices?.map(c => [c.question_id, c.proposal]) ?? []))
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = search?.state === 'running'
  const stale = structureIsStale(council)
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const found = new Map(search?.options.map(o => [o.question_id, o]) ?? [])
  const chosen = scope.filter(q => picked.has(q.id)).length
  // Пока ИИ работает с утверждённым выбором (проверяет, собирает итоги), выбор не поменять: 423.
  const checking = [stream.analysis, stream.outcomes].some(run => run?.state === 'running')
  const canApprove = !busy && !sought && !checking && !stale && search !== null && chosen === scope.length
  const idea = stream.idea
  if (!idea || !stream.scope) return null

  const pick = (question: string, proposal: string | null) =>
    setPicked(before => new Map(before).set(question, proposal))
  const seek = () => void retry.go(() => startOrFollow(
    () => api.seekProposals(council.id, group.id), council, c => streamOf(c, group.id)?.proposals))
  const submit = () => void approve.go(async () => {
    try {
      return await api.approveChoices(council.id, { run: structure.run, revision: structure.revision },
                                      group.id, search?.run ?? '',
                                      scope.map(q => ({ question_id: q.id, proposal: picked.get(q.id) ?? null })))
    } catch (e) {
      // Группы уже другие (поправили в другой вкладке) — показываем нынешние.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, onApproved)

  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t(sought ? 'options.capsAi' : 'options.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('options.title')}</h2>
        <p className="panel-hint">{t('options.hint')}</p>
      </section>
      <p className="options-idea">
        <span className="fragment-id">I1</span> {idea.text}{' '}
        <button className="btn-link" onClick={onBack}>{t('options.change')}</button>
      </p>
      {!search && (
        <div>
          <p className="muted">
            {t('options.notSought')}{' '}
            <button className="btn-link" disabled={busy || stale} onClick={seek}>{t('options.seek')}</button>
          </p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
        </div>
      )}
      {search?.state === 'failed' && (
        <div>
          <p className="error-text" role="alert">{search.error}</p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
          <p className="fragment-note">
            {t('options.failedNote')}{' '}
            <button className="btn-link" disabled={busy || stale} onClick={seek}>{t('run.retry')}</button>
          </p>
        </div>
      )}
      {scope.map(question => (
        <QuestionChoice key={question.id} question={question} options={found.get(question.id)}
                        sought={sought} fragments={fragments} value={picked.get(question.id)}
                        busy={busy} onPick={proposal => pick(question.id, proposal)} />
      ))}
      {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
      {checking && <p className="fragment-note">{t('options.belowRunning')}</p>}
      <div className="stream-actions spread">
        <span className="muted">{t('options.count', { count: chosen, total: scope.length })}</span>
        <button className="btn-primary large" disabled={!canApprove} onClick={submit}>{t('options.approve')}</button>
      </div>
    </>
  )
}

/** Вопрос и его варианты: из текста группы, найденные советом и «пока не решаю». */
function QuestionChoice({ question, options, sought, fragments, value, busy, onPick }: Readonly<{
  question: OpenQuestion; options: QuestionOptions | undefined; sought: boolean
  fragments: Map<number, LabeledFragment>; value: string | null | undefined; busy: boolean
  onPick: (proposal: string | null) => void
}>) {
  const { t } = useTranslation()
  const name = `choice-${question.id}`
  const fromModels = question.source === 'inferred' || question.source === 'discovered'
  const option = (id: string | null, body: ReactNode, className = 'option') => (
    <li key={id ?? 'unresolved'}>
      <label className={className}>
        <input type="radio" name={name} checked={value === id} disabled={busy} onChange={() => onPick(id)} />
        <span className="option-body">{body}</span>
      </label>
    </li>
  )
  return (
    <section className="card panel" aria-labelledby={`${name}-title`}>
      <div className="question-head">
        <span className="fragment-id">{question.id}</span>
        <span className={fromModels ? 'source-tag ai' : 'source-tag'}>{t(`questions.source.${question.source}`)}</span>
        <h3 id={`${name}-title`} className="question-text">{question.text}</h3>
      </div>
      <ul className="option-list" role="radiogroup" aria-labelledby={`${name}-title`}>
        {question.proposal_ids.map(id => option(`F${id}`, (
          <>
            <span className="option-head">
              <span className="fragment-id">F{id}</span>
              <span className="source-tag">{t('options.fromGroup')}</span>
            </span>
            <span>{fragments.get(id)?.text ?? '—'}</span>
          </>
        )))}
        {options?.proposals.map(proposal => option(proposal.id, (
          <>
            <span className="option-head">
              <span className="fragment-id">{proposal.id}</span>
              <span className="source-tag ai">{t('options.byAi')}</span>
              <span className="option-text">{proposal.text}</span>
              {proposal.recommended && <span className="pill ready">{t('options.recommended')}</span>}
            </span>
            {proposal.reason && <span className="option-note">{t('options.why', { reason: proposal.reason })}</span>}
            {proposal.constraint_ids.length > 0 && (
              <span className="option-note">{t('options.limits', { ids: fragmentRange(proposal.constraint_ids) })}</span>
            )}
            {proposal.risk_ids.length > 0 && (
              <span className="option-note">{t('options.risks', { ids: fragmentRange(proposal.risk_ids) })}</span>
            )}
            {proposal.depends_on.length > 0 && (
              <span className="option-note">{t('options.depends', { ids: proposal.depends_on.join(', ') })}</span>
            )}
          </>
        )))}
        {option(null, t('options.unresolved'), 'option unresolved')}
      </ul>
      {!options && sought && <p className="option-note">{t('options.seeking')}</p>}
      {options?.verdict === 'alternatives' && options.reason && (
        <p className="option-note">{t('options.alternatives', { reason: options.reason })}</p>
      )}
      {options?.verdict === 'none' && (
        <p className="option-note">{options.reason ? t('options.none', { reason: options.reason }) : t('options.noneShort')}</p>
      )}
    </section>
  )
}

/**
 * Шаг «Решения»: совет проверяет выбор по каждому вопросу, а для unresolved подбирает вариант из
 * тех, что есть; человек фиксирует решения — ADR: вариант и почему он, — или оставляет вопрос
 * открытым. Решить можно любым вариантом вопроса, не только проверенным: решает человек, и
 * проблема, которую нашёл совет, этому не мешает. Обоснование совета — черновик: оставленное
 * как есть, при фиксации оно подтверждено человеком. Черновик решений — к нынешней проверке.
 */
function DecisionsStep({ council, structure, stream, group, onChange, approve, focus, onBack, onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>
  /** Вопрос, к которому прокрутить: к нему вернулись из итогов. */
  focus: string | null
  onBack: () => void; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const analysis = stream.analysis
  const scope = stream.scope ?? []
  // Решение по вопросу: id варианта, null — открыт. Сначала — зафиксированное, иначе — выбор.
  const [picked, setPicked] = useState<ReadonlyMap<string, string | null>>(() => new Map(scope.map(q => [
    q.id, (stream.decisions ?? stream.choices)?.find(d => d.question_id === q.id)?.proposal ?? null])))
  // Обоснование — своё у каждой пары «вопрос — вариант»: переключились и вернулись — правка на месте.
  const [written, setWritten] = useState<ReadonlyMap<string, string>>(() => new Map(
    (stream.decisions ?? []).filter(d => d.proposal).map(d => [`${d.question_id}:${d.proposal}`, d.rationale ?? ''])))
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = analysis?.state === 'running'
  const stale = structureIsStale(council)
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const found = new Map(stream.proposals?.options.map(o => [o.question_id, o.proposals]) ?? [])
  const said = new Map(analysis?.analyses.map(a => [a.question_id, a]) ?? [])
  // Обоснование совета — к тому варианту, который он проверил или рекомендовал.
  const suggested = (question: string, proposal: string) => {
    const one = said.get(question)
    return one?.proposal === proposal ? one.rationale : null
  }
  const rationaleOf = (question: string, proposal: string) =>
    written.get(`${question}:${proposal}`) ?? suggested(question, proposal) ?? ''
  const decided = scope.filter(q => picked.get(q.id))
  const complete = decided.every(q => squash(rationaleOf(q.id, picked.get(q.id) ?? '')) !== '')
  // Пока ИИ собирает итоги по решениям, их не поменять: сервер ответит 423.
  const assembling = stream.outcomes?.state === 'running'
  const canApprove = !busy && !sought && !assembling && !stale && analysis !== null && complete
  useEffect(() => {
    if (focus) document.getElementById(`decision-${focus}-title`)?.scrollIntoView?.({ block: 'center' })
  }, [focus])
  const idea = stream.idea
  if (!idea || !stream.scope || !stream.choices) return null

  const optionsOf = (question: OpenQuestion) => [
    ...question.proposal_ids.map(id => ({ id: `F${id}`, text: fragments.get(id)?.text ?? '—' })),
    ...(found.get(question.id) ?? []).map(p => ({ id: p.id, text: p.text })),
  ]
  const check = () => void retry.go(() => startOrFollow(
    () => api.checkChoices(council.id, group.id), council, c => streamOf(c, group.id)?.analysis))
  const submit = () => void approve.go(async () => {
    try {
      return await api.approveDecisions(council.id, { run: structure.run, revision: structure.revision },
                                        group.id, analysis?.run ?? '', scope.map(q => {
        const proposal = picked.get(q.id) ?? null
        return { question_id: q.id, proposal, rationale: proposal ? squash(rationaleOf(q.id, proposal)) : null }
      }))
    } catch (e) {
      // Группы уже другие (поправили в другой вкладке) — показываем нынешние.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, onApproved)

  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t(sought ? 'decisions.capsAi' : 'decisions.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('decisions.title')}</h2>
        <p className="panel-hint">{t('decisions.hint')}</p>
      </section>
      <p className="options-idea">
        <span className="fragment-id">I1</span> {idea.text}{' '}
        <button className="btn-link" onClick={onBack}>{t('decisions.change')}</button>
      </p>
      {!analysis && (
        <div>
          <p className="muted">
            {t('decisions.notChecked')}{' '}
            <button className="btn-link" disabled={busy || stale} onClick={check}>{t('decisions.check')}</button>
          </p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
        </div>
      )}
      {analysis?.state === 'failed' && (
        <div>
          <p className="error-text" role="alert">{analysis.error}</p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
          <p className="fragment-note">
            {t('decisions.failedNote')}{' '}
            <button className="btn-link" disabled={busy || stale || stream.decisions !== null} onClick={check}>
              {t('run.retry')}
            </button>
          </p>
        </div>
      )}
      {scope.map((question, n) => {
        const value = picked.get(question.id) ?? null
        const rationale = value ? rationaleOf(question.id, value) : ''
        const fixed = stream.decisions?.find(d => d.question_id === question.id)
        return (
          <DecisionCard key={question.id} question={question} n={n + 1} options={optionsOf(question)}
                        choice={stream.choices?.find(c => c.question_id === question.id)?.proposal ?? null}
                        said={said.get(question.id)} sought={sought} value={value} rationale={rationale}
                        byAi={value !== null && squash(rationale) === squash(suggested(question.id, value) ?? '')}
                        fixed={fixed !== undefined && fixed.proposal === value
                          && (value === null || fixed.rationale === squash(rationale))}
                        busy={busy} onPick={proposal => setPicked(before => new Map(before).set(question.id, proposal))}
                        onRationale={text => value && setWritten(before => new Map(before).set(`${question.id}:${value}`, text))} />
        )
      })}
      {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
      {assembling && <p className="fragment-note">{t('decisions.belowRunning')}</p>}
      <div className="stream-actions spread">
        <span className="muted">{t('decisions.count', { count: decided.length, total: scope.length })}</span>
        <button className="btn-primary large" disabled={!canApprove} onClick={submit}>{t('decisions.approve')}</button>
      </div>
    </>
  )
}

/**
 * Вопрос на шаге «Решения»: выбор человека, что о нём сказал совет, черновик ADR и само решение —
 * вариант или «оставить открытым».
 */
function DecisionCard({ question, n, options, choice, said, sought, value, rationale, byAi, fixed, busy, onPick, onRationale }: Readonly<{
  question: OpenQuestion; n: number; options: { id: string; text: string }[]; choice: string | null
  said: QuestionAnalysis | undefined; sought: boolean; value: string | null; rationale: string; byAi: boolean
  fixed: boolean; busy: boolean; onPick: (proposal: string | null) => void; onRationale: (text: string) => void
}>) {
  const { t } = useTranslation()
  const name = `decision-${question.id}`
  const textOf = (id: string) => options.find(o => o.id === id)?.text ?? id
  // Проверка совета — о том варианте, что сейчас решением: иначе её последствия не про него.
  const checkedHere = said?.proposal === value && (said?.verdict === 'validated' || said?.verdict === 'conflict')
  let verdict = null
  if (said?.verdict === 'validated') verdict = (
    <p className="check ok"><strong>{t('decisions.validated')}</strong> {consequences(said, t)}</p>
  )
  else if (said?.verdict === 'conflict') verdict = (
    <p className="check problem">
      <strong>{t('decisions.conflict')}</strong> {[said.reason, consequences(said, t)].filter(Boolean).join(' ')}
    </p>
  )
  else if (said?.verdict === 'recommended' && said.proposal) {
    const proposal = said.proposal
    verdict = (
      <div className="check ai">
        <p className="check-head">
          <span className="role-tag ai">{t('chain.ai')}</span>
          <span>{t('decisions.suggests')} <strong>{proposal} · {textOf(proposal)}</strong></span>
          <button className="btn-secondary" disabled={busy || value === proposal} onClick={() => onPick(proposal)}>
            {t('decisions.accept')}
          </button>
        </p>
        {said.reason && <p className="option-note">{said.reason}</p>}
      </div>
    )
  } else if (said?.verdict === 'none') verdict = (
    <p className="option-note">
      {options.length === 0 ? t('decisions.noOptions')
        : said.reason ? t('decisions.noPick', { reason: said.reason }) : t('decisions.noPickShort')}
    </p>
  )
  else if (sought) verdict = <p className="option-note">{t('decisions.checking')}</p>

  return (
    <section className="card panel" aria-labelledby={`${name}-title`}>
      <div className="question-head">
        <span className="fragment-id">{question.id}</span>
        <h3 id={`${name}-title`} className="question-text">{question.text}</h3>
        {value
          ? <span className="pill ready">{t('decisions.decided', { id: value })}</span>
          : <span className="pill open">{t('decisions.open')}</span>}
      </div>
      {choice && <p className="decision-choice">{t('decisions.yourChoice')} <strong>{choice} · {textOf(choice)}</strong></p>}
      {verdict}
      <div className="adr">
        <p className="adr-head">ADR-{n} · {t(fixed ? 'decisions.fixed' : 'decisions.draft')}</p>
        <dl className="adr-rows">
          <dt>{t('decisions.context')}</dt>
          <dd>{question.text}</dd>
          <dt>{t('decisions.decision')}</dt>
          <dd>{value ? `${value} · ${textOf(value)}` : t('decisions.waits')}</dd>
          {value && (
            <>
              <dt>{t('decisions.rationale')}</dt>
              <dd className="adr-why">
                <textarea className="idea-text" aria-label={t('decisions.rationaleField', { id: question.id })}
                          value={rationale} maxLength={2000} readOnly={busy} onChange={e => onRationale(e.target.value)} />
                <span className={byAi ? 'source-tag ai' : 'source-tag'}>{t(byAi ? 'decisions.byAi' : 'decisions.byYou')}</span>
              </dd>
            </>
          )}
          <dt>{t('decisions.consequences')}</dt>
          <dd>{checkedHere && said ? consequences(said, t) : '—'}</dd>
        </dl>
        {value && said && said.proposal !== value && <p className="option-note">{t('decisions.unchecked')}</p>}
        {value && squash(rationale) === '' && <p className="fragment-note">{t('decisions.rationaleHint')}</p>}
      </div>
      <div className="decision-pick" role="radiogroup" aria-label={t('decisions.choose')}>
        <span className="muted" aria-hidden="true">{t('decisions.choose')}</span>
        {options.map(option => (
          <button key={option.id} className="seg" role="radio" aria-checked={value === option.id} title={option.text}
                  disabled={busy} onClick={() => onPick(option.id)}>
            {option.id}
          </button>
        ))}
        <button className="seg" role="radio" aria-checked={value === null} disabled={busy} onClick={() => onPick(null)}>
          {t('decisions.keepOpen')}
        </button>
      </div>
    </section>
  )
}

/** Последствия решения по проверке совета: от каких вопросов зависит, риски, противоречия. */
function consequences(said: QuestionAnalysis, t: T): string {
  const parts = []
  if (said.depends_on.length > 0) parts.push(t('decisions.needs', { ids: said.depends_on.join(', ') }))
  if (said.risk_ids.length > 0) parts.push(t('decisions.risks', { ids: fragmentRange(said.risk_ids) }))
  parts.push(said.constraint_conflicts.length > 0
    ? t('decisions.conflicts', { ids: fragmentRange(said.constraint_conflicts) })
    : t('decisions.noConflicts'))
  return parts.join(' ')
}

/**
 * Шаг «Итоги»: совет собирает зафиксированные решения в законченные изменения системы. Итог,
 * которому не хватает решения открытого вопроса, заблокирован им, а не додуман: из него можно
 * вернуться к вопросу. Человеку здесь утверждать нечего — менять можно решения.
 */
function OutcomesStep({ council, stream, group, onChange, onBack, onQuestion, onGap }: Readonly<{
  council: Council; stream: Stream; group: Group; onChange: (council: Council) => void
  onBack: () => void; onQuestion: (question: string) => void
  /** Пробел — в вопросы: его добавляют в отбор, и цепочка ниже идёт заново. */
  onGap: (question: string) => void
}>) {
  const { t } = useTranslation()
  const run = stream.outcomes
  const retry = useAction(onChange)
  const stale = structureIsStale(council)
  const scope = stream.scope ?? []
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const found = new Map(stream.proposals?.options.flatMap(o => o.proposals).map(p => [p.id, p.text]) ?? [])
  const textOf = (id: string) => (id.startsWith('F') ? fragments.get(Number(id.slice(1)))?.text : found.get(id)) ?? id
  // Решение ADR-n — по n-му вопросу отбора: тот же номер, что у его карточки на шаге «Решения».
  const adrs = new Map(scope.flatMap((question, n) => {
    const proposal = stream.decisions?.find(d => d.question_id === question.id)?.proposal
    return proposal ? [[`ADR-${n + 1}`, { question: question.id, text: textOf(proposal) }] as const] : []
  }))
  const questions = new Map(scope.map(q => [q.id, q.text]))
  const assemble = () => void retry.go(() => startOrFollow(
    () => api.seekOutcomes(council.id, group.id), council, c => streamOf(c, group.id)?.outcomes))
  if (!stream.decisions) return null

  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t('outcomes.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('outcomes.title')}</h2>
        <p className="panel-hint">{t('outcomes.hint')}</p>
      </section>
      {!run && (
        <div>
          <p className="muted">
            {t('outcomes.notAssembled')}{' '}
            <button className="btn-link" disabled={retry.busy || stale} onClick={assemble}>{t('outcomes.assemble')}</button>
          </p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
        </div>
      )}
      {run?.state === 'running' && <p className="muted">{t('outcomes.assembling')} {t('run.note')}</p>}
      {run?.state === 'failed' && (
        <div>
          <p className="error-text" role="alert">{run.error}</p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
          <p className="fragment-note">
            {t('outcomes.failedNote')}{' '}
            <button className="btn-link" disabled={retry.busy || stale} onClick={assemble}>{t('run.retry')}</button>
          </p>
        </div>
      )}
      {run?.state === 'done' && run.outcomes.length === 0 && <p className="muted">{t('outcomes.none')}</p>}
      {run?.outcomes.map((outcome, n) => (
        <OutcomeCard key={outcome.id} outcome={outcome} n={n + 1} adrs={adrs} questions={questions}
                     fragments={fragments} onQuestion={onQuestion} onGap={onGap} />
      ))}
      {run && run.uncovered_adr_ids.length > 0 && (
        <p className="fragment-note">{t('outcomes.uncovered', { ids: run.uncovered_adr_ids.join(', ') })}</p>
      )}
      <div className="stream-actions">
        <button className="btn-link" onClick={onBack}>{t('outcomes.change')}</button>
      </div>
    </>
  )
}

/** Итог: что меняется, на каких решениях стоит, что соблюдать, когда готово — и чего не хватает. */
function OutcomeCard({ outcome, n, adrs, questions, fragments, onQuestion, onGap }: Readonly<{
  outcome: Outcome; n: number; adrs: Map<string, { question: string; text: string }>
  questions: Map<string, string>; fragments: Map<number, LabeledFragment>
  onQuestion: (question: string) => void; onGap: (question: string) => void
}>) {
  const { t } = useTranslation()
  const name = `outcome-${outcome.id}`
  const blocked = outcome.blocked_by
  let pill = <span className="pill ready">{t('outcomes.ready')}</span>
  if (blocked.length > 0) pill = <span className="pill blocked">{t('outcomes.blocked', { ids: blocked.join(', ') })}</span>
  else if (outcome.gaps.length > 0) pill = <span className="pill open">{t('outcomes.withGaps')}</span>
  else if (!outcomeReady(outcome)) pill = <span className="pill open">{t('outcomes.noCriteria')}</span>
  const limits = (ids: number[]) => (
    <ul>{ids.map(id => <li key={id}><span className="fragment-id">F{id}</span> {fragments.get(id)?.text ?? '—'}</li>)}</ul>
  )
  return (
    <section className="card panel" aria-labelledby={`${name}-title`}>
      <div className="question-head">
        <span className="fragment-id">{String(n).padStart(2, '0')}</span>
        <h3 id={`${name}-title`} className="question-text">{outcome.title}</h3>
        {pill}
      </div>
      {blocked.length > 0 && (
        <div className="check problem outcome-missing">
          <span>{t('outcomes.missing', { ids: blocked.join(', ') })}</span>
          <button className="btn-secondary" onClick={() => onQuestion(blocked[0])}>{t('outcomes.back')}</button>
        </div>
      )}
      <dl className="outcome-rows">
        <dt>{t('outcomes.changes')}</dt>
        <dd>{outcome.behavior}</dd>
        {outcome.adr_ids.length + blocked.length > 0 && (
          <>
            <dt>{t('outcomes.decisions')}</dt>
            <dd>
              <ul>
                {outcome.adr_ids.map(id => {
                  const adr = adrs.get(id)
                  return <li key={id}><span className="fragment-id">{adr?.question ?? id}</span> {adr?.text ?? id}</li>
                })}
                {blocked.map(id => (
                  <li key={id} className="outcome-open">
                    <span className="fragment-id">{id}</span> {t('outcomes.open')} — {questions.get(id) ?? id}
                  </li>
                ))}
              </ul>
            </dd>
          </>
        )}
        {outcome.constraint_ids.length > 0 && (
          <><dt>{t('outcomes.keep')}</dt><dd>{limits(outcome.constraint_ids)}</dd></>
        )}
        {outcome.risk_ids.length > 0 && <><dt>{t('outcomes.risks')}</dt><dd>{limits(outcome.risk_ids)}</dd></>}
        {outcome.acceptance_criteria.length > 0 && (
          <>
            <dt>{t('outcomes.doneWhen')}</dt>
            <dd><ul>{outcome.acceptance_criteria.map(text => <li key={text}>— {text}</li>)}</ul></dd>
          </>
        )}
        {outcome.gaps.length > 0 && (
          <>
            <dt>{t('outcomes.gaps')}</dt>
            <dd>
              <ul>{outcome.gaps.map(gap => (
                <li key={gap.question} className="outcome-gap">
                  <span>{gap.reason ? `${gap.question} — ${gap.reason}` : gap.question}</span>
                  <button className="btn-link" onClick={() => onGap(gap.question)}>{t('outcomes.toQuestions')}</button>
                </li>
              ))}</ul>
            </dd>
          </>
        )}
      </dl>
    </section>
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
