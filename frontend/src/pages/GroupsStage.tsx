import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import {
  api, ApiError, councilPath, groupsConfirmed, startOrFollow, structureIsStale,
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
 * разделить и переименовать группы и вернуть их как предложил совет. Подтверждённые группы
 * становятся потоками.
 */
export function GroupsStage({ council, settings, onStart }: Readonly<{
  council: Council; settings: Settings; onStart: (started: Council) => void
}>) {
  const { t } = useTranslation()
  const structure = council.structure
  const restart = () => startOrFollow(() => api.startStructure(council.id), council.id, c => c.structure)
  const again = useAction(onStart)
  const edits = useGroupEdits(council.id, onStart)
  // Ответ на правку мог сменить экран: группы раскладывают заново или их стёрла новая нарезка.
  // Тогда ошибка правки — здесь, над тем, что показано вместо групп.
  const lost = structure?.state !== 'done' && edits.error
    ? <p className="error-text" role="alert">{edits.error}</p>
    : null

  if (!structure) return (
    <>
      {lost}
      <div className="card placeholder">
        {t('groups.none')} <Link to={councilPath(council.id, 'slices')}>{t('groups.toSlices')}</Link>
      </div>
    </>
  )

  return (
    <div className="slices-layout">
      <div className="slices-main">
        {lost}
        {structure.state === 'done'
          ? <Result council={council} structure={structure} restart={restart} again={again} edits={edits} />
          : <RunStatus run={structure} kind="groups" restart={restart} onStart={onStart} />}
      </div>
      <aside className="slices-side">
        {structure.state === 'done' && (
          <Confirm council={council} structure={structure} busy={again.busy || edits.busy} edits={edits} />
        )}
        <Progress steps={structure.steps} models={settings.models} />
      </aside>
    </div>
  )
}

/** Где правили, если это подтверждение: не буква, с группой не спутать. */
const CONFIRM = 'confirm'

/**
 * Правки групп и их подтверждение: busy, ошибка и где правили — там её и показать. Живут
 * выше экрана итога: ответ на правку может его сменить, а ошибка должна остаться видна.
 * 409 — группы уже разложили заново: правка была к прежним, показываем нынешние.
 */
function useGroupEdits(councilId: string, onChange: (council: Council) => void) {
  const action = useAction(onChange, 'groups.editFailed')
  const [at, setAt] = useState<string | null>(null)
  const edit = (where: string | null, call: () => Promise<Council>) => {
    setAt(where)
    return action.go(async () => {
      try {
        return await call()
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) onChange(await api.council(councilId))
        throw e
      }
    })
  }
  return { busy: action.busy, error: action.error, at, edit }
}

/** Правки одной группы; каждая отвечает, сохранилась ли. */
interface GroupEdits {
  merge: (other: string) => Promise<boolean>
  split: (fragmentIds: number[], title: string) => Promise<boolean>
  rename: (title: string) => Promise<boolean>
}

function Result({ council, structure, restart, again, edits }: Readonly<{
  council: Council; structure: Structure; restart: () => Promise<Council>
  again: ReturnType<typeof useAction>; edits: ReturnType<typeof useGroupEdits>
}>) {
  const { t } = useTranslation()
  // Правка, пока запускается новая раскладка, пропала бы под ней, поэтому пока идёт одно —
  // другое недоступно.
  const busy = again.busy || edits.busy
  const answered = structure.steps.find(s => s.name === 'structure')?.runs.filter(r => r.state === 'done').length ?? 0
  const fragments = new Map((council.slicing?.fragments ?? []).map(f => [f.id, f]))
  const stale = structureIsStale(council)
  // Типы поменяли после раскладки — группы могли устареть, и новая раскладка всё равно
  // заменит правки. Править их можно, разложив заново.
  const locked = busy || stale
  const { id } = council
  const at = { run: structure.run, revision: structure.revision }

  const editsOf = (group: Group): GroupEdits => ({
    merge: other => edits.edit(group.id, () => api.mergeGroups(id, at, group.id, other)),
    split: (ids, title) => edits.edit(group.id, () => api.splitGroup(id, at, group.id, ids, title)),
    rename: title => edits.edit(group.id, () => api.renameGroup(id, at, group.id, title)),
  })
  // Группы, где правили, после ответа может уже не быть (409 — разложили заново): тогда в шапку.
  // Ошибка подтверждения — у его кнопки.
  const target = edits.at === CONFIRM || structure.groups.some(g => g.id === edits.at) ? edits.at : null
  const errorAt = (where: string | null) => (target === where ? edits.error : null)

  return (
    <>
      <Panel title={t(structure.edited ? 'groups.editedTitle' : 'groups.title', { count: structure.groups.length })}
             hint={t('groups.hint')} large aside={<ReadyBadge count={answered} />}>
        {structure.edited && (
          <p className="fragment-note">
            {t('groups.edited')}{' '}
            <button className="btn-link" disabled={locked}
                    onClick={() => void edits.edit(null, () => api.restoreGroups(id, at))}>
              {t('groups.restore')}
            </button>
          </p>
        )}
        {stale && (
          <p className="fragment-note">
            {t('groups.stale')}{' '}
            <button className="btn-link" onClick={() => void again.go(restart)} disabled={busy}>{t('groups.again')}</button>
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
      {/* Состав группы поменялся (объединение, откат) — карточка заново: черновик разделения
          был к прежнему составу. */}
      {structure.groups.map(group => (
        <GroupCard key={`${group.id}:${group.fragment_ids.join(',')}`} group={group} groups={structure.groups}
                   fragments={fragments} edits={editsOf(group)} busy={locked} error={errorAt(group.id)}
                   relations={structure.relations.filter(r => r.source === group.id || r.target === group.id)} />
      ))}
    </>
  )
}

/**
 * «Дальше»: подтвердить группы — каждая станет потоком — и перейти к потокам. Подтверждаются
 * группы на экране: поправили их в другой вкладке или разложили заново — сервер откажет, и
 * видны станут нынешние. Устаревшие после смены типов не подтвердить: сперва разложить заново.
 */
function Confirm({ council, structure, busy, edits }: Readonly<{
  council: Council; structure: Structure; busy: boolean; edits: ReturnType<typeof useGroupEdits>
}>) {
  const { t } = useTranslation()
  const nav = useNavigate()
  const confirmed = groupsConfirmed(council)
  const stale = structureIsStale(council)
  const streams = councilPath(council.id, 'streams')
  const confirm = async () => {
    const at = { run: structure.run, revision: structure.revision }
    if (await edits.edit(CONFIRM, () => api.confirmGroups(council.id, at))) nav(streams)
  }

  return (
    <section className="card panel next-step" aria-labelledby="confirm-title">
      <p className="next-caps">{t('next.caps')}</p>
      <h2 id="confirm-title" className="panel-title">{t('confirm.title')}</h2>
      <p className="panel-hint">{t(confirmed ? 'confirm.done' : 'confirm.hint')}</p>
      {stale && !confirmed && <p className="fragment-note">{t('confirm.stale')}</p>}
      {edits.at === CONFIRM && edits.error && <p className="error-text" role="alert">{edits.error}</p>}
      {confirmed
        ? <Link className="btn-primary large block" to={streams}>{t('confirm.open')}</Link>
        : <button className="btn-primary large block" onClick={() => void confirm()} disabled={busy || stale}>
            {t('confirm.confirm')}
          </button>}
    </section>
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
        {/* Черновик названия — к этому названию: откат поменял его — черновик ни к чему. */}
        <GroupTitle key={group.title} id={titleId} group={group} busy={busy} rename={edits.rename} />
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
                    <input type="checkbox" aria-label={`F${id}`} checked={picked.has(id)} disabled={busy}
                           onChange={() => toggle(id)} />
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
                 value={newTitle} maxLength={200} readOnly={busy} onChange={e => setNewTitle(e.target.value)} />
          <button type="button" className="btn-secondary" disabled={busy} onClick={stopSplitting}>
            {t('groups.cancel')}
          </button>
          <button type="submit" className="btn-primary" disabled={busy || !canSplit}>{t('groups.split')}</button>
        </form>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  )
}

/**
 * Название группы: щелчок — правка на месте. Enter или уход из поля сохраняют, Escape — отмена.
 * Пока правка сохраняется, поле не меняется и не закрывается: ответ применит отправленное.
 */
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
                 value={draft} maxLength={200} autoFocus readOnly={busy} onChange={e => setDraft(e.target.value)}
                 onBlur={() => void save()}
                 onKeyDown={e => {
                   if (e.key === 'Enter') { e.preventDefault(); void save() }
                   if (e.key === 'Escape' && !busy) setDraft(null)
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
            <button key={g.id} role="menuitem" disabled={busy} onClick={() => { setOpen(false); void merge(g.id) }}>
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
