import { useState } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import {
  api, ApiError, runningFrom, startOrFollow, streamOf, structureIsStale,
  type Council, type Group, type IdeaDiscovery, type LabeledFragment, type Model, type Stream, type Structure,
} from '../api'
import { LabelPill } from '../components/Labels'
import { modelOf } from '../components/ModelBadge'
import { fragmentRange, squash } from '../text'
import { useAction } from '../useAction'

type T = TFunction

/** Что с идеей потока: утверждена, записана в тексте, ищется, упала, найдена или за вами. */
export function ideaStatus(stream: Stream, group: Group, t: T): string {
  const search = stream.discovery
  if (stream.idea) return t('chain.ideaApproved')
  if (!group.missing_idea) return t('chain.ideaText')
  if (search?.state === 'running') return t('chain.ideaSeeking')
  if (search?.state === 'failed') return t('chain.ideaFailed')
  if (search?.proposal?.idea) return t('chain.ideaFound')
  return t('chain.ideaNone')
}

/**
 * Идея группы — на этапе «Группы», после подтверждения: фрагменты группы и её идея. Записана в тексте — её
 * только утверждают. Нет — её ищет совет; человек берёт предложение или другой вариант, правит формулировку
 * или пишет свою и утверждает. Когда идеи всех групп утверждены — дальше исследование.
 */
export function IdeaStep({ council, structure, stream, group, models, onChange }: Readonly<{
  council: Council; structure: Structure; stream: Stream; group: Group; models: Model[]
  onChange: (council: Council) => void
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
  })
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
      <section className="card panel" aria-labelledby={`idea-${group.id}`}>
        <p className="next-caps">{t(sought ? 'idea.capsAi' : 'idea.caps')}</p>
        <h3 id={`idea-${group.id}`} className="panel-title large">
          <span className="group-letter">{group.id}</span> {group.title}
          {' · '}<span className={`light-dot ${stream.idea ? 'done' : 'yours'}`} aria-hidden="true" />
          {ideaStatus(stream, group, t)}
        </h3>
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

function offeredBy(search: IdeaDiscovery | null): { idea: string; evidence: number[]; reason: string }[] {
  if (!search) return []
  const proposal = search.proposal?.idea ? [{ ...search.proposal, idea: search.proposal.idea }] : []
  return [...proposal, ...search.options]
}

