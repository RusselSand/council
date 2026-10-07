import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'
import { en } from './en'
import { ru } from './ru'

export const LANGUAGES = ['ru', 'en'] as const
export type Language = (typeof LANGUAGES)[number]

const STORAGE_KEY = 'lang'
const isLanguage = (value: unknown): value is Language =>
  LANGUAGES.includes(value as Language)

// localStorage кидает в приватном режиме и при запрете cookies — выбор языка того не стоит.
const saved = () => {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

const initialLanguage = (): Language => {
  const stored = saved()
  if (isLanguage(stored)) return stored
  return navigator.language.toLowerCase().startsWith('ru') ? 'ru' : 'en'
}

i18next.use(initReactI18next).init({
  lng: initialLanguage(),
  fallbackLng: 'ru',
  resources: { ru: { translation: ru }, en: { translation: en } },
  keySeparator: false,  // ключи вида home.title берём целиком, без вложенности
  nsSeparator: false,   // двоеточие встречается в самих текстах
  interpolation: { escapeValue: false },  // React экранирует сам
})

// <html lang> должен совпадать с языком: от него зависят переносы и произношение в скринридере.
const applyLanguage = (language: string) => {
  document.documentElement.lang = language
}

applyLanguage(i18next.language)
i18next.on('languageChanged', language => {
  applyLanguage(language)
  try {
    localStorage.setItem(STORAGE_KEY, language)
  } catch { /* приватный режим */ }
})

export const setLanguage = (language: Language) => i18next.changeLanguage(language)

/** Момент с бэкенда (ISO с часовым поясом) — дата в поясе человека, в привычном для языка виде. */
export const formatDate = (iso: string) =>
  new Intl.DateTimeFormat(i18next.language, { dateStyle: 'medium' }).format(new Date(iso))

/** Сегодня, словами: «среда, 7 октября 2026 г.». */
export const formatToday = () =>
  new Intl.DateTimeFormat(i18next.language, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
    .format(new Date())

export default i18next
