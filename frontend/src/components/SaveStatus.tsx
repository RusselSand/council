import { useTranslation } from 'react-i18next'
import type { Autosave } from '../useAutosave'

/**
 * Что с сохранением правок: идёт, не прошло (повторить) или не прошло, а человек уходит
 * со страницы (уйти без сохранения). Пока всё сохранено, ничего не показывает.
 */
export function SaveStatus<P extends object>({ saver }: Readonly<{ saver: Autosave<P> }>) {
  const { t } = useTranslation()
  if (saver.state === 'saving') return <span className="muted">{t('save.saving')}</span>
  if (saver.state !== 'error') return null
  return (
    <span className="error-text" role="alert">
      {t('save.failed')}{' '}
      <button className="btn-link" onClick={() => void saver.retry()}>{t('common.retry')}</button>
      {saver.leaving && <>{' · '}
        <button className="btn-link" onClick={saver.leaveAnyway}>{t('save.leaveAnyway')}</button>
      </>}
    </span>
  )
}
