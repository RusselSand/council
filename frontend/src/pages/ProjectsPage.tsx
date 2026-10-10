import { useId, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, REPOSITORIES_MAX, type Project, type ProjectDraft, type WorkingCopies } from '../api'
import { FieldList, listField } from '../components/FieldList'
import { useLoad } from '../useLoad'

/**
 * Проекты: рабочие копии и папка документации, которые совет берёт по проекту, а не вводит в каждом потоке.
 * Проект выбирают на «Вводе» совета: его репозитории подставляются в шаг «Репозиторий» каждого потока, а его
 * папка — каталог заметок. Рабочие копии предлагаются из каталога репозиториев сервера — отметить галочкой.
 */
export function ProjectsPage() {
  const { t } = useTranslation()
  const { state, retry, update } = useLoad(() => Promise.all([api.projects(), api.workingCopies()]), [])
  // Какой проект правят: его id, 'new' — новый, null — никакой.
  const [editing, setEditing] = useState<string | null>(null)

  const saved = (project: Project) => {
    update(([projects, copies]) => [
      [...projects.filter(p => p.id !== project.id), project]
        .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })),
      copies,
    ])
    setEditing(null)
  }
  const removed = (id: string) => update(([projects, copies]) => [projects.filter(p => p.id !== id), copies])

  return (
    <main className="main">
      <div className="section-head projects-head">
        <div>
          <h1 className="page-title">{t('projects.title')}</h1>
          <p className="page-sub">{t('projects.sub')}</p>
        </div>
        {state.kind === 'ok' && editing !== 'new' && (
          <button className="btn-primary" onClick={() => setEditing('new')}>{t('projects.new')}</button>
        )}
      </div>
      {state.kind === 'loading' && <div className="card muted section-gap">{t('common.loading')}</div>}
      {state.kind === 'error' && (
        <div className="card muted section-gap">
          {t('projects.loadFailed')}{' '}
          <button className="btn-primary" onClick={retry}>{t('common.retry')}</button>
        </div>
      )}
      {state.kind === 'ok' && (
        <div className="project-list">
          {editing === 'new' && (
            <ProjectForm copies={state.data[1]} onSaved={saved} onCancel={() => setEditing(null)} />
          )}
          {state.data[0].length === 0 && editing !== 'new' && <div className="card muted">{t('projects.empty')}</div>}
          {state.data[0].map(project => editing === project.id
            ? <ProjectForm key={project.id} project={project} copies={state.data[1]} onSaved={saved}
                           onCancel={() => setEditing(null)} />
            : <ProjectCard key={project.id} project={project} onEdit={() => setEditing(project.id)}
                           onRemoved={() => removed(project.id)} />)}
        </div>
      )}
    </main>
  )
}

/** Отказ сервера его словами, иначе — общая фраза. */
const reason = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)

/** Проект в списке: его рабочие копии, папка документации и что с ней не так. Удаление — со вторым шагом. */
function ProjectCard({ project, onEdit, onRemoved }: Readonly<{
  project: Project; onEdit: () => void; onRemoved: () => void
}>) {
  const { t } = useTranslation()
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const remove = async () => {
    setBusy(true); setError(null)
    try {
      await api.deleteProject(project.id)
      onRemoved()
    } catch (e) {
      setError(reason(e, t('projects.deleteFailed')))
      setAsking(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card panel" aria-label={project.name}>
      <div className="panel-head">
        <h2 className="panel-title large">{project.name}</h2>
        <div className="project-actions">
          {asking ? (
            <>
              <span className="muted">{t('projects.deleteAsk')}</span>
              <button className="btn-secondary" disabled={busy} onClick={() => void remove()}>{t('projects.deleteYes')}</button>
              <button className="btn-link" disabled={busy} onClick={() => setAsking(false)}>{t('projects.cancel')}</button>
            </>
          ) : (
            <>
              <button className="btn-secondary" onClick={onEdit}>{t('projects.edit')}</button>
              <button className="btn-link" onClick={() => setAsking(true)}>{t('projects.delete')}</button>
            </>
          )}
        </div>
      </div>
      <p className="select-label">{t('projects.repositories')}</p>
      {project.repositories.length > 0
        ? <ul className="project-paths">{project.repositories.map(path => <li key={path}>{path}</li>)}</ul>
        : <p className="muted">{t('projects.noRepositories')}</p>}
      <p className="select-label project-label">{t('projects.notesTitle')}</p>
      {project.notes
        ? <p className="project-paths">{project.notes}</p>
        : <p className="muted">{t('projects.noNotes')}</p>}
      {project.problem && <p className="error-text">{project.problem}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
    </section>
  )
}

/**
 * Новый проект или правка. Рабочие копии из каталога репозиториев — галочками; копию глубже или без каталога
 * репозиториев (тогда пути абсолютные) вписывают путём. Пустые поля путей не уходят.
 */
function ProjectForm({ project, copies, onSaved, onCancel }: Readonly<{
  project?: Project; copies: WorkingCopies; onSaved: (project: Project) => void; onCancel: () => void
}>) {
  const { t } = useTranslation()
  const nameId = useId()
  const notesId = useId()
  const offered = copies.paths
  const [name, setName] = useState(project?.name ?? '')
  const [picked, setPicked] = useState(() => new Set(project?.repositories.filter(path => offered.includes(path)) ?? []))
  const [paths, setPaths] = useState(() => (project?.repositories ?? [])
    .filter(path => !offered.includes(path)).map(path => listField(path)))
  const [notes, setNotes] = useState(project?.notes ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ticked = offered.filter(path => picked.has(path))
  const repositories = [...ticked, ...paths.map(f => f.value).filter(path => path.trim() !== '')]
  const toggle = (path: string) => setPicked(before => {
    const next = new Set(before)
    if (!next.delete(path)) next.add(path)
    return next
  })

  const save = async (event: FormEvent) => {
    event.preventDefault()
    const draft: ProjectDraft = { name, repositories, notes }
    setBusy(true); setError(null)
    try {
      onSaved(project ? await api.updateProject(project.id, draft) : await api.createProject(draft))
    } catch (e) {
      setError(reason(e, t('projects.saveFailed')))
    } finally {
      setBusy(false)
    }
  }

  const root = copies.root
  return (
    <form className="card panel project-form" onSubmit={e => void save(e)}
          aria-label={project ? project.name : t('projects.newTitle')}>
      <h2 className="panel-title large">{project ? project.name : t('projects.newTitle')}</h2>
      <label className="select-label" htmlFor={nameId}>{t('projects.name')}</label>
      <input id={nameId} className="text-field" value={name} readOnly={busy}
             placeholder={t('projects.namePlaceholder')} onChange={e => setName(e.target.value)} />

      <fieldset className="project-fieldset">
        <legend className="select-label">{t('projects.repositories')}</legend>
        <p className="panel-hint">{root ? t('projects.repositoriesHint', { root }) : t('projects.repositoriesAbsolute')}</p>
        {offered.length > 0 && (
          <div className="project-copies">
            {offered.map(path => (
              <label key={path} className="decision-pick">
                <input type="checkbox" checked={picked.has(path)} disabled={busy} onChange={() => toggle(path)} />
                <span className="repo-known-path">{path}</span>
              </label>
            ))}
          </div>
        )}
        {root && offered.length === 0 && <p className="muted">{t('projects.noCopies', { root })}</p>}
        <div className="project-extra">
          <FieldList fields={paths} onFields={setPaths} max={REPOSITORIES_MAX - ticked.length} min={0} locked={busy}
                     placeholder={root ? t('repository.pathRoot', { root }) : t('repository.pathAbsolute')}
                     label={n => t('projects.path', { n })} removeLabel={n => t('projects.removePath', { n })}
                     addLabel={t('projects.addPath')} />
        </div>
        {repositories.length > REPOSITORIES_MAX && (
          <p className="error-text">{t('projects.tooMany', { max: REPOSITORIES_MAX })}</p>
        )}
      </fieldset>

      <label className="select-label project-label" htmlFor={notesId}>{t('projects.notesTitle')}</label>
      <p className="panel-hint">{t('projects.notesHint')}</p>
      <input id={notesId} className="text-field project-mono" value={notes} readOnly={busy}
             placeholder={root ? t('projects.notesPlaceholder', { root }) : t('projects.notesAbsolute')}
             onChange={e => setNotes(e.target.value)} />

      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="stream-actions spread">
        <button type="button" className="btn-link" disabled={busy} onClick={onCancel}>{t('projects.cancel')}</button>
        <button type="submit" className="btn-primary large"
                disabled={busy || !name.trim() || repositories.length > REPOSITORIES_MAX}>
          {t(project ? 'projects.save' : 'projects.create')}
        </button>
      </div>
    </form>
  )
}
