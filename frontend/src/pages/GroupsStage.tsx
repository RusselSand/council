import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import {
  api, ApiError, councilPath, startOrFollow, structureIsStale,
  type Council, type Group, type GroupRelation, type LabeledFragment, type Settings, type Structure,
} from '../api'
import { LabelPill } from '../components/Labels'
import { Panel } from '../components/Panel'
import { Progress } from '../components/Progress'
import { ReadyBadge, RunStatus } from '../components/RunStatus'
import { useAction } from '../useAction'

/**
 * Группы: совет раскладывает фрагменты готовой нарезки вокруг идей — участники по
 * отдельности, судья только там, где раскладки разошлись. Человек может объединить,
 * разделить и переименовать группы и вернуть их как предложил совет. Каждая группа потом
 * станет потоком.
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
          ? <Result council={council} structure={structure} restart={restart} onChange={onStart} />
          : <RunStatus run={structure} kind="groups" restart={restart} onStart={onStart} />}
      </div>
      <aside className="slices-side">
        <Progress steps={structure.steps} models={settings.models} />
      </aside>
    </div>
  )
}

/** Правки одной группы; каждая отвечает, сохранилась ли. */
interface GroupEdits {
  merge: (other: string) => Promise<boolean>
  split: (fragmentIds: number[], title: string) => Promise<boolean>
  rename: (title: string) => Promise<boolean>
}

function Result({ council, structure, restart, onChange }: Readonly<{
  council: Council; structure: Structure
  restart: () => Promise<Council>; onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const again = useAction(onChange)
  const edits = useAction(onChange, 'groups.editFailed')
  // Где была последняя правка: там и показать, если сервер её не принял.
  const [editedAt, setEditedAt] = useState<string | null>(null)
  const answered = structure.steps.find(s => s.name === 'structure')?.runs.filter(r => r.state === 'done').length ?? 0
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const stale = structureIsStale(council)

  // 409 — группы уже разложили заново: правка была к прежним, показываем нынешние.
  const edit = (where: string | null, call: (run: string) => Promise<Council>) => {
    setEditedAt(where)
    return edits.go(async () => {
      try {
        return await call(structure.run)
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
        throw e
      }
    })
  }
  const editsOf = (group: Group): GroupEdits => ({
    merge: other => edit(group.id, run => api.mergeGroups(council.id, run, group.id, other)),
    split: (ids, title) => edit(group.id, run => api.splitGroup(council.id, run, group.id, ids, title)),
    rename: title => edit(group.id, run => api.renameGroup(council.id, run, group.id, title)),
  })
  const errorAt = (where: string | null) => (editedAt === where ? edits.error : null)

  return (
    <>
      <Panel title={t(structure.edited ? 'groups.editedTitle' : 'groups.title', { count: structure.groups.length })}
             hint={t('groups.hint')} large aside={<ReadyBadge count={answered} />}>
        {structure.edited && (
          <p className="fragment-note">
            {t('groups.edited')}{' '}
            <button className="btn-link" disabled={edits.busy}
                    onClick={() => void edit(null, run => api.restoreGroups(council.id, run))}>
              {t('groups.restore')}
            </button>
          </p>
        )}
        {stale && (
          <p className="fragment-note">
            {t('groups.stale')}{' '}
            <button className="btn-link" onClick={() => void again.go(restart)} disabled={again.busy}>{t('groups.again')}</button>
          </p>
        )}
        {again.error && <p className="error-text" role="alert">{again.error}</p>}
        {errorAt(null) && <p className="error-text" role="alert">{errorAt(null)}</p>}
        {structure.decisions.map(d => (
          <p key={d.issue} className="fragment-note">
            {t('groups.decision', { issue: d.issue, decision: d.decision, reason: d.reason })}
          </p>
        ))}
      </Panel>
      {structure.groups.map(group => (
        <GroupCard key={group.id} group={group} groups={structure.groups} fragments={fragments}
                   relations={structure.relations.filter(r => r.source === group.id || r.target === group.id)}
                   edits={editsOf(group)} busy={edits.busy} error={errorAt(group.id)} />
      ))}
    </>
  )
}

function GroupCard({ group, groups, fragments, relations, edits, busy, error }: Readonly<{
  group: Group; groups: Group[]; fragments: Map<number, LabeledFragment>; relations: GroupRelation[]
  edits: GroupEdits; busy: boolean; error: string | null
}>) {
  const { t } = useTranslation()
  const titleId = `group-${group.id}`
  // Разделение: отмеченные фрагменты уходят в новую группу с названием newTitle.
  const [splitting, setSplitting] = useState(false)
  const [picked, setPicked] = useState<ReadonlySet<number>>(new Set())
  const [newTitle, setNewTitle] = useState('')
  const canSplit = picked.size > 0 && picked.size < group.fragment_ids.length && newTitle.trim() !== ''

  const stopSplitting = () => { setSplitting(false); setPicked(new Set()); setNewTitle('') }
  const toggle = (id: number) => setPicked(before => {
    const next = new Set(before)
    if (!next.delete(id)) next.add(id)
    return next
  })
  const submitSplit = async (event: FormEvent) => {
    event.preventDefault()
    if (canSplit && await edits.split(group.fragment_ids.filter(id => picked.has(id)), newTitle)) stopSplitting()
  }

  return (
    <section className="card panel group-card" aria-labelledby={titleId}>
      <div className="group-head">
        <span className="group-letter" aria-hidden="true">{group.id}</span>
        <GroupTitle id={titleId} group={group} busy={busy} rename={edits.rename} />
        {group.missing_idea && <span className="group-tag">{t('groups.missingIdea')}</span>}
        {relations.map(r => <span key={`${r.source}-${r.target}`} className="group-tag">{relationTag(r, group, t)}</span>)}
        <span className="group-actions">
          <MergeMenu others={groups.filter(g => g.id !== group.id)} busy={busy} merge={edits.merge} />
          <button className="btn-secondary" disabled={busy || splitting || group.fragment_ids.length < 2}
                  onClick={() => setSplitting(true)}>
            {t('groups.split')}
          </button>
        </span>
      </div>
      {/* Почему связаны — у той группы, от которой связь идёт: у второй только метка. */}
      {relations.filter(r => r.reason && r.source === group.id).map(r => (
        <p key={`${r.source}-${r.target}-why`} className="group-note">{r.reason}</p>
      ))}
      {group.missing_idea && <p className="group-note">{t('groups.missingIdeaNote')}</p>}
      {splitting && <p className="group-note">{t('groups.splitHint')}</p>}
      <ol className="group-fragments">
        {group.fragment_ids.map(id => {
          const fragment = fragments.get(id)
          const others = groups.filter(g => g.id !== group.id && g.fragment_ids.includes(id)).map(g => g.id)
          const row = (
            <>
              <span className="fragment-id">F{id}</span>
              {fragment && <LabelPill label={fragment.label} />}
              <span className="group-fragment-text">{fragment?.text ?? '—'}</span>
              {others.length > 0 && (
                <span className="shared-chip">{t('groups.shared', { groups: others.join(', ') })}</span>
              )}
            </>
          )
          return (
            <li key={id} className="group-fragment">
              {splitting
                ? <label className="group-fragment-pick">
                    <input type="checkbox" aria-label={`F${id}`} checked={picked.has(id)} onChange={() => toggle(id)} />
                    {row}
                  </label>
                : row}
            </li>
          )
        })}
      </ol>
      {splitting && (
        <form className="group-split" aria-label={t('groups.split')} onSubmit={e => void submitSplit(e)}>
          <input className="text-field" aria-label={t('groups.newTitle')} placeholder={t('groups.newTitle')}
                 value={newTitle} maxLength={200} onChange={e => setNewTitle(e.target.value)} />
          <button type="button" className="btn-secondary" onClick={stopSplitting}>{t('groups.cancel')}</button>
          <button type="submit" className="btn-primary" disabled={busy || !canSplit}>{t('groups.split')}</button>
        </form>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  )
}

/** Название группы: щелчок — правка на месте. Enter или уход из поля сохраняют, Escape — отмена. */
function GroupTitle({ id, group, busy, rename }: Readonly<{
  id: string; group: Group; busy: boolean; rename: (title: string) => Promise<boolean>
}>) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<string | null>(null)
  const saving = useRef(false)  // Enter и уход из поля не должны сохранить дважды

  const save = async () => {
    if (draft === null || saving.current) return
    const title = draft.trim()
    if (!title || title === group.title) { setDraft(null); return }
    saving.current = true
    try {
      if (await rename(title)) setDraft(null)
    } finally {
      saving.current = false
    }
  }

  return (
    <h2 id={id} className="panel-title group-title">
      {draft === null
        ? <button className="group-title-button" title={t('groups.rename')} disabled={busy}
                  onClick={() => setDraft(group.title)}>
            {group.title}<span className="group-title-pen" aria-hidden="true">✎</span>
          </button>
        : <input className="text-field group-title-input" aria-label={t('groups.titleField', { group: group.id })}
                 value={draft} maxLength={200} autoFocus onChange={e => setDraft(e.target.value)}
                 onBlur={() => void save()}
                 onKeyDown={e => {
                   if (e.key === 'Enter') { e.preventDefault(); void save() }
                   if (e.key === 'Escape') setDraft(null)
                 }} />}
    </h2>
  )
}

/** «Объединить с…»: список остальных групп; выбор сразу объединяет. Закрывается щелчком мимо и Escape. */
function MergeMenu({ others, busy, merge }: Readonly<{
  others: Group[]; busy: boolean; merge: (other: string) => Promise<boolean>
}>) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onPress = (e: MouseEvent) => {
      if (e.target instanceof Node && !box.current?.contains(e.target)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onPress)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onPress)
    }
  }, [open])

  return (
    <span className="merge" ref={box}>
      <button className="btn-secondary" aria-haspopup="menu" aria-expanded={open}
              disabled={busy || others.length === 0} onClick={() => setOpen(!open)}>
        {t('groups.merge')}
      </button>
      {open && (
        <span className="merge-menu" role="menu" aria-label={t('groups.mergeMenu')}>
          {others.map(g => (
            <button key={g.id} role="menuitem" onClick={() => { setOpen(false); void merge(g.id) }}>
              <span className="group-letter">{g.id}</span> {g.title}
            </button>
          ))}
        </span>
      )}
    </span>
  )
}

/** Связь с точки зрения этой группы: «зависит от A», «от неё зависит B», «связана с C». */
function relationTag(relation: GroupRelation, group: Group, t: ReturnType<typeof useTranslation>['t']): string {
  const outgoing = relation.source === group.id
  const other = outgoing ? relation.target : relation.source
  if (relation.type === 'related') return t('groups.relatedTo', { group: other })
  return t(outgoing ? 'groups.dependsOn' : 'groups.dependedBy', { group: other })
}
