import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import {
  api, councilPath, startOrFollow, structureIsStale,
  type Council, type CouncilPatch, type Label, type LabeledFragment, type Model, type Settings, type Slicing,
} from '../api'
import { LabelChips, LabelLegend, SlicedText } from '../components/Labels'
import { modelOf } from '../components/ModelBadge'
import { Panel } from '../components/Panel'
import { Progress } from '../components/Progress'
import { ReadyBadge, RunStatus } from '../components/RunStatus'
import { SaveStatus } from '../components/SaveStatus'
import type { Autosave } from '../useAutosave'
import { useStart } from '../useStart'

/**
 * Нарезка: участники по отдельности режут текст на смысловые фрагменты и размечают их,
 * судья решает только там, где они разошлись. Итог — исходный текст с подсветкой и список
 * фрагментов, где тип можно поменять; сбоку — что дальше и как шла работа.
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
          : <RunStatus run={slicing} kind="slices" onStart={onStart}
                       restart={() => startOrFollow(() => api.startSlicing(council.id), council.id)} />}
      </div>
      <aside className="slices-side">
        {slicing.state === 'done' && <NextStep council={council} onStart={onStart} />}
        <Progress steps={slicing.steps} models={settings.models} />
      </aside>
    </div>
  )
}

/** Что дальше: разложить фрагменты по группам — или открыть уже разложенные. */
function NextStep({ council, onStart }: Readonly<{ council: Council; onStart: (started: Council) => void }>) {
  const { t } = useTranslation()
  const nav = useNavigate()
  const { busy, error, go } = useStart(onStart)
  const structure = council.structure
  const stale = structure !== null && structureIsStale(council)
  const propose = () => void go(() => startOrFollow(() => api.startStructure(council.id), council.id),
                                () => nav(councilPath(council.id, 'structure')))

  return (
    <section className="card panel next-step" aria-labelledby="next-step-title">
      <p className="next-caps">{t('next.caps')}</p>
      <h2 id="next-step-title" className="panel-title">{t('next.title')}</h2>
      <p className="panel-hint">{t('next.hint')}</p>
      {stale && <p className="fragment-note">{t('next.stale')}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
      {structure && !stale
        ? <Link className="btn-primary large block" to={councilPath(council.id, 'structure')}>{t('next.open')}</Link>
        : <button className="btn-primary large block" onClick={propose} disabled={busy}>
            {t(stale ? 'next.again' : 'next.propose')}
          </button>}
    </section>
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
             aside={<ReadyBadge count={answered} />}>
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
