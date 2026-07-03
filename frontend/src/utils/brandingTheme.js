import { Dark, setCssVar } from 'quasar'

const STYLE_ID = 'pyrate-branding-css'
const THEME_CLASS_PREFIX = 'pyrate-theme-'

function safeToken(value) {
  return String(value || '')
    .trim()
    .replace(/[^A-Za-z0-9_-]/g, '-')
}

function setStyleContent(cssText) {
  let style = document.getElementById(STYLE_ID)
  if (!style) {
    style = document.createElement('style')
    style.id = STYLE_ID
    document.head.appendChild(style)
  }
  style.textContent = cssText || ''
}

function clearThemeClasses() {
  for (const className of Array.from(document.body.classList)) {
    if (className.startsWith(THEME_CLASS_PREFIX)) {
      document.body.classList.remove(className)
    }
  }
}

function applyThemeVariables(theme) {
  const rootStyle = document.documentElement.style

  for (const [name, value] of Object.entries(theme?.colors || {})) {
    if (!name || !value) continue
    const token = safeToken(name)
    setCssVar(token, value)
    rootStyle.setProperty(`--q-${token}`, String(value))
  }

  for (const [name, value] of Object.entries(theme?.variables || {})) {
    if (!name || value == null) continue
    const cssVariable = String(name).startsWith('--') ? String(name) : `--pyrate-${safeToken(name)}`
    rootStyle.setProperty(cssVariable, String(value))
  }
}

export function applyBranding(configuration, theme) {
  clearThemeClasses()
  document.body.classList.add(theme?.id ? `${THEME_CLASS_PREFIX}${safeToken(theme.id)}` : 'pyrate-theme-default')

  if (typeof theme?.dark === 'boolean') {
    Dark.set(theme.dark)
  }

  applyThemeVariables(theme)
  setStyleContent([configuration?.custom_css, theme?.custom_css].filter(Boolean).join('\n\n'))
}
