import { isTauri as isTauriRuntime } from '@tauri-apps/api/core'

const EXTERNAL_PROTOCOLS = new Set(['http:', 'https:', 'mailto:', 'tel:'])

let desktopRuntime

export function isDesktopApp() {
  if (desktopRuntime === undefined) {
    desktopRuntime = isTauriRuntime()
  }
  return desktopRuntime
}

export async function getDesktopAppVersion() {
  if (!isDesktopApp()) return null

  const { getVersion } = await import('@tauri-apps/api/app')
  return getVersion()
}

export function reloadDesktopWindow() {
  window.location.reload()
}

export async function openExternalUrl(value) {
  let url
  try {
    url = new URL(value, window.location.href)
  } catch {
    return false
  }

  if (!EXTERNAL_PROTOCOLS.has(url.protocol)) {
    return false
  }

  if (isDesktopApp()) {
    const { openUrl } = await import('@tauri-apps/plugin-opener')
    await openUrl(url.href)
  } else {
    window.open(url.href, '_blank', 'noopener,noreferrer')
  }

  return true
}
