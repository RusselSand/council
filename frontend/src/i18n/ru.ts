/** Все надписи интерфейса. Ключ — `<экран>.<элемент>`, тексты правятся только здесь. */
export const ru = {
  'common.retry': 'Повторить',
  'common.loading': 'Загрузка…',

  'header.newCouncil': '+ Новый бриф',
  'header.creating': 'Создаём…',
  'header.createFailed': 'Не удалось создать бриф',
  'header.switchLanguage': 'Switch to English',

  'home.title': 'Советы',
  'home.subtitle': 'От брифа до согласованного ТЗ.',
  'home.loadFailed': 'Не удалось загрузить советы: сервер недоступен или ответил ошибкой.',
  'home.empty': 'Нет советов — нажмите «Новый бриф».',
  'home.meta': 'Автор: {{author}} · Ревьюер: {{reviewer}} · {{updated}}',

  'council.untitled': 'Без названия',
  'council.notFound': 'Совет не найден',
  'council.notFoundHint': 'Возможно, ссылка устарела.',
  'council.backToList': 'К списку советов',
  'council.loadFailed': 'Не удалось загрузить совет',
  'council.loadFailedHint': 'Сервер недоступен или ответил ошибкой.',
  'council.stub': '{{stage}} — заглушка',

  'stage.brief': 'Бриф',
  'stage.approaches': 'Подходы',
  'stage.decisions': 'Решения',
  'stage.spec': 'ТЗ и ревью',
  'stage.history': 'История',

  'status.brief': 'Бриф',
  'status.approaches': 'Подходы',
  'status.decisions': 'Решения',
  'status.review': 'Ревью',
  'status.ready': 'ТЗ согласовано',
} as const

/** Ключи фиксированы словарём ru: у остальных языков ровно такой же набор. */
export type Dict = Record<keyof typeof ru, string>
