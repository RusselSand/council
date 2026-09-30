import { useTranslation } from 'react-i18next'
import type { Council } from '../api'
import { useAction } from '../useAction'
import { Panel } from './Panel'

/** «Готово ×N»: сколько моделей сделали работу независимо друг от друга. */
export function ReadyBadge({ count }: Readonly<{ count: number }>) {
  const { t } = useTranslation()
  return <span className="pill ready badge" title={t('run.readyHint', { count })}>{t('run.ready', { count })}</span>
}

/**
 * Ход совета, пока нет итога: идёт — что происходит; упал — почему и кнопка повтора.
 * kind — чьи надписи: нарезки или групп. restart запускает ход заново.
 */
export function RunStatus({ run, kind, restart, onStart }: Readonly<{
  run: { state: 'running' | 'done' | 'failed'; error: string | null }
  kind: 'slices' | 'groups'
  restart: () => Promise<Council>
  onStart: (started: Council) => void
}>) {
  const { t } = useTranslation()
  const { busy, error, go } = useAction(onStart)

  if (run.state === 'running') return (
    <Panel title={t(`${kind}.runningTitle`)} hint={t(`${kind}.runningHint`)} large>
      <p className="muted">{t('run.note')}</p>
    </Panel>
  )

  return (
    <Panel title={t(`${kind}.failedTitle`)} hint={t('run.failedHint')} large>
      <p className="error-text" role="alert">{run.error}</p>
      {error && <p className="error-text" role="alert">{error}</p>}
      <button className="btn-primary large" onClick={() => void go(restart)} disabled={busy}>
        {t('run.retry')}
      </button>
    </Panel>
  )
}
