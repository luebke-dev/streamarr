import { useI18n } from 'vue-i18n'
import {
  getTmdbPosterUrl,
  getTmdbBackdropUrl,
  getTmdbStillUrl,
  formatYear as baseFormatYear,
  formatAirDate as baseFormatAirDate,
  formatDate as baseFormatDate,
  formatRelativeTime as baseFormatRelativeTime,
  formatRuntime,
  formatFileSize,
  formatDuration,
  formatGenres,
  formatRating,
  getRatingColor,
  isFutureDate,
} from './useMediaFormatters'

/**
 * Composable that wraps useMediaFormatters with i18n-aware defaults.
 * Use this in components that need localized fallback strings.
 */
export function useMediaHelpers() {
  const { t } = useI18n()

  const getPosterUrl = (media) => {
    if (media?.poster_url) return getTmdbPosterUrl(media.poster_url)
    if (!media?.poster_path) return null
    return getTmdbPosterUrl(media.poster_path)
  }

  const getBackdropUrl = (media) => {
    if (!media?.backdrop_path) return null
    return getTmdbBackdropUrl(media.backdrop_path)
  }

  const getStillUrl = (media) => {
    if (!media?.still_path) return null
    return getTmdbStillUrl(media.still_path)
  }

  const formatYear = (dateString) => {
    if (!dateString) return null
    return baseFormatYear(dateString)
  }

  const formatFullDate = (dateString) => {
    if (!dateString) return t('common.toBeAnnounced') || 'To be announced'
    const locale = t('common.locale') || 'en-US'
    return baseFormatAirDate(dateString, locale)
  }

  const formatDateTime = (dateString) => {
    if (!dateString) return t('common.unknown') || 'Unknown'
    const locale = t('common.locale') || 'en-US'
    return baseFormatDate(dateString, { locale })
  }

  const formatRelativeTime = (dateString) => {
    if (!dateString) return t('common.unknown') || 'Unknown'
    return baseFormatRelativeTime(dateString)
  }

  const getMediaStatus = (dateString) => {
    if (!dateString) return 'unknown'
    return new Date(dateString) > new Date() ? 'upcoming' : 'released'
  }

  const isEpisodeFuture = (dateString) => {
    if (!dateString) return true
    return isFutureDate(dateString)
  }

  return {
    getPosterUrl,
    getBackdropUrl,
    getStillUrl,
    formatYear,
    formatFullDate,
    formatDateTime,
    formatRelativeTime,
    formatRuntime,
    formatFileSize,
    formatDuration,
    formatGenres,
    formatRating,
    getMediaStatus,
    isEpisodeFuture,
    getRatingColor,
  }
}
