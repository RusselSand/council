import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { councilPath, groupsConfirmed, structureIsStale, type Council } from '../api'
import { Panel } from '../components/Panel'

/**
 * Потоки: каждая подтверждённая группа — отдельный поток. Пока только их список: вопросы,
 * варианты и решения внутри потока — следующие шаги.
 */
export function StreamsStage({ council }: Readonly<{ council: Council }>) {
  const { t } = useTranslation()
  const structure = council.structure
  const toGroups = councilPath(council.id, 'structure')

  if (!structure || !groupsConfirmed(council)) return (
    <div className="card placeholder">
      {t('streams.none')} <Link to={toGroups}>{t('streams.toGroups')}</Link>
    </div>
  )

  return (
    <Panel title={t('streams.title', { count: structure.groups.length })} hint={t('streams.hint')} large>
      {structureIsStale(council) && (
        <p className="fragment-note">
          {t('streams.stale')} <Link className="btn-link" to={toGroups}>{t('streams.toGroups')}</Link>
        </p>
      )}
      <ol className="stream-list">
        {structure.groups.map(group => (
          <li key={group.id} className="stream">
            <span className="group-letter" aria-hidden="true">{group.id}</span>
            <span className="stream-text">
              <span className="stream-title">{group.title}</span>
              <span className="stream-meta">
                {t('streams.fragments', { count: group.fragment_ids.length })}
                {group.missing_idea && ` · ${t('groups.missingIdea')}`}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </Panel>
  )
}
