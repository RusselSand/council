import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { api, ApiError, councilPath, type Council, type CouncilPatch, type Settings } from '../api'
import { ModelCheckbox } from '../components/ModelBadge'
import { Panel } from '../components/Panel'
import { SelectField } from '../components/SelectField'
import type { Autosave } from '../useAutosave'

/** Текст сохраняется, когда человек перестал печатать; выбор в списках — сразу. */
export const TYPING_DELAY = 600

const countWords = (text: string) => text.split(/\s+/).filter(Boolean).length

/**
 * Ввод: мысли в свободной форме, название и состав совета. Каждый участник изолированно
 * предлагает свой вариант, судья выбирает лучший; судья может и не участвовать.
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
  const [slicing, setSlicing] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const { models, min_participants: minimum } = settings

  const toggle = (alias: string, on: boolean) => {
    const chosen = new Set(council.participants)
    if (on) chosen.add(alias); else chosen.delete(alias)
    // Порядок — как в списке моделей, а не как кликали.
    onChange({ participants: models.map(m => m.alias).filter(a => chosen.has(a)) }, 0)
  }

  // Нарезают сохранённый текст, поэтому сначала сохранить, потом запускать.
  const slice = async () => {
    setSlicing(true); setStartError(null)
    try {
      if (!(await saver.flush())) return
      onStart(await api.startSlicing(council.id))
      nav(councilPath(council.id, 'slices'))
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Уже идёт: показать её ход. Совет перечитываем, иначе на экране не будет нарезки.
        api.council(council.id).then(onStart, () => { /* покажет опрос */ })
        nav(councilPath(council.id, 'slices'))
      } else {
        setStartError(e instanceof ApiError ? e.message : t('brief.startFailed'))
      }
    } finally {
      setSlicing(false)
    }
  }

  return (
    <div className="stage-layout">
      <Panel title={t('brief.title')} hint={t('brief.hint')} htmlFor={briefId} large>
        <textarea id={briefId} className="brief-text" value={council.brief}
                  placeholder={t('brief.placeholder')}
                  onChange={e => onChange({ brief: e.target.value }, TYPING_DELAY)} />
        <div className="brief-foot">
          <span className="muted">
            {t('brief.words', { count: countWords(council.brief) })}
            {saver.state === 'saving' && ` · ${t('brief.saving')}`}
          </span>
          {saver.state === 'error' && (
            <span className="error-text" role="alert">
              {t('brief.saveFailed')}{' '}
              <button className="btn-link" onClick={() => void saver.retry()}>{t('common.retry')}</button>
              {saver.leaving && <>{' · '}
                <button className="btn-link" onClick={saver.leaveAnyway}>{t('brief.leaveAnyway')}</button>
              </>}
            </span>
          )}
          {startError && <span className="error-text" role="alert">{startError}</span>}
          <button className="btn-primary large" onClick={slice}
                  disabled={slicing || !council.brief.trim()}>{t('brief.slice')}</button>
        </div>
      </Panel>

      <div className="stage-side">
        <Panel title={t('brief.nameTitle')} hint={t('brief.nameHint')} htmlFor={nameId}>
          <input id={nameId} className="text-field" value={council.name}
                 placeholder={t('council.untitled')}
                 onChange={e => onChange({ name: e.target.value }, TYPING_DELAY)} />
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
