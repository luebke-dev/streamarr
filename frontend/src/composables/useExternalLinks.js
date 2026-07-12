/**
 * Shared safety helper for external-provider links.
 *
 * `link.url` on media/person records comes from remote/scraped provider
 * metadata, so it must never be bound to an anchor href without a scheme
 * allow-list. A `javascript:` or `data:` URL that lands in that metadata would
 * otherwise execute in the app origin when the user clicks the link.
 *
 * Mirrors the EXTERNAL_PROTOCOLS allow-list used by the Tauri desktop click
 * handler (utils/desktopPlatform.js) so web and desktop behave the same.
 */
const SAFE_PROTOCOLS = new Set(['http:', 'https:', 'mailto:', 'tel:'])

/**
 * Return a safe href for an external link, or null when the URL is missing or
 * uses a disallowed scheme. Bind the result to `:href` so a null value renders
 * a non-navigating button instead of an executable link.
 *
 * @param {string} value
 * @returns {string|null}
 */
export function safeExternalHref(value) {
  if (!value) return null
  let url
  try {
    url = new URL(value, window.location.href)
  } catch {
    return null
  }
  return SAFE_PROTOCOLS.has(url.protocol) ? url.href : null
}
