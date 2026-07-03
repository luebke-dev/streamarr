import { defineBoot } from '#q-app/wrappers'
import { isDesktopApp, openExternalUrl } from 'src/utils/desktopPlatform'
import { logger } from 'src/utils/logger'

function isExternalNavigation(url) {
  if (!['http:', 'https:', 'mailto:', 'tel:'].includes(url.protocol)) {
    return false
  }

  return url.protocol === 'mailto:' || url.protocol === 'tel:' || url.origin !== window.location.origin
}

function findAnchor(target) {
  return target?.closest?.('a[href]')
}

export default defineBoot(() => {
  if (!isDesktopApp()) return

  document.addEventListener('click', (event) => {
    const anchor = findAnchor(event.target)
    if (!anchor) return

    let url
    try {
      url = new URL(anchor.href, window.location.href)
    } catch {
      return
    }

    if (!isExternalNavigation(url)) return

    event.preventDefault()
    openExternalUrl(url.href).catch((error) => {
      logger.error('[Desktop] Failed to open external URL:', error)
    })
  })
})
