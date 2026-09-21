import type { Dict } from './ru'

// Без этого t() принимает любую строку: опечатка в ключе всплыла бы только на экране.
declare module 'i18next' {
  interface CustomTypeOptions {
    resources: { translation: Dict }
    keySeparator: false
    nsSeparator: false
  }
}
