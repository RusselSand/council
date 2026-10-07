import { useCallback, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useOutletContext, useParams } from 'react-router'
import {
  api, ApiError, councilPath, isNotFound, seeking,
  type Council, type CouncilPatch, type Label, type Slicing, type Stream,
} from '../api'
import type { Layout } from '../App'
import { stageLight } from '../light'
import { useAutosave } from '../useAutosave'
import { useInterval } from '../useInterval'
import { useLoad } from '../useLoad'
import { BriefStage } from './BriefStage'
import { GroupsStage } from './GroupsStage'
import { SlicesStage } from './SlicesStage'
import { StreamsStage } from './StreamsStage'

export const STAGES = ['brief', 'slices', 'structure', 'streams', 'history'] as const

/** Путь этапа под /councils/:id/. У потоков в нём ещё буква открытого потока. */
export const stagePath = (stage: Stage) => (stage === 'streams' ? 'streams/:stream?' : stage)

/** Как часто спрашивать сервер, пока идёт нарезка: ходы моделей длятся минутами. */
export const POLL_MS = 2000
export type Stage = (typeof STAGES)[number]


/**
 * Потоки из ответа опроса. Берутся только потоки, где на экране ещё идёт поиск идеи или
 * вопросов, и только если на сервере это те же ходы: запоздалый ответ не затрёт утверждённые
 * здесь идею и отбор вопросов. На сервере потоки уже другие (группы поправили в другой
 * вкладке) — берём их целиком.
 */
const followed = (mine: Stream[], fresh: Stream[] | null): Stream[] | null => {
  const same = (stream: Stream) => fresh?.find(f => f.group === stream.group
    && f.discovery?.run === stream.discovery?.run && f.questions?.run === stream.questions?.run)
  const live = mine.filter(stream => stream.discovery?.state === 'running' || stream.questions?.state === 'running')
  if (live.some(stream => !same(stream))) return fresh
  return mine.map(stream => (live.includes(stream) ? same(stream) ?? stream : stream))
}

/** 404 на сам совет. 404 от настроек — обычная ошибка загрузки: совет-то есть, и повтор уместен. */
class CouncilMissing extends Error {}

const loadCouncil = (id: string) => Promise.all([
  api.council(id).catch((e: unknown) => { throw isNotFound(e) ? new CouncilMissing() : e }),
  api.settings(),
])

/**
 * Нарезка из ответа на запуск. sent — нарезка на экране, когда запрос ушёл: типы, поменянные
 * здесь после этого, ответ ещё не знает, и они остаются. Остальное — как на сервере, в том
 * числе правки из других вкладок.
 */
const rebased = (fresh: Slicing | null, sent: Slicing, mine: Slicing | null): Slicing | null => {
  if (fresh?.state !== 'done' || fresh.run !== sent.run || mine?.run !== sent.run) return fresh
  const before = new Map(sent.fragments.map(f => [f.id, f.label]))
  const now = new Map(mine.fragments.map(f => [f.id, f.label]))
  return {
    ...fresh,
    fragments: fresh.fragments.map(f => {
      const label = now.get(f.id)
      return label !== undefined && label !== before.get(f.id) ? { ...f, label } : f
    }),
  }
}

export function CouncilPage({ stage }: Readonly<{ stage: Stage }>) {
  const { id = '' } = useParams()
  // Свой экземпляр на каждый совет: очередь сохранения не перенесёт правки в чужой.
  return <CouncilView key={id} id={id} stage={stage} />
}

function CouncilView({ id, stage }: Readonly<{ id: string; stage: Stage }>) {
  const { t } = useTranslation()
  const { state, retry, update } = useLoad(() => loadCouncil(id), [id])

  // С сервера берём ходы совета и статус: текст и название могут быть ещё не сохранены.
  // sent — нарезка на экране, когда ушёл запуск: правки типов после него ответ не откатит.
  // Сколько ответов на действия экран принял: опрос, ушедший раньше последнего, устарел.
  const acted = useRef(0)
  const adopt = useCallback((fresh: Council, sent?: Slicing | null) => {
    acted.current += 1
    update(([c, settings]) => [{
      ...c, status: fresh.status, structure: fresh.structure, streams: fresh.streams,
      slicing: sent ? rebased(fresh.slicing, sent, c.slicing) : fresh.slicing,
    }, settings])
  }, [update])

  const saver = useAutosave(async (patch: CouncilPatch) => {
    try {
      return await api.updateCouncil(id, patch)
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409 && patch.labels)) throw e
      // Нарезку переделали, пока здесь была прежняя: её типы относятся к другим фрагментам.
      // Остальное из правки сохраняем, типы бросаем и показываем нынешнюю нарезку.
      const rest: CouncilPatch = { ...patch }
      delete rest.labels
      delete rest.slicing_run
      if (Object.keys(rest).length > 0) await api.updateCouncil(id, rest)
      adopt(await api.council(id))
      return undefined
    }
  })
  const { schedule } = saver

  const council = state.kind === 'ok' ? state.data[0] : null
  const title = council && (council.name || t('council.untitled'))
  const setCrumb = useOutletContext<Layout | undefined>()?.setCrumb
  useEffect(() => {
    setCrumb?.(title)
    return () => setCrumb?.(null)
  }, [setCrumb, title])

  // Экран показывает правку сразу, сервер получает её чуть позже.
  const change = useCallback((patch: CouncilPatch, wait: number) => {
    update(([c, settings]) => [{ ...c, ...patch }, settings])
    schedule(patch, wait)
  }, [update, schedule])

  // Тип фрагмента, выбранный человеком. Уходит только он: правка из другой вкладки по
  // другому фрагменту не откатится, а очередь сохранения сольёт несколько правок в одну.
  const relabel = useCallback((fragmentId: number, label: Label) => {
    const done = council?.slicing
    if (!done) return
    const fragments = done.fragments.map(f => (f.id === fragmentId ? { ...f, label } : f))
    update(([c, settings]) => [{ ...c, slicing: { ...done, fragments } }, settings])
    schedule({ labels: { [fragmentId]: label }, slicing_run: done.run }, 0)
  }, [council?.slicing, update, schedule])

  // Опрос, пока идёт нарезка, раскладка или поиск идей. Следующий запрос — только после
  // ответа на предыдущий, и из ответа берётся только тот ход, что на экране ещё идёт:
  // запоздалый ответ не затрёт готовый итог, правки типов и утверждённые идеи.
  const polling = useRef(false)
  const polled = useCallback((fresh: Council) =>
    update(([c, settings]) => {
      const next = { ...c, status: fresh.status }
      if (c.slicing?.state === 'running') next.slicing = fresh.slicing
      if (c.structure?.state === 'running') next.structure = fresh.structure
      if (c.streams && seeking(c)) next.streams = followed(c.streams, fresh.streams)
      return [next, settings]
    }), [update])
  const working = council?.slicing?.state === 'running' || council?.structure?.state === 'running'
    || (council !== null && seeking(council))
  useInterval(() => {
    if (polling.current) return
    polling.current = true
    // Пока опрос был в пути, экран принял ответ на действие (утвердили идею, начали поиск) —
    // ответ опроса старше него и стёр бы его. Пропускаем: следующий опрос принесёт свежее.
    const at = acted.current
    api.council(id).then(fresh => { if (acted.current === at) polled(fresh) }, () => { /* следующий опрос */ })
      .finally(() => { polling.current = false })
  }, working ? POLL_MS : null)

  if (state.kind === 'error' && state.error instanceof CouncilMissing) return (
    <main className="main">
      <h1 className="page-title">{t('council.notFound')}</h1>
      <p className="page-sub">
        {t('council.notFoundHint')} <Link to="/">{t('council.backToList')}</Link>
      </p>
    </main>
  )

  if (state.kind === 'error') return (
    <main className="main">
      <h1 className="page-title">{t('council.loadFailed')}</h1>
      <p className="page-sub">{t('council.loadFailedHint')}</p>
      <button className="btn-primary" style={{ marginTop: 12 }} onClick={retry}>{t('common.retry')}</button>
    </main>
  )

  return (
    <>
      <nav className="stage-bar" aria-label={t('council.stages')}>
        {/* Номер этапа — в цвете светофора; словами то же — для скринридера. */}
        {STAGES.map((s, i) => {
          const light = council === null ? 'idle' : stageLight(council, s)
          return (
            <NavLink key={s} to={councilPath(id, s)} className="tab">
              {({ isActive }) => (
                <>
                  <span className={`tab-num ${light}`} aria-hidden="true">
                    {light === 'done' && !isActive ? '✓' : i + 1}
                  </span>
                  {t(`stage.${s}`)}
                  <span className="sr-only"> ({t(`light.${light}`)})</span>
                </>
              )}
            </NavLink>
          )
        })}
      </nav>
      <main className="main">
        <h1 className="sr-only">{title ?? t('common.loading')}</h1>
        {state.kind === 'loading' && <div className="card muted">{t('common.loading')}</div>}
        {state.kind === 'ok' && stage === 'brief' && (
          <BriefStage council={state.data[0]} settings={state.data[1]} onChange={change}
                      onStart={adopt} saver={saver} />
        )}
        {state.kind === 'ok' && stage === 'slices' && (
          <SlicesStage council={state.data[0]} settings={state.data[1]} onStart={adopt}
                       onRelabel={relabel} saver={saver} />
        )}
        {state.kind === 'ok' && stage === 'structure' && (
          <GroupsStage council={state.data[0]} settings={state.data[1]} onStart={adopt} />
        )}
        {state.kind === 'ok' && stage === 'streams' && (
          <StreamsStage council={state.data[0]} settings={state.data[1]} onChange={adopt} />
        )}
        {state.kind === 'ok' && stage === 'history' && (
          <div className="card placeholder">{t('council.stub', { stage: t(`stage.${stage}`) })}</div>
        )}
      </main>
    </>
  )
}
