import type { Dict } from './ru'

/** Недостающий или лишний ключ — ошибка компиляции, а не пустое место в интерфейсе. */
export const en: Dict = {
  'common.retry': 'Retry',
  'common.loading': 'Loading…',

  'header.newCouncil': '+ New brief',
  'header.creating': 'Creating…',
  'header.createFailed': 'Could not create the brief',
  'header.switchLanguage': 'Переключить на русский',

  'home.title': 'Councils',
  'home.subtitle': 'From a brief to an approved spec.',
  'home.loadFailed': 'Could not load councils: the server is unavailable or returned an error.',
  'home.empty': 'No councils yet — click “New brief”.',
  'home.meta': 'Author: {{author}} · Reviewer: {{reviewer}} · {{updated}}',

  'council.untitled': 'Untitled',
  'council.notFound': 'Council not found',
  'council.notFoundHint': 'The link may be out of date.',
  'council.backToList': 'Back to the council list',
  'council.loadFailed': 'Could not load the council',
  'council.loadFailedHint': 'The server is unavailable or returned an error.',
  'council.stub': '{{stage}} — placeholder',

  'stage.brief': 'Brief',
  'stage.approaches': 'Approaches',
  'stage.decisions': 'Decisions',
  'stage.spec': 'Spec & review',
  'stage.history': 'History',

  'status.brief': 'Brief',
  'status.approaches': 'Approaches',
  'status.decisions': 'Decisions',
  'status.review': 'Review',
  'status.ready': 'Spec approved',
}
