import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { api, councilPath, projectOf, startOrFollow, type Council, type CouncilPatch, type Settings } from '../api'
import { ModelCheckbox } from '../components/ModelBadge'
import { Panel } from '../components/Panel'
import { SaveStatus } from '../components/SaveStatus'
import { SelectField } from '../components/SelectField'
import type { Autosave } from '../useAutosave'
import { useAction } from '../useAction'

/** Текст сохраняется, когда человек перестал печатать; выбор в списках — сразу. */
export const TYPING_DELAY = 600

const countWords = (text: string) => text.split(/\s+/).filter(Boolean).length

/**
 * Ввод: мысли в свободной форме, название, проект и состав совета. Каждый участник изолированно
 * предлагает свой вариант, судья выбирает лучший; судья может и не участвовать. Проект даёт потокам
 * репозитории для скана и папку документации для заметок.
 */
export function BriefStage({ council, settings, onChange, onStart, saver }: Readonly<{
  council: Council; settings: Settings
  onChange: (patch: CouncilPatch, wait: number) => void
  /** Нарезка запущена: сервер вернул совет с ней. */
  onStart: (started: Council) => void
  saver: Autosave<CouncilPatch>
}>) {
  const { t } = useTranslation()
  const nav = useNavigate()
  const briefId = useId()
  const nameId = useId()
  const { busy, error, go } = useAction(onStart)
  const { models, min_participants: minimum } = settings
  const project = projectOf(council, settings)
  // Проекта совета больше нет среди проектов (файл проекта не прочитался) — он виден, а не подменён первым.
  const lost = council.project && !project ? [{ value: council.project, label: t('brief.projectMissing') }] : []

  const toggle = (alias: string, on: boolean) => {
    const chosen = new Set(council.participants)
    if (on) chosen.add(alias); else chosen.delete(alias)
    // Порядок — как в списке моделей, а не как кликали.
    onChange({ participants: models.map(m => m.alias).filter(a => chosen.has(a)) }, 0)
  }

  // Нарезают сохранённый текст, поэтому сначала сохранить, потом запускать.
  const slice = () => go(
    async () => (await saver.flush()) ? startOrFollow(() => api.startSlicing(council.id), council, c => c.slicing) : null,
    () => nav(councilPath(council.id, 'slices')),
  )

  return (
    <div className="stage-layout">
      <Panel title={t('brief.title')} hint={t('brief.hint')} htmlFor={briefId} large>
        <textarea id={briefId} className="brief-text" value={council.brief}
                  placeholder={t('brief.placeholder')}
                  onChange={e => onChange({ brief: e.target.value }, TYPING_DELAY)} />
        <div className="brief-foot">
          <span className="muted">{t('brief.words', { count: countWords(council.brief) })}</span>
          <SaveStatus saver={saver} />
          {error && <span className="error-text" role="alert">{error}</span>}
          <button className="btn-primary large" onClick={slice}
                  disabled={busy || !council.brief.trim()}>{t('brief.slice')}</button>
        </div>
      </Panel>

      <div className="stage-side">
        <Panel title={t('brief.nameTitle')} hint={t('brief.nameHint')} htmlFor={nameId}>
          <input id={nameId} className="text-field" value={council.name}
                 placeholder={t('council.untitled')}
                 onChange={e => onChange({ name: e.target.value }, TYPING_DELAY)} />
        </Panel>

        <Panel title={t('brief.projectTitle')} hint={t('brief.projectHint')}>
          <SelectField label={t('brief.project')} value={council.project}
                       options={[{ value: '', label: t('brief.noProject') }, ...lost,
                                 ...settings.projects.map(p => ({ value: p.id, label: p.name }))]}
                       onChange={chosen => onChange({ project: chosen }, 0)} />
          {project && !project.notes_root && (
            <p className="fragment-note">{project.problem ?? t('brief.projectNoNotes')}</p>
          )}
          <p className="brief-projects"><Link to="/projects">{t('brief.projectsLink')}</Link></p>
        </Panel>

        <Panel title={t('brief.councilTitle')} hint={t('brief.councilHint')}>
          <div className="model-list">
            {models.map(model => {
              const checked = council.participants.includes(model.alias)
              return (
                <ModelCheckbox key={model.alias} model={model} checked={checked}
                               locked={checked && council.participants.length <= minimum}
                               onChange={on => toggle(model.alias, on)} />
              )
            })}
          </div>
          <button className="btn-dashed" disabled title={t('brief.connectModelSoon')}>
            {t('brief.connectModel')}
          </button>
          <SelectField label={t('brief.judge')} value={council.judge}
                       options={models.map(m => ({ value: m.alias, label: m.short_name }))}
                       onChange={judge => onChange({ judge }, 0)} />
        </Panel>
      </div>
    </div>
  )
}
