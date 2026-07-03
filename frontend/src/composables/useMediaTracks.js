import { ref, watch, onMounted, onUnmounted } from 'vue'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

const TRACKS_RETRY_DELAY_MS = 2000
const TRACKS_RETRY_FALLBACK_MS = 1000

/**
 * Loads audio/subtitle/quality tracks from the unified media streams API and
 * exposes the selection logic for the player UI.
 *
 * The composable owns its own state + lifecycle:
 *   - On mount: load tracks immediately for the current contentId, retry once
 *     after TRACKS_RETRY_DELAY_MS if no tracks turn up.
 *   - Watches the supplied `player` getter so we can reload after the player
 *     instance changes and subscribe to its `qualityLevels` change events.
 *   - Watches the `contentId` getter so a late-arriving id triggers a load.
 *
 * Audio-track and quality-level selections that need to be handled by the
 * page (retranscode / file switch) are delegated via the callback options
 * instead of emitting events directly so the consumer keeps full control.
 *
 * @param {Object} options
 * @param {() => (number|string|null)} options.getContentId
 * @param {() => (string|null)} options.getContentType
 * @param {() => any} options.getPlayer - Returns the Video.js player instance.
 * @param {(streamIndex: number) => void} options.onChangeAudioTrack
 * @param {(level: Object) => void} options.onSelectQuality
 */
export function useMediaTracks({
  getContentId,
  getContentType,
  getPlayer,
  onChangeAudioTrack,
  onSelectQuality,
}) {
  const audioTracks = ref([])
  const subtitleTracks = ref([])
  const qualityLevels = ref([])
  const currentAudioTrack = ref(null)
  const currentSubtitle = ref(null)
  const currentQuality = ref(null)
  const remoteSubtitleTracks = new Map()
  let savedTrackPreferences = null
  let loadedTracksContentId = null

  const subtitleLabel = (stream, fallback) => {
    const flags = []
    if (stream.forced) flags.push('Forced')
    if (stream.default) flags.push('Default')
    const suffix = flags.length ? ` (${flags.join(', ')})` : ''
    return stream.title || stream.language || `${fallback}${suffix}`
  }

  const srtToVtt = (content) => {
    if (!content) return 'WEBVTT\n\n'
    if (content.trimStart().startsWith('WEBVTT')) return content
    return `WEBVTT\n\n${content.replace(/\r/g, '').replace(/(\d\d:\d\d:\d\d),(\d{3})/g, '$1.$2')}`
  }

  const persistTrackPreferences = async (payload) => {
    const contentId = getContentId()
    if (!contentId) return
    try {
      await api.put(`/api/media/${contentId}/user-data`, payload)
    } catch (error) {
      logger.debug('[useMediaTracks] Failed to persist track preference:', error)
    }
  }

  const loadSavedTrackPreferences = async (contentId) => {
    try {
      const response = await api.get(`/api/media/${contentId}/user-data`)
      savedTrackPreferences = response.data || {}
      return savedTrackPreferences
    } catch (error) {
      logger.debug('[useMediaTracks] Failed to load track preferences:', error)
      savedTrackPreferences = {}
      return savedTrackPreferences
    }
  }

  const releaseManagedSubtitleTracks = () => {
    for (const value of remoteSubtitleTracks.values()) {
      if (value.blobUrl) {
        URL.revokeObjectURL(value.blobUrl)
      }
    }
    remoteSubtitleTracks.clear()
  }

  const resetTrackStateForContent = (contentId) => {
    if (loadedTracksContentId === contentId) return
    releaseManagedSubtitleTracks()
    audioTracks.value = []
    subtitleTracks.value = []
    qualityLevels.value = []
    currentAudioTrack.value = null
    currentSubtitle.value = null
    currentQuality.value = null
    loadedTracksContentId = contentId
  }

  const preferredIndex = (items, preferences, kind) => {
    if (!preferences) return null
    if (kind === 'audio') {
      if (preferences.selected_audio_track_index != null) {
        return items.findIndex((item) => item.streamIndex === preferences.selected_audio_track_index)
      }
      if (preferences.selected_audio_language) {
        return items.findIndex((item) => item.language === preferences.selected_audio_language)
      }
      return null
    }
    if (preferences.selected_subtitle_track_id) {
      return items.findIndex((item) => item.id === preferences.selected_subtitle_track_id)
    }
    if (preferences.selected_subtitle_track_index != null) {
      return items.findIndex((item) => item.streamIndex === preferences.selected_subtitle_track_index)
    }
    if (preferences.selected_subtitle_language) {
      return items.findIndex((item) => item.language === preferences.selected_subtitle_language)
    }
    return null
  }

  const loadTracksFromAPI = async (contentId) => {
    resetTrackStateForContent(contentId)
    try {
      // Use unified media API for all content types
      const endpoint = `/api/media/${contentId}/streams`

      logger.debug('[useMediaTracks] Fetching tracks from API:', endpoint)
      const response = await api.get(endpoint, { timeout: 10000 })
      const data = response.data
      const preferences = await loadSavedTrackPreferences(contentId)

      logger.debug('[useMediaTracks] API response:', data)
      logger.debug('[useMediaTracks] Quality options from API:', data.quality_options)

      // Map audio streams from API
      if (data.audio_streams && data.audio_streams.length > 0) {
        audioTracks.value = data.audio_streams.map((stream, index) => ({
          label: stream.title || stream.language || `Audio ${index + 1}`,
          language: stream.language,
          index: stream.index !== undefined ? stream.index : index,
          streamIndex: stream.stream_index !== undefined ? stream.stream_index : index,
          channels: stream.channels,
          codec: stream.codec_name,
        }))
        logger.debug(
          '[useMediaTracks] Loaded audio tracks from API:',
          audioTracks.value.length,
          'tracks',
        )
        const savedIndex = preferredIndex(audioTracks.value, preferences, 'audio')
        currentAudioTrack.value = savedIndex != null && savedIndex >= 0 ? savedIndex : 0
      } else {
        logger.warn('[useMediaTracks] No audio streams in API response')
      }

      // Map subtitle streams from API
      if (data.subtitle_streams && data.subtitle_streams.length > 0) {
        subtitleTracks.value = data.subtitle_streams.map((stream, index) => ({
          label: subtitleLabel(stream, `Subtitle ${index + 1}`),
          language: stream.language,
          id: stream.id,
          index: stream.index !== undefined ? stream.index : index,
          streamIndex: stream.stream_index,
          codec: stream.codec_name,
          format: stream.format || stream.codec_name,
          forced: stream.forced,
          default: stream.default,
          source: stream.source || 'embedded',
          url: stream.url,
          contentUrl: stream.content_url,
        }))
        logger.debug(
          '[useMediaTracks] Loaded subtitle tracks from API:',
          subtitleTracks.value.length,
          'tracks',
        )
        const savedSubtitleIndex = preferredIndex(subtitleTracks.value, preferences, 'subtitle')
        if (savedSubtitleIndex != null && savedSubtitleIndex >= 0) {
          selectSubtitle(savedSubtitleIndex, { persist: false })
        } else {
          const defaultIndex = subtitleTracks.value.findIndex((subtitle) => subtitle.default)
          if (defaultIndex >= 0) {
            selectSubtitle(defaultIndex, { persist: false })
          }
        }
      } else {
        logger.debug('[useMediaTracks] No subtitle streams in API response')
      }

      // Map quality options from available releases
      if (data.quality_options && data.quality_options.length > 0) {
        qualityLevels.value = data.quality_options.map((option, index) => ({
          label: option.label,
          height: option.height,
          quality: option.quality,
          release_guid: option.release_guid,
          file_guid: option.file_guid,
          is_downloaded: option.is_downloaded,
          is_available: option.is_available,
          is_current: option.is_current,
          source: option.source || 'file',
          index: index,
        }))
        logger.debug(
          '[useMediaTracks] Loaded quality options from API:',
          qualityLevels.value.length,
          'options',
        )
        // Set current quality based on is_current flag
        const currentIndex = qualityLevels.value.findIndex((q) => q.is_current)
        if (currentIndex !== -1) {
          currentQuality.value = currentIndex
        } else if (qualityLevels.value.length > 0) {
          currentQuality.value = 0
        }
      } else {
        logger.debug('[useMediaTracks] No quality options in API response')
      }
    } catch (error) {
      logger.error('[useMediaTracks] Error loading tracks from API:', error.message)
      if (error.response) {
        logger.error(
          '[useMediaTracks] API error response:',
          error.response.status,
          error.response.data,
        )
      }
    }
  }

  const disableTextTracks = (player) => {
    const textTracks = player?.textTracks?.()
    if (!textTracks) return
    for (let i = 0; i < textTracks.length; i++) {
      textTracks[i].mode = 'disabled'
    }
  }

  const loadManagedSubtitleTrack = async (player, subtitle) => {
    const cacheKey = subtitle.id || subtitle.url || subtitle.contentUrl
    if (remoteSubtitleTracks.has(cacheKey)) {
      return remoteSubtitleTracks.get(cacheKey).track
    }

    let src = subtitle.url
    let blobUrl = null
    if (subtitle.contentUrl) {
      const response = await api.get(subtitle.contentUrl, { responseType: 'text' })
      const format = (subtitle.format || subtitle.codec || '').toLowerCase()
      const text = format === 'vtt' || format === 'webvtt' ? response.data : srtToVtt(response.data)
      blobUrl = URL.createObjectURL(new Blob([text], { type: 'text/vtt' }))
      src = blobUrl
    }
    if (!src) return null

    const remote = player.addRemoteTextTrack(
      {
        kind: 'subtitles',
        label: subtitle.label,
        srclang: subtitle.language || 'und',
        src,
        default: false,
      },
      false,
    )
    const track = remote?.track || remote
    remoteSubtitleTracks.set(cacheKey, { track, blobUrl })
    return track
  }

  // Select subtitle track
  const selectSubtitle = (index, { persist = true } = {}) => {
    const player = getPlayer()
    if (!player) return

    const applySelection = async () => {
      disableTextTracks(player)
      if (index !== null && subtitleTracks.value[index]) {
        const subtitle = subtitleTracks.value[index]
        if (subtitle.source !== 'embedded' || subtitle.contentUrl || subtitle.url) {
          const track = await loadManagedSubtitleTrack(player, subtitle)
          if (track) {
            track.mode = 'showing'
            currentSubtitle.value = index
            if (persist) {
              await persistTrackPreferences({
                selected_subtitle_track_index: null,
                selected_subtitle_track_id: subtitle.id || null,
                selected_subtitle_language: subtitle.language || null,
              })
            }
            logger.debug('Managed subtitle track enabled:', subtitle.label)
          }
          return
        }

        const textTracks = player.textTracks()
        const trackIndex = subtitle.index
        if (textTracks?.[trackIndex]) {
          textTracks[trackIndex].mode = 'showing'
          currentSubtitle.value = index
          if (persist) {
            await persistTrackPreferences({
              selected_subtitle_track_index: subtitle.streamIndex ?? trackIndex,
              selected_subtitle_track_id: subtitle.id || null,
              selected_subtitle_language: subtitle.language || null,
            })
          }
          logger.debug('Subtitle track enabled:', subtitle.label)
        }
      } else {
        currentSubtitle.value = null
        if (persist) {
          await persistTrackPreferences({
            selected_subtitle_track_index: null,
            selected_subtitle_track_id: null,
            selected_subtitle_language: null,
          })
        }
        logger.debug('Subtitles disabled')
      }
    }

    try {
      applySelection().catch((e) => logger.error('Error selecting subtitle:', e))
    } catch (e) {
      logger.error('Error selecting subtitle:', e)
    }
  }

  // Select audio track
  const selectAudioTrack = (index) => {
    if (index === currentAudioTrack.value) {
      logger.debug('[AudioTrack] Already selected track', index)
      return
    }

    const track = audioTracks.value[index]
    if (!track) {
      logger.warn('[AudioTrack] No track at index', index)
      return
    }

    // stream_index is the 0-based position among audio streams (for ffmpeg -map 0:a:N)
    const streamIndex = track.streamIndex !== undefined ? track.streamIndex : index
    currentAudioTrack.value = index
    persistTrackPreferences({
      selected_audio_track_index: streamIndex,
      selected_audio_language: track.language || null,
    })
    logger.debug('[AudioTrack] Switch requested:', track.label, 'streamIndex:', streamIndex)

    // Delegate to consumer so PlayPage can retranscode with the new audio track
    onChangeAudioTrack(streamIndex)
  }

  // Select quality level
  const selectQuality = (index) => {
    const level = qualityLevels.value[index]
    if (!level) return

    // Release options are disabled — do nothing
    if (level.source === 'release') return

    // Transcode option — delegate so PlayPage can restart playback with resolution
    if (level.source === 'transcode') {
      currentQuality.value = index
      onSelectQuality(level)
      logger.debug('Quality transcode selected:', level.label, `${level.height}p`)
      return
    }

    // File option — delegate so PlayPage can switch to the file
    if (level.file_guid) {
      currentQuality.value = index
      onSelectQuality(level)
      logger.debug('Quality file selected:', level.label)
      return
    }

    // Fallback: try Video.js quality levels plugin
    const player = getPlayer()
    if (!player || !player.qualityLevels) return

    try {
      const qualityList = player.qualityLevels()
      if (!qualityList) return

      for (let i = 0; i < qualityList.length; i++) {
        qualityList[i].enabled = false
      }

      const levelIndex = level.index
      if (qualityList[levelIndex]) {
        qualityList[levelIndex].enabled = true
        currentQuality.value = index
        logger.debug('Quality level set to:', level.label)
      }
    } catch (e) {
      logger.error('Error selecting quality:', e)
    }
  }

  onMounted(() => {
    const contentId = getContentId()
    const contentType = getContentType()
    if (contentId && contentType) {
      logger.debug('[useMediaTracks] Loading tracks from API for:', contentId, contentType)
      // Try immediately
      loadTracksFromAPI(contentId)
      // Try again after delay if no tracks found
      setTimeout(() => {
        if (audioTracks.value.length === 0 && subtitleTracks.value.length === 0) {
          logger.debug('[useMediaTracks] No tracks found yet, trying API again...')
          loadTracksFromAPI(contentId)
        }
      }, TRACKS_RETRY_DELAY_MS)
    } else {
      logger.warn('[useMediaTracks] No contentId or contentType provided, got:', {
        contentId,
        contentType,
      })
    }
  })

  onUnmounted(() => {
    releaseManagedSubtitleTracks()
  })

  // Watch for player changes and reload tracks
  watch(
    () => getPlayer(),
    (newPlayer) => {
      if (!newPlayer) return
      logger.debug('[useMediaTracks] Player instance changed')

      const contentId = getContentId()
      const contentType = getContentType()
      // Reload tracks from API when player changes
      if (
        contentId &&
        contentType &&
        (audioTracks.value.length === 0 || loadedTracksContentId !== contentId)
      ) {
        logger.debug('[useMediaTracks] Player ready, reloading tracks from API')
        setTimeout(() => {
          loadTracksFromAPI(contentId)
        }, TRACKS_RETRY_FALLBACK_MS)
      }

      // Listen for quality changes (if using HLS quality selector)
      if (newPlayer.qualityLevels) {
        newPlayer.qualityLevels().on('change', () => {
          const qualityList = newPlayer.qualityLevels()
          for (let i = 0; i < qualityList.length; i++) {
            if (qualityList[i].enabled) {
              currentQuality.value = i
              logger.debug('[useMediaTracks] Quality changed to:', qualityLevels.value[i])
              break
            }
          }
        })
      }
    },
    { immediate: true },
  )

  // Watch for contentId changes (when it becomes available)
  watch(
    () => getContentId(),
    (newContentId, oldContentId) => {
      logger.debug('[useMediaTracks] contentId changed:', { old: oldContentId, new: newContentId })

      if (newContentId && getContentType() && newContentId !== oldContentId) {
        logger.debug('[useMediaTracks] contentId now available, loading tracks from API')
        loadTracksFromAPI(newContentId)
      }
    },
    { immediate: true },
  )

  return {
    audioTracks,
    subtitleTracks,
    qualityLevels,
    currentAudioTrack,
    currentSubtitle,
    currentQuality,
    loadTracksFromAPI,
    selectAudioTrack,
    selectSubtitle,
    selectQuality,
  }
}
