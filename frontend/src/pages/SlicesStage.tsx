import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, ApiError, councilPath, type Council, type Model, type Settings, type Slicing } from '../api'
import { ModelBadge } from '../components/ModelBadge'
import { Panel } from '../components/Panel'

/** Модель, которой уже нет в настройках, всё равно показывается — по её alias. */
const modelOf = (models: Model[], alias: string): Model =>
  models.find(m => m.alias === alias)
  ?? { alias, short_name: alias, display_name: alias, cli: '?', available: false }

/**
 * Нарезка: участники по отдельности режут текст на смысловые фрагменты и размечают их,
 * судья решает только там, где они разошлись. Слева итог, справа — как шла работа.
 */
export function SlicesStage({ council, settings, onStart }: Readonly<{
  council: Council; settings: Settings; onStart: (started: Council) => void
}>) {
  const { t } = useTranslation()
  const slicing = council.slicing

  if (!slicing) return (
    <div className="card placeholder">
      {t('slices.none')} <Link to={councilPath(council.id)}>{t('slices.toBrief')}</Link>
    </div>
  )

  return (
    <div className="stage-layout">
      {slicing.state === 'done'
        ? <Result slicing={slicing} />
        : <Status council={council} slicing={slicing} onStart={onStart} />}
      <div className="stage-side">
        <Panel title={t('slices.progressTitle')} hint={t('slices.progressHint')}>
          <ol className="step-list">
            {slicing.steps.map(step => (
              <li key={step.name} className="step">
                <div className="step-head">
                  <span className="step-name">{t(`slices.step.${step.name}`)}</span>
                  <span className={`step-state ${step.state}`}>{t(`slices.stepState.${step.state}`)}</span>
                </div>
                {step.runs.map(run => (
                  <div key={run.model} className="run">
                    <ModelBadge model={modelOf(settings.models, run.model)} />
                    <span className={`run-state ${run.state}`}>{t(`slices.runState.${run.state}`)}</span>
                    {run.error && <p className="run-error">{run.error}</p>}
                  </div>
                ))}
              </li>
            ))}
          </ol>
        </Panel>
      </div>
    </div>
  )
}

function Result({ slicing }: Readonly<{ slicing: Slicing }>) {
  const { t } = useTranslation()
  return (
    <Panel title={t('slices.resultTitle')} hint={t('slices.resultHint')} large>
      <table className="fragments">
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">{t('slices.colText')}</th>
            <th scope="col">{t('slices.colLabel')}</th>
          </tr>
        </thead>
        <tbody>
          {slicing.fragments.map(f => (
            <tr key={f.id}>
              <td className="fragment-id">{f.id}</td>
              <td>
                <div className="fragment-text">{f.text}</div>
                <div className="fragment-reason">{f.reason}</div>
              </td>
              <td><span className={`pill label-${f.label}`}>{t(`label.${f.label}`)}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
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
      onStart(await api.startSlicing(council.id))
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
