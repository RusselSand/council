import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import {
  ApiError, councilPath, startOrFollowSlicing,
  type Council, type CouncilPatch, type Label, type LabeledFragment, type Model, type Settings, type Slicing,
} from '../api'
import { LabelChips, LabelLegend, SlicedText } from '../components/Labels'
import { ModelBadge } from '../components/ModelBadge'
import { Panel } from '../components/Panel'
import { SaveStatus } from '../components/SaveStatus'
import type { Autosave } from '../useAutosave'

/** Модель, которой уже нет в настройках, всё равно показывается — по её alias. */
const modelOf = (models: Model[], alias: string): Model =>
  models.find(m => m.alias === alias)
  ?? { alias, short_name: alias, display_name: alias, cli: '?', available: false }

/**
 * Нарезка: участники по отдельности режут текст на смысловые фрагменты и размечают их,
 * судья решает только там, где они разошлись. Итог — исходный текст с подсветкой и список
 * фрагментов, где тип можно поменять; слева — как шла работа.
 */
export function SlicesStage({ council, settings, onStart, onRelabel, saver }: Readonly<{
  council: Council; settings: Settings
  onStart: (started: Council) => void
  onRelabel: (fragmentId: number, label: Label) => void
  saver: Autosave<CouncilPatch>
}>) {
  const { t } = useTranslation()
  const slicing = council.slicing

  if (!slicing) return (
    <div className="card placeholder">
      {t('slices.none')} <Link to={councilPath(council.id)}>{t('slices.toBrief')}</Link>
    </div>
  )

  return (
    <div className="slices-layout">
      <div className="slices-main">
        {slicing.state === 'done'
          ? <Result slicing={slicing} models={settings.models} onRelabel={onRelabel} saver={saver} />
          : <Status council={council} slicing={slicing} onStart={onStart} />}
      </div>
      <aside className="slices-side">
        <Progress slicing={slicing} models={settings.models} />
      </aside>
    </div>
  )
}

function Result({ slicing, models, onRelabel, saver }: Readonly<{
  slicing: Slicing; models: Model[]
  onRelabel: (fragmentId: number, label: Label) => void
  saver: Autosave<CouncilPatch>
}>) {
  const { t } = useTranslation()
  const answered = slicing.steps.find(s => s.name === 'label')?.runs.filter(r => r.state === 'done').length ?? 0
  return (
    <>
      <Panel title={t('slices.resultTitle')} hint={t('slices.resultHint')} large
             aside={<span className="pill ready badge" title={t('slices.readyHint', { count: answered })}>
               {t('slices.ready', { count: answered })}
             </span>}>
        <SlicedText text={slicing.text} fragments={slicing.fragments} />
        <LabelLegend fragments={slicing.fragments} />
      </Panel>
      <Panel title={t('slices.fragmentsTitle')} caps aside={<SaveStatus saver={saver} />}>
        <ol className="fragment-list">
          {slicing.fragments.map(fragment => (
            <li key={fragment.id} className="fragment-row">
              <span className="fragment-id">F{fragment.id}</span>
              <div>
                <div className="fragment-text" title={fragment.reason}>{fragment.text}</div>
                {notesOf(fragment, models, t).map(note => <p key={note} className="fragment-note">{note}</p>)}
              </div>
              <LabelChips name={`F${fragment.id}`} value={fragment.label}
                          onChange={label => onRelabel(fragment.id, label)} />
            </li>
          ))}
        </ol>
      </Panel>
    </>
  )
}

/** Пометки под фрагментом: где человек не согласился с советом, где модели разошлись, где судья двигал границу. */
function notesOf(fragment: LabeledFragment, models: Model[], t: ReturnType<typeof useTranslation>['t']): string[] {
  const labelName = (label: Label) => t(`label.${label}`)
  const notes = []
  if (fragment.label !== fragment.council_label) {
    notes.push(t('slices.noteHuman', { label: labelName(fragment.council_label) }))
  }
  if (fragment.decided_by === 'judge') {
    const votes = fragment.votes
      .map(v => `${modelOf(models, v.model).short_name} — ${v.labels.map(labelName).join(' / ')}`)
      .join(', ')
    notes.push(t('slices.noteJudge', { votes, reason: fragment.reason }))
  }
  if (fragment.slice_note) notes.push(t('slices.noteSlice', { note: fragment.slice_note }))
  return notes
}

function Progress({ slicing, models }: Readonly<{ slicing: Slicing; models: Model[] }>) {
  const { t } = useTranslation()
  return (
    <Panel title={t('slices.progressTitle')} hint={t('slices.progressHint')}>
      <ol className="step-list">
        {slicing.steps.map(step => (
          <li key={step.name} className="step">
            <div className="step-head">
              <span className="step-name">{t(`slices.step.${step.name}`)}</span>
              <span className={`step-state ${step.state}`}>{t(`slices.stepState.${step.state}`)}</span>
            </div>
            {step.state === 'skipped' && <p className="step-note">{t('slices.skippedNote')}</p>}
            {step.runs.map(run => (
              <div key={run.model} className="run">
                <ModelBadge model={modelOf(models, run.model)} compact />
                <span className={`run-state ${run.state}`}>{t(`slices.runState.${run.state}`)}</span>
                {run.error && <p className="run-error">{run.error}</p>}
              </div>
            ))}
          </li>
        ))}
      </ol>
    </Panel>
  )
}

/** Пока идёт — что происходит; если упало — почему и кнопка повтора. */
function Status({ council, slicing, onStart }: Readonly<{
  council: Council; slicing: Slicing; onStart: (started: Council) => void
}>) {
  const { t } = useTranslation()
  const [restarting, setRestarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const restart = async () => {
    setRestarting(true); setError(null)
    try {
      onStart(await startOrFollowSlicing(council.id))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t('brief.startFailed'))
    } finally {
      setRestarting(false)
    }
  }

  if (slicing.state === 'running') return (
    <Panel title={t('slices.runningTitle')} hint={t('slices.runningHint')} large>
      <p className="muted">{t('slices.runningNote')}</p>
    </Panel>
  )

  return (
    <Panel title={t('slices.failedTitle')} hint={t('slices.failedHint')} large>
      <p className="error-text" role="alert">{slicing.error}</p>
      {error && <p className="error-text" role="alert">{error}</p>}
      <button className="btn-primary large" onClick={restart} disabled={restarting}>{t('slices.retry')}</button>
    </Panel>
  )
}
