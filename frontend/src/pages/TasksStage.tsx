import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import {
  api, ApiError, councilPath, groupsConfirmed, issuesOf, notesOf, startOrFollow, structureIsStale, tasksBasis,
  tasksExported, tasksStale, tasksWaitFor,
  type Council, type GroupsVersion, type Issue, type LabeledFragment, type NotePlan, type Settings, type TaskPlan,
} from '../api'
import { Progress } from '../components/Progress'
import { firstOpen, Slider, type Slide } from '../components/Slider'
import { shortSha } from '../text'
import { useAction } from '../useAction'

/**
 * Задачи — на весь совет, после потоков. Когда итоги всех потоков утверждены и выгружены в заметки, совет строит
 * один план задач для coding agents — по всем итогам разом, по порядку и с зависимостями. У каждой задачи ровно
 * один итог; что неясно в реализации — в её открытых вопросах. План выгружают файлами в папку задач проекта.
 * Потоки поменяли после плана — видно, что он устарел; сбрасывает его человек.
 */
export function TasksStage({ council, settings, onChange }: Readonly<{
  council: Council; settings: Settings; onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const planning = useAction(onChange, 'tasks.planFailed')
  const reset = useAction(onChange, 'tasks.resetFailed')
  const { structure, streams } = council
  if (!structure || !streams || !groupsConfirmed(council)) return (
    <div className="card placeholder">
      {t('tasks.waits')} <Link to={councilPath(council.id, 'structure')}>{t('streams.toGroups')}</Link>
    </div>
  )
  const at: GroupsVersion = { run: structure.run, revision: structure.revision }
  const notes = notesOf(council, settings)
  const issues = issuesOf(council, settings)
  const plan = council.tasks
  const draft = council.tasks_draft
  const waits = new Map(tasksWaitFor(council, notes).map(wait => [wait.group, wait.why]))
  const stale = tasksStale(council)
  const now = tasksBasis(council)
  const changed = streams.filter(stream => plan && plan.basis[stream.group] !== now[stream.group]).map(s => s.group)
  const running = plan?.state === 'running' || draft?.state === 'running'
  const locked = planning.busy || reset.busy || running || structureIsStale(council)
  const canPlan = waits.size === 0 && (!plan || plan.state === 'failed') && !locked
  const titles = new Map(structure.groups.map(group => [group.id, group.title]))
  const build = () => void planning.go(() => startOrFollow(() => api.planTasks(council.id, at), council, c => c.tasks))
  const drop = () => void reset.go(async () => {
    try {
      return await api.resetTasks(council.id, at)
    } catch (e) {
      // Группы уже другие или совет ещё работает с планом (другая вкладка) — показываем нынешнее.
      if (e instanceof ApiError && (e.status === 409 || e.status === 423)) onChange(await api.council(council.id))
      throw e
    }
  })
  // Ход работы — того, что идёт: плана или перевода выгрузки.
  const steps = (draft?.state === 'running' ? draft.steps : plan?.steps) ?? []

  return (
    <div className="streams-layout">
      <div className="streams-main">
        <section className="card panel" aria-labelledby="tasks-title">
          <h2 id="tasks-title" className="panel-title large">{t('tasks.title')}</h2>
          <p className="panel-hint">{t('tasks.hint')}</p>
          <h3 className="panel-title caps section-gap">{t('tasks.streams')}</h3>
          <ul className="repo-list">
            {streams.map(stream => {
              const why = waits.get(stream.group)
              return (
                <li key={stream.group}>
                  <span className="group-letter" aria-hidden="true">{stream.group}</span>{' '}
                  <Link to={councilPath(council.id, `streams/${stream.group}`)}>{titles.get(stream.group) ?? stream.group}</Link>
                  {' — '}
                  <span className={why ? 'muted' : 'check ok'}>{t(why ? `tasks.stream.${why}` : 'tasks.stream.ready')}</span>
                </li>
              )
            })}
          </ul>
          {!notes && <p className="fragment-note">{t('notes.noRoot')}</p>}
          {stale && <p className="fragment-note">{t('tasks.stale', { groups: changed.join(', ') })}</p>}
          {planning.error && <p className="error-text" role="alert">{planning.error}</p>}
          {reset.error && <p className="error-text" role="alert">{reset.error}</p>}
          <div className="stream-actions spread">
            {plan ? <button className="btn-secondary" disabled={locked} onClick={drop}>{t('tasks.reset')}</button> : <span />}
            {(!plan || plan.state === 'failed') && (
              <button className="btn-primary large" disabled={!canPlan} onClick={build}>{t('tasks.plan')}</button>
            )}
          </div>
        </section>
        {plan?.state === 'running' && <p className="muted">{t('tasks.planning')} {t('run.note')}</p>}
        {plan?.state === 'failed' && (
          <div>
            <p className="error-text" role="alert">{plan.error}</p>
            <p className="fragment-note">{t('tasks.failedNote')}</p>
          </div>
        )}
        {plan?.state === 'done' && <Plan council={council} plan={plan} />}
        {plan?.state === 'done' && (
          // Новый черновик — и правки заново, к его файлам.
          <TasksExport key={draft?.run ?? ''} council={council} at={at} plan={plan} root={issues} onChange={onChange} />
        )}
      </div>
      <aside className="streams-side">
        {running && steps.length > 0 && <Progress steps={steps} models={settings.models} />}
      </aside>
    </div>
  )
}

/** Что известно о номерах заметок: итог — его название и поток, решение — его текст. */
interface Known {
  outcomes: Map<string, { title: string; group: string }>
  decisions: Map<string, string>
  fragments: Map<number, LabeledFragment>
}

function knownOf(council: Council): Known {
  const outcomes = new Map<string, { title: string; group: string }>()
  const decisions = new Map<string, string>()
  for (const stream of council.streams ?? []) {
    const refs = stream.notes?.refs ?? {}
    for (const outcome of stream.outcomes?.outcomes ?? []) {
      const id = refs[outcome.id]
      if (id) outcomes.set(id, { title: outcome.title, group: stream.group })
    }
    for (const note of stream.notes?.notes ?? []) if (note.type === 'adr') decisions.set(note.id, note.written)
    for (const decision of stream.project_decisions ?? []) decisions.set(decision.adr_id, decision.decision)
  }
  return { outcomes, decisions, fragments: new Map((council.slicing?.fragments ?? []).map(f => [f.id, f])) }
}

/** План: с какого кода, что в него не вошло — и задачи по порядку. */
function Plan({ council, plan }: Readonly<{ council: Council; plan: TaskPlan }>) {
  const { t } = useTranslation()
  const known = knownOf(council)
  // Номер задачи на весь проект — когда план выгружен или черновик выгрузки собран к нему.
  const record = council.tasks_export?.plan === plan.run ? council.tasks_export : null
  const drafted = council.tasks_draft?.plan === plan.run ? council.tasks_draft : null
  const numbers = new Map((record ?? drafted)?.numbers.map(n => [n.issue_id, n.id]) ?? [])
  const [first] = plan.sources
  let code = t('tasks.noCode')
  if (plan.code && plan.sources.length > 1) {
    code = t('tasks.codeSeveral', { list: plan.sources.map(source => t(source.dirty ? 'tasks.sourceDirty' : 'tasks.source', {
      path: source.path, sha: shortSha(source.commit_sha) })).join('; ') })
  } else if (plan.code) {
    code = t(first?.dirty ? 'tasks.codeDirty' : 'tasks.code', { sha: shortSha(first?.commit_sha ?? '') })
  }
  // Задача с открытыми вопросами — ход за человеком: их решают с агентом, но видеть их надо.
  const slides: Slide[] = plan.issues.map(issue => ({
    id: issue.id, title: issue.title, light: issue.open_questions.length > 0 ? 'yours' : 'done',
  }))
  return (
    <>
      <section className="card panel" aria-label={t('tasks.slides')}>
        <p className="muted">{code}</p>
        {plan.skipped.map(reason => <p key={reason} className="fragment-note">{reason}</p>)}
        {plan.uncovered.length > 0 && <p className="fragment-note">{t('tasks.uncovered', { ids: plan.uncovered.join(', ') })}</p>}
        {plan.issues.length === 0 && <p className="muted">{t('tasks.none')}</p>}
      </section>
      {plan.issues.length > 0 && (
        <Slider key={plan.run} slides={slides} label={t('tasks.slides')} start={firstOpen(slides)}>
          {n => <IssueCard key={plan.issues[n].id} issue={plan.issues[n]} plan={plan} known={known}
                           number={numbers.get(plan.issues[n].id)} />}
        </Slider>
      )}
    </>
  )
}

/** Задача: кому и зачем, где менять и что там сейчас, что сделать, на чём стоит, после чего — и что неясно. */
function IssueCard({ issue, plan, known, number }: Readonly<{
  issue: Issue; plan: TaskPlan; known: Known; number?: string
}>) {
  const { t } = useTranslation()
  const name = `issue-${issue.id}`
  const outcome = known.outcomes.get(issue.outcome_id)
  const titles = new Map(plan.issues.map(other => [other.id, other.title]))
  const limits = (ids: number[]) => (
    <ul>{ids.map(id => <li key={id}><span className="fragment-id">F{id}</span> {known.fragments.get(id)?.text ?? '—'}</li>)}</ul>
  )
  return (
    <section className="card panel" aria-labelledby={`${name}-title`}>
      <div className="question-head">
        <span className="fragment-id">{issue.id}</span>
        {number && <span className="pill ready">{number}</span>}
        <h3 id={`${name}-title`} className="question-text">{issue.title}</h3>
        {issue.open_questions.length > 0 && (
          <span className="pill open">{t('tasks.open', { count: issue.open_questions.length })}</span>
        )}
      </div>
      {number && <p className="fragment-note">{t('tasks.commit', { id: number })}</p>}
      <dl className="outcome-rows">
        <dt>{t('tasks.story')}</dt>
        <dd>{issue.user_story}</dd>
        {issue.main_entry_points.length > 0 && (
          <><dt>{t('tasks.entry')}</dt><dd><ul>{issue.main_entry_points.map(text => <li key={text}><code>{text}</code></li>)}</ul></dd></>
        )}
        {issue.current_state && <><dt>{t('tasks.now')}</dt><dd>{issue.current_state}</dd></>}
        {issue.scope.length > 0 && (
          <><dt>{t('tasks.scope')}</dt><dd><ul>{issue.scope.map(text => <li key={text}>— {text}</li>)}</ul></dd></>
        )}
        <dt>{t('tasks.outcome')}</dt>
        <dd>
          <span className="fragment-id">{issue.outcome_id}</span> {outcome ? `${outcome.title} (${outcome.group})` : ''}
        </dd>
        {issue.adr_ids.length > 0 && (
          <>
            <dt>{t('tasks.decisions')}</dt>
            <dd><ul>{issue.adr_ids.map(id => (
              <li key={id}><span className="fragment-id">{id}</span> {known.decisions.get(id) ?? ''}</li>
            ))}</ul></dd>
          </>
        )}
        {issue.constraint_ids.length > 0 && <><dt>{t('tasks.keep')}</dt><dd>{limits(issue.constraint_ids)}</dd></>}
        {issue.risk_ids.length > 0 && <><dt>{t('tasks.risks')}</dt><dd>{limits(issue.risk_ids)}</dd></>}
        {issue.depends_on.length > 0 && (
          <><dt>{t('tasks.after')}</dt><dd><ul>{issue.depends_on.map(id => (
            <li key={id}><span className="fragment-id">{id}</span> {titles.get(id) ?? ''}</li>
          ))}</ul></dd></>
        )}
        {issue.open_questions.length > 0 && (
          <><dt>{t('tasks.questions')}</dt><dd><ul>{issue.open_questions.map(text => (
            <li key={text} className="outcome-open">— {text}</li>
          ))}</ul></dd></>
        )}
      </dl>
    </section>
  )
}

const ACTION_PILL = { create: 'pill ready', update: 'pill open', same: 'pill', edited: 'pill blocked' } as const

/**
 * Выгрузка плана в папку задач проекта: черновик (номера на весь проект, тексты и что с каждым файлом будет),
 * правки человека и запись. Файл, правленный руками после прошлой выгрузки, совет не трогает.
 */
function TasksExport({ council, at, plan, root, onChange }: Readonly<{
  council: Council; at: GroupsVersion; plan: TaskPlan; root: string | null; onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const draft = council.tasks_draft
  const record = council.tasks_export
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [remove, setRemove] = useState<ReadonlySet<string>>(new Set())
  const drafting = useAction(onChange, 'tasks.draftFailed')
  const act = useAction(onChange, 'tasks.writeFailed')
  const building = draft?.state === 'running'
  const stale = !!draft && draft.plan !== plan.run
  const moved = !!draft && draft.state === 'done' && !!root && draft.root !== root
  const ready = draft?.state === 'done' && !stale && !moved
  const done = tasksExported(council, root)
  const written = !!draft && record?.run === draft.run && done
  const wrote = new Map(written ? record?.notes.map(note => [note.key, note.written]) : [])
  const shown = (note: NotePlan) => wrote.get(note.key) ?? edits[note.key] ?? note.text
  const locked = act.busy || drafting.busy || building || structureIsStale(council)
  const build = () => void drafting.go(() => startOrFollow(() => api.draftTasks(council.id, at), council, c => c.tasks_draft))
  const write = () => void act.go(async () => {
    if (!draft) return council
    const changed = Object.fromEntries(draft.notes.filter(note => edits[note.key] !== undefined
      && edits[note.key] !== note.text).map(note => [note.key, edits[note.key]]))
    try {
      return await api.writeTasks(council.id, at, draft.run, changed, [...remove])
    } catch (e) {
      // Черновик устарел или папка поменялась — показываем нынешнее.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  })

  return (
    <section className="card panel" aria-labelledby="tasks-export-title">
      <h3 id="tasks-export-title" className="panel-title">{t('tasks.export')}</h3>
      {root ? <p className="repo-summary">{t('tasks.where', { root })}</p> : <p className="fragment-note">{t('tasks.noRoot')}</p>}
      {record && (
        <p className={done ? 'check ok' : 'fragment-note'}>
          {t(done ? 'tasks.written' : record.root !== root ? 'tasks.elsewhere' : 'tasks.outdated',
             { count: record.notes.filter(note => !note.kept).length, root: record.root })}
        </p>
      )}
      <div className="stream-actions">
        <button className="btn-secondary" disabled={!root || locked} onClick={build}>
          {t(draft ? 'tasks.rebuild' : 'tasks.build')}
        </button>
      </div>
      {drafting.error && <p className="error-text" role="alert">{drafting.error}</p>}
      {building && <p className="muted">{t('tasks.translating', { language: draft.language })} {t('run.note')}</p>}
      {draft?.state === 'failed' && <p className="error-text" role="alert">{draft.error}</p>}
      {stale && <p className="fragment-note">{t('tasks.draftStale')}</p>}
      {moved && !stale && <p className="fragment-note">{t('tasks.moved')}</p>}
      {ready && (
        <>
          <p className="repo-summary">{t('notes.language', { language: draft.language })}</p>
          <ul className="repo-list">{draft.notes.map(note => (
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
                <textarea className="text-field note-text" aria-label={t('tasks.text', { id: note.id })}
                          value={shown(note)} readOnly={locked || written}
                          rows={Math.min(12, shown(note).split('\n').length + 1)}
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
          {draft.vanished.length > 0 && (
            <div>
              <h4 className="panel-title caps notes-type">{t('tasks.vanished')}</h4>
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
            <span className="muted">{t('tasks.files', { count: draft.notes.length })}</span>
            <button className="btn-primary large" disabled={locked || written || !root} onClick={write}>
              {t(written ? 'tasks.done' : 'tasks.write')}
            </button>
          </div>
        </>
      )}
    </section>
  )
}
