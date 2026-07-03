// Formatters and helpers for release metadata (score, source, language, etc.)

const langToCountry = {
  en: 'GB',
  de: 'DE',
  fr: 'FR',
  es: 'ES',
  it: 'IT',
  ja: 'JP',
  ko: 'KR',
  zh: 'CN',
  nl: 'NL',
  pt: 'BR',
  ru: 'RU',
  pl: 'PL',
  cs: 'CZ',
  hu: 'HU',
  sv: 'SE',
  no: 'NO',
  da: 'DK',
  fi: 'FI',
  tr: 'TR',
  ar: 'SA',
  he: 'IL',
  hi: 'IN',
  th: 'TH',
  multi: 'UN',
}

const langNames = {
  en: 'English',
  de: 'Deutsch',
  fr: 'Français',
  es: 'Español',
  it: 'Italiano',
  ja: '日本語',
  ko: '한국어',
  zh: '中文',
  nl: 'Nederlands',
  pt: 'Português',
  ru: 'Русский',
  pl: 'Polski',
  cs: 'Čeština',
  hu: 'Magyar',
  sv: 'Svenska',
  no: 'Norsk',
  da: 'Dansk',
  fi: 'Suomi',
  tr: 'Türkçe',
  ar: 'العربية',
  he: 'עברית',
  hi: 'हिन्दी',
  th: 'ไทย',
  multi: 'Multi',
}

const sourceLabels = {
  bluray: 'Blu-ray',
  'web-dl': 'WEB-DL',
  webrip: 'WEBRip',
  hdtv: 'HDTV',
  dvd: 'DVD',
  remux: 'REMUX',
  telesync: 'Telesync',
  telecine: 'Telecine',
  cam: 'CAM',
}

const sourceColors = {
  bluray: 'blue',
  'web-dl': 'cyan-8',
  webrip: 'light-blue-8',
  hdtv: 'green',
  dvd: 'orange',
  remux: 'deep-purple',
  telesync: 'red',
  telecine: 'red',
  cam: 'red',
}

export function getScoreColor(score) {
  if (score == null) return 'grey'
  if (score >= 80) return 'positive'
  if (score >= 60) return 'green'
  if (score >= 40) return 'warning'
  if (score >= 20) return 'orange'
  return 'negative'
}

export function langToFlag(lang) {
  const country = langToCountry[lang?.toLowerCase()]
  if (!country) return lang?.toUpperCase() || '?'
  if (country === 'UN') return '🌍'
  return country
    .split('')
    .map((c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65))
    .join('')
}

export function langToName(lang) {
  return langNames[lang?.toLowerCase()] || lang?.toUpperCase() || '?'
}

export function getSourceLabel(source) {
  return sourceLabels[source?.toLowerCase()] || source?.toUpperCase() || '-'
}

export function getSourceColor(source) {
  return sourceColors[source?.toLowerCase()] || 'grey-7'
}
