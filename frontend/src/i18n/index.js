import enUS from './en-US'

export const DEFAULT_LOCALE = 'en-US'
export const AVAILABLE_LOCALES = ['en-US', 'de-DE']

// Only the default locale is bundled eagerly. Others load on demand via loadLocale().
export default {
  'en-US': enUS,
}

const loaders = {
  'de-DE': () => import('./de-DE'),
}

export async function loadLocale(locale) {
  if (!loaders[locale]) return null
  const mod = await loaders[locale]()
  return mod.default
}
