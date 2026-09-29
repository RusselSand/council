import { useTranslation } from 'react-i18next'
import type { Model, Step } from '../api'
import { ModelBadge, modelOf } from './ModelBadge'
import { Panel } from './Panel'

/** Ход работы совета по шагам: кто из моделей что делает, где ошибся, где судья не понадобился. */
export function Progress({ steps, models }: Readonly<{ steps: Step[]; models: Model[] }>) {
  const { t } = useTranslation()
  return (
    <Panel title={t('progress.title')} hint={t('progress.hint')}>
      <ol className="step-list">
        {steps.map(step => (
          <li key={step.name} className="step">
            <div className="step-head">
              <span className="step-name">{t(`step.${step.name}`)}</span>
              <span className={`step-state ${step.state}`}>{t(`progress.stepState.${step.state}`)}</span>
            </div>
            {step.state === 'skipped' && <p className="step-note">{t('progress.skippedNote')}</p>}
            {step.runs.map(run => (
              <div key={run.model} className="run">
                <ModelBadge model={modelOf(models, run.model)} compact />
                <span className={`run-state ${run.state}`}>{t(`progress.runState.${run.state}`)}</span>
                {run.error && <p className="run-error">{run.error}</p>}
              </div>
            ))}
          </li>
        ))}
      </ol>
    </Panel>
  )
}
