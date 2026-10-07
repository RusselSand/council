import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import {
  api, ApiError, councilPath, groupsConfirmed, startOrFollow, structureIsStale,
  type Council, type Group, type IdeaDiscovery, type LabeledFragment, type Model, type Settings,
  type Stream, type Structure,
} from '../api'
import { LabelPill } from '../components/Labels'
import { modelOf } from '../components/ModelBadge'
import { Panel } from '../components/Panel'
import { Progress } from '../components/Progress'
import { CHAIN, chainLight, streamLight, type ChainStep } from '../light'
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
  const [view, setView] = useState<ChainStep>(stream.idea ? 'questions' : 'group')
  const group = structure.groups.find(g => g.id === stream.group)
  if (!group) return null  // поток без группы не бывает: состав меняют, только сняв подтверждение
  const search = stream.discovery

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
        {view === 'questions' && stream.idea
          ? <QuestionsStep stream={stream} onBack={() => setView('group')} />
          // Поиск закончился — черновик заново, из предложения совета.
          : <GroupStep key={`${search?.run}:${search?.state}`} council={council} structure={structure}
                       stream={stream} group={group} models={models} onChange={onChange}
                       onApproved={() => setView('questions')} />}
      </div>
      <aside className="streams-side">
        {search && <Progress steps={search.steps} models={models} />}
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
  if (stream.idea) return t('streams.atQuestions')
  if (stream.discovery?.state === 'running') return t('streams.seeking')
  if (stream.discovery?.state === 'failed') return t('streams.failed')
  return t('streams.yourMove')
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
                {state !== 'idle' && <span className="sr-only"> ({t(`light.${state}`)})</span>}
              </span>
              {step === 'group' && <span className="segment-sub">{ideaStatus(stream, group, t)}</span>}
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
  const reached = stream.idea ? 1 : 0
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
                  {step === 'group' ? groupStatus(stream, group, t) : t(i === reached ? 'chain.soon' : 'chain.notStarted')}
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
  const canApprove = !busy && !sought && text !== '' && !structureIsStale(council)

  const submit = () => void approve.go(async () => {
    try {
      return await api.approveIdea(council.id, { run: structure.run, revision: structure.revision }, group.id, text)
    } catch (e) {
      // Группы уже другие (поправили в другой вкладке) — показываем нынешние.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  }, onApproved)
  const seekAgain = () => void retry.go(() => startOrFollow(() => api.seekIdea(council.id, group.id), council.id))

  let idea
  if (!group.missing_idea) idea = <TextIdea group={group} fragments={fragments} />
  else if (sought) idea = <p className="muted">{t('idea.seeking')} {t('run.note')}</p>
  else idea = (
    <>
      {search?.state === 'failed' && (
        <>
          <p className="error-text" role="alert">{search.error}</p>
          {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
          <p className="fragment-note">
            {t('idea.failedNote')}{' '}
            <button className="btn-link" disabled={busy} onClick={seekAgain}>{t('run.retry')}</button>
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

/** Шаг «Вопросы» пока не готов: здесь утверждённая идея и дорога назад, к её правке. */
function QuestionsStep({ stream, onBack }: Readonly<{ stream: Stream; onBack: () => void }>) {
  const { t } = useTranslation()
  const idea = stream.idea
  if (!idea) return null
  return (
    <>
      <section className="card panel" aria-labelledby="step-title">
        <p className="next-caps">{t('questions.caps')}</p>
        <h2 id="step-title" className="panel-title large">{t('questions.title')}</h2>
        <p className="panel-hint">{t('questions.hint')}</p>
      </section>
      <Panel title={t('questions.idea')} caps aside={<span className="source-tag">{t(`questions.by.${idea.by}`)}</span>}>
        <p className="idea-fixed">{idea.text}</p>
        <button className="btn-link" onClick={onBack}>{t('questions.change')}</button>
      </Panel>
      <div className="card placeholder">{t('questions.stub')}</div>
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
