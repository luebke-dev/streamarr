import { MediaTypes } from 'src/composables/useUnifiedMedia'
import { startPlayback, getDirectFileUrl, getPlaylistUrl } from 'src/composables/usePlay'
import { getServerUrl } from 'src/utils/authStorage'

/**
 * Cast / remote-target playback routing for the media detail page.
 *
 * Encapsulates how a play action is dispatched to a remote target: native
 * Cast devices get a resolved media URL + metadata pushed via a remote
 * command, while other remote targets receive higher-level play-media/queue
 * commands. Also exposes the play-type resolvers and the audio-player track
 * mapper shared between the page's play handlers.
 *
 * @param {Object} deps
 * @param {import('vue').Ref} deps.mediaItem
 * @param {import('vue').Ref} deps.files
 * @param {import('vue').Ref} deps.parentItem
 * @param {import('vue').Ref} deps.heroTitle
 * @param {import('vue').Ref} deps.heroPosterUrl
 * @param {import('vue').Ref} deps.mediaType
 * @param {import('vue').Ref} deps.isMovie
 * @param {import('vue').Ref} deps.isShow
 * @param {import('vue').Ref} deps.isEpisode
 * @param {import('vue').Ref} deps.isGame
 * @param {import('vue').Ref} deps.isSong
 * @param {import('vue').Ref} deps.isMusicType
 * @param {Object} deps.remoteControlStore
 * @param {Function} deps.getPosterUrl
 */
export function useMediaCastPlayback({
  mediaItem,
  files,
  parentItem,
  heroTitle,
  heroPosterUrl,
  mediaType,
  isMovie,
  isShow,
  isEpisode,
  isGame,
  isSong,
  isMusicType,
  remoteControlStore,
  getPosterUrl,
}) {
  function absoluteUrl(url) {
    if (!url) return null
    if (/^https?:\/\//i.test(url)) return url
    const baseUrl = getServerUrl(window.location.origin)
    return new URL(url, baseUrl).toString()
  }

  function getCastMimeType(playResponse) {
    if (playResponse?.session_id && !playResponse?.direct_play) {
      return 'application/x-mpegURL'
    }
    if (isSong.value || isMusicType.value) {
      return 'audio/mpeg'
    }

    const fileName = String(
      files.value[0]?.file_path || files.value[0]?.path || files.value[0]?.filename || '',
    ).toLowerCase()
    if (fileName.endsWith('.mkv')) return 'video/x-matroska'
    if (fileName.endsWith('.webm')) return 'video/webm'
    if (fileName.endsWith('.m4v')) return 'video/mp4'
    if (fileName.endsWith('.mp4')) return 'video/mp4'
    if (fileName.endsWith('.mp3')) return 'audio/mpeg'
    if (fileName.endsWith('.m4a')) return 'audio/mp4'
    if (fileName.endsWith('.flac')) return 'audio/flac'
    return 'video/mp4'
  }

  function getCastMediaUrl(playResponse) {
    if (!playResponse?.token) return null
    if (playResponse.direct_file_url) {
      return absoluteUrl(playResponse.direct_file_url)
    }
    if (playResponse.session_id && !playResponse.direct_play) {
      return absoluteUrl(getPlaylistUrl(playResponse.session_id, playResponse.token))
    }
    return absoluteUrl(getDirectFileUrl(playResponse.token))
  }

  async function playNativeCastTarget(mediaGuid) {
    const playResponse = await startPlayback(
      mediaGuid,
      remoteControlStore.playbackOptionsForTarget(remoteControlStore.targetDevice),
    )
    if (playResponse?.status !== 'ready') {
      return false
    }

    const mediaUrl = getCastMediaUrl(playResponse)
    if (!mediaUrl) return false

    return await remoteControlStore.sendRemoteCommand('play', {
      media_url: mediaUrl,
      title: mediaItem.value?.title || '',
      mime_type: getCastMimeType(playResponse),
      start_position: playResponse.start_position || 0,
      artwork_url: absoluteUrl(heroPosterUrl.value),
      metadata: {
        title: mediaItem.value?.title || '',
        subtitle: heroTitle.value || '',
      },
    })
  }

  async function playSelectedRemoteTarget(mediaGuid, playType) {
    if (!remoteControlStore.hasRemoteTarget || !mediaGuid) {
      return false
    }
    if (remoteControlStore.isNativeCastTarget(remoteControlStore.targetDevice)) {
      return await playNativeCastTarget(mediaGuid)
    }
    return await remoteControlStore.sendPlayMediaCommand(
      playType,
      mediaGuid,
      mediaItem.value?.title || '',
    )
  }

  async function playSelectedRemoteQueue(itemIds) {
    if (!remoteControlStore.hasRemoteTarget || itemIds.length === 0) {
      return false
    }
    if (remoteControlStore.isNativeCastTarget(remoteControlStore.targetDevice)) {
      return false
    }
    return await remoteControlStore.sendPlayCommand(itemIds, { playCommand: 'play_now' })
  }

  async function playSelectedRemoteInstantMix(itemIds) {
    if (!remoteControlStore.hasRemoteTarget || itemIds.length === 0) {
      return false
    }
    if (remoteControlStore.isNativeCastTarget(remoteControlStore.targetDevice)) {
      return await playNativeCastTarget(itemIds[0])
    }
    return await remoteControlStore.sendPlayCommand(itemIds, { playCommand: 'play_instant_mix' })
  }

  // Get play type for route parameter
  function getPlayType() {
    if (isMovie.value) return 'movie'
    if (isShow.value || isEpisode.value) return 'episode'
    if (isGame.value) return 'game'
    if (isMusicType.value) return 'music'
    return 'movie'
  }

  function getPlayTypeForItem(item) {
    const itemType = item?.media_type
    if (itemType === MediaTypes.MOVIES) return 'movie'
    if (itemType === MediaTypes.SERIES) return 'episode'
    if (itemType === MediaTypes.GAMES) return 'game'
    if (
      itemType === MediaTypes.MUSIC ||
      itemType === MediaTypes.ARTISTS ||
      itemType === MediaTypes.ALBUMS ||
      itemType === MediaTypes.SONGS
    ) {
      return 'music'
    }
    return getPlayType()
  }

  // Convert a media item / child to audio player track format
  function trackToPlayerTrack(track) {
    return {
      guid: track.guid,
      title: track.title,
      artist: track.description || mediaItem.value?.title || '',
      artistGuid: track.parent_guid || parentItem.value?.guid || null,
      mediaType: track.media_type || mediaType.value || null,
      albumTitle: mediaItem.value?.title || '',
      albumGuid: track.parent_guid || mediaItem.value?.guid || null,
      albumArt: getPosterUrl(track) || getPosterUrl(mediaItem.value),
      duration: track.duration || track.runtime || 0,
    }
  }

  return {
    absoluteUrl,
    getCastMimeType,
    getCastMediaUrl,
    playNativeCastTarget,
    playSelectedRemoteTarget,
    playSelectedRemoteQueue,
    playSelectedRemoteInstantMix,
    getPlayType,
    getPlayTypeForItem,
    trackToPlayerTrack,
  }
}
