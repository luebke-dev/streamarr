// Available languages with native labels and flags.
// Shared across language selector components.

export const UI_LANGUAGES = [
  { value: 'en-US', label: 'English', flag: '🇺🇸' },
  { value: 'de-DE', label: 'Deutsch', flag: '🇩🇪' },
  { value: 'fr-FR', label: 'Français', flag: '🇫🇷' },
  { value: 'es-ES', label: 'Español', flag: '🇪🇸' },
  { value: 'it-IT', label: 'Italiano', flag: '🇮🇹' },
  { value: 'pt-BR', label: 'Português', flag: '🇧🇷' },
  { value: 'ja-JP', label: '日本語', flag: '🇯🇵' },
  { value: 'ko-KR', label: '한국어', flag: '🇰🇷' },
  { value: 'zh-CN', label: '中文', flag: '🇨🇳' },
]

export const MEDIA_LANGUAGES = [
  { value: 'en', label: 'English', flag: '🇺🇸' },
  { value: 'de', label: 'Deutsch', flag: '🇩🇪' },
  { value: 'fr', label: 'Français', flag: '🇫🇷' },
  { value: 'es', label: 'Español', flag: '🇪🇸' },
  { value: 'it', label: 'Italiano', flag: '🇮🇹' },
  { value: 'pt', label: 'Português', flag: '🇧🇷' },
  { value: 'ja', label: '日本語', flag: '🇯🇵' },
  { value: 'ko', label: '한국어', flag: '🇰🇷' },
  { value: 'zh', label: '中文', flag: '🇨🇳' },
  { value: 'ru', label: 'Русский', flag: '🇷🇺' },
  { value: 'hi', label: 'हिन्दी', flag: '🇮🇳' },
  { value: 'ar', label: 'العربية', flag: '🇸🇦' },
]

export const SUBTITLE_LANGUAGES_OFF = { value: null, label: 'Off', flag: '🚫' }
export const SUBTITLE_LANGUAGES = MEDIA_LANGUAGES

export function getMediaLanguageLabel(code) {
  const lang = MEDIA_LANGUAGES.find((l) => l.value === code)
  return lang ? `${lang.flag} ${lang.label}` : code
}
