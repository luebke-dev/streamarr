/**
 * Overlay-aware poster URL helpers.
 *
 * For local MediaItems of type MOVIES/SHOWS we point the browser at the
 * overlay-serving endpoint, which returns a pre-rendered overlay on
 * cache hit and 302-redirects to the original poster on miss. For any
 * other media type or external item (search results without a local
 * guid), the caller's existing TMDB / artwork resolution should kick
 * in via the ``fallback`` argument.
 */

/**
 * @param {object|null|undefined} item — media item with optional ``guid`` and ``media_type``.
 * @returns {string|null} serve URL when applicable, else null.
 */
export function overlayServeUrl(item, target = 'POSTER') {
  if (!item || !item.guid) return null
  const mt = item.media_type
  if (mt !== 'MOVIES' && mt !== 'SHOWS') return null
  return `/api/overlays/serve/${item.guid}?target=${encodeURIComponent(target)}`
}

/**
 * Combined resolver: overlay URL when applicable, else the supplied fallback.
 *
 * Pattern:
 *   const url = posterUrl(item, () => getTmdbImageUrl(item.poster_path, 'w300'))
 */
export function posterUrl(item, fallback) {
  const overlay = overlayServeUrl(item, 'POSTER')
  if (overlay) return overlay
  if (typeof fallback === 'function') return fallback()
  return fallback ?? null
}

/** Same but for backdrops. */
export function backdropUrl(item, fallback) {
  const overlay = overlayServeUrl(item, 'BACKDROP')
  if (overlay) return overlay
  if (typeof fallback === 'function') return fallback()
  return fallback ?? null
}
