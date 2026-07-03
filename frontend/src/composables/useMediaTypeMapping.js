import { getTmdbImageUrl } from 'src/composables/useMediaFormatters'

/**
 * Maps a result.type (lowercased) to the card-component type expected by PosterCard.
 */
const CARD_TYPE_MAP = {
  games: 'game',
  shows: 'show',
  artists: 'artist',
  albums: 'album',
  songs: 'song',
  music: 'music',
  books: 'book',
  movies: 'movie',
}

/**
 * Maps a result.type (lowercased) to the upper-case media_type string expected
 * by the /api/search/get-or-import endpoint.
 */
const IMPORT_MEDIA_TYPE_MAP = {
  movies: 'MOVIES',
  shows: 'SHOWS',
  games: 'GAMES',
  books: 'BOOKS',
  music: 'MUSIC',
  artists: 'ARTISTS',
  albums: 'MUSIC',
  songs: 'SONGS',
}

/**
 * Composable bundling the small helper functions that translate a search
 * result object into different representations (media type, card type,
 * poster URL, stable key, subtitle).
 *
 * Stateless – safe to call from anywhere.
 */
export function useMediaTypeMapping() {
  function getMediaType(result) {
    return (result?.type || '').toLowerCase()
  }

  function getCardType(result) {
    const type = getMediaType(result)
    return CARD_TYPE_MAP[type] || 'movie'
  }

  /**
   * Returns the upper-case media_type string used by the import endpoint.
   * Spotify results are special-cased based on result.music_type.
   */
  function getImportMediaType(result) {
    if (result?.spotify_id) {
      const musicType = result.music_type || 'album'
      if (musicType === 'artist') return 'ARTISTS'
      if (musicType === 'track') return 'SONGS'
      return 'MUSIC'
    }
    return IMPORT_MEDIA_TYPE_MAP[getMediaType(result)] || 'SHOWS'
  }

  function getPosterUrl(result) {
    if (result?.poster_path) {
      if (result.poster_path.startsWith('http')) return result.poster_path
      return getTmdbImageUrl(result.poster_path, 'w500')
    }
    if (result?.backdrop_path) {
      if (result.backdrop_path.startsWith('http')) return result.backdrop_path
      return getTmdbImageUrl(result.backdrop_path, 'w500')
    }
    return null
  }

  function getResultKey(result) {
    if (result?.id) return result.id
    if (result?.tmdb_id) return `tmdb-${result.type}-${result.tmdb_id}`
    if (result?.spotify_id) return `spotify-${result.music_type || 'album'}-${result.spotify_id}`
    return `${result?.type}-${result?.title}`
  }

  function getSubtitle(result) {
    const parts = []
    if (result?.release_date) parts.push(result.release_date.substring(0, 4))
    else if (result?.first_air_date) parts.push(result.first_air_date.substring(0, 4))
    if (result?.vote_average) parts.push(`${result.vote_average.toFixed(1)}`)
    return parts.join(' · ')
  }

  return {
    getMediaType,
    getCardType,
    getImportMediaType,
    getPosterUrl,
    getResultKey,
    getSubtitle,
  }
}
