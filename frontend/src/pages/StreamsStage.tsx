import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import {
  api, ApiError, councilPath, earlierOf, groupsConfirmed, issueReady, LINKS_MAX, notesOf, outcomeReady, projectOf,
  REPOSITORIES_MAX, runningFrom, sameChoice, startOrFollow,
  streamOf, structureIsStale, type Choice, type Council, type Decision, type DesignNode, type DesignScan, type Group, type IdeaDiscovery, type Issue,
  type IssueGap, type LabeledFragment, type Model, type NotePlan, type OpenQuestion, type Outcome, type QuestionAnalysis,
  type QuestionOptions, type RepositoryScan, type ScannedRepository, type Settings, type Stream, type Structure,
} from '../api'
import { FieldList, listField } from '../components/FieldList'
import { LabelPill } from '../components/Labels'
import { modelOf } from '../components/ModelBadge'
import { Progress } from '../components/Progress'
import { CHAIN, chainLight, currentStep, exported, exportedCount, reachable, streamLight, type ChainStep } from '../light'
import { useAction } from '../useAction'

type T = TFunction

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
                     models={settings.models} repositories={settings.repositories} figma={settings.figma}
                     notes={notesOf(council, settings)} known={projectOf(council, settings)?.repositories ?? []}
                     onChange={onChange} />
}

function StreamPage({ council, structure, stream, models, repositories, figma, notes, known, onChange }: Readonly<{
  council: Council; structure: Structure; stream: Stream; models: Model[]; repositories: string | null; figma: boolean
  /** Каталог заметок — папка документации проекта совета; known — рабочие копии проекта. */
  notes: string | null; known: string[]
  onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const [chosen, setView] = useState<ChainStep>(currentStep(stream))
  // Утверждение отбора — здесь, а не в шаге: отказ (409) приносит новый поиск, шаг рисуется
  // заново, а ошибка должна остаться видна.
  const passing = useAction(onChange, 'repository.approveFailed')
  const designing = useAction(onChange, 'design.approveFailed')
  const choosing = useAction(onChange, 'questions.approveFailed')
  const picking = useAction(onChange, 'options.approveFailed')
  const fixing = useAction(onChange, 'decisions.approveFailed')
  const cutting = useAction(onChange, 'outcomes.approveFailed')
  // Открытый вопрос, к которому вернулись из итогов: шаг «Решения» прокрутит к нему.
  const [focus, setFocus] = useState<string | null>(null)
  // Черновик отбора вопросов — здесь, а не в шаге «Вопросы»: за пробелами уходят в «Итоги» и «Задачи» и
  // возвращаются, и добавленное не теряется, пока отбор не утвердили. К другому поиску вопросов — заново.
  const [kept, setDraft] = useState<ScopeDraft | null>(null)
  const draft = kept?.run === (stream.questions?.run ?? '') ? kept : draftOf(stream)
  const gaps: Gaps = {
    has: question => inDraft(draft, stream, question),
    add: question => setDraft(withQuestion(draft, stream, question)),
  }
  const pending = pendingOf(draft, stream)
  const group = structure.groups.find(g => g.id === stream.group)
  if (!group) return null  // поток без группы не бывает: состав меняют, только сняв подтверждение
  // Открыть можно пройденный шаг и текущий: дальше — нечего.
  const view = CHAIN.indexOf(chosen) <= CHAIN.indexOf(reachable(stream)) ? chosen : currentStep(stream)
  const search = stream.discovery
  const runs = { group: search, repository: stream.scan, design: stream.design_scan,
                 questions: stream.questions ?? stream.decisions_search, options: stream.proposals,
                 decisions: stream.analysis, outcomes: stream.outcomes, issues: stream.issues, notes: stream.notes_draft }
  const run = runs[view]
  const open = (step: ChainStep) => {
    setFocus(null)
    setView(step)
  }

  return (
    <div className="streams-layout">
      <aside className="streams-nav">
        <StreamList council={council} structure={structure} open={stream.group} notes={notes} />
        <Chain stream={stream} group={group} view={view} onView={open} notes={notes} />
      </aside>
      <div className="streams-main">
        <Now stream={stream} group={group} notes={notes} />
        {(view === 'outcomes' || view === 'issues') && pending > 0 && (
          <section className="card panel pending-questions" aria-label={t('gaps.title')}>
            <p className="pending-text">{t('gaps.pending', { count: pending })}</p>
            <button className="btn-primary" onClick={() => open('questions')}>{t('gaps.toQuestions')}</button>
          </section>
        )}
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
          // Новый скан или другие рабочие копии проекта (поправили в другой вкладке) — отметки и пути заново.
          <RepositoryStep key={JSON.stringify([stream.scan?.run ?? '', known])} council={council} structure={structure}
                          stream={stream}
                          group={group} repositories={repositories} known={known} onChange={onChange} approve={passing}
                          onApproved={() => open('design')} />
        )}
        {view === 'design' && (
          // Новый скан — и ссылки заново, из него.
          <DesignStep key={stream.design_scan?.run ?? ''} council={council} structure={structure} stream={stream}
                      group={group} figma={figma} onChange={onChange} approve={designing}
                      onApproved={() => open('questions')} />
        )}
        {view === 'questions' && (
          // Новый поиск вопросов — и отбор заново, к его вопросам.
          <QuestionsStep key={stream.questions?.run ?? ''} council={council} structure={structure}
                         stream={stream} group={group} notes={notes} onChange={onChange} approve={choosing}
                         draft={draft} onDraft={setDraft}
                         onBack={() => open('group')} onApproved={() => { setDraft(null); open('options') }} />
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
          <OutcomesStep council={council} structure={structure} stream={stream} group={group} onChange={onChange}
                        approve={cutting} onBack={() => open('decisions')} onApproved={() => open('issues')}
                        onQuestion={question => { setFocus(question); setView('decisions') }} gaps={gaps} />
        )}
        {view === 'notes' && (
          // Новый черновик — и правки заново, к его заметкам.
          <NotesStep key={stream.notes_draft?.run ?? ''} council={council} structure={structure} stream={stream}
                     group={group} root={notes} onChange={onChange} />
        )}
        {view === 'issues' && (
          <IssuesStep council={council} stream={stream} group={group} notes={notes} onChange={onChange}
                      onBack={() => open('outcomes')} onNext={() => open('notes')}
                      onQuestion={question => { setFocus(question); setView('decisions') }} gaps={gaps} />
        )}
      </div>
      <aside className="streams-side">
        {run && run.steps.length > 0 && <Progress steps={run.steps} models={models} />}
      </aside>
    </div>
  )
}

function StreamList({ council, structure, open, notes }: Readonly<{
  council: Council; structure: Structure; open: string; notes: string | null
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
                  <span className={`light-dot ${streamLight(stream, notes)}`} aria-hidden="true" />{whereIs(stream, notes, t)}
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
function whereIs(stream: Stream, notes: string | null, t: T): string {
  const step = currentStep(stream)
  const run = { group: stream.discovery, repository: stream.scan, design: stream.design_scan,
                questions: stream.questions ?? stream.decisions_search, options: stream.proposals,
                decisions: stream.analysis, outcomes: stream.outcomes, issues: stream.issues,
                notes: stream.notes_draft }[step]
  if (run?.state === 'running') return t(`streams.${step}.seeking`)
  if (run?.state === 'failed') return t(`streams.${step}.failed`)
  if (step === 'notes' && streamLight(stream, notes) === 'done') return t('streams.notes.done')
  return t(`streams.${step}.yours`)
}

/** «Сейчас»: где поток и чей ход — и вся его цепочка сегментами в цветах светофора. */
function Now({ stream, group, notes }: Readonly<{ stream: Stream; group: Group; notes: string | null }>) {
  const { t } = useTranslation()
  const light = streamLight(stream, notes)
  return (
    <section className="now" aria-labelledby="now-title">
      <p className={`now-caps ${light}`}>{t('now.caps', { group: stream.group, state: t(`now.${light}`) })}</p>
      <h2 id="now-title" className="now-title">{group.title}</h2>
      <ol className="segments">
        {CHAIN.map(step => {
          const state = chainLight(stream, step, notes)
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
              {step === 'design' && stream.repository && (
                <span className="segment-sub">{designStatus(stream, t)}</span>
              )}
              {step === 'questions' && stream.design && (
                <span className="segment-sub">{questionsStatus(stream, t)}</span>
              )}
              {step === 'options' && stream.scope && <span className="segment-sub">{optionsStatus(stream, t)}</span>}
              {step === 'decisions' && stream.choices && (
                <span className="segment-sub">{decisionsStatus(stream, t)}</span>
              )}
              {step === 'outcomes' && stream.decisions && (
                <span className="segment-sub">{outcomesStatus(stream, t)}</span>
              )}
              {step === 'issues' && stream.issues && <span className="segment-sub">{issuesStatus(stream, t)}</span>}
              {step === 'notes' && stream.issues?.state === 'done' && <span className="segment-sub">{notesStatus(stream, notes, t)}</span>}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

/** Цепочка шагов потока: пройденные и текущий открываются, дальше — что будет. */
function Chain({ stream, group, view, onView, notes }: Readonly<{
  stream: Stream; group: Group; view: ChainStep; onView: (step: ChainStep) => void; notes: string | null
}>) {
  const { t } = useTranslation()
  const reached = CHAIN.indexOf(currentStep(stream))
  const open = CHAIN.indexOf(reachable(stream))
  const status = (step: ChainStep, i: number) => {
    if (step === 'group') return groupStatus(stream, group, t)
    if (step === 'repository' && stream.idea) return repositoryStatus(stream, t)
    if (step === 'design' && stream.repository) return designStatus(stream, t)
    if (step === 'questions' && stream.design) return questionsStatus(stream, t)
    if (step === 'options' && stream.scope) return optionsStatus(stream, t)
    if (step === 'decisions' && stream.choices) return decisionsStatus(stream, t)
    if (step === 'outcomes' && stream.decisions) return outcomesStatus(stream, t)
    if (step === 'issues' && stream.issues) return issuesStatus(stream, t)
    if (step === 'notes' && stream.issues?.state === 'done') return notesStatus(stream, notes, t)
    return t(i === reached ? 'chain.soon' : 'chain.notStarted')
  }
  return (
    <section className="card panel chain" aria-labelledby="chain-title">
      <h2 id="chain-title" className="panel-title caps">
        {t('chain.title')} <span className="chain-of">{t('chain.of', { group: stream.group })}</span>
      </h2>
      <ol className="chain-steps">
        {CHAIN.map((step, i) => {
          const light = chainLight(stream, step, notes)
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
                {step !== 'issues' && (
                  <span className="chain-role"><span className="role-tag">{t('chain.you')}</span>{t(`chain.${step}.you`)}</span>
                )}
              </span>
            </>
          )
          const className = `chain-step ${i < reached ? 'done' : state}${view === step ? ' open' : ''}`
          return (
            <li key={step}>
              {i <= open
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
function issuesStatus(stream: Stream, t: T): string {
  const run = stream.issues
  if (run?.state === 'running') return t('chain.issuesCutting')
  if (run?.state === 'failed') return t('chain.issuesFailed')
  if (!run) return t('chain.notStarted')
  const total = run.issues.length
  if (total === 0) return t('chain.issuesEmpty')
  const blocked = run.issues.filter(issue => !issueReady(issue)).length
  if (blocked > 0) return t('chain.issuesBlocked', { count: blocked, total })
  if (run.gaps.length > 0) return t('chain.issuesGaps', { count: run.gaps.length })
  if (run.uncovered_outcome_ids.length > 0) return t('chain.issuesUncovered', { ids: run.uncovered_outcome_ids.join(', ') })
  const lost = stream.outcomes?.uncovered_adr_ids ?? []
  if (lost.length > 0) return t('chain.issuesLost', { ids: lost.join(', ') })
  const vague = (stream.outcomes?.outcomes ?? []).filter(o => o.acceptance_criteria.length === 0).map(o => o.id)
  if (vague.length > 0) return t('chain.issuesVague', { ids: vague.join(', ') })
  return t('chain.issuesReady', { count: total, total })
}

function outcomesStatus(stream: Stream, t: T): string {
  const run = stream.outcomes
  if (run?.state === 'running') return t('chain.outcomesAssembling')
  if (run?.state === 'failed') return t('chain.outcomesFailed')
  if (!run) return t('chain.outcomesNone')
  if (stream.issues) return t('chain.outcomesApproved')
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

/** Что с шагом «Дизайн»: пройден (с описанием или без), скан идёт, упал, готов или его не было. */
function designStatus(stream: Stream, t: T): string {
  const scan = stream.design_scan
  if (stream.design) return t(stream.design.by === 'scan' ? 'chain.designTaken' : 'chain.designSkipped')
  if (scan?.state === 'running') return t('chain.designScanning')
  if (scan?.state === 'failed') return t('chain.designFailed')
  if (scan) return t('chain.designScanned')
  return t('chain.designNone')
}

/** Что с документацией потока: черновик переводится, перевод упал, выгружена, черновик ждёт или не собирали. */
function notesStatus(stream: Stream, notes: string | null, t: T): string {
  const draft = stream.notes_draft
  if (draft?.state === 'running') return t('chain.notesTranslating')
  if (draft?.state === 'failed') return t('chain.notesFailed')
  if (exported(stream, notes)) return t('chain.notesWritten', { count: exportedCount(stream) })
  if (stream.notes) return t(stream.notes.root === notes ? 'chain.notesOutdated' : 'chain.notesElsewhere')
  if (draft) return t('chain.notesDrafted')
  return t('chain.notesNone')
}

/** Что с вопросами потока: решения проекта отбираются или ждут, вопросы ищутся, упали, найдены, отобраны. */
function questionsStatus(stream: Stream, t: T): string {
  const search = stream.questions
  if (stream.scope) return t('chain.questionsChosen', { count: stream.scope.length })
  const decisions = stream.decisions_search
  if (!search && decisions?.state === 'running') return t('chain.projectSearching')
  if (!search && decisions?.state === 'failed') return t('chain.projectFailed')
  if (!search && decisions) return t('chain.projectWait')
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
  const asking = runningFrom(stream, 'scan')
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
 * Рабочие копии проекта (known) уже отмечены — лишние для этой идеи снимают; свои добавляют путём.
 */
function RepositoryStep({ council, structure, stream, group, repositories, known, onChange, approve, onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group; repositories: string | null; known: string[]
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const scan = stream.scan
  // Был скан — отмечено то, что сканировали; нет — все рабочие копии проекта.
  const scanned = scan?.repositories.map(r => r.path) ?? []
  const [picked, setPicked] = useState(() => new Set(scanned.length ? known.filter(path => scanned.includes(path)) : known))
  const [paths, setPaths] = useState(() => {
    const own = scanned.filter(path => !known.includes(path))
    return own.length || known.length ? own.map(path => listField(path)) : [listField()]
  })
  const ticked = known.filter(path => picked.has(path))
  const chosen = [...ticked, ...paths.map(f => f.value)]
  const toggle = (path: string) => setPicked(before => {
    const next = new Set(before)
    if (!next.delete(path)) next.add(path)
    return next
  })
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = scan?.state === 'running'
  const stale = structureIsStale(council)
  // Пока ИИ работает ниже по цепочке, шаг не поменять: сервер ответит 423.
  const below = runningFrom(stream, 'decisions_search')
  const idea = stream.idea
  if (!idea) return null
  const at = { run: structure.run, revision: structure.revision }

  const start = (event: FormEvent) => {
    event.preventDefault()
    void retry.go(async () => {
      try {
        return await startOrFollow(() => api.scanRepository(council.id, at, group.id, chosen, idea.text), council,
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
  const placeholder = repositories ? t('repository.pathRoot', { root: repositories }) : t('repository.pathAbsolute')
  // Пока сканируется макет, шаг «Репозиторий» иначе не пройти: сервер ответит 423.
  const held = below || stream.design_scan?.state === 'running'

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
          {known.length > 0 && (
            <fieldset className="repo-known">
              <legend className="select-label">{t('repository.known')}</legend>
              {known.map(path => (
                <label key={path} className="decision-pick">
                  <input type="checkbox" checked={picked.has(path)} disabled={busy || sought}
                         onChange={() => toggle(path)} />
                  <span className="repo-known-path">{path}</span>
                </label>
              ))}
            </fieldset>
          )}
          <FieldList fields={paths} onFields={setPaths} max={REPOSITORIES_MAX - ticked.length} min={known.length ? 0 : 1}
                     locked={busy || sought} placeholder={placeholder} addLabel={t('repository.addPath')}
                     label={n => paths.length > 1 || known.length ? t('repository.pathN', { n }) : t('repository.path')}
                     removeLabel={n => t('repository.removePath', { n })} />
          <button type="submit" className="btn-secondary"
                  disabled={busy || sought || below || stale || chosen.length === 0 || chosen.length > REPOSITORIES_MAX
                            || paths.some(f => f.value.trim() === '')}>
            {t('repository.scan')}
          </button>
        </form>
        {known.length > 0 && <p className="fragment-note">{t('repository.knownNote')}</p>}
        {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
        {(stream.design || stream.questions) && !sought && <p className="fragment-note">{t('repository.rescanNote')}</p>}
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
        {held && <p className="fragment-note">{t('repository.belowRunning')}</p>}
        <div className="stream-actions spread">
          <button className="btn-secondary" disabled={busy || sought || held || stale} onClick={() => pass(null)}>
            {t('repository.skip')}
          </button>
          {ready && (
            <button className="btn-primary large" disabled={busy || held || stale} onClick={() => pass(scan.run)}>
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

/** Коммит коротко; нет коммитов — прочерк. */
const shortSha = (sha: string) => sha.slice(0, 8) || '—'

/**
 * Рабочая копия скана: путь, коммит, сколько файлов и чего модели не видели. У нескольких — и её папка в
 * карте (пути находок начинаются с неё), а замечания — с её путём.
 */
function ScannedSource({ source, several }: Readonly<{ source: ScannedRepository; several: boolean }>) {
  const { t } = useTranslation()
  const of = several ? `${source.path}: ` : ''
  return (
    <>
      <p className="repo-summary">
        {t('repository.summary', { path: source.path, sha: shortSha(source.commit_sha), files: source.files })}
        {several && ` · ${t('repository.folder', { folder: source.name })}`}
      </p>
      {source.dirty && <p className="fragment-note">{of}{t('repository.dirty')}</p>}
      {source.outside > 0 && <p className="fragment-note">{of}{t('repository.outside', { count: source.outside })}</p>}
      {source.omitted_count > 0 && <p className="fragment-note">{of}{t('repository.omitted', {
        count: source.omitted_count,
        items: source.omitted.join('; ') + (source.omitted_count > source.omitted.length ? '; …' : '') })}</p>}
    </>
  )
}

/** Карта скана: находки с подтверждениями, как идёт выполнение, покрытие, неизвестное и расхождения. */
function RepositoryMapView({ scan }: Readonly<{ scan: RepositoryScan }>) {
  const { t } = useTranslation()
  const result = scan.result
  if (!result) return null
  const several = scan.repositories.length > 1
  return (
    <>
      {scan.repositories.map(source => (
        <ScannedSource key={source.name || source.path} source={source} several={several} />
      ))}
      <p className="repo-summary">{t('repository.rounds', { rounds: scan.rounds })}</p>
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
 * Шаг «Дизайн» — необязательный, после «Репозитория». Совет снимает макет Figma по ссылкам — страницы
 * со структурой и картинками фреймов, с одной версии файла, — участники и судья исследуют снимок и
 * описывают, какой интерфейс и какое поведение предусмотрены. Человек утверждает описание или
 * пропускает шаг — и совет сразу ищет вопросы; описание идёт во все следующие шаги.
 */
function DesignStep({ council, structure, stream, group, figma, onChange, approve, onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group; figma: boolean
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const scan = stream.design_scan
  const [links, setLinks] = useState(() => scan?.links.length ? scan.links.map(listField) : [listField()])
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = scan?.state === 'running'
  const stale = structureIsStale(council)
  // Пока ИИ работает ниже по цепочке, шаг не поменять: сервер ответит 423.
  const below = runningFrom(stream, 'decisions_search')
  const idea = stream.idea
  if (!idea) return null
  const at = { run: structure.run, revision: structure.revision }

  const start = (event: FormEvent) => {
    event.preventDefault()
    void retry.go(async () => {
      try {
        return await startOrFollow(() => api.scanDesign(council.id, at, group.id, links.map(f => f.value), idea.text),
                                   council, c => streamOf(c, group.id)?.design_scan)
      } catch (e) {
        // Идею поменяли в другой вкладке — показываем нынешнюю: скан пойдёт уже к ней.
        if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
        throw e
      }
    })
  }
  const pass = (scanRun: string | null) => void approve.go(async () => {
    try {
      return await api.approveDesign(council.id, at, group.id, scanRun, idea.text)
    } catch (e) {
      // Группы уже другие или скан уже другой (другая вкладка) — показываем нынешнее.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, onApproved)
  const taken = stream.design
  const ready = scan?.state === 'done' && scan.result !== null
  const round = Math.min((scan?.rounds ?? 0) + 1, 3)

  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t(sought ? 'design.capsAi' : 'design.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('design.title')}</h2>
        <p className="panel-hint">{t('design.hint')}</p>
        <p className="fragment-note">{t('design.trust')}</p>
      </section>
      <p className="options-idea"><span className="fragment-id">I1</span> {idea.text}</p>
      <section className="card panel" aria-label={t('design.title')}>
        {!figma && <p className="fragment-note">{t('design.noToken')}</p>}
        <form className="repo-scan" onSubmit={start}>
          <FieldList fields={links} onFields={setLinks} max={LINKS_MAX} locked={busy || sought}
                     placeholder={t('design.linkPlaceholder')} addLabel={t('design.addLink')}
                     label={n => links.length > 1 ? t('design.linkN', { n }) : t('design.link')}
                     removeLabel={n => t('design.removeLink', { n })} />
          <button type="submit" className="btn-secondary"
                  disabled={!figma || busy || sought || below || stale || links.some(f => f.value.trim() === '')}>
            {t('design.scan')}
          </button>
        </form>
        <p className="fragment-note">{t('design.linksNote')}</p>
        {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
        {stream.questions && !sought && <p className="fragment-note">{t('design.rescanNote')}</p>}
        {sought && (
          <p className="muted">{scan.source ? t('design.scanning', { round }) : t('design.fetching')} {t('run.note')}</p>
        )}
        {scan?.state === 'failed' && (
          <>
            <p className="error-text" role="alert">{scan.error}</p>
            <p className="fragment-note">{t('design.failedNote')}</p>
          </>
        )}
        {scan?.result && <DesignMapView scan={scan} />}
        {taken && <p className="fragment-note">{t(taken.by === 'scan' ? 'design.taken' : 'design.skipped')}</p>}
        {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
        {below && <p className="fragment-note">{t('design.belowRunning')}</p>}
        <div className="stream-actions spread">
          <button className="btn-secondary" disabled={busy || sought || below || stale} onClick={() => pass(null)}>
            {t('design.skip')}
          </button>
          {ready && (
            <button className="btn-primary large" disabled={busy || below || stale} onClick={() => pass(scan.run)}>
              {t('design.approve')}
            </button>
          )}
        </div>
      </section>
    </>
  )
}

/** Узел макета, как его видит человек: имя и номер. */
const nodeLabel = (node: DesignNode) => [node.name, node.node_id || node.page_id].filter(Boolean).join(' · ')

/** Описание макета: какой файл, находки, экраны, сценарии, покрытие, неизвестное и противоречия. */
function DesignMapView({ scan }: Readonly<{ scan: DesignScan }>) {
  const { t } = useTranslation()
  const result = scan.result
  if (!result) return null
  const source = scan.source
  return (
    <>
      {source && (
        <p className="repo-summary">
          {t('design.source', { name: source.name, version: source.version, pages: source.pages, images: source.images })}
        </p>
      )}
      {source && source.requested.length > 0 && (
        <p className="repo-summary">{t('design.requested', { nodes: source.requested.map(nodeLabel).join(', ') })}</p>
      )}
      <p className="repo-summary">{t('design.rounds', { rounds: scan.rounds })}</p>
      {scan.state === 'done' && scan.complete && <p className="check ok">{t('design.complete')}</p>}
      {scan.state === 'done' && !scan.complete && (
        <div className="check problem">
          <p>{t('design.incomplete')}</p>
          <ul>{scan.follow_up.map(item => (
            <li key={item.objective}>
              {item.targets.length > 0 ? `${item.objective} — ${item.targets.map(nodeLabel).join(', ')}` : item.objective}
            </li>
          ))}</ul>
        </div>
      )}
      {result.findings.length === 0 && <p className="muted">{t('design.empty')}</p>}
      <dl className="outcome-rows">
        {result.findings.length > 0 && (
          <>
            <dt>{t('design.findings')}</dt>
            <dd>
              <ul className="repo-list">{result.findings.map(finding => (
                <li key={finding.id} className="repo-finding">
                  <span className="repo-finding-head">
                    <span className="fragment-id">{finding.id}</span>
                    <span className={FINDING_PILL[finding.status]}>{t(`repository.status.${finding.status}`)}</span>
                    <span className="repo-statement">{finding.statement}</span>
                  </span>
                  {finding.evidence.length > 0 && (
                    <span className="repo-evidence">{finding.evidence.map(nodeLabel).join('; ')}</span>
                  )}
                  {finding.relevance && <span className="option-note">{finding.relevance}</span>}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.screens.length > 0 && (
          <>
            <dt>{t('design.screens')}</dt>
            <dd>
              <ul className="repo-list">{result.screens.map(screen => (
                <li key={`${screen.name}:${screen.node_id}`} className="repo-finding">
                  <span className="repo-finding-head">
                    <strong>{screen.name}</strong>
                    {screen.node_id && <span className="repo-evidence">{screen.node_id}</span>}
                  </span>
                  {screen.purpose && <span>{screen.purpose}</span>}
                  {screen.data.length > 0 && (
                    <span className="option-note">{t('design.data', { items: screen.data.join(', ') })}</span>
                  )}
                  {screen.actions.length > 0 && (
                    <ul className="repo-steps">{screen.actions.map(action => (
                      <li key={action.action}>
                        <span className={FINDING_PILL[action.status]}>{t(`repository.status.${action.status}`)}</span>{' '}
                        {t('design.action', { action: action.action, result: action.result ?? t('design.noResult') })}
                      </li>
                    ))}</ul>
                  )}
                  {screen.states.length > 0 && (
                    <span className="option-note">
                      {t('design.states', { items: screen.states.map(state => state.name).join(', ') })}
                    </span>
                  )}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.flows.length > 0 && (
          <>
            <dt>{t('design.flows')}</dt>
            <dd>
              <ul className="repo-list">{result.flows.map(flow => (
                <li key={flow.name}>
                  <span className="repo-finding-head">
                    <strong>{flow.name}</strong>
                    <span className={FINDING_PILL[flow.status]}>{t(`repository.status.${flow.status}`)}</span>
                  </span>
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
            <dt>{t('design.coverage')}</dt>
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
            <dt>{t('design.unknowns')}</dt>
            <dd>
              <ul className="repo-list">{result.unknowns.map(unknown => (
                <li key={unknown.question} className="repo-finding">
                  <span>{unknown.reason ? `${unknown.question} — ${unknown.reason}` : unknown.question}</span>
                  {unknown.investigate.length > 0 && (
                    <span className="option-note">
                      {t('repository.investigate', { targets: unknown.investigate.map(nodeLabel).join(', ') })}
                    </span>
                  )}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.design_conflicts.length > 0 && (
          <>
            <dt>{t('design.conflicts')}</dt>
            <dd><ul className="repo-list">{result.design_conflicts.map(text => <li key={text}>{text}</li>)}</ul></dd>
          </>
        )}
      </dl>
    </>
  )
}

const RELEVANCE_PILL = { applicable: 'pill ready', potential_conflict: 'pill blocked', uncertain: 'pill open' } as const

/**
 * Блок «Решения проекта» в начале шага «Вопросы»: совет отобрал прошлые решения из каталога заметок, что
 * относятся к идее, — человек отмечает, какие учитывать, и совет ищет вопросы с ними. Решения соседних
 * потоков попадают в каталог, только когда поток выгружен: какие не выгружены — видно здесь.
 */
function ProjectDecisions({ council, structure, stream, group, notes, onChange }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group; notes: string | null
  onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const search = stream.decisions_search
  const chosen = stream.project_decisions
  const [keep, setKeep] = useState<ReadonlySet<string>>(() => new Set(chosen
    ? chosen.map(d => d.adr_id)
    : (search?.decisions ?? []).filter(d => d.relevance !== 'uncertain').map(d => d.adr_id)))
  const [editing, setEditing] = useState(chosen === null)
  const act = useAction(onChange, 'project.selectFailed')
  const idea = stream.idea
  if (!search || !idea) return null
  const at = { run: structure.run, revision: structure.revision }
  const sought = search.state === 'running'
  // Пока ИИ работает с вопросами или ниже, отбор не поменять: сервер ответит 423.
  const below = runningFrom(stream, 'questions')
  const locked = act.busy || sought || below || structureIsStale(council)
  const unexported = (council.streams ?? [])
    .filter(other => other.group !== stream.group && other.decisions && !exported(other, notes)).map(other => other.group)
  const toggle = (id: string) => setKeep(before => {
    const next = new Set(before)
    if (!next.delete(id)) next.add(id)
    return next
  })
  const submit = (ids: string[]) => void act.go(async () => {
    try {
      return await api.selectDecisions(council.id, at, group.id, search.run, ids, idea.text)
    } catch (e) {
      // Отбор уже другой или идею поменяли (другая вкладка) — показываем нынешнее.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, () => setEditing(false))
  const retry = () => void act.go(() => startOrFollow(
    () => api.searchDecisions(council.id, group.id), council, c => streamOf(c, group.id)?.decisions_search))

  return (
    <section className="card panel" aria-labelledby="project-title">
      <h3 id="project-title" className="panel-title">{t('project.title')}</h3>
      {!editing && chosen ? (
        <>
          <p className="muted">
            {chosen.length > 0 ? t('project.taken', { ids: chosen.map(d => d.adr_id).join(', ') }) : t('project.none')}
          </p>
          <div className="stream-actions">
            <button className="btn-link" disabled={locked} onClick={() => setEditing(true)}>{t('project.change')}</button>
          </div>
        </>
      ) : (
        <>
          <p className="panel-hint">{t('project.hint')}</p>
          {unexported.length > 0 && <p className="fragment-note">{t('project.unexported', { groups: unexported.join(', ') })}</p>}
          {sought && <p className="muted">{t('project.searching')} {t('run.note')}</p>}
          {search.state === 'failed' && (
            <>
              <p className="error-text" role="alert">{search.error}</p>
              <p className="fragment-note">
                {t('project.failedNote')}{' '}
                <button className="btn-link" disabled={locked} onClick={retry}>{t('run.retry')}</button>
              </p>
            </>
          )}
          {search.state === 'done' && (
            <>
              <p className="repo-summary">{t('project.catalog', { count: search.catalog, traced: search.traced })}</p>
              {search.decisions.length === 0 && <p className="muted">{t('project.empty')}</p>}
              <ul className="repo-list">{search.decisions.map(decision => (
                <li key={decision.adr_id} className="repo-finding">
                  <label className="decision-pick">
                    <input type="checkbox" checked={keep.has(decision.adr_id)} disabled={locked}
                           onChange={() => toggle(decision.adr_id)} />
                    <span className="fragment-id">{decision.adr_id}</span>
                    {decision.relevance && (
                      <span className={RELEVANCE_PILL[decision.relevance]}>{t(`project.relevance.${decision.relevance}`)}</span>
                    )}
                    <span className="repo-statement">{decision.decision}</span>
                  </label>
                  {decision.question && <span className="option-note">{t('project.question', { question: decision.question })}</span>}
                  {decision.reason && <span className="option-note">{decision.reason}</span>}
                  {decision.found_in_code.length > 0 && (
                    <span className="repo-evidence">{t('project.trail', {
                      items: decision.found_in_code.map(trail => `${trail.issue} · ${trail.file} · ${trail.commit}`).join('; ') })}</span>
                  )}
                  {decision.status !== 'active' && <span className="option-note">{t(`project.status.${decision.status}`)}</span>}
                </li>
              ))}</ul>
            </>
          )}
          {stream.questions && <p className="fragment-note">{t('project.changeNote')}</p>}
          {act.error && <p className="error-text" role="alert">{act.error}</p>}
          <div className="stream-actions spread">
            <button className="btn-secondary" disabled={locked} onClick={() => submit([])}>{t('project.skip')}</button>
            {search.state === 'done' && search.decisions.length > 0 && (
              <button className="btn-primary" disabled={locked} onClick={() => submit([...keep])}>{t('project.approve')}</button>
            )}
          </div>
        </>
      )}
    </section>
  )
}

const ACTION_PILL = { create: 'pill ready', update: 'pill open', same: 'pill', edited: 'pill blocked' } as const
const NOTE_TYPES = ['idea', 'open_question', 'proposal', 'adr', 'outcome'] as const

/**
 * Шаг «Документация» — после задач. Совет собирает черновик выгрузки потока в заметки проекта (IDEA,
 * вопросы, варианты, решения, итоги — файлом на заметку, в формате Causa): номера, тексты и что с каждой
 * будет. Человек правит тексты, отмечает исчезнувшие к удалению и записывает. Файл, правленный руками после
 * прошлой выгрузки, совет не трогает.
 */
function NotesStep({ council, structure, stream, group, root, onChange }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group; root: string | null
  onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const draft = stream.notes_draft
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [remove, setRemove] = useState<ReadonlySet<string>>(new Set())
  // Сборка и запись — порознь: отказ сборки виден и там, где черновика ещё нет.
  const drafting = useAction(onChange, 'notes.draftFailed')
  const act = useAction(onChange, 'notes.writeFailed')
  const at = { run: structure.run, revision: structure.revision }
  const building = draft?.state === 'running'
  const stale = !!draft && stream.issues?.run !== draft.issues
  // Проект совета или его папку сменили после сборки: черновик — к прежней папке.
  const moved = !!draft && draft.state === 'done' && !!root && draft.root !== root
  const ready = draft?.state === 'done' && !stale && !moved
  const written = !!draft && stream.notes?.run === draft.run && exported(stream, root)
  // Записанное — с правками человека: они есть только в выгрузке, черновик их не знает.
  const wrote = new Map(written ? stream.notes?.notes.map(note => [note.key, note.written]) : [])
  const shown = (note: NotePlan) => wrote.get(note.key) ?? edits[note.key] ?? note.text
  const locked = act.busy || drafting.busy || building || structureIsStale(council)
  const build = () => void drafting.go(() => startOrFollow(
    () => api.draftNotes(council.id, at, group.id), council, c => streamOf(c, group.id)?.notes_draft))
  const write = () => void act.go(async () => {
    if (!draft) return council
    const changed = Object.fromEntries(draft.notes.filter(note => edits[note.key] !== undefined
      && edits[note.key] !== note.text).map(note => [note.key, edits[note.key]]))
    try {
      return await api.writeNotes(council.id, at, group.id, draft.run, changed, [...remove])
    } catch (e) {
      // Черновик устарел или каталог поменялся — показываем нынешнее.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  })

  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t(building ? 'notes.capsAi' : 'notes.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('notes.title')}</h2>
        <p className="panel-hint">{t('notes.hint')}</p>
      </section>
      <section className="card panel" aria-label={t('notes.title')}>
        {root ? <p className="repo-summary">{t('notes.where', { root })}</p> : <p className="fragment-note">{t('notes.noRoot')}</p>}
        {stream.notes && (
          <p className={exported(stream, root) ? 'check ok' : 'fragment-note'}>
            {t(exported(stream, root) ? 'notes.written' : stream.notes.root === root ? 'notes.outdated' : 'notes.elsewhere',
               { count: exportedCount(stream), root: stream.notes.root })}
          </p>
        )}
        <div className="stream-actions">
          <button className="btn-secondary" disabled={!root || locked} onClick={build}>
            {t(draft ? 'notes.rebuild' : 'notes.build')}
          </button>
        </div>
        {drafting.error && <p className="error-text" role="alert">{drafting.error}</p>}
        {building && <p className="muted">{t('notes.translating', { language: draft.language })} {t('run.note')}</p>}
        {draft?.state === 'failed' && <p className="error-text" role="alert">{draft.error}</p>}
        {stale && <p className="fragment-note">{t('notes.stale')}</p>}
        {moved && !stale && <p className="fragment-note">{t('notes.moved')}</p>}
        {ready && (
          <>
            <p className="repo-summary">{t('notes.language', { language: draft.language })}</p>
            {draft.skipped.map(reason => <p key={reason} className="fragment-note">{reason}</p>)}
            {NOTE_TYPES.map(type => {
              const notes = draft.notes.filter(note => note.type === type)
              if (notes.length === 0) return null
              return (
                <div key={type}>
                  <h3 className="panel-title caps notes-type">{t(`notes.type.${type}`)}</h3>
                  <ul className="repo-list">{notes.map(note => (
                    <li key={note.key} className="note-plan">
                      <span className="repo-finding-head">
                        <span className="fragment-id">{note.id}</span>
                        <span className={ACTION_PILL[note.action]}>{t(`notes.action.${note.action}`)}</span>
                        {note.links.length > 0 && <span className="repo-evidence">→ {note.links.join(', ')}</span>}
                      </span>
                      {note.action === 'edited' ? (
                        <>
                          <span className="fragment-note">{t('notes.editedNote')}</span>
                          <span className="note-current">{note.current}</span>
                        </>
                      ) : (
                        <textarea className="text-field note-text" aria-label={t('notes.text', { id: note.id })}
                                  value={shown(note)} readOnly={locked || written}
                                  rows={Math.min(8, shown(note).split('\n').length + 1)}
                                  onChange={e => {
                                    const value = e.target.value
                                    setEdits(before => ({ ...before, [note.key]: value }))
                                  }} />
                      )}
                      {note.action === 'update' && note.current && (
                        <details className="question-proposals">
                          <summary>{t('notes.current')}</summary>
                          <span className="note-current">{note.current}</span>
                        </details>
                      )}
                    </li>
                  ))}</ul>
                </div>
              )
            })}
            {draft.vanished.length > 0 && (
              <div>
                <h3 className="panel-title caps notes-type">{t('notes.vanished')}</h3>
                <ul className="repo-list">{draft.vanished.map(note => (
                  <li key={note.id} className="repo-finding">
                    <label className="decision-pick">
                      <input type="checkbox" checked={remove.has(note.id)} disabled={locked || written || note.linked_from.length > 0}
                             onChange={() => setRemove(before => {
                               const next = new Set(before)
                               if (!next.delete(note.id)) next.add(note.id)
                               return next
                             })} />
                      <span className="fragment-id">{note.id}</span>
                      <span className="repo-statement">{note.text}</span>
                    </label>
                    {note.linked_from.length > 0 && (
                      <span className="option-note">{t('notes.linkedFrom', { ids: note.linked_from.join(', ') })}</span>
                    )}
                  </li>
                ))}</ul>
              </div>
            )}
            {draft.numbers.length > 0 && (
              <div>
                <h3 className="panel-title caps notes-type">{t('notes.issues')}</h3>
                <ul className="repo-list">{draft.numbers.map(number => (
                  <li key={number.key}><span className="fragment-id">{number.id}</span> {number.issue_id} · {number.title}</li>
                ))}</ul>
              </div>
            )}
            {act.error && <p className="error-text" role="alert">{act.error}</p>}
            <div className="stream-actions spread">
              <span className="muted">{t('notes.count', { count: draft.notes.length })}</span>
              <button className="btn-primary large" disabled={locked || written || !root} onClick={write}>
                {t(written ? 'notes.done' : 'notes.write')}
              </button>
            </div>
          </>
        )}
      </section>
    </>
  )
}

/**
 * Шаг «Вопросы»: совет ищет открытые вопросы к утверждённой идее, а человек оставляет нужные,
 * убирает лишние, добавляет свои и утверждает, какие вопросы потоку решать. Ответы здесь не
 * выбирают. Черновик отбора — к нынешнему поиску; утверждённый отбор — его начало.
 */
function QuestionsStep({ council, structure, stream, group, notes, onChange, approve, draft: scopeDraft, onDraft, onBack,
  onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group; notes: string | null
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>
  /** Черновик отбора — что убрано из найденных и какие свои добавлены (и пробелы из итогов): он живёт на странице потока. */
  draft: ScopeDraft; onDraft: (draft: ScopeDraft) => void
  onBack: () => void; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const search = stream.questions
  const found = search?.questions ?? []
  const removed = new Set(scopeDraft.removed)
  const added = scopeDraft.added
  const setRemoved = (next: ReadonlySet<string>) => onDraft({ ...scopeDraft, removed: [...next] })
  const setAdded = (next: string[]) => onDraft({ ...scopeDraft, added: next })
  // Своих вопросов, которых ещё нет в утверждённом отборе: по ним — варианты, выбор и решения, по остальным всё на месте.
  const fresh = stream.scope ? added.filter(text => !stream.scope?.some(q => sameQuestion(q.text) === sameQuestion(text))) : []
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
  const offering = runningFrom(stream, 'proposals')
  const canApprove = !locked && !offering && search !== null && chosen > 0 && !structureIsStale(council)
  const idea = stream.idea
  if (!idea) return null

  const toggle = (id: string) => {
    const next = new Set(removed)
    if (!next.delete(id)) next.add(id)
    setRemoved(next)
  }
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
  const seek = () => void retry.go(async () => {
    try {
      return await startOrFollow(
        () => api.seekQuestions(council.id, group.id), council, c => streamOf(c, group.id)?.questions)
    } catch (e) {
      // Решения проекта в каталоге поменялись — сервер снял отбор и вопросы: показываем нынешнее.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  })
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
  if (!search && stream.decisions_search && stream.project_decisions === null) list = (
    <p className="muted">{t('questions.afterDecisions')}</p>
  )
  else if (!search) list = (
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
      {fresh.length > 0 && <p className="fragment-note">{t('questions.pending', { count: fresh.length })}</p>}
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
        {/* Ключ — и состояние: отбор закончился — рекомендованные отмечаются заново, уже по найденному. */}
        <ProjectDecisions key={`${stream.decisions_search?.run ?? ''}:${stream.decisions_search?.state ?? ''}`}
                          council={council} structure={structure}
                          stream={stream} group={group} notes={notes} onChange={onChange} />
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
        {question.revisits && <span className="pill blocked">{t('questions.revisits', { id: question.revisits })}</span>}
        {removed && <span className="group-tag">{t('questions.removedTag')}</span>}
        <button className="btn-secondary" disabled={busy} onClick={onToggle}>
          {t(removed ? 'questions.restore' : 'questions.remove')}
        </button>
      </div>
      {question.note && question.note !== question.text && (
        <p className="question-why">{t('questions.note', { note: question.note })}</p>
      )}
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

/** Выбран свой вариант: номер ему даст сервер, а до того в выборе — эта метка. */
const OWN = 'own'

/**
 * Шаг «Варианты»: к каждому отобранному вопросу совет ищет новые варианты ответа, а человек
 * выбирает один — из текста группы, найденный или свой, написанный тут же, — либо оставляет
 * вопрос unresolved: его разберёт следующий шаг. Найденное к вопросу видно, как только готово.
 * Черновик выбора — к нынешнему поиску; утверждённый выбор — его начало.
 */
function OptionsStep({ council, structure, stream, group, onChange, approve, onBack, onApproved }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>
  onBack: () => void; onApproved: () => void
}>) {
  const { t } = useTranslation()
  const search = stream.proposals
  const scope = stream.scope ?? []
  // Выбор, с которого начать: утверждённый, а после правки отбора — прежний по тем же вопросам (если его вариант
  // у вопроса ещё есть): выбирать остаётся только новое.
  const [start] = useState(() => stream.choices ?? earlierChoices(stream))
  // Выбор по вопросу: id варианта, OWN — свой, null — unresolved; нет ключа — ещё не выбран.
  const [picked, setPicked] = useState<ReadonlyMap<string, string | null>>(
    () => new Map(start.map(c => [c.question_id, c.text ? OWN : c.proposal])))
  // Свой вариант по вопросу: выбрали другой — текст остаётся, вернулись — он на месте.
  const [owned, setOwned] = useState<ReadonlyMap<string, string>>(
    () => new Map(start.flatMap(c => c.text ? [[c.question_id, c.text] as const] : [])))
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = search?.state === 'running'
  const stale = structureIsStale(council)
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const found = new Map(search?.options.map(o => [o.question_id, o]) ?? [])
  const ownOf = (question: string) => squash(owned.get(question) ?? '')
  // Свой вариант без текста — ещё не выбор: такой сервер не примет.
  const chosen = scope.filter(q => picked.has(q.id) && (picked.get(q.id) !== OWN || ownOf(q.id) !== '')).length
  // Пока ИИ работает с утверждённым выбором (проверяет, собирает итоги), выбор не поменять: 423.
  const checking = runningFrom(stream, 'analysis')
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
                                      group.id, search?.run ?? '', scope.map(q => {
        const proposal = picked.get(q.id) ?? null
        return proposal === OWN ? { question_id: q.id, proposal: null, text: ownOf(q.id) } : { question_id: q.id, proposal }
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
      {scope.map(question => {
        const kept = stream.choices?.find(c => c.question_id === question.id)
        return (
          <QuestionChoice key={question.id} question={question} options={found.get(question.id)}
                          sought={sought} fragments={fragments} value={picked.get(question.id)}
                          own={owned.get(question.id) ?? ''}
                          ownId={kept?.text && squash(kept.text) === ownOf(question.id) ? kept.proposal : null}
                          busy={busy} onPick={proposal => pick(question.id, proposal)}
                          onOwn={text => setOwned(before => new Map(before).set(question.id, text))} />
        )
      })}
      {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
      {checking && <p className="fragment-note">{t('options.belowRunning')}</p>}
      <div className="stream-actions spread">
        <span className="muted">{t('options.count', { count: chosen, total: scope.length })}</span>
        <button className="btn-primary large" disabled={!canApprove} onClick={submit}>{t('options.approve')}</button>
      </div>
    </>
  )
}

/** Вопрос и его варианты: из текста группы, найденные советом, свой и «пока не решаю». */
function QuestionChoice({ question, options, sought, fragments, value, own, ownId, busy, onPick, onOwn }: Readonly<{
  question: OpenQuestion; options: QuestionOptions | undefined; sought: boolean
  fragments: Map<number, LabeledFragment>; value: string | null | undefined
  /** Свой вариант и его номер, если сервер уже принял этот текст. */
  own: string; ownId: string | null; busy: boolean
  onPick: (proposal: string | null) => void; onOwn: (text: string) => void
}>) {
  const { t } = useTranslation()
  const name = `choice-${question.id}`
  const fromModels = question.source === 'inferred' || question.source === 'discovered'
  // Свой вариант выбрали только что — поле сразу под курсором; восстановленный выбор фокус не берёт.
  const [writing, setWriting] = useState(false)
  const option = (id: string | null, body: ReactNode, className = 'option', more?: ReactNode) => (
    <li key={id ?? 'unresolved'}>
      <label className={className}>
        <input type="radio" name={name} checked={value === id} disabled={busy}
               onChange={() => { setWriting(id === OWN); onPick(id) }} />
        <span className="option-body">{body}</span>
      </label>
      {more}
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
        {option(OWN, (
          <span className="option-head">
            {ownId && <span className="fragment-id">{ownId}</span>}
            <span className="source-tag">{t('options.byYou')}</span>
            <span className="option-text">{t('options.own')}</span>
          </span>
        ), 'option', value === OWN && (
          <div className="option-own">
            <textarea className="idea-text" aria-label={t('options.ownField', { id: question.id })} autoFocus={writing}
                      placeholder={t('options.ownPlaceholder')} value={own} maxLength={600} readOnly={busy}
                      onChange={e => onOwn(e.target.value)} />
            {squash(own) === '' && <p className="fragment-note">{t('options.ownEmpty')}</p>}
          </div>
        ))}
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
  // С чего начать: зафиксированные решения, а после правки отбора или выбора — прежние решения к тому же выбору
  // по тем же вопросам: решать и обосновывать остаётся только новое.
  const [start] = useState(() => stream.decisions ?? earlierDecisions(stream))
  // Решение по вопросу: id варианта, null — открыт. Сначала — зафиксированное или прежнее, иначе — выбор.
  const [picked, setPicked] = useState<ReadonlyMap<string, string | null>>(() => new Map(scope.map(q => {
    const before = start.find(d => d.question_id === q.id)
    return [q.id, before ? before.proposal : stream.choices?.find(c => c.question_id === q.id)?.proposal ?? null]
  })))
  // Обоснование — своё у каждой пары «вопрос — вариант»: переключились и вернулись — правка на месте.
  const [written, setWritten] = useState<ReadonlyMap<string, string>>(() => new Map(
    start.filter(d => d.proposal).map(d => [`${d.question_id}:${d.proposal}`, d.rationale ?? ''])))
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = analysis?.state === 'running'
  const stale = structureIsStale(council)
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const found = foundOf(stream)
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
  // Пока ИИ собирает итоги по решениям или нарезает их на задачи, их не поменять: сервер ответит 423.
  const assembling = runningFrom(stream, 'outcomes')
  const canApprove = !busy && !sought && !assembling && !stale && analysis !== null && complete
  useEffect(() => {
    if (focus) document.getElementById(`decision-${focus}-title`)?.scrollIntoView?.({ block: 'center' })
  }, [focus])
  const idea = stream.idea
  if (!idea || !stream.scope || !stream.choices) return null

  const optionsOf = (question: OpenQuestion) => [
    ...question.proposal_ids.map(id => ({ id: `F${id}`, text: fragments.get(id)?.text ?? '—' })),
    ...(found.get(question.id) ?? []),
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
function OutcomesStep({ council, structure, stream, group, onChange, approve, onBack, onApproved, onQuestion, gaps }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group; onChange: (council: Council) => void
  approve: ReturnType<typeof useAction>; onBack: () => void; onApproved: () => void
  onQuestion: (question: string) => void
  /** Пробелы — в черновик отбора вопросов: сколько угодно, потом к вопросам — одним переходом. */
  gaps: Gaps
}>) {
  const { t } = useTranslation()
  const run = stream.outcomes
  const retry = useAction(onChange)
  const stale = structureIsStale(council)
  const scope = stream.scope ?? []
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const found = new Map([...foundOf(stream).values()].flat().map(p => [p.id, p.text]))
  const textOf = (id: string) => (id.startsWith('F') ? fragments.get(Number(id.slice(1)))?.text : found.get(id)) ?? id
  // Решение ADR-n — по n-му вопросу отбора: тот же номер, что у его карточки на шаге «Решения».
  const adrs = new Map(scope.flatMap((question, n) => {
    const proposal = stream.decisions?.find(d => d.question_id === question.id)?.proposal
    return proposal ? [[`ADR-${n + 1}`, { question: question.id, text: textOf(proposal) }] as const] : []
  }))
  const questions = new Map(scope.map(q => [q.id, q.text]))
  const assemble = () => void retry.go(() => startOrFollow(
    () => api.seekOutcomes(council.id, group.id), council, c => streamOf(c, group.id)?.outcomes))
  // Утверждены — по ним уже нарезают задачи: утвердить те же ещё раз — ничего не поменять.
  const approved = stream.issues !== null && stream.issues.outcomes === run?.run
  const canApprove = run?.state === 'done' && run.outcomes.length > 0 && !approve.busy && !stale
  const pass = () => void approve.go(async () => {
    try {
      return await api.approveOutcomes(council.id, { run: structure.run, revision: structure.revision },
                                       group.id, run?.run ?? '')
    } catch (e) {
      // Группы или итоги уже другие (другая вкладка) — показываем нынешние.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, onApproved)
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
                     fragments={fragments} onQuestion={onQuestion} gaps={gaps} />
      ))}
      {run && run.uncovered_adr_ids.length > 0 && (
        <p className="fragment-note">{t('outcomes.uncovered', { ids: run.uncovered_adr_ids.join(', ') })}</p>
      )}
      {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
      {canApprove && !approved && <p className="fragment-note">{t('outcomes.approveHint')}</p>}
      <div className="stream-actions spread">
        <button className="btn-link" onClick={onBack}>{t('outcomes.change')}</button>
        {approved
          ? <button className="btn-primary large" onClick={onApproved}>{t('outcomes.toIssues')}</button>
          : <button className="btn-primary large" disabled={!canApprove} onClick={pass}>{t('outcomes.approve')}</button>}
      </div>
    </>
  )
}

/**
 * Задачи: утверждённые итоги, нарезанные на задачи для coding agents. Задачу, которой не хватает
 * решения, держит пробел или открытый вопрос: пробел несут в вопросы, к вопросу возвращаются.
 */
function IssuesStep({ council, stream, group, notes, onChange, onBack, onNext, onQuestion, gaps }: Readonly<{
  council: Council; stream: Stream; group: Group; notes: string | null; onChange: (council: Council) => void
  onBack: () => void; onNext: () => void; onQuestion: (question: string) => void; gaps: Gaps
}>) {
  const { t } = useTranslation()
  const run = stream.issues
  // Номера задач на весь проект — у выгруженного к этим задачам потока.
  const numbers = new Map(exported(stream, notes) ? (stream.notes?.numbers ?? []).map(n => [n.issue_id, n.id]) : [])
  const retry = useAction(onChange)
  const stale = structureIsStale(council)
  const scope = stream.scope ?? []
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const found = new Map([...foundOf(stream).values()].flat().map(p => [p.id, p.text]))
  const textOf = (id: string) => (id.startsWith('F') ? fragments.get(Number(id.slice(1)))?.text : found.get(id)) ?? id
  const adrs = new Map(scope.flatMap((question, n) => {
    const proposal = stream.decisions?.find(d => d.question_id === question.id)?.proposal
    return proposal ? [[`ADR-${n + 1}`, { question: question.id, text: textOf(proposal) }] as const] : []
  }))
  const questions = new Map(scope.map(q => [q.id, q.text]))
  const outcomes = new Map((stream.outcomes?.outcomes ?? []).map(o => [o.id, o.title]))
  // Решения, не вошедшие ни в один итог, нет и в задачах: их видно и здесь.
  const lost = stream.outcomes?.uncovered_adr_ids ?? []
  // Итоги без критериев готовности: задачи по ним не проверить — это видно и здесь.
  const vague = (stream.outcomes?.outcomes ?? []).filter(o => o.acceptance_criteria.length === 0).map(o => o.id)
  const cut = () => void retry.go(() => startOrFollow(
    () => api.seekIssues(council.id, group.id), council, c => streamOf(c, group.id)?.issues))
  if (!run) return null
  const [first] = run.sources
  let code = t('issues.noCode')
  if (run.code && run.sources.length > 1) {
    code = t('issues.codeSeveral', { list: run.sources.map(source => t(source.dirty ? 'issues.sourceDirty' : 'issues.source', {
      path: source.path, sha: shortSha(source.commit_sha) })).join('; ') })
  } else if (run.code) {
    code = t(first?.dirty ? 'issues.codeDirty' : 'issues.code', { sha: shortSha(first?.commit_sha ?? '') })
  }

  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t('issues.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('issues.title')}</h2>
        <p className="panel-hint">{t('issues.hint')}</p>
        {/* С какого кода нарезали — только у готовой нарезки: идущая или упавшая ещё ничего не прочла. */}
        {run.state === 'done' && <p className="muted">{code}</p>}
      </section>
      {run.state === 'running' && <p className="muted">{t('issues.cutting')} {t('run.note')}</p>}
      {run.state === 'failed' && (
        <div>
          <p className="error-text" role="alert">{run.error}</p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
          <p className="fragment-note">
            {t('issues.failedNote')}{' '}
            <button className="btn-link" disabled={retry.busy || stale} onClick={cut}>{t('run.retry')}</button>
          </p>
        </div>
      )}
      {run.state === 'done' && run.issues.length === 0 && <p className="muted">{t('issues.none')}</p>}
      {run.issues.map((issue, n) => (
        <IssueCard key={issue.id} issue={issue} n={n + 1} adrs={adrs} questions={questions} outcomes={outcomes}
                   gaps={run.gaps} fragments={fragments} onQuestion={onQuestion} number={numbers.get(issue.id)} />
      ))}
      {run.gaps.length > 0 && (
        <section className="card panel" aria-labelledby="issue-gaps-title">
          <h3 id="issue-gaps-title" className="panel-title">{t('issues.gapsTitle')}</h3>
          <ul className="issue-gaps">{run.gaps.map(gap => (
            <li key={gap.id} className="outcome-gap">
              <span>
                <span className="fragment-id">{gap.id}</span> {gap.reason ? `${gap.question} — ${gap.reason}` : gap.question}
                {gap.outcome_ids.length > 0 && <span className="muted"> · {t('issues.gapOutcomes', { ids: gap.outcome_ids.join(', ') })}</span>}
              </span>
              <GapButton question={gap.question} gaps={gaps} label={t('issues.toQuestions')} />
            </li>
          ))}</ul>
        </section>
      )}
      {run.uncovered_outcome_ids.length > 0 && (
        // Итог без задач — с тем, что его держит: иначе не понять, что сделать, чтобы его нарезать.
        <section className="card panel" aria-labelledby="issue-uncovered-title">
          <h3 id="issue-uncovered-title" className="panel-title">{t('issues.uncoveredTitle')}</h3>
          <ul className="issue-gaps">{run.uncovered_outcome_ids.map(id => {
            const outcome = stream.outcomes?.outcomes.find(o => o.id === id)
            const open = outcome?.blocked_by ?? []
            return (
              <li key={id} className="outcome-gap">
                <span>
                  <span className="fragment-id">{id}</span> {outcomes.get(id) ?? id}
                  {open.length > 0 && <span className="outcome-open"> — {t('issues.heldBy', { ids: open.join(', ') })}</span>}
                </span>
                {open.length > 0 && <button className="btn-link" onClick={() => onQuestion(open[0])}>{t('outcomes.back')}</button>}
              </li>
            )
          })}</ul>
        </section>
      )}
      {lost.length > 0 && <p className="fragment-note">{t('issues.lostDecisions', { ids: lost.join(', ') })}</p>}
      {vague.length > 0 && <p className="fragment-note">{t('issues.vagueOutcomes', { ids: vague.join(', ') })}</p>}
      <div className="stream-actions spread">
        <button className="btn-link" onClick={onBack}>{t('issues.change')}</button>
        {run.state === 'done' && <button className="btn-primary large" onClick={onNext}>{t('issues.toNotes')}</button>}
      </div>
    </>
  )
}

/** Задача: кому и зачем, где менять и что там сейчас, что сделать, на чём стоит — и что её держит. */
function IssueCard({ issue, n, adrs, questions, outcomes, gaps, fragments, onQuestion, number }: Readonly<{
  issue: Issue; n: number; adrs: Map<string, { question: string; text: string }>
  questions: Map<string, string>; outcomes: Map<string, string>; gaps: IssueGap[]
  fragments: Map<number, LabeledFragment>; onQuestion: (question: string) => void
  /** Номер задачи на весь проект — когда поток выгружен в заметки к этим задачам. */
  number?: string
}>) {
  const { t } = useTranslation()
  const name = `issue-${issue.id}`
  const blocked = issue.blocked_by
  const open = blocked.filter(id => questions.has(id))
  const gapOf = new Map(gaps.map(gap => [gap.id, gap.question]))
  const pill = issueReady(issue)
    ? <span className="pill ready">{t('issues.ready')}</span>
    : <span className="pill blocked">{t('issues.blocked', { ids: blocked.join(', ') })}</span>
  const limits = (ids: number[]) => (
    <ul>{ids.map(id => <li key={id}><span className="fragment-id">F{id}</span> {fragments.get(id)?.text ?? '—'}</li>)}</ul>
  )
  return (
    <section className="card panel" aria-labelledby={`${name}-title`}>
      <div className="question-head">
        <span className="fragment-id">{issue.id}</span>
        {number && <span className="pill ready">{number}</span>}
        <h3 id={`${name}-title`} className="question-text">{issue.title}</h3>
        {pill}
      </div>
      {number && <p className="fragment-note">{t('issues.commit', { id: number })}</p>}
      {open.length > 0 && (
        <div className="check problem outcome-missing">
          <span>{t('issues.missing', { ids: open.join(', ') })}</span>
          <button className="btn-secondary" onClick={() => onQuestion(open[0])}>{t('outcomes.back')}</button>
        </div>
      )}
      <dl className="outcome-rows">
        <dt>{t('issues.story')}</dt>
        <dd>{issue.user_story}</dd>
        {issue.main_entry_points.length > 0 && (
          <><dt>{t('issues.entry')}</dt><dd><ul>{issue.main_entry_points.map(text => <li key={text}><code>{text}</code></li>)}</ul></dd></>
        )}
        {issue.current_state && <><dt>{t('issues.now')}</dt><dd>{issue.current_state}</dd></>}
        {issue.scope.length > 0 && (
          <><dt>{t('issues.scope')}</dt><dd><ul>{issue.scope.map(text => <li key={text}>— {text}</li>)}</ul></dd></>
        )}
        <dt>{t('issues.outcomes')}</dt>
        <dd><ul>{issue.outcome_ids.map(id => (
          <li key={id}><span className="fragment-id">{id}</span> {outcomes.get(id) ?? id}</li>
        ))}</ul></dd>
        {issue.acceptance_criteria.length > 0 && (
          <>
            <dt>{t('issues.doneWhen')}</dt>
            <dd><ul>{issue.acceptance_criteria.map(text => <li key={text}>— {text}</li>)}</ul></dd>
          </>
        )}
        {issue.adr_ids.length > 0 && (
          <>
            <dt>{t('issues.decisions')}</dt>
            <dd><ul>{issue.adr_ids.map(id => {
              const adr = adrs.get(id)
              return <li key={id}><span className="fragment-id">{adr?.question ?? id}</span> {adr?.text ?? id}</li>
            })}</ul></dd>
          </>
        )}
        {issue.constraint_ids.length > 0 && <><dt>{t('issues.keep')}</dt><dd>{limits(issue.constraint_ids)}</dd></>}
        {issue.risk_ids.length > 0 && <><dt>{t('issues.risks')}</dt><dd>{limits(issue.risk_ids)}</dd></>}
        {issue.depends_on.length > 0 && <><dt>{t('issues.after')}</dt><dd>{issue.depends_on.join(', ')}</dd></>}
        {blocked.length > 0 && (
          <>
            <dt>{t('issues.blockedBy')}</dt>
            <dd><ul>{blocked.map(id => (
              <li key={id} className="outcome-open">
                <span className="fragment-id">{id}</span> {questions.has(id) ? `${t('outcomes.open')} — ${questions.get(id)}` : gapOf.get(id) ?? id}
              </li>
            ))}</ul></dd>
          </>
        )}
      </dl>
    </section>
  )
}

/** Итог: что меняется, на каких решениях стоит, что соблюдать, когда готово — и чего не хватает. */
function OutcomeCard({ outcome, n, adrs, questions, fragments, onQuestion, gaps }: Readonly<{
  outcome: Outcome; n: number; adrs: Map<string, { question: string; text: string }>
  questions: Map<string, string>; fragments: Map<number, LabeledFragment>
  onQuestion: (question: string) => void; gaps: Gaps
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
                  <GapButton question={gap.question} gaps={gaps} label={t('outcomes.toQuestions')} />
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
/** Варианты вопросов, кроме предложений группы: найденные советом и свой вариант человека из выбора. */
function foundOf(stream: Stream): Map<string, { id: string; text: string }[]> {
  const found = new Map((stream.proposals?.options ?? []).map(o => [
    o.question_id, o.proposals.map(p => ({ id: p.id, text: p.text }))]))
  for (const { question_id, proposal, text } of stream.choices ?? []) {
    if (proposal && text) found.set(question_id, [...(found.get(question_id) ?? []), { id: proposal, text }])
  }
  return found
}

function offeredBy(search: IdeaDiscovery | null): { idea: string; evidence: number[]; reason: string }[] {
  if (!search) return []
  const proposal = search.proposal?.idea ? [{ ...search.proposal, idea: search.proposal.idea }] : []
  return [...proposal, ...search.options]
}

/** Текст идеи без лишних пробелов — так его сравнивает и сервер. */
const squash = (text: string) => text.trim().split(/\s+/).join(' ')

/** Черновик отбора вопросов: к какому поиску, какие найденные убраны, какие свои добавлены. */
interface ScopeDraft { run: string; removed: string[]; added: string[] }

/** Пробелы из итогов и задач — в черновик отбора: has — он уже там, add — добавить. */
interface Gaps { has: (question: string) => boolean; add: (question: string) => void }

/** Черновик, каким его видно, пока его не трогали: утверждённый отбор (или ещё ничего не убрано и не добавлено). */
function draftOf(stream: Stream): ScopeDraft {
  const found = stream.questions?.questions ?? []
  const scope = stream.scope
  return {
    run: stream.questions?.run ?? '',
    removed: scope ? found.filter(q => !scope.some(s => s.id === q.id)).map(q => q.id) : [],
    added: scope?.filter(q => q.source === 'added').map(q => q.text) ?? [],
  }
}

/** Вопросы черновика: оставленные найденные и свои. */
const draftTexts = (draft: ScopeDraft, stream: Stream) => [
  ...(stream.questions?.questions ?? []).filter(q => !draft.removed.includes(q.id)).map(q => q.text), ...draft.added]

/** Такой вопрос в черновике уже есть — так их сравнивает сервер. */
const inDraft = (draft: ScopeDraft, stream: Stream, question: string) =>
  draftTexts(draft, stream).some(text => sameQuestion(text) === sameQuestion(question))

const withQuestion = (draft: ScopeDraft, stream: Stream, question: string): ScopeDraft =>
  inDraft(draft, stream, question) ? draft : { ...draft, added: [...draft.added, squash(question)] }

/** Сколько вопросов черновика ещё не в утверждённом отборе. */
const pendingOf = (draft: ScopeDraft, stream: Stream) => {
  const approved = (stream.scope ?? []).map(q => sameQuestion(q.text))
  return draftTexts(draft, stream).filter(text => !approved.includes(sameQuestion(text))).length
}

/** Прежний выбор по тем же вопросам отбора — если его вариант у вопроса ещё есть. */
function earlierChoices(stream: Stream): Choice[] {
  const found = foundOf(stream)
  return (stream.scope ?? []).flatMap(question => {
    const choice = earlierOf(stream, question)?.choice
    if (!choice) return []
    const offered = choice.proposal === null || choice.text
      || question.proposal_ids.some(id => `F${id}` === choice.proposal)
      || (found.get(question.id) ?? []).some(p => p.id === choice.proposal)
    return offered ? [choice] : []
  })
}

/** Прежние решения — к тому же выбору по тем же вопросам. */
const earlierDecisions = (stream: Stream): Decision[] => (stream.scope ?? []).flatMap(question => {
  const work = earlierOf(stream, question)
  const choice = stream.choices?.find(c => c.question_id === question.id)
  return work?.decision && choice && sameChoice(work.choice, choice) ? [work.decision] : []
})

/** Пробел — в вопросы: в черновик отбора, без перехода; уже там — так и сказано. */
function GapButton({ question, gaps, label }: Readonly<{ question: string; gaps: Gaps; label: string }>) {
  const { t } = useTranslation()
  return gaps.has(question)
    ? <span className="pill ready">{t('gaps.added')}</span>
    : <button className="btn-link" onClick={() => gaps.add(question)}>{label}</button>
}

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
