/**
 * Unified formatting and image URL utilities for media items.
 *
 * This is the SINGLE SOURCE OF TRUTH for:
 * - Duration/time formatting
 * - Date formatting
 * - File size formatting
 * - Artwork image URL building
 * - Media item type detection and property access
 *
 * Do NOT duplicate these functions elsewhere.
 */

import { getServerUrl } from 'src/utils/authStorage'

// ─────────────────────────────────────────────────────────────────────────────
// Artwork Image URLs
// ─────────────────────────────────────────────────────────────────────────────

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p'
const ARTWORK_PROXY_HOSTS = new Set([
  'image.tmdb.org',
  'images.igdb.com',
  'covers.openlibrary.org',
  'i.scdn.co',
])

function artworkCacheEnabled() {
  const override =
    typeof localStorage !== 'undefined'
      ? localStorage.getItem('pyrate_artwork_cache_enabled')
      : null
  if (override != null) return ['1', 'true', 'yes', 'on'].includes(override.toLowerCase())
  return ['1', 'true', 'yes', 'on'].includes(
    String(import.meta.env.VITE_ARTWORK_CACHE_ENABLED || '').toLowerCase(),
  )
}

function canProxyArtwork(url) {
  try {
    const parsed = new URL(url)
    return ARTWORK_PROXY_HOSTS.has(parsed.hostname.toLowerCase())
  } catch {
    return false
  }
}

function getArtworkProxyUrl(url) {
  if (!artworkCacheEnabled() || !canProxyArtwork(url)) return url
  const baseUrl = getServerUrl().replace(/\/$/, '')
  return `${baseUrl}/api/media/images/proxy?url=${encodeURIComponent(url)}`
}

/**
 * Build a display URL for artwork from local paths, remote URLs or provider paths.
 * Remote provider URLs are routed through the optional pyrate artwork cache when enabled.
 *
 * @param {string} source - Local URL, remote URL, or provider image path.
 * @param {Object} options
 * @param {string} options.provider - Provider path namespace. Currently "tmdb" for relative paths.
 * @param {string} options.size - Provider size key (e.g. w300, w500, w1280, original).
 * @returns {string|null} Full URL or null if no path
 */
export function getArtworkImageUrl(source, { provider = 'tmdb', size = 'w500' } = {}) {
  if (!source) return null
  if (
    source.startsWith('/api/') ||
    source.startsWith('/icons/') ||
    source.startsWith('blob:') ||
    source.startsWith('data:')
  ) {
    return source
  }
  if (source.startsWith('http')) return getArtworkProxyUrl(source)
  if (provider === 'tmdb') return getArtworkProxyUrl(`${TMDB_IMAGE_BASE}/${size}${source}`)
  return source
}

/**
 * TMDB compatibility helper for existing call sites.
 * Prefer getArtworkImageUrl() for new code.
 */
export function getTmdbImageUrl(path, size = 'w500') {
  return getArtworkImageUrl(path, { provider: 'tmdb', size })
}

/** Poster URL (default w500) */
export function getTmdbPosterUrl(posterPath, size = 'w500') {
  return getArtworkImageUrl(posterPath, { provider: 'tmdb', size })
}

/** Backdrop URL (default w1280) */
export function getTmdbBackdropUrl(backdropPath, size = 'w1280') {
  return getArtworkImageUrl(backdropPath, { provider: 'tmdb', size })
}

/** Still image URL for episodes (default w300) */
export function getTmdbStillUrl(stillPath, size = 'w300') {
  return getArtworkImageUrl(stillPath, { provider: 'tmdb', size })
}

/**
 * Get the best available image URL for a media item.
 * Prefers backdrop for wide formats, falls back to poster, then a default icon.
 *
 * For local MOVIE/SHOW items with a guid this routes through the
 * overlay-aware serving endpoint (``/api/overlays/serve/{guid}``) so
 * the browser receives a pre-rendered overlay on cache hit, transparently
 * falling back to the original poster URL on miss.
 */
export function getMediaImageUrl(mediaItem, { preferBackdrop = true, width = 'w780' } = {}) {
  const fallback = '/icons/favicon-128x128.png'
  if (!mediaItem) return fallback

  // Overlay-aware route for local items. Episodes/books/games/music
  // skip this branch and fall through to provider-specific logic.
  if (
    mediaItem.guid
    && (mediaItem.media_type === 'MOVIES' || mediaItem.media_type === 'SHOWS')
    && (mediaItem.poster_path || mediaItem.backdrop_path)
  ) {
    const target = preferBackdrop && mediaItem.backdrop_path ? 'BACKDROP' : 'POSTER'
    return `/api/overlays/serve/${mediaItem.guid}?target=${target}`
  }

  if (mediaItem.cover_url) return getArtworkImageUrl(mediaItem.cover_url)
  if (mediaItem.poster_url) {
    return getArtworkImageUrl(mediaItem.poster_url, { provider: 'tmdb', size: 'w500' })
  }
  if (preferBackdrop && mediaItem.backdrop_path) {
    return getArtworkImageUrl(mediaItem.backdrop_path, { provider: 'tmdb', size: width })
  }
  if (mediaItem.poster_path) {
    return getArtworkImageUrl(mediaItem.poster_path, { provider: 'tmdb', size: 'w500' })
  }
  return fallback
}

// ─────────────────────────────────────────────────────────────────────────────
// Duration / Time formatting
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format seconds into H:MM:SS or M:SS (player-style).
 * @param {number} seconds
 * @returns {string} e.g. "1:23:45" or "3:05"
 */
export function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return '--:--'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }
  return `${m}:${String(s).padStart(2, '0')}`
}

/**
 * Format time for player display. Alias for formatDuration with NaN guard.
 */
export function formatTime(seconds) {
  if (!seconds || !isFinite(seconds)) return '0:00'
  return formatDuration(seconds)
}

/**
 * Format seconds into compact watch-time string (Xh Ym).
 */
export function formatWatchTime(seconds) {
  if (!seconds || seconds === 0) return '0m'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

/**
 * Format runtime in minutes to "Xh Ym" (for movie/episode metadata).
 */
export function formatRuntime(minutes) {
  if (!minutes) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

/**
 * Format seconds into H:MM:SS with seconds always shown (e.g., session duration).
 */
export function formatLongDuration(seconds, fallback = '-') {
  if (!seconds) return fallback
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

// ─────────────────────────────────────────────────────────────────────────────
// Date formatting
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format date with time (e.g., "Jan 15, 2024, 14:30").
 */
export function formatDate(dateString, { locale = 'en-US', fallback = 'Unknown' } = {}) {
  if (!dateString) return fallback
  return new Date(dateString).toLocaleDateString(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Format date without time (e.g., "January 15, 2024").
 */
export function formatAirDate(dateString, locale = 'en-US') {
  if (!dateString) return 'To be announced'
  return new Date(dateString).toLocaleDateString(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

/**
 * Format date to year only.
 */
export function formatYear(dateString) {
  if (!dateString) return 'TBA'
  return new Date(dateString).getFullYear().toString()
}

/**
 * Format relative time (e.g., "2 hours ago", "3 days ago").
 */
export function formatRelativeTime(dateString) {
  if (!dateString) return ''
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.round(diffMs / 60000)
  const diffHours = Math.round(diffMs / 3600000)
  const diffDays = Math.round(diffMs / 86400000)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`
  if (diffHours < 24) return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`
  if (diffDays < 7) return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`
  return formatAirDate(dateString)
}

/**
 * Check if a date is in the future.
 */
export function isFutureDate(dateString) {
  if (!dateString) return false
  return new Date(dateString) > new Date()
}

// ─────────────────────────────────────────────────────────────────────────────
// File / size formatting
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format file size in human-readable format (e.g., "1.5 GB").
 */
export function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

/**
 * Extract filename from file path.
 */
export function getFileName(filePath) {
  if (!filePath) return 'Unknown'
  const parts = filePath.split('/')
  return parts[parts.length - 1]
}

// ─────────────────────────────────────────────────────────────────────────────
// Episode title formatting
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format an episode title with show name and S##E## label.
 */
export function formatEpisodeTitle({
  showTitle,
  seasonNumber,
  episodeNumber,
  episodeTitle,
  fallback = '',
}) {
  if (showTitle && seasonNumber != null && episodeNumber != null) {
    const label = `S${String(seasonNumber).padStart(2, '0')}E${String(episodeNumber).padStart(2, '0')}`
    return episodeTitle ? `${showTitle} - ${label}: ${episodeTitle}` : `${showTitle} - ${label}`
  }
  return episodeTitle || fallback
}

// ─────────────────────────────────────────────────────────────────────────────
// Media item type detection
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Normalize a media type string to a singular lowercase form.
 * @param {object} item - Media item with media_type or type field
 * @returns {string} 'movie' | 'show' | 'game' | 'music' | 'book'
 */
export function getItemType(item) {
  if (!item) return 'movie'
  const type = (item.media_type || item.type || '').toUpperCase()
  if (type === 'MOVIES' || type === 'MOVIE') return 'movie'
  if (type === 'SHOWS' || type === 'SHOW' || type === 'SEASONS' || type === 'EPISODES')
    return 'show'
  if (type === 'GAMES' || type === 'GAME') return 'game'
  if (type === 'ARTISTS' || type === 'ARTIST') return 'artist'
  if (type === 'ALBUMS' || type === 'ALBUM') return 'album'
  if (type === 'SONGS' || type === 'SONG') return 'song'
  if (type === 'MUSIC') return 'music'
  if (type === 'BOOKS' || type === 'BOOK') return 'book'
  if (type === 'AUDIOBOOKS' || type === 'AUDIOBOOK') return 'book'
  return 'movie'
}

// ─────────────────────────────────────────────────────────────────────────────
// Rating helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format vote average to rating with star.
 */
export function formatRating(voteAverage) {
  if (!voteAverage) return 'N/A'
  return `${voteAverage.toFixed(1)} ★`
}

/**
 * Get Quasar color name based on vote average.
 */
export function getRatingColor(voteAverage) {
  if (!voteAverage) return 'grey'
  if (voteAverage >= 7) return 'positive'
  if (voteAverage >= 5) return 'warning'
  return 'negative'
}

// ─────────────────────────────────────────────────────────────────────────────
// Genre formatting
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format genres array to comma-separated string.
 */
export function formatGenres(genres) {
  if (!genres || !genres.length) return ''
  return genres.map((genre) => genre.name || genre).join(', ')
}
