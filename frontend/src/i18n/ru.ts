/** Все надписи интерфейса. Ключ — `<экран>.<элемент>`, тексты правятся только здесь. */
export const ru = {
  'common.retry': 'Повторить',
  'common.loading': 'Загрузка…',

  'header.newCouncil': '+ Новый совет',
  'header.creating': 'Создаём…',
  'header.createFailed': 'Не удалось создать совет',
  'header.switchLanguage': 'Switch to English',

  'home.title': 'Советы',
  'home.subtitle': 'От брифа до согласованного ТЗ.',
  'home.loadFailed': 'Не удалось загрузить советы: сервер недоступен или ответил ошибкой.',
  'home.empty': 'Нет советов — нажмите «Новый совет».',
  // Склонение по count — числу участников.
  'home.meta_one': 'Судья: {{judge}} · {{count}} модель · {{updated}}',
  'home.meta_few': 'Судья: {{judge}} · {{count}} модели · {{updated}}',
  'home.meta_many': 'Судья: {{judge}} · {{count}} моделей · {{updated}}',
  'home.meta_other': 'Судья: {{judge}} · {{count}} модели · {{updated}}',

  'council.untitled': 'Без названия',
  'council.notFound': 'Совет не найден',
  'council.notFoundHint': 'Возможно, ссылка устарела.',
  'council.backToList': 'К списку советов',
  'council.loadFailed': 'Не удалось загрузить совет',
  'council.loadFailedHint': 'Сервер недоступен или ответил ошибкой.',
  'council.stub': '{{stage}} — заглушка',
  'council.stages': 'Этапы',
  'council.stageDone': 'пройден',

  'brief.title': 'Мысли в свободной форме',
  'brief.hint': 'Проблема, идея, вопросы, готовые решения — в любом порядке и вперемешку. Совет сам разберёт, что здесь что.',
  'brief.placeholder': 'Что болит, что придумали, что уже решено…',
  'brief.words_one': '{{count}} слово',
  'brief.words_few': '{{count}} слова',
  'brief.words_many': '{{count}} слов',
  'brief.words_other': '{{count}} слова',
  'brief.saving': 'сохраняем…',
  'brief.saveFailed': 'Не удалось сохранить.',
  'brief.leaveAnyway': 'Уйти без сохранения',
  'brief.slice': 'Нарезать →',
  'brief.nameTitle': 'Название',
  'brief.nameHint': 'Как совет будет называться в списке проектов.',
  'brief.councilTitle': 'Совет',
  'brief.councilHint': 'Кто участвует. Нужны минимум две модели.',
  'brief.connectModel': '+ Подключить модель',
  'brief.connectModelSoon': 'Скоро: пока модели задаются в настройках сервера',
  'brief.judge': 'Судья',

  'stage.brief': 'Ввод',
  'stage.slices': 'Нарезка',
  'stage.structure': 'Структура',
  'stage.spec': 'ТЗ и ревью',
  'stage.history': 'История',

  'status.brief': 'Ввод',
  'status.slices': 'Нарезка',
  'status.structure': 'Структура',
  'status.review': 'Ревью',
  'status.ready': 'ТЗ согласовано',
} as const

/** Ключи фиксированы словарём ru: у остальных языков ровно такой же набор. */
export type Dict = Record<keyof typeof ru, string>
