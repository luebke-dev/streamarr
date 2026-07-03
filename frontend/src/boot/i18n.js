import { defineBoot } from '#q-app/wrappers'
import { createI18n } from 'vue-i18n'
import { LocalStorage } from 'quasar'
import messages, { AVAILABLE_LOCALES, DEFAULT_LOCALE, loadLocale } from 'src/i18n'

function pickInitialLocale() {
  const savedLanguage = LocalStorage.getItem('user-language')
  if (savedLanguage && AVAILABLE_LOCALES.includes(savedLanguage)) {
    return savedLanguage
  }
  const browserLanguage = navigator.language || navigator.languages?.[0]
  if (browserLanguage) {
    const matched = AVAILABLE_LOCALES.find((l) => browserLanguage.startsWith(l.split('-')[0]))
    if (matched) return matched
  }
  return DEFAULT_LOCALE
}

export default defineBoot(async ({ app }) => {
  const initial = pickInitialLocale()

  const i18n = createI18n({
    locale: initial,
    fallbackLocale: DEFAULT_LOCALE,
    globalInjection: true,
    messages,
  })

  if (initial !== DEFAULT_LOCALE && !messages[initial]) {
    const loaded = await loadLocale(initial)
    if (loaded) {
      i18n.global.setLocaleMessage(initial, loaded)
    } else {
      i18n.global.locale.value = DEFAULT_LOCALE
    }
  }

  app.use(i18n)
})
