import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import {
  api, ApiError, councilPath, groupsConfirmed, ideasOf, LINKS_MAX, projectOf, REPOSITORIES_MAX, researched,
  researching, startOrFollow, structureIsStale,
  type Council, type DesignNode, type DesignScan, type RepositoryScan, type ScannedRepository, type Settings,
  type Structure,
} from '../api'
import { FieldList, listField } from '../components/FieldList'
import { Progress } from '../components/Progress'
import { shortSha } from '../text'
import { useAction } from '../useAction'

/**
 * Исследование — на весь совет, между группами и потоками: когда идеи всех групп утверждены, совет исследует
 * код и макет под них все разом. Сначала шаг «Репозиторий», потом «Дизайн»; оба можно пропустить. Пройдено —
 * потоки можно начинать: поток берёт себе копию карты и описания. Идеи поменяли после скана — видно, что
 * исследование было к прежним, и его можно сбросить.
 */
export function ResearchStage({ council, settings, onChange }: Readonly<{
  council: Council; settings: Settings; onChange: (council: Council) => void
}>) {
  const { t } = useTranslation()
  const passing = useAction(onChange, 'repository.approveFailed')
  const designing = useAction(onChange, 'design.approveFailed')
  const reset = useAction(onChange)
  const { structure, research } = council
  const ideas = ideasOf(council)
  if (!structure || !groupsConfirmed(council) || ideas === null) return (
    <div className="card placeholder">
      {t('research.waits')} <Link to={councilPath(council.id, 'structure')}>{t('streams.toGroups')}</Link>
    </div>
  )
  const at = { run: structure.run, revision: structure.revision }
  // Скан помнит идеи, под которые шёл: их с тех пор поменяли — исследование было к прежним.
  const scans = [research?.scan, research?.design_scan].filter(scan => !!scan)
  const outdated = scans.some(scan => scan.idea !== ideas)
  // Ход работы — того скана, что идёт, а нет такого — шага, на котором исследование сейчас.
  const shown = [research?.scan, research?.design_scan].find(scan => scan?.state === 'running')
    ?? (research?.repository ? research.design_scan : research?.scan)
  const steps = shown?.steps ?? []
  const drop = () => void reset.go(async () => {
    try {
      return await api.resetResearch(council.id, at)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  })

  return (
    <div className="streams-layout">
      <div className="streams-main">
        <section className="card panel" aria-labelledby="research-title">
          <h2 id="research-title" className="panel-title large">{t('research.title')}</h2>
          <p className="panel-hint">{t('research.hint')}</p>
          <ul className="repo-list">
            {(council.streams ?? []).map(stream => (
              <li key={stream.group}><span className="group-letter" aria-hidden="true">{stream.group}</span> {stream.idea?.text}</li>
            ))}
          </ul>
          {outdated && <p className="fragment-note">{t('research.outdated')}</p>}
          {reset.error && <p className="error-text" role="alert">{reset.error}</p>}
          {research && (
            <div className="stream-actions">
              <button className="btn-secondary" disabled={reset.busy || researching(council) || structureIsStale(council)}
                      onClick={drop}>{t('research.reset')}</button>
            </div>
          )}
          {researched(council) && (
            <p className="check ok">
              {t('research.done')} <Link to={councilPath(council.id, 'streams')}>{t('research.toStreams')}</Link>
            </p>
          )}
        </section>
        {/* Новый скан или другие рабочие копии проекта — отметки и пути заново. */}
        <RepositoryStep key={JSON.stringify([research?.scan?.run ?? '', projectOf(council, settings)?.repositories ?? []])}
                        council={council} structure={structure} repositories={settings.repositories}
                        known={projectOf(council, settings)?.repositories ?? []} onChange={onChange} approve={passing} />
        {research?.repository && (
          <DesignStep key={research.design_scan?.run ?? ''} council={council} structure={structure}
                      figma={settings.figma} onChange={onChange} approve={designing} />
        )}
      </div>
      <aside className="streams-side">
        {steps.length > 0 && <Progress steps={steps} models={settings.models} />}
      </aside>
    </div>
  )
}

/**
 * Шаг «Репозиторий» — необязательный. Совет сканирует рабочие копии под идеи всех групп: inventory — список
 * файлов, участники и судья читают код и составляют карту того, как система устроена сейчас. Человек
 * утверждает карту или пропускает шаг; дальше — шаг «Дизайн». Рабочие копии проекта (known) уже отмечены —
 * лишние снимают; свои добавляют путём.
 */
function RepositoryStep({ council, structure, repositories, known, onChange, approve }: Readonly<{
  council: Council; structure: Structure; repositories: string | null; known: string[]
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>
}>) {
  const { t } = useTranslation()
  const research = council.research
  const scan = research?.scan ?? null
  // Был скан — отмечено то, что сканировали; нет — все рабочие копии проекта.
  const scanned = scan?.repositories.map(r => r.path) ?? []
  const [picked, setPicked] = useState(() => new Set(scanned.length ? known.filter(path => scanned.includes(path)) : known))
  const [paths, setPaths] = useState(() => {
    const own = scanned.filter(path => !known.includes(path))
    return own.length || known.length ? own.map(path => listField(path)) : [listField()]
  })
  const ticked = known.filter(path => picked.has(path))
  const chosen = [...ticked, ...paths.map(f => f.value)]
  const toggle = (path: string) => setPicked(before => {
    const next = new Set(before)
    if (!next.delete(path)) next.add(path)
    return next
  })
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = scan?.state === 'running'
  const stale = structureIsStale(council)
  const at = { run: structure.run, revision: structure.revision }

  const start = (event: FormEvent) => {
    event.preventDefault()
    void retry.go(async () => {
      try {
        return await startOrFollow(() => api.scanRepository(council.id, at, chosen), council,
                                   c => c.research?.scan ?? null)
      } catch (e) {
        // Группы или идеи поменяли в другой вкладке — показываем нынешние.
        if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
        throw e
      }
    })
  }
  const pass = (scanRun: string | null) => void approve.go(async () => {
    try {
      return await api.approveRepository(council.id, at, scanRun)
    } catch (e) {
      // Группы уже другие или скан уже другой (другая вкладка) — показываем нынешнее.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  })
  const taken = research?.repository ?? null
  const ready = scan?.state === 'done' && scan.result !== null
  const placeholder = repositories ? t('repository.pathRoot', { root: repositories }) : t('repository.pathAbsolute')
  
  return (
    <>
      <section className="card panel" aria-labelledby="repository-title">
        <p className="next-caps">{t(sought ? 'repository.capsAi' : 'repository.caps')}</p>
        <h2 id="repository-title" className="panel-title large">{t('repository.title')}</h2>
        <p className="panel-hint">{t('repository.hint')}</p>
        <p className="fragment-note">{t('repository.trust')}</p>
      </section>
      <section className="card panel" aria-label={t('repository.title')}>
        <form className="repo-scan" onSubmit={start}>
          {known.length > 0 && (
            <fieldset className="repo-known">
              <legend className="select-label">{t('repository.known')}</legend>
              {known.map(path => (
                <label key={path} className="decision-pick">
                  <input type="checkbox" checked={picked.has(path)} disabled={busy || sought}
                         onChange={() => toggle(path)} />
                  <span className="repo-known-path">{path}</span>
                </label>
              ))}
            </fieldset>
          )}
          <FieldList fields={paths} onFields={setPaths} max={REPOSITORIES_MAX - ticked.length} min={known.length ? 0 : 1}
                     locked={busy || sought} placeholder={placeholder} addLabel={t('repository.addPath')}
                     label={n => paths.length > 1 || known.length ? t('repository.pathN', { n }) : t('repository.path')}
                     removeLabel={n => t('repository.removePath', { n })} />
          <button type="submit" className="btn-secondary"
                  disabled={busy || sought || stale || chosen.length === 0 || chosen.length > REPOSITORIES_MAX
                            || paths.some(f => f.value.trim() === '')}>
            {t('repository.scan')}
          </button>
        </form>
        {known.length > 0 && <p className="fragment-note">{t('repository.knownNote')}</p>}
        {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
        {research?.design && !sought && <p className="fragment-note">{t('repository.rescanNote')}</p>}
        {sought && (
          <p className="muted">{t('repository.scanning', { round: Math.min(scan.rounds + 1, 3) })} {t('run.note')}</p>
        )}
        {scan?.state === 'failed' && (
          <>
            <p className="error-text" role="alert">{scan.error}</p>
            <p className="fragment-note">{t('repository.failedNote')}</p>
          </>
        )}
        {scan?.result && <RepositoryMapView scan={scan} />}
        {taken && <p className="fragment-note">{t(taken.by === 'scan' ? 'repository.taken' : 'repository.skipped')}</p>}
        {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
        <div className="stream-actions spread">
          <button className="btn-secondary" disabled={busy || sought || stale} onClick={() => pass(null)}>
            {t('repository.skip')}
          </button>
          {ready && (
            <button className="btn-primary large" disabled={busy || stale} onClick={() => pass(scan.run)}>
              {t('repository.approve')}
            </button>
          )}
        </div>
      </section>
    </>
  )
}

const FINDING_PILL = { verified: 'pill ready', inferred: 'pill open', unknown: 'pill' } as const
const COVERAGE_PILL = { covered: 'pill ready', partial: 'pill open', not_investigated: 'pill blocked', not_applicable: 'pill' } as const


/**
 * Рабочая копия скана: путь, коммит, сколько файлов и чего модели не видели. У нескольких — и её папка в
 * карте (пути находок начинаются с неё), а замечания — с её путём.
 */
function ScannedSource({ source, several }: Readonly<{ source: ScannedRepository; several: boolean }>) {
  const { t } = useTranslation()
  const of = several ? `${source.path}: ` : ''
  return (
    <>
      <p className="repo-summary">
        {t('repository.summary', { path: source.path, sha: shortSha(source.commit_sha), files: source.files })}
        {several && ` · ${t('repository.folder', { folder: source.name })}`}
      </p>
      {source.dirty && <p className="fragment-note">{of}{t('repository.dirty')}</p>}
      {source.outside > 0 && <p className="fragment-note">{of}{t('repository.outside', { count: source.outside })}</p>}
      {source.omitted_count > 0 && <p className="fragment-note">{of}{t('repository.omitted', {
        count: source.omitted_count,
        items: source.omitted.join('; ') + (source.omitted_count > source.omitted.length ? '; …' : '') })}</p>}
    </>
  )
}

/** Карта скана: находки с подтверждениями, как идёт выполнение, покрытие, неизвестное и расхождения. */
function RepositoryMapView({ scan }: Readonly<{ scan: RepositoryScan }>) {
  const { t } = useTranslation()
  const result = scan.result
  if (!result) return null
  const several = scan.repositories.length > 1
  return (
    <>
      {scan.repositories.map(source => (
        <ScannedSource key={source.name || source.path} source={source} several={several} />
      ))}
      <p className="repo-summary">{t('repository.rounds', { rounds: scan.rounds })}</p>
      {scan.state === 'done' && scan.complete && <p className="check ok">{t('repository.complete')}</p>}
      {scan.state === 'done' && !scan.complete && (
        <div className="check problem">
          <p>{t('repository.incomplete')}</p>
          <ul>{scan.follow_up.map(item => (
            <li key={item.objective}>{item.targets.length > 0 ? `${item.objective} — ${item.targets.join(', ')}` : item.objective}</li>
          ))}</ul>
        </div>
      )}
      {result.findings.length === 0 && <p className="muted">{t('repository.empty')}</p>}
      <dl className="outcome-rows">
        {result.findings.length > 0 && (
          <>
            <dt>{t('repository.findings')}</dt>
            <dd>
              <ul className="repo-list">{result.findings.map(finding => (
                <li key={finding.id} className="repo-finding">
                  <span className="repo-finding-head">
                    <span className="fragment-id">{finding.id}</span>
                    <span className={FINDING_PILL[finding.status]}>{t(`repository.status.${finding.status}`)}</span>
                    <span className="repo-statement">{finding.statement}</span>
                  </span>
                  {finding.evidence.length > 0 && (
                    <span className="repo-evidence">
                      {finding.evidence.map(e => [e.path, e.lines, e.symbol].filter(Boolean).join(' · ')).join('; ')}
                    </span>
                  )}
                  {finding.relevance && <span className="option-note">{finding.relevance}</span>}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.flows.length > 0 && (
          <>
            <dt>{t('repository.flows')}</dt>
            <dd>
              <ul className="repo-list">{result.flows.map(flow => (
                <li key={flow.name}>
                  <strong>{flow.name}</strong>
                  {flow.entry_point && <span className="repo-evidence"> · {t('repository.entry', { path: flow.entry_point })}</span>}
                  <ol className="repo-steps">{flow.steps.map(step => (
                    <li key={step.description}>
                      {step.description}{step.finding_ids.length > 0 && ` (${step.finding_ids.join(', ')})`}
                    </li>
                  ))}</ol>
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.coverage.length > 0 && (
          <>
            <dt>{t('repository.coverage')}</dt>
            <dd>
              <ul className="repo-list">{result.coverage.map(area => (
                <li key={area.area} className="repo-finding-head">
                  <span>{area.area}</span>
                  <span className={COVERAGE_PILL[area.status]}>{t(`repository.coverage.${area.status}`)}</span>
                  {area.reason && <span className="option-note">{area.reason}</span>}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.unknowns.length > 0 && (
          <>
            <dt>{t('repository.unknowns')}</dt>
            <dd>
              <ul className="repo-list">{result.unknowns.map(unknown => (
                <li key={unknown.question} className="repo-finding">
                  <span>{unknown.reason ? `${unknown.question} — ${unknown.reason}` : unknown.question}</span>
                  {unknown.investigate.length > 0 && (
                    <span className="option-note">{t('repository.investigate', { targets: unknown.investigate.join(', ') })}</span>
                  )}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.documentation_conflicts.length > 0 && (
          <>
            <dt>{t('repository.conflicts')}</dt>
            <dd><ul className="repo-list">{result.documentation_conflicts.map(text => <li key={text}>{text}</li>)}</ul></dd>
          </>
        )}
      </dl>
    </>
  )
}

/**
 * Шаг «Дизайн» — необязательный, после «Репозитория». Совет снимает макет Figma по ссылкам — страницы
 * со структурой и картинками фреймов, с одной версии файла, — участники и судья исследуют снимок и
 * описывают, какой интерфейс и какое поведение предусмотрены под идеи всех групп. Человек утверждает
 * описание или пропускает шаг — исследование пройдено, потоки можно начинать.
 */
function DesignStep({ council, structure, figma, onChange, approve }: Readonly<{
  council: Council; structure: Structure; figma: boolean
  onChange: (council: Council) => void; approve: ReturnType<typeof useAction>
}>) {
  const { t } = useTranslation()
  const research = council.research
  const scan = research?.design_scan ?? null
  const [links, setLinks] = useState(() => scan?.links.length ? scan.links.map(listField) : [listField()])
  const retry = useAction(onChange)
  const busy = approve.busy || retry.busy
  const sought = scan?.state === 'running'
  const stale = structureIsStale(council)
  const at = { run: structure.run, revision: structure.revision }

  const start = (event: FormEvent) => {
    event.preventDefault()
    void retry.go(async () => {
      try {
        return await startOrFollow(() => api.scanDesign(council.id, at, links.map(f => f.value)),
                                   council, c => c.research?.design_scan ?? null)
      } catch (e) {
        // Группы или идеи поменяли в другой вкладке — показываем нынешние.
        if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
        throw e
      }
    })
  }
  const pass = (scanRun: string | null) => void approve.go(async () => {
    try {
      return await api.approveDesign(council.id, at, scanRun)
    } catch (e) {
      // Группы уже другие или скан уже другой (другая вкладка) — показываем нынешнее.
      if (e instanceof ApiError && e.status === 409) onChange(await api.council(council.id))
      throw e
    }
  })
  const taken = research?.design ?? null
  const ready = scan?.state === 'done' && scan.result !== null
  const round = Math.min((scan?.rounds ?? 0) + 1, 3)

  return (
    <>
      <section className="card panel" aria-labelledby="design-title">
        <p className="next-caps">{t(sought ? 'design.capsAi' : 'design.caps')}</p>
        <h2 id="design-title" className="panel-title large">{t('design.title')}</h2>
        <p className="panel-hint">{t('design.hint')}</p>
        <p className="fragment-note">{t('design.trust')}</p>
      </section>
      <section className="card panel" aria-label={t('design.title')}>
        {!figma && <p className="fragment-note">{t('design.noToken')}</p>}
        <form className="repo-scan" onSubmit={start}>
          <FieldList fields={links} onFields={setLinks} max={LINKS_MAX} locked={busy || sought}
                     placeholder={t('design.linkPlaceholder')} addLabel={t('design.addLink')}
                     label={n => links.length > 1 ? t('design.linkN', { n }) : t('design.link')}
                     removeLabel={n => t('design.removeLink', { n })} />
          <button type="submit" className="btn-secondary"
                  disabled={!figma || busy || sought || stale || links.some(f => f.value.trim() === '')}>
            {t('design.scan')}
          </button>
        </form>
        <p className="fragment-note">{t('design.linksNote')}</p>
        {retry.error && <p className="error-text" role="alert">{retry.error}</p>}
        {taken && !sought && <p className="fragment-note">{t('design.rescanNote')}</p>}
        {sought && (
          <p className="muted">{scan.source ? t('design.scanning', { round }) : t('design.fetching')} {t('run.note')}</p>
        )}
        {scan?.state === 'failed' && (
          <>
            <p className="error-text" role="alert">{scan.error}</p>
            <p className="fragment-note">{t('design.failedNote')}</p>
          </>
        )}
        {scan?.result && <DesignMapView scan={scan} />}
        {taken && <p className="fragment-note">{t(taken.by === 'scan' ? 'design.taken' : 'design.skipped')}</p>}
        {approve.error && <p className="error-text" role="alert">{approve.error}</p>}
        <div className="stream-actions spread">
          <button className="btn-secondary" disabled={busy || sought || stale} onClick={() => pass(null)}>
            {t('design.skip')}
          </button>
          {ready && (
            <button className="btn-primary large" disabled={busy || stale} onClick={() => pass(scan.run)}>
              {t('design.approve')}
            </button>
          )}
        </div>
      </section>
    </>
  )
}

/** Узел макета, как его видит человек: имя и номер. */
const nodeLabel = (node: DesignNode) => [node.name, node.node_id || node.page_id].filter(Boolean).join(' · ')

/** Описание макета: какой файл, находки, экраны, сценарии, покрытие, неизвестное и противоречия. */
function DesignMapView({ scan }: Readonly<{ scan: DesignScan }>) {
  const { t } = useTranslation()
  const result = scan.result
  if (!result) return null
  const source = scan.source
  return (
    <>
      {source && (
        <p className="repo-summary">
          {t('design.source', { name: source.name, version: source.version, pages: source.pages, images: source.images })}
        </p>
      )}
      {source && source.requested.length > 0 && (
        <p className="repo-summary">{t('design.requested', { nodes: source.requested.map(nodeLabel).join(', ') })}</p>
      )}
      <p className="repo-summary">{t('design.rounds', { rounds: scan.rounds })}</p>
      {scan.state === 'done' && scan.complete && <p className="check ok">{t('design.complete')}</p>}
      {scan.state === 'done' && !scan.complete && (
        <div className="check problem">
          <p>{t('design.incomplete')}</p>
          <ul>{scan.follow_up.map(item => (
            <li key={item.objective}>
              {item.targets.length > 0 ? `${item.objective} — ${item.targets.map(nodeLabel).join(', ')}` : item.objective}
            </li>
          ))}</ul>
        </div>
      )}
      {result.findings.length === 0 && <p className="muted">{t('design.empty')}</p>}
      <dl className="outcome-rows">
        {result.findings.length > 0 && (
          <>
            <dt>{t('design.findings')}</dt>
            <dd>
              <ul className="repo-list">{result.findings.map(finding => (
                <li key={finding.id} className="repo-finding">
                  <span className="repo-finding-head">
                    <span className="fragment-id">{finding.id}</span>
                    <span className={FINDING_PILL[finding.status]}>{t(`repository.status.${finding.status}`)}</span>
                    <span className="repo-statement">{finding.statement}</span>
                  </span>
                  {finding.evidence.length > 0 && (
                    <span className="repo-evidence">{finding.evidence.map(nodeLabel).join('; ')}</span>
                  )}
                  {finding.relevance && <span className="option-note">{finding.relevance}</span>}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.screens.length > 0 && (
          <>
            <dt>{t('design.screens')}</dt>
            <dd>
              <ul className="repo-list">{result.screens.map(screen => (
                <li key={`${screen.name}:${screen.node_id}`} className="repo-finding">
                  <span className="repo-finding-head">
                    <strong>{screen.name}</strong>
                    {screen.node_id && <span className="repo-evidence">{screen.node_id}</span>}
                  </span>
                  {screen.purpose && <span>{screen.purpose}</span>}
                  {screen.data.length > 0 && (
                    <span className="option-note">{t('design.data', { items: screen.data.join(', ') })}</span>
                  )}
                  {screen.actions.length > 0 && (
                    <ul className="repo-steps">{screen.actions.map(action => (
                      <li key={action.action}>
                        <span className={FINDING_PILL[action.status]}>{t(`repository.status.${action.status}`)}</span>{' '}
                        {t('design.action', { action: action.action, result: action.result ?? t('design.noResult') })}
                      </li>
                    ))}</ul>
                  )}
                  {screen.states.length > 0 && (
                    <span className="option-note">
                      {t('design.states', { items: screen.states.map(state => state.name).join(', ') })}
                    </span>
                  )}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.flows.length > 0 && (
          <>
            <dt>{t('design.flows')}</dt>
            <dd>
              <ul className="repo-list">{result.flows.map(flow => (
                <li key={flow.name}>
                  <span className="repo-finding-head">
                    <strong>{flow.name}</strong>
                    <span className={FINDING_PILL[flow.status]}>{t(`repository.status.${flow.status}`)}</span>
                  </span>
                  <ol className="repo-steps">{flow.steps.map(step => (
                    <li key={step.description}>
                      {step.description}{step.finding_ids.length > 0 && ` (${step.finding_ids.join(', ')})`}
                    </li>
                  ))}</ol>
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.coverage.length > 0 && (
          <>
            <dt>{t('design.coverage')}</dt>
            <dd>
              <ul className="repo-list">{result.coverage.map(area => (
                <li key={area.area} className="repo-finding-head">
                  <span>{area.area}</span>
                  <span className={COVERAGE_PILL[area.status]}>{t(`repository.coverage.${area.status}`)}</span>
                  {area.reason && <span className="option-note">{area.reason}</span>}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.unknowns.length > 0 && (
          <>
            <dt>{t('design.unknowns')}</dt>
            <dd>
              <ul className="repo-list">{result.unknowns.map(unknown => (
                <li key={unknown.question} className="repo-finding">
                  <span>{unknown.reason ? `${unknown.question} — ${unknown.reason}` : unknown.question}</span>
                  {unknown.investigate.length > 0 && (
                    <span className="option-note">
                      {t('repository.investigate', { targets: unknown.investigate.map(nodeLabel).join(', ') })}
                    </span>
                  )}
                </li>
              ))}</ul>
            </dd>
          </>
        )}
        {result.design_conflicts.length > 0 && (
          <>
            <dt>{t('design.conflicts')}</dt>
            <dd><ul className="repo-list">{result.design_conflicts.map(text => <li key={text}>{text}</li>)}</ul></dd>
          </>
        )}
      </dl>
    </>
  )
}

