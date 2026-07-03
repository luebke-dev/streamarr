/**
 * Unified Media API Composable
 *
 * Provides methods to interact with the unified /api/media endpoints
 * for all media types (movies, shows, games, music, books).
 */

import { api } from 'boot/axios'
import { cachedApiGet, invalidateApiCache } from 'src/composables/useApiResponseCache'

/**
 * List media items with filtering and pagination
 * @param {Object} params - Query parameters
 * @param {string} params.media_type - Filter by media type (movies, series, games, music, books)
 * @param {string} params.media_type - Filter by media type (MOVIES, SHOWS, etc.)
 * @param {string} params.parent_guid - Filter by parent GUID (for episodes, tracks, etc.)
 * @param {number} params.page - Page number (default: 1)
 * @param {number} params.per_page - Items per page (default: 20)
 * @param {string} params.order_by - Field to order by (default: created_at)
 * @param {boolean} params.order_desc - Descending order (default: true)
 * @returns {Promise} API response with paginated media items
 */
export async function listMediaItems(params = {}) {
  const response = await cachedApiGet(
    '/api/media',
    { params },
    { ttlMs: 30_000, staleTtlMs: 300_000 },
  )
  return response.data
}

/**
 * Get a specific media item by GUID
 * @param {string} itemGuid - Media item GUID
 * @param {Object} options - Loading options
 * @param {boolean} options.load_files - Load associated files
 * @param {boolean} options.load_releases - Load available releases
 * @param {boolean} options.load_external_ids - Load external IDs
 * @returns {Promise} API response with media item details
 */
export async function getMediaItem(itemGuid, options = {}) {
  const params = {
    load_files: options.load_files !== false,
    load_releases: options.load_releases !== false,
    load_external_ids: options.load_external_ids !== false,
  }
  // Always go through the response cache so reads are consistent (no runtime
  // fetcher switch that bypasses caching / dedup).
  const response = await cachedApiGet(
    `/api/media/${itemGuid}`,
    { params },
    { ttlMs: 60_000, staleTtlMs: 10 * 60_000 },
  )
  return response.data
}

/**
 * Create a new media item
 * @param {Object} itemData - Media item data
 * @returns {Promise} API response with created media item
 */
export async function createMediaItem(itemData) {
  const response = await api.post('/api/media', itemData)
  return response.data
}

/**
 * Update a media item
 * @param {string} itemGuid - Media item GUID
 * @param {Object} updateData - Fields to update
 * @returns {Promise} API response with updated media item
 */
export async function updateMediaItem(itemGuid, updateData) {
  const response = await api.patch(`/api/media/${itemGuid}`, updateData)
  invalidateApiCache(`/api/media/${itemGuid}`)
  invalidateApiCache('/api/page-layouts/')
  return response.data
}

/**
 * Delete a media item
 * @param {string} itemGuid - Media item GUID
 * @returns {Promise} API response
 */
export async function deleteMediaItem(itemGuid) {
  const response = await api.delete(`/api/media/${itemGuid}`)
  invalidateApiCache(`/api/media/${itemGuid}`)
  invalidateApiCache('/api/page-layouts/')
  return response.data
}

/**
 * Search media items by query
 * @param {string} query - Search query
 * @param {Object} options - Search options
 * @param {string} options.media_type - Filter by media type
 * @param {string} options.media_type - Filter by media type
 * @param {number} options.limit - Max results (default: 50)
 * @returns {Promise} API response with search results
 */
export async function searchMediaItems(query, options = {}) {
  const params = {
    q: query,
    ...options,
  }
  const response = await cachedApiGet(
    '/api/media/search/query',
    { params },
    { ttlMs: 60_000, staleTtlMs: 10 * 60_000 },
  )
  return response.data
}

/**
 * Get child media items (seasons, episodes, tracks)
 * @param {string} itemGuid - Parent media item GUID
 * @param {boolean} orderBySequence - Order by sequence number
 * @returns {Promise} API response with child items
 */
export async function getMediaItemChildren(itemGuid, orderBySequence = true) {
  const params = { order_by_sequence: orderBySequence }
  const response = await cachedApiGet(
    `/api/media/${itemGuid}/children`,
    { params },
    { ttlMs: 60_000, staleTtlMs: 10 * 60_000 },
  )
  return response.data
}

/**
 * Get complete show hierarchy (show -> seasons -> episodes)
 * @param {string} showGuid - Show GUID
 * @returns {Promise} API response with show hierarchy
 */
export async function getShowHierarchy(showGuid) {
  const response = await api.get(`/api/media/shows/${showGuid}/hierarchy`)
  return response.data
}

/**
 * Get album with tracks
 * @param {string} albumGuid - Album GUID
 * @returns {Promise} API response with album and tracks
 */
export async function getAlbumTracks(albumGuid) {
  const response = await api.get(`/api/media/albums/${albumGuid}/tracks`)
  return response.data
}

/**
 * Get releases for a media item
 * @param {string} itemGuid - Media item GUID
 * @param {Object} params - Query parameters
 * @param {number} params.page - Page number
 * @param {number} params.per_page - Items per page
 * @returns {Promise} API response with releases
 */
export async function getMediaItemReleases(itemGuid, params = {}) {
  const response = await api.get(`/api/media/${itemGuid}/releases`, { params })
  return response.data
}

/**
 * Create a new release for a media item
 * @param {string} itemGuid - Media item GUID
 * @param {Object} releaseData - Release data
 * @returns {Promise} API response with created release
 */
export async function createMediaRelease(itemGuid, releaseData) {
  const response = await api.post(`/api/media/${itemGuid}/releases`, releaseData)
  return response.data
}

/**
 * Get media item by external ID
 * @param {string} provider - Provider name (tmdb, igdb, etc.)
 * @param {string} externalId - External ID
 * @param {string} mediaType - Optional media type filter
 * @returns {Promise} API response with media item
 */
export async function getMediaItemByExternalId(provider, externalId, mediaType = null) {
  const params = mediaType ? { media_type: mediaType } : {}
  const response = await api.get(`/api/media/external/${provider}/${externalId}`, { params })
  return response.data
}

/**
 * Update availability status of a media item
 * @param {string} itemGuid - Media item GUID
 * @param {string} status - New status (unknown, available, downloadable, unavailable)
 * @returns {Promise} API response
 */
export async function updateMediaAvailability(itemGuid, status) {
  const params = { status }
  const response = await api.patch(`/api/media/${itemGuid}/availability`, null, { params })
  return response.data
}

// Media type constants for convenience
// These match the backend MediaType enum values
export const MediaTypes = {
  MOVIES: 'MOVIES',
  SHOWS: 'SHOWS', // Backend uses SHOWS not SERIES
  SERIES: 'SHOWS', // Alias for backward compatibility
  GAMES: 'GAMES',
  MUSIC: 'MUSIC',
  ARTISTS: 'ARTISTS',
  ALBUMS: 'ALBUMS',
  SONGS: 'SONGS',
  BOOKS: 'BOOKS',
}

// Availability status constants
export const AvailabilityStatus = {
  UNKNOWN: 'unknown',
  AVAILABLE: 'available',
  DOWNLOADABLE: 'downloadable',
  UNAVAILABLE: 'unavailable',
}
