import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import {
  api, councilPath, startOrFollow, structureIsStale,
  type Council, type Group, type GroupRelation, type LabeledFragment, type Settings, type Structure,
} from '../api'
import { LabelPill } from '../components/Labels'
import { Panel } from '../components/Panel'
import { Progress } from '../components/Progress'
import { ReadyBadge, RunStatus } from '../components/RunStatus'
import { useStart } from '../useStart'

/**
 * Группы: совет раскладывает фрагменты готовой нарезки вокруг идей — участники по
 * отдельности, судья только там, где раскладки разошлись. Каждая группа потом станет потоком.
 */
export function GroupsStage({ council, settings, onStart }: Readonly<{
  council: Council; settings: Settings; onStart: (started: Council) => void
}>) {
  const { t } = useTranslation()
  const structure = council.structure
  const restart = () => startOrFollow(() => api.startStructure(council.id), council.id)

  if (!structure) return (
    <div className="card placeholder">
      {t('groups.none')} <Link to={councilPath(council.id, 'slices')}>{t('groups.toSlices')}</Link>
    </div>
  )

  return (
    <div className="slices-layout">
      <div className="slices-main">
        {structure.state === 'done'
          ? <Result council={council} structure={structure} restart={restart} onStart={onStart} />
          : <RunStatus run={structure} kind="groups" restart={restart} onStart={onStart} />}
      </div>
      <aside className="slices-side">
        <Progress steps={structure.steps} models={settings.models} />
      </aside>
    </div>
  )
}

function Result({ council, structure, restart, onStart }: Readonly<{
  council: Council; structure: Structure
  restart: () => Promise<Council>; onStart: (started: Council) => void
}>) {
  const { t } = useTranslation()
  const { busy, error, go } = useStart(onStart)
  const answered = structure.steps.find(s => s.name === 'structure')?.runs.filter(r => r.state === 'done').length ?? 0
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const stale = structureIsStale(council)

  return (
    <>
      <Panel title={t('groups.title', { count: structure.groups.length })} hint={t('groups.hint')} large
             aside={<ReadyBadge count={answered} />}>
        {stale && (
          <p className="fragment-note">
            {t('groups.stale')}{' '}
            <button className="btn-link" onClick={() => void go(restart)} disabled={busy}>{t('groups.again')}</button>
          </p>
        )}
        {error && <p className="error-text" role="alert">{error}</p>}
        {structure.decisions.map(d => (
          <p key={d.issue} className="fragment-note">
            {t('groups.decision', { issue: d.issue, decision: d.decision, reason: d.reason })}
          </p>
        ))}
      </Panel>
      {structure.groups.map(group => (
        <GroupCard key={group.id} group={group} groups={structure.groups} fragments={fragments}
                   relations={structure.relations.filter(r => r.source === group.id || r.target === group.id)} />
      ))}
    </>
  )
}

function GroupCard({ group, groups, fragments, relations }: Readonly<{
  group: Group; groups: Group[]; fragments: Map<number, LabeledFragment>; relations: GroupRelation[]
}>) {
  const { t } = useTranslation()
  const titleId = `group-${group.id}`
  return (
    <section className="card panel group-card" aria-labelledby={titleId}>
      <div className="group-head">
        <span className="group-letter" aria-hidden="true">{group.id}</span>
        <h2 id={titleId} className="panel-title">{group.title}</h2>
        {group.missing_idea && <span className="group-tag">{t('groups.missingIdea')}</span>}
        {relations.map(r => <span key={`${r.source}-${r.target}`} className="group-tag">{relationTag(r, group, t)}</span>)}
        <span className="group-actions">
          <button className="btn-secondary" disabled title={t('groups.soon')}>{t('groups.merge')}</button>
          <button className="btn-secondary" disabled title={t('groups.soon')}>{t('groups.split')}</button>
        </span>
      </div>
      {/* Почему связаны — у той группы, от которой связь идёт: у второй только метка. */}
      {relations.filter(r => r.reason && r.source === group.id).map(r => (
        <p key={`${r.source}-${r.target}-why`} className="group-note">{r.reason}</p>
      ))}
      {group.missing_idea && <p className="group-note">{t('groups.missingIdeaNote')}</p>}
      <ol className="group-fragments">
        {group.fragment_ids.map(id => {
          const fragment = fragments.get(id)
          const others = groups.filter(g => g.id !== group.id && g.fragment_ids.includes(id)).map(g => g.id)
          return (
            <li key={id} className="group-fragment">
              <span className="fragment-id">F{id}</span>
              {fragment && <LabelPill label={fragment.label} />}
              <span className="group-fragment-text">{fragment?.text ?? '—'}</span>
              {others.length > 0 && (
                <span className="shared-chip">{t('groups.shared', { groups: others.join(', ') })}</span>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

/** Связь с точки зрения этой группы: «зависит от A», «от неё зависит B», «связана с C». */
function relationTag(relation: GroupRelation, group: Group, t: ReturnType<typeof useTranslation>['t']): string {
  const outgoing = relation.source === group.id
  const other = outgoing ? relation.target : relation.source
  if (relation.type === 'related') return t('groups.relatedTo', { group: other })
  return t(outgoing ? 'groups.dependsOn' : 'groups.dependedBy', { group: other })
}
