import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import {
  api, ApiError, councilPath, earlierOf, groupsConfirmed, issuesOf, notesOf, outcomeReady, outcomesFree,
  researched, runningFrom, sameChoice, startedWithResearch, startOrFollow,
  streamOf, structureIsStale, type Choice, type Council, type Decision, type Group,
  type Folders, type LabeledFragment, type Model, type NotePlan, type OpenQuestion, type Outcome, type OutcomeTouch, type QuestionAnalysis,
  type QuestionOptions, type Settings, type Stream, type Structure,
} from '../api'
import { LabelPill } from '../components/Labels'
import { modelOf } from '../components/ModelBadge'
import { Progress } from '../components/Progress'
import { firstOpen, Slider, type Slide } from '../components/Slider'
import {
  CHAIN, chainLight, currentStep, exported, exportedCount, exportedNotes, exportedTo, openable, streamLight, type ChainStep,
} from '../light'
import { fragmentRange, squash } from '../text'
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
                     models={settings.models} notes={notesOf(council, settings)} issues={issuesOf(council, settings)}
                     onChange={onChange} />
}

function StreamPage({ council, structure, stream, models, notes, issues, onChange }: Readonly<{
  council: Council; structure: Structure; stream: Stream; models: Model[]
  /** Каталог заметок — папка документации проекта совета; issues — его папка задач. */
  notes: string | null; issues: string | null
  onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  // Куда выгружают поток: по обеим папкам выгрузка — выгрузка, и шаг «Документация» зелёный.
  const folders: Folders = { notes, issues }
  const ready = researched(council)
  const [chosen, setView] = useState<ChainStep>(currentStep(stream))
  // Утверждение отбора — здесь, а не в шаге: отказ (409) приносит новый поиск, шаг рисуется
  // заново, а ошибка должна остаться видна.
  const choosing = useAction(onChange, 'questions.approveFailed')
  const picking = useAction(onChange, 'options.approveFailed')
  const fixing = useAction(onChange, 'decisions.approveFailed')
  const approving = useAction(onChange, 'outcomes.approveFailed')
  // Открытый вопрос, к которому вернулись из итогов: шаг «Решения» прокрутит к нему.
  const [focus, setFocus] = useState<string | null>(null)
  // Черновик отбора вопросов — здесь, а не в шаге «Вопросы»: за пробелами уходят в «Итоги» и
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
  const view = openable(stream, chosen) ? chosen : currentStep(stream)
  const runs = { start: null, questions: stream.questions ?? stream.decisions_search, options: stream.proposals,
                 decisions: stream.analysis, outcomes: stream.outcomes, notes: stream.notes_draft }
  const run = runs[view]
  const open = (step: ChainStep) => {
    setFocus(null)
    setView(step)
  }

  return (
    <div className="streams-layout">
      <aside className="streams-nav">
        <StreamList council={council} structure={structure} open={stream.group} folders={folders} />
        <Chain stream={stream} group={group} view={view} onView={open} folders={folders} ready={ready} />
      </aside>
      <div className="streams-main">
        <Now stream={stream} group={group} folders={folders} ready={ready} />
        <StepBanner stream={stream} group={group} view={view} folders={folders} ready={ready} />
        {view === 'outcomes' && pending > 0 && (
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
        {view === 'start' && (
          <StartStep council={council} structure={structure} stream={stream} group={group} onChange={onChange}
                     onStarted={() => open('questions')} />
        )}
        {view === 'questions' && (
          // Новый поиск вопросов — и отбор заново, к его вопросам.
          <QuestionsStep key={stream.questions?.run ?? ''} council={council} structure={structure}
                         stream={stream} group={group} notes={notes} onChange={onChange} approve={choosing}
                         draft={draft} onDraft={setDraft}
                         onBack={() => open('start')} onApproved={() => { setDraft(null); open('options') }} />
        )}
        {view === 'options' && (
          // Новый поиск вариантов — и выбор заново, к его вариантам.
          <OptionsStep key={stream.proposals?.run ?? ''} council={council} structure={structure}
                       stream={stream} group={group} onChange={onChange} approve={picking}
                       onBack={() => setView('questions')} onApproved={() => setView('decisions')} />
        )}
        {view === 'decisions' && (
          // Другой выбор — и решения заново, к его проверке. Перепроверка одного вопроса (и повтор упавшей) выбора не
          // меняет: что человек уже решил и вписал на других карточках, остаётся.
          <DecisionsStep key={stream.analysis?.choices.join('\n') ?? ''} council={council} structure={structure}
                         stream={stream} group={group} onChange={onChange} approve={fixing} focus={focus}
                         onBack={() => open('options')} onApproved={() => open('outcomes')} />
        )}
        {view === 'outcomes' && (
          <OutcomesStep council={council} structure={structure} stream={stream} group={group} onChange={onChange}
                        approve={approving} onBack={() => open('decisions')} onApproved={() => open('notes')}
                        onQuestion={question => { setFocus(question); setView('decisions') }} gaps={gaps} />
        )}
        {view === 'notes' && (
          // Новый черновик — и правки заново, к его заметкам.
          <NotesStep key={stream.notes_draft?.run ?? ''} council={council} structure={structure} stream={stream}
                     group={group} root={notes} onChange={onChange} />
        )}
      </div>
      <aside className="streams-side">
        {run && run.steps.length > 0 && <Progress steps={run.steps} models={models} />}
      </aside>
    </div>
  )
}

function StreamList({ council, structure, open, folders }: Readonly<{
  council: Council; structure: Structure; open: string; folders: Folders
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
                  <span className={`light-dot ${streamLight(stream, folders, researched(council))}`} aria-hidden="true" />
                  {whereIs(stream, folders, researched(council), t)}
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
function whereIs(stream: Stream, folders: Folders, ready: boolean, t: T): string {
  const step = currentStep(stream)
  if (step === 'start') return t(stream.idea && ready ? 'streams.start.yours' : 'streams.start.waits')
  const run = { questions: stream.questions ?? stream.decisions_search, options: stream.proposals,
                decisions: stream.analysis, outcomes: stream.outcomes, notes: stream.notes_draft }[step]
  if (run?.state === 'running') return t(`streams.${step}.seeking`)
  if (run?.state === 'failed') return t(`streams.${step}.failed`)
  if (step === 'notes' && streamLight(stream, folders) === 'done') return t('streams.notes.done')
  return t(`streams.${step}.yours`)
}

/** «Сейчас»: где поток и чей ход — и вся его цепочка сегментами в цветах светофора. */
function Now({ stream, group, folders, ready }: Readonly<{ stream: Stream; group: Group; folders: Folders; ready: boolean }>) {
  const { t } = useTranslation()
  const light = streamLight(stream, folders, ready)
  return (
    <section className="now" aria-labelledby="now-title">
      <p className={`now-caps ${light}`}>{t('now.caps', { group: stream.group, state: t(`now.${light}`) })}</p>
      <h2 id="now-title" className="now-title">{group.title}</h2>
      <ol className="segments">
        {CHAIN.map(step => {
          const state = chainLight(stream, step, folders, ready)
          return (
            <li key={step} className={`segment ${state}`}>
              <span className="segment-name">
                {t(`chain.${step}`)}
                <span className="sr-only"> ({t(`light.${state}`)})</span>
              </span>
              {step === 'start' && <span className="segment-sub">{startStatus(stream, ready, t)}</span>}
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
              {step === 'notes' && stream.outcomes?.approved && <span className="segment-sub">{notesStatus(stream, folders, t)}</span>}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

/** Цепочка шагов потока: пройденные и текущий открываются, дальше — что будет. */
function Chain({ stream, group, view, onView, folders, ready }: Readonly<{
  stream: Stream; group: Group; view: ChainStep; onView: (step: ChainStep) => void; folders: Folders; ready: boolean
}>) {
  const { t } = useTranslation()
  const reached = CHAIN.indexOf(currentStep(stream))
  const status = (step: ChainStep, i: number) =>
    stepStatus(stream, group, step, folders, ready, t) ?? t(i === reached ? 'chain.soon' : 'chain.notStarted')
  return (
    <section className="card panel chain" aria-labelledby="chain-title">
      <h2 id="chain-title" className="panel-title caps">
        {t('chain.title')} <span className="chain-of">{t('chain.of', { group: stream.group })}</span>
      </h2>
      <ol className="chain-steps">
        {CHAIN.map((step, i) => {
          const light = chainLight(stream, step, folders, ready)
          const state = i === reached ? 'current' : 'later'
          const compact = i !== reached && view !== step
          const body = (
            <>
              <span className={`chain-num ${light}`} aria-hidden="true">{light === 'done' ? '✓' : i + 1}</span>
              <span className="chain-body">
                <span className="chain-name">{t(`chain.${step}`)}</span>
                {/* Свёрнутый шаг — одной строкой: длинный статус обрезан, целиком — в подсказке. */}
                <span className={`chain-status ${light}`} title={compact ? status(step, i) : undefined}>
                  {status(step, i)}
                </span>
                {!compact && (
                  <span className="chain-role"><span className="role-tag ai">{t('chain.ai')}</span>{t(`chain.${step}.ai`)}</span>
                )}
                {!compact && (
                  <span className="chain-role"><span className="role-tag">{t('chain.you')}</span>{t(`chain.${step}.you`)}</span>
                )}
              </span>
            </>
          )
          const className = `chain-step ${i < reached ? 'done' : state}${view === step ? ' open' : ''}${compact ? ' compact' : ''}`
          return (
            <li key={step}>
              {openable(stream, step)
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

/** Что с шагом потока — словами, как в цепочке; шаг ещё не начат — null. */
function stepStatus(stream: Stream, group: Group, step: ChainStep, folders: Folders, ready: boolean, t: T): string | null {
  if (step === 'start') return `${t('chain.fragments', { count: group.fragment_ids.length })} · ${startStatus(stream, ready, t)}`
  if (step === 'questions' && stream.design) return questionsStatus(stream, t)
  if (step === 'options' && stream.scope) return optionsStatus(stream, t)
  if (step === 'decisions' && stream.choices) return decisionsStatus(stream, t)
  if (step === 'outcomes' && stream.decisions) return outcomesStatus(stream, t)
  if (step === 'outcomes' && stream.saved_outcomes.length > 0) return t('chain.outcomesSaved', { count: stream.saved_outcomes.length })
  if (step === 'notes' && stream.outcomes?.approved) return notesStatus(stream, folders, t)
  return null
}

/**
 * Плашка открытого шага: чего ждём — цветом, значком и словами. ИИ работает — зелёная, ход за вами — жёлтая, сбой —
 * красная; готовый и не начатый шаг плашки не дают. Причину сбоя и кнопку повтора шаг показывает ниже, а ход
 * каждой модели — колонка справа.
 */
function StepBanner({ stream, group, view, folders, ready }: Readonly<{
  stream: Stream; group: Group; view: ChainStep; folders: Folders; ready: boolean
}>) {
  const { t } = useTranslation()
  const light = chainLight(stream, view, folders, ready)
  if (light !== 'running' && light !== 'yours' && light !== 'failed') return null
  const icon = { running: '◔', yours: '!', failed: '×' }[light]
  return (
    <div className={`banner ${light}`} role="status">
      <span className="banner-icon" aria-hidden="true">{icon}</span>
      <span className="banner-text">
        <strong>{t(`banner.${light}`)}</strong> · {light === 'yours'
          ? t(`chain.${view}.you`) : stepStatus(stream, group, view, folders, ready, t) ?? t(`chain.${view}`)}
        {light === 'running' && <span className="banner-note"> {t('banner.runningNote')}</span>}
        {light === 'failed' && <span className="banner-note"> {t('banner.failedNote')}</span>}
      </span>
    </div>
  )
}

/** Что с началом потока: начат (с картой и описанием или без), ждёт вас или ждёт идею и исследование. */
function startStatus(stream: Stream, ready: boolean, t: T): string {
  if (stream.design) {
    return t('chain.started', {
      repository: t(stream.repository?.by === 'scan' ? 'chain.withMap' : 'chain.withoutMap'),
      design: t(stream.design.by === 'scan' ? 'chain.withDesign' : 'chain.withoutDesign') })
  }
  if (!stream.idea) return t('chain.startNoIdea')
  return t(ready ? 'chain.startReady' : 'chain.startWaits')
}

/**
 * Начало потока: его идея (её утверждают на этапе «Группы») и исследование совета, с которым его начинают. Поток
 * берёт себе копию карты кода и описания макета — и совет сразу ищет вопросы (или сначала отбирает решения
 * проекта). Исследование с тех пор прошли иначе — поток работает с прежним, пока его не начнут заново: тогда
 * вопросы и всё ниже ищутся заново.
 */
function StartStep({ council, structure, stream, group, onChange, onStarted }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group
  onChange: (council: Council) => void; onStarted: () => void
}>) {
  const { t } = useTranslation()
  const start = useAction(onChange, 'start.failed')
  const ready = researched(council)
  const started = !!stream.design
  const current = startedWithResearch(council, stream)
  // Пока ИИ работает с потоком, начать заново нельзя: сервер ответит 423.
  const busy = start.busy || runningFrom(stream, 'decisions_search')
  const idea = stream.idea
  const go = () => void start.go(async () => {
    try {
      return await api.startStream(council.id, { run: structure.run, revision: structure.revision }, group.id,
                                   idea?.text ?? '')
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, onStarted)
  const research = council.research
  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t('start.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('start.title')}</h2>
        <p className="panel-hint">{t('start.hint')}</p>
      </section>
      <section className="card panel" aria-label={t('start.title')}>
        <h3 className="panel-title caps">{t('idea.section')}</h3>
        {idea
          ? <p className="options-idea"><span className="fragment-id">I1</span> {idea.text}</p>
          : <p className="fragment-note">{t('start.noIdea')}</p>}
        <p className="fragment-note">
          <Link className="btn-link" to={councilPath(council.id, 'structure')}>{t('start.toIdeas')}</Link>
        </p>
        <h3 className="panel-title caps section-gap">{t('start.research')}</h3>
        {research?.repository && research.design ? (
          <p className="repo-summary">{t('chain.started', {
            repository: t(research.repository.by === 'scan' ? 'chain.withMap' : 'chain.withoutMap'),
            design: t(research.design.by === 'scan' ? 'chain.withDesign' : 'chain.withoutDesign') })}</p>
        ) : <p className="fragment-note">{t('start.noResearch')}</p>}
        <p className="fragment-note">
          <Link className="btn-link" to={councilPath(council.id, 'research')}>{t('start.toResearch')}</Link>
        </p>
        {started && (
          <p className={current ? 'check ok' : 'fragment-note'}>{t(current ? 'start.current' : 'start.another')}</p>
        )}
        {start.error && <p className="error-text" role="alert">{start.error}</p>}
        <div className="stream-actions">
          <button className="btn-primary large" disabled={!idea || !ready || busy || (started && current)
                                                          || structureIsStale(council)} onClick={go}>
            {t(started ? 'start.again' : 'start.start')}
          </button>
        </div>
      </section>
    </>
  )
}

/**
 * Что с итогами потока: собираются, сборка упала, утверждены, сколько держат открытые вопросы, сколько ещё не
 * готово, какие решения не вошли ни в один, сколько готово.
 */
function outcomesStatus(stream: Stream, t: T): string {
  const run = stream.outcomes
  if (run?.state === 'running') return t('chain.outcomesAssembling')
  if (run?.state === 'failed') return t('chain.outcomesFailed')
  if (!run) return t('chain.outcomesNone')
  if (run.approved) return t('chain.outcomesApproved')
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

/** Что с документацией потока: черновик переводится, перевод упал, выгружена, черновик ждёт или не собирали. */
function notesStatus(stream: Stream, folders: Folders, t: T): string {
  const draft = stream.notes_draft
  if (draft?.state === 'running') return t('chain.notesTranslating')
  if (draft?.state === 'failed') return t('chain.notesFailed')
  if (exported(stream, folders)) return t('chain.notesWritten', { count: exportedCount(stream) })
  if (stream.notes) return t(stream.notes.root === folders.notes ? 'chain.notesOutdated' : 'chain.notesElsewhere')
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
    .filter(other => other.group !== stream.group && other.decisions && !exportedNotes(other, notes)).map(other => other.group)
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
 * Шаг «Документация» — сразу после утверждения итогов. Совет собирает черновик выгрузки потока в заметки проекта
 * (IDEA, вопросы, варианты, решения, итоги — файлом на заметку, в формате Causa): номера, тексты и что с каждой
 * будет. Человек правит тексты, отмечает исчезнувшие к удалению и записывает. Файл, правленный руками после прошлой
 * выгрузки, совет не трогает. Задачи режет этап «Задачи» — на весь совет.
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
  const stale = !!draft && (!stream.outcomes?.approved || stream.outcomes.run !== draft.outcomes)
  // Проект совета или его папку сменили после сборки: черновик — к прежней папке.
  const moved = !!draft && draft.state === 'done' && !!root && draft.root !== root
  const ready = draft?.state === 'done' && !stale && !moved
  const folders = { notes: root, issues: null }
  const written = !!draft && stream.notes?.run === draft.run && exported(stream, folders)
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
          <p className={exported(stream, folders) ? 'check ok' : 'fragment-note'}>
            {t(exported(stream, folders) ? 'notes.written'
               : stream.notes.root !== root ? 'notes.elsewhere' : 'notes.outdated',
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
    // Сравнение — как на сервере: совпавший с оставленным или своим вопрос он всё равно бы выкинул, а убранный
    // найденный — возвращается, а не встаёт рядом своим.
    const there = [...kept.map(q => q.text), ...added].some(own => sameQuestion(own) === sameQuestion(text))
    setTwice(there)
    if (!there) {
      onDraft(withQuestion(scopeDraft, stream, text))
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
        {question.technical && (
          <span className="pill open" title={t('questions.technicalHint')}>{t('questions.technical')}</span>
        )}
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
/** Выбрана правка варианта: в выборе — «edit:» и номер варианта, который правят. */
const EDIT = 'edit:'
const editOf = (base: string) => `${EDIT}${base}`
const baseOf = (value: string | null | undefined) => value?.startsWith(EDIT) ? value.slice(EDIT.length) : null

/**
 * Шаг «Варианты»: к каждому отобранному вопросу совет ищет новые варианты ответа, а человек
 * выбирает один — из текста группы, найденный, его правку или свой, написанный тут же, — либо
 * оставляет вопрос unresolved: его разберёт следующий шаг. Найденное к вопросу видно, как только
 * готово. Черновик выбора — к нынешнему поиску; утверждённый выбор — его начало.
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
  // Правка варианта, которого у вопроса уже нет, — просто свой вариант.
  const editedBase = (c: Choice) => {
    const question = scope.find(q => q.id === c.question_id)
    const offered = !!c.based_on && (question?.proposal_ids.some(id => `F${id}` === c.based_on)
      || (search?.options.find(o => o.question_id === c.question_id)?.proposals ?? []).some(p => p.id === c.based_on))
    return c.text && offered ? c.based_on ?? null : null
  }
  // Выбор по вопросу: id варианта, OWN — свой, editOf(id) — правка варианта, null — unresolved; нет ключа — ещё
  // не выбран.
  const [picked, setPicked] = useState<ReadonlyMap<string, string | null>>(() => new Map(start.map(c => {
    const base = editedBase(c)
    if (base) return [c.question_id, editOf(base)] as const
    return [c.question_id, c.text ? OWN : c.proposal] as const
  })))
  // Свой вариант по вопросу: выбрали другой — текст остаётся, вернулись — он на месте.
  const [owned, setOwned] = useState<ReadonlyMap<string, string>>(
    () => new Map(start.flatMap(c => c.text && !editedBase(c) ? [[c.question_id, c.text] as const] : [])))
  // Правки вариантов: ключ — «вопрос вариант». Как и свой, правка остаётся, если выбрали другое.
  const [edited, setEdited] = useState<ReadonlyMap<string, string>>(() => new Map(start.flatMap(c => {
    const base = editedBase(c)
    return base && c.text ? [[`${c.question_id} ${base}`, c.text] as const] : []
  })))
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = search?.state === 'running'
  const stale = structureIsStale(council)
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const found = new Map(search?.options.map(o => [o.question_id, o]) ?? [])
  const ownOf = (question: string) => squash(owned.get(question) ?? '')
  const editedOf = (question: string, base: string) => squash(edited.get(`${question} ${base}`) ?? '')
  // Свой вариант или правка без текста — ещё не выбор: такой сервер не примет.
  const answered = (question: string) => {
    if (!picked.has(question)) return false
    const value = picked.get(question)
    const base = baseOf(value)
    if (base) return editedOf(question, base) !== ''
    return value !== OWN || ownOf(question) !== ''
  }
  const chosen = scope.filter(q => answered(q.id)).length
  // Выбран вариант — готово. «Пока не решаю» — ответ шага, но вопрос открыт, как и на «Решениях»: жёлтый,
  // даже пока к нему ищут варианты. Без ответа: вариантов ещё ищут — ИИ работает, иначе — ход за человеком.
  const choiceSlides: Slide[] = scope.map(q => {
    let light: Slide['light'] = 'yours'
    if (answered(q.id)) light = picked.get(q.id) === null ? 'yours' : 'done'
    else if (sought && !found.has(q.id)) light = 'running'
    return { id: q.id, title: q.text, light }
  })
  // Открыть — на первом вопросе совсем без ответа, даже если к нему ещё ищут варианты (новый вопрос после правки
  // отбора); нет таких — на первом жёлтом, то есть «пока не решаю».
  const waiting = scope.findIndex(q => !answered(q.id))
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
        const base = baseOf(proposal)
        if (base) return { question_id: q.id, proposal: null, text: editedOf(q.id, base), based_on: base }
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
      <Slider slides={choiceSlides} label={t('options.slides')} start={waiting >= 0 ? waiting : firstOpen(choiceSlides)}>
        {n => {
          const question = scope[n]
          const kept = stream.choices?.find(c => c.question_id === question.id)
          const keptBase = kept ? editedBase(kept) : null
          const edits = new Map([...edited].flatMap(([key, text]) => {
            const [of, base] = key.split(' ')
            return of === question.id ? [[base, text] as const] : []
          }))
          return (
            <QuestionChoice key={question.id} question={question} options={found.get(question.id)}
                            sought={sought} fragments={fragments} value={picked.get(question.id)}
                            own={owned.get(question.id) ?? ''}
                            ownId={kept?.text && !keptBase && squash(kept.text) === ownOf(question.id) ? kept.proposal : null}
                            edits={edits}
                            editId={kept?.text && keptBase && squash(kept.text) === editedOf(question.id, keptBase)
                              ? { base: keptBase, id: kept.proposal ?? '' } : null}
                            busy={busy} onPick={proposal => pick(question.id, proposal)}
                            onOwn={text => setOwned(before => new Map(before).set(question.id, text))}
                            onEdit={(base, text) => setEdited(before => new Map(before).set(`${question.id} ${base}`, text))} />
          )
        }}
      </Slider>
      {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
      {checking && <p className="fragment-note">{t('options.belowRunning')}</p>}
      <div className="stream-actions spread">
        <span className="muted">{t('options.count', { count: chosen, total: scope.length })}</span>
        <button className="btn-primary large" disabled={!canApprove} onClick={submit}>{t('options.approve')}</button>
      </div>
    </>
  )
}

/**
 * Вопрос и его варианты: из текста группы, найденные советом, свой и «пока не решаю». Вариант из текста или
 * найденный можно поправить: правка — своя строка под ним, а в заметках она встанет на его место.
 */
function QuestionChoice({ question, options, sought, fragments, value, own, ownId, edits, editId, busy, onPick, onOwn,
  onEdit }: Readonly<{
  question: OpenQuestion; options: QuestionOptions | undefined; sought: boolean
  fragments: Map<number, LabeledFragment>; value: string | null | undefined
  /** Свой вариант и его номер, если сервер уже принял этот текст. */
  own: string; ownId: string | null
  /** Правки вариантов: какой вариант → текст; номер правки, если сервер уже принял её текст. */
  edits: ReadonlyMap<string, string>; editId: { base: string; id: string } | null; busy: boolean
  onPick: (proposal: string | null) => void; onOwn: (text: string) => void; onEdit: (base: string, text: string) => void
}>) {
  const { t } = useTranslation()
  const name = `choice-${question.id}`
  const fromModels = question.source === 'inferred' || question.source === 'discovered'
  // Свой вариант или правку выбрали только что — поле сразу под курсором; восстановленный выбор фокус не берёт.
  const [writing, setWriting] = useState<string | null>(null)
  const choose = (id: string | null) => { setWriting(id); onPick(id) }
  // Правка варианта — строка под ним, пока её выбрали или текст уже другой; иначе — кнопка «Поправить», и
  // правка начинается с текста варианта.
  const edit = (base: string, text: string) => {
    const id = editOf(base)
    const draft = edits.get(base)
    if (value !== id && (draft === undefined || squash(draft) === squash(text))) return (
      <button className="btn-link option-edit" aria-label={t('options.editOf', { id: base })} disabled={busy}
              onClick={() => { if (draft === undefined) onEdit(base, text); choose(id) }}>
        {t('options.edit')}
      </button>
    )
    return (
      <div className="option-edited">
        <label className="option">
          <input type="radio" name={name} checked={value === id} disabled={busy} onChange={() => choose(id)} />
          <span className="option-body">
            <span className="option-head">
              {editId?.base === base && <span className="fragment-id">{editId.id}</span>}
              <span className="source-tag">{t('options.byYou')}</span>
              <span className="option-text">{t('options.edited', { id: base })}</span>
            </span>
          </span>
        </label>
        {value === id && (
          <div className="option-own">
            <textarea className="idea-text" aria-label={t('options.editField', { id: base, question: question.id })}
                      autoFocus={writing === id} value={draft ?? ''} maxLength={600} readOnly={busy}
                      onChange={e => onEdit(base, e.target.value)} />
            {squash(draft ?? '') === '' && <p className="fragment-note">{t('options.ownEmpty')}</p>}
          </div>
        )}
      </div>
    )
  }
  const option = (id: string | null, body: ReactNode, className = 'option', more?: ReactNode) => (
    <li key={id ?? 'unresolved'}>
      <label className={className}>
        <input type="radio" name={name} checked={value === id} disabled={busy} onChange={() => choose(id)} />
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
        ), 'option', fragments.has(id) && edit(`F${id}`, fragments.get(id)?.text ?? '')))}
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
        ), 'option', edit(proposal.id, proposal.text)))}
        {option(OWN, (
          <span className="option-head">
            {ownId && <span className="fragment-id">{ownId}</span>}
            <span className="source-tag">{t('options.byYou')}</span>
            <span className="option-text">{t('options.own')}</span>
          </span>
        ), 'option', value === OWN && (
          <div className="option-own">
            <textarea className="idea-text" aria-label={t('options.ownField', { id: question.id })} autoFocus={writing === OWN}
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
  // Готово — решение есть: вариант с обоснованием (своим, подсказанным ИИ или прежним). Открытый вопрос не готов,
  // даже зафиксированный: он держит свои итоги. Проверку ещё ведут — ИИ работает; остальное — ход за человеком.
  const decisionSlides: Slide[] = scope.map(q => {
    const value = picked.get(q.id) ?? null
    let light: Slide['light'] = 'yours'
    if (value !== null && squash(rationaleOf(q.id, value)) !== '') light = 'done'
    else if (sought && !said.has(q.id)) light = 'running'
    return { id: q.id, title: q.text, light }
  })
  // Пока ИИ собирает итоги по решениям или нарезает их на задачи, их не поменять: сервер ответит 423.
  const assembling = runningFrom(stream, 'outcomes')
  const canApprove = !busy && !sought && !assembling && !stale && analysis !== null && complete
  // Без обоснования решение не зафиксировать: каким вопросам его не хватает — видно у кнопки.
  const unjustified = decided.filter(q => squash(rationaleOf(q.id, picked.get(q.id) ?? '')) === '')
  // Перепроверить выбор по одному вопросу можно, пока решения не зафиксированы и совет не занят.
  const canRecheck = !busy && !sought && !assembling && !stale && analysis !== null && stream.decisions === null
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
  const recheck = (question: string) => void retry.go(() => startOrFollow(
    () => api.recheckChoice(council.id, group.id, question), council, c => streamOf(c, group.id)?.analysis))
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
      <Slider slides={decisionSlides} label={t('decisions.slides')}
              start={focus ? Math.max(scope.findIndex(q => q.id === focus), 0) : firstOpen(decisionSlides)}>
        {n => {
          const question = scope[n]
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
                          busy={busy} onRecheck={canRecheck ? () => recheck(question.id) : undefined}
                          onPick={proposal => setPicked(before => new Map(before).set(question.id, proposal))}
                          onRationale={text => value && setWritten(before => new Map(before).set(`${question.id}:${value}`, text))} />
          )
        }}
      </Slider>
      {analysis?.state === 'done' && retry.error && <p className="error-text" role="alert">{retry.error}</p>}
      {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
      {assembling && <p className="fragment-note">{t('decisions.belowRunning')}</p>}
      {unjustified.length > 0 && !sought && (
        <p className="fragment-note">{t('decisions.unjustified', { ids: unjustified.map(q => q.id).join(', ') })}</p>
      )}
      <div className="stream-actions spread">
        <span className="muted">{t('decisions.count', { count: decisionSlides.filter(slide => slide.light === 'done').length,
                                                          total: scope.length })}</span>
        <button className="btn-primary large" disabled={!canApprove} onClick={submit}>{t('decisions.approve')}</button>
      </div>
    </>
  )
}

/**
 * Вопрос на шаге «Решения»: выбор человека, что о нём сказал совет, черновик ADR и само решение —
 * вариант или «оставить открытым».
 */
function DecisionCard({ question, n, options, choice, said, sought, value, rationale, byAi, fixed, busy, onRecheck, onPick,
  onRationale }: Readonly<{
  question: OpenQuestion; n: number; options: { id: string; text: string }[]; choice: string | null
  said: QuestionAnalysis | undefined; sought: boolean; value: string | null; rationale: string; byAi: boolean
  fixed: boolean; busy: boolean
  /** Перепроверить выбор по этому вопросу; нет — сейчас нельзя (решения зафиксированы или совет занят). */
  onRecheck?: () => void
  onPick: (proposal: string | null) => void; onRationale: (text: string) => void
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
    <div className="check problem">
      <p><strong>{t('decisions.conflict')}</strong> {[said.reason, consequences(said, t)].filter(Boolean).join(' ')}</p>
      {said.fixes.length > 0 && (
        <>
          <p><strong>{t('decisions.fixes')}</strong></p>
          <ol className="decision-fixes">{said.fixes.map(fix => (
            <li key={`${fix.question_id}:${fix.change}`}>
              <strong>{fix.question_id}</strong> — {fix.change}{fix.why && ` ${t('decisions.fixWhy', { why: fix.why })}`}
            </li>
          ))}</ol>
          {said.fixes.some(fix => fix.question_id === question.id) && <p>{t('decisions.fixHere')}</p>}
        </>
      )}
    </div>
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
      {onRecheck && said && (
        <p className="fragment-note">
          <button className="btn-link" onClick={onRecheck}>{t('decisions.recheck')}</button> {t('decisions.recheckHint')}
        </p>
      )}
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
 * вернуться к вопросу. Утвердить итоги можно, когда их не держат ни открытые вопросы, ни пробелы;
 * утверждённые выгружают в заметки.
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
  const known = knownDecisions(stream)
  const adrs = new Map(scope.flatMap((question, n) => {
    const proposal = known.find(d => d.question_id === question.id)?.proposal
    return proposal ? [[`ADR-${n + 1}`, { question: question.id, text: textOf(proposal) }] as const] : []
  }))
  const questions = new Map(scope.map(q => [q.id, q.text]))
  // Прошлые решения проекта, отобранные для потока: итог ссылается на те, на которые опирается.
  const projects = new Map((stream.project_decisions ?? []).map(d => [d.adr_id, d.decision]))
  const assemble = () => void retry.go(() => startOrFollow(
    () => api.seekOutcomes(council.id, group.id), council, c => streamOf(c, group.id)?.outcomes))
  // Утверждены — утвердить те же ещё раз ничего не поменяет: дальше документация.
  const approved = !!run?.approved
  const touched = run?.touched ?? []
  // Итог готов — готов; его задевают новые решения или что-то держит — ход за человеком.
  const outcomeSlides: Slide[] = (run?.outcomes ?? []).map(outcome => ({
    id: outcome.id, title: outcome.title,
    light: !touched.some(touch => touch.outcome_id === outcome.id) && outcomeReady(outcome) ? 'done' : 'yours',
  }))
  // Итоги держит открытый вопрос или пробел — утверждать рано: сервер ответит 409.
  const held = !!run && !outcomesFree(run.outcomes)
  const canApprove = run?.state === 'done' && run.outcomes.length > 0 && !approve.busy && !stale && touched.length === 0
    && !held
  // Закреплённый итог, который задевают новые решения: оставить или пересобрать — решает человек.
  const settling = useAction(onChange)
  const settle = (outcome: string, rebuild: boolean) => void settling.go(async () => {
    try {
      return await api.settleTouch(council.id, { run: structure.run, revision: structure.revision }, group.id,
                                   run?.run ?? '', outcome, rebuild)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  })
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
  // Сохранённые итоги — пока сборки нет (поток до неё не дошёл или её не запускали): закрепятся, если решения
  // не поменяются. Их видно, но утверждать тут нечего.
  const saved = run ? [] : stream.saved_outcomes
  const savedSlides: Slide[] = saved.map(outcome => ({ id: outcome.id, title: outcome.title, light: 'done' }))
  const savedCards = saved.length > 0 && (
    <>
      <p className="fragment-note">{t('outcomes.saved')}</p>
      <Slider slides={savedSlides} label={t('outcomes.slides')}>
        {n => (
          <OutcomeCard key={saved[n].id} outcome={saved[n]} n={n + 1} adrs={adrs} questions={questions}
                       projects={projects} fragments={fragments} onQuestion={onQuestion} gaps={gaps} kept />
        )}
      </Slider>
    </>
  )
  if (!stream.decisions) {
    return saved.length > 0 ? (
      <>
        <section className="card panel" aria-labelledby="step-title">
          <p className="next-caps">{t('outcomes.savedCaps')}</p>
          <h2 id="step-title" className="panel-title large">{t('outcomes.title')}</h2>
          <p className="panel-hint">{t('outcomes.hint')}</p>
        </section>
        {savedCards}
      </>
    ) : null
  }

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
      {savedCards}
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
      {settling.error && <p className="error-text" role="alert">{settling.error}</p>}
      {run && run.outcomes.length > 0 && (
        // Новая сборка — и слайдер заново, с первого итога, который ждёт человека.
        <Slider key={run.run} slides={outcomeSlides} label={t('outcomes.slides')} start={firstOpen(outcomeSlides)}>
          {n => {
            const outcome = run.outcomes[n]
            return (
              <OutcomeCard key={outcome.id} outcome={outcome} n={n + 1} adrs={adrs} questions={questions}
                           projects={projects} fragments={fragments} onQuestion={onQuestion} gaps={gaps}
                           kept={run.kept.includes(outcome.id)}
                           touch={touched.find(touch => touch.outcome_id === outcome.id)} busy={settling.busy}
                           onSettle={rebuild => settle(outcome.id, rebuild)} />
            )
          }}
        </Slider>
      )}
      {run && run.uncovered_adr_ids.length > 0 && (
        <p className="fragment-note">{t('outcomes.uncovered', { ids: run.uncovered_adr_ids.join(', ') })}</p>
      )}
      {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
      {canApprove && !approved && <p className="fragment-note">{t('outcomes.approveHint')}</p>}
      {run?.state === 'done' && held && <p className="fragment-note">{t('outcomes.heldHint')}</p>}
      {touched.length > 0 && <p className="fragment-note">{t('outcomes.touchedHint')}</p>}
      <div className="stream-actions spread">
        <button className="btn-link" onClick={onBack}>{t('outcomes.change')}</button>
        {approved
          ? <button className="btn-primary large" onClick={onApproved}>{t('outcomes.toNotes')}</button>
          : <button className="btn-primary large" disabled={!canApprove} onClick={pass}>{t('outcomes.approve')}</button>}
      </div>
    </>
  )
}

/** Итог: что меняется, на каких решениях стоит, что соблюдать, когда готово — и чего не хватает. */
function OutcomeCard({ outcome, n, adrs, questions, projects = new Map(), fragments, onQuestion, gaps, kept = false,
  touch, busy = false, onSettle }: Readonly<{
  outcome: Outcome; n: number; adrs: Map<string, { question: string; text: string }>
  questions: Map<string, string>
  /** Прошлые решения проекта, отобранные для потока: номер — что решено. */
  projects?: Map<string, string>
  fragments: Map<number, LabeledFragment>
  onQuestion: (question: string) => void; gaps: Gaps
  /** Закреплён: был готов, его решения те же — его не пересобирали. touch — его задевают новые решения. */
  kept?: boolean; touch?: OutcomeTouch; busy?: boolean; onSettle?: (rebuild: boolean) => void
}>) {
  const { t } = useTranslation()
  const name = `outcome-${outcome.id}`
  const blocked = outcome.blocked_by
  const earlier = outcome.project_decision_ids ?? []
  const relies = outcome.relies_on_adr_ids ?? []
  const notes = outcome.adr_notes ?? {}
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
        <span className="fragment-id">{outcome.id}</span>
        <h3 id={`${name}-title`} className="question-text">{outcome.title}</h3>
        {pill}
        {kept && <span className="pill" title={t('outcomes.keptHint')}>{t('outcomes.kept')}</span>}
      </div>
      {touch && (
        <div className="check problem outcome-touch">
          <span>{t('outcomes.touched', { ids: touch.adr_ids.join(', ') })}{touch.reason ? ` ${touch.reason}` : ''}</span>
          <span className="outcome-touch-actions">
            <button className="btn-secondary" disabled={busy} onClick={() => onSettle?.(false)}>{t('outcomes.keepAsIs')}</button>
            <button className="btn-secondary" disabled={busy} onClick={() => onSettle?.(true)}>{t('outcomes.rebuild')}</button>
          </span>
        </div>
      )}
      {blocked.length > 0 && (
        <div className="check problem outcome-missing">
          <span>{t('outcomes.missing', { ids: blocked.join(', ') })}</span>
          <button className="btn-secondary" onClick={() => onQuestion(blocked[0])}>{t('outcomes.back')}</button>
        </div>
      )}
      <dl className="outcome-rows">
        <dt>{t('outcomes.changes')}</dt>
        <dd>{outcome.behavior}</dd>
        {outcome.adr_ids.length + blocked.length + earlier.length + relies.length > 0 && (
          <>
            <dt>{t('outcomes.decisions')}</dt>
            <dd>
              <ul>
                {outcome.adr_ids.map(id => {
                  const adr = adrs.get(id)
                  return (
                    <li key={id}>
                      <span className="fragment-id">{adr?.question ?? id}</span> {adr?.text ?? id}
                      {notes[id] && <span className="outcome-note"> → {notes[id]}</span>}
                    </li>
                  )
                })}
                {relies.map(id => {
                  const adr = adrs.get(id)
                  return (
                    <li key={id} className="outcome-relies">
                      <span className="fragment-id">{adr?.question ?? id}</span> {t('outcomes.relies')} — {adr?.text ?? id}
                    </li>
                  )
                })}
                {earlier.map(id => (
                  <li key={id} className="outcome-project">
                    <span className="fragment-id">{id}</span> {t('outcomes.project')} — {projects.get(id) ?? id}
                  </li>
                ))}
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
  // Свои варианты — из утверждённого выбора, а пока его нет (после правки отбора) — из прежней работы: на них
  // держатся прежние решения, а с ними и сохранённые итоги.
  for (const { question_id, proposal, text } of stream.choices ?? stream.earlier.map(work => work.choice)) {
    if (proposal && text) found.set(question_id, [...(found.get(question_id) ?? []), { id: proposal, text }])
  }
  return found
}

/** Черновик отбора вопросов: к какому поиску, какие найденные убраны, какие свои добавлены. */
interface ScopeDraft { run: string; removed: string[]; added: string[] }

/** Пробелы из итогов — в черновик отбора: has — он уже там, add — добавить. */
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

/**
 * Вопрос — в черновик: уже там — как есть; такой найденный советом убрали — он возвращается (со своим номером и всей
 * работой по нему), а не встаёт рядом своим вопросом; иначе — свой вопрос.
 */
function withQuestion(draft: ScopeDraft, stream: Stream, question: string): ScopeDraft {
  if (inDraft(draft, stream, question)) return draft
  const found = (stream.questions?.questions ?? []).find(q => sameQuestion(q.text) === sameQuestion(question))
  if (found) return { ...draft, removed: draft.removed.filter(id => id !== found.id) }
  return { ...draft, added: [...draft.added, squash(question)] }
}

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

/**
 * Решения, какие известны сейчас: зафиксированные, а пока их нет — прежние по тем же вопросам к тому же выбору
 * (выбор ещё не утверждали — к прежнему). Как known_decisions на сервере: по ним видны номера ADR в сохранённом.
 */
const knownDecisions = (stream: Stream): Decision[] => stream.decisions ?? (stream.scope ?? []).flatMap(question => {
  const work = earlierOf(stream, question)
  const choice = stream.choices?.find(c => c.question_id === question.id)
  return work?.decision && (!stream.choices || (choice && sameChoice(work.choice, choice))) ? [work.decision] : []
})

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
