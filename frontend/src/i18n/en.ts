import type { Dict } from './ru'

/**
 * Недостающий или лишний ключ — ошибка компиляции, а не пустое место в интерфейсе.
 * Формы _few и _many английский не использует, но набор ключей общий с ru.
 */
export const en: Dict = {
  'common.retry': 'Retry',
  'common.loading': 'Loading…',

  'header.newCouncil': '+ New council',
  'header.creating': 'Creating…',
  'header.createFailed': 'Could not create the council',
  'header.switchLanguage': 'Переключить на русский',

  'home.title': 'Councils',
  'home.subtitle': 'From a brief to an approved spec.',
  'home.loadFailed': 'Could not load councils: the server is unavailable or returned an error.',
  'home.empty': 'No councils yet — click “New council”.',
  'home.meta_one': 'Judge: {{judge}} · {{count}} model · {{updated}}',
  'home.meta_few': 'Judge: {{judge}} · {{count}} models · {{updated}}',
  'home.meta_many': 'Judge: {{judge}} · {{count}} models · {{updated}}',
  'home.meta_other': 'Judge: {{judge}} · {{count}} models · {{updated}}',

  'council.untitled': 'Untitled',
  'council.notFound': 'Council not found',
  'council.notFoundHint': 'The link may be out of date.',
  'council.backToList': 'Back to the council list',
  'council.loadFailed': 'Could not load the council',
  'council.loadFailedHint': 'The server is unavailable or returned an error.',
  'council.stub': '{{stage}} — placeholder',
  'council.stages': 'Stages',
  'council.stageDone': 'done',

  'brief.title': 'Free-form thoughts',
  'brief.hint': 'Problem, idea, questions, ready-made solutions — in any order, all mixed up. The council will sort out what is what.',
  'brief.placeholder': 'What hurts, what you came up with, what is already decided…',
  'brief.words_one': '{{count}} word',
  'brief.words_few': '{{count}} words',
  'brief.words_many': '{{count}} words',
  'brief.words_other': '{{count}} words',
  'brief.saving': 'saving…',
  'brief.saveFailed': 'Could not save.',
  'brief.slice': 'Slice →',
  'brief.nameTitle': 'Name',
  'brief.nameHint': 'How the council is listed among projects.',
  'brief.councilTitle': 'Council',
  'brief.councilHint': 'Who takes part. At least two models.',
  'brief.connectModel': '+ Connect a model',
  'brief.connectModelSoon': 'Coming soon: models are set in the server settings for now',
  'brief.judge': 'Judge',

  'stage.brief': 'Input',
  'stage.slices': 'Slicing',
  'stage.structure': 'Structure',
  'stage.spec': 'Spec & review',
  'stage.history': 'History',

  'status.brief': 'Input',
  'status.slices': 'Slicing',
  'status.structure': 'Structure',
  'status.review': 'Review',
  'status.ready': 'Spec approved',
}
