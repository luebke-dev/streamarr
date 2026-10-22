import { defineBoot } from '#q-app/wrappers'
import { invoke } from '@tauri-apps/api/core'
import { isDesktopApp } from 'src/utils/desktopPlatform'

/**
 * Sends JavaScript errors from the webview into the app's log.
 *
 * Why this exists: a failure in the UI used to be invisible. It happened in the
 * webview's console, which nothing reads, and the symptom was "nothing happens" with an
 * empty log — the exact shape of the login and playback problems that cost a day. The
 * shell writes the app log, so the UI has to hand its errors over.
 *
 * Outside the desktop app this is a no-op: a browser console is where those errors
 * belong.
 */
export default defineBoot(({ app }) => {
  if (!isDesktopApp()) return

  const send = (level, message) => {
    // Never let the reporter break the page it reports on.
    try {
      invoke('frontend_log', { level, message: String(message).slice(0, 2000) }).catch(() => {})
    } catch {
      /* nothing left to report to */
    }
  }

  window.addEventListener('error', (event) => {
    const where = event.filename ? ` (${event.filename}:${event.lineno}:${event.colno})` : ''
    send('error', `${event.message}${where}`)
  })

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    send('error', `unbehandelte Zusage: ${reason?.stack || reason?.message || reason}`)
  })

  // Vue catches errors thrown inside its own event handlers and prints them to the
  // console — `window.onerror` never sees them. A click handler that throws therefore
  // looked exactly like a click that did nothing, which is what this was chasing.
  app.config.errorHandler = (error, instance, info) => {
    const component = instance?.$options?.name || instance?.$?.type?.name || 'unbekannt'
    const name = error?.name || 'Fehler'
    const message = error?.message || String(error)
    send('error', `Vue (${info}) in ${component}: ${name}: ${message}\n${error?.stack || ''}`)
  }
})
