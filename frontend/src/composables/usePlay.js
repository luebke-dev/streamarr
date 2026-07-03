/**
 * Unified Play & Streaming Composable
 *
 * Provides methods to interact with the unified /api/play and /api/stream endpoints
 * for playing all media types (movies, shows, games, music).
 */

import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

// Cache for detected codec capabilities
let cachedCodecCapabilities = null

/**
 * Detect browser codec capabilities using MediaCapabilities API and MediaSource
 * Results are cached for the session lifetime
 *
 * @returns {Promise<Object>} Object with supported video and audio codecs
 */
export async function detectCodecCapabilities() {
  // Return cached result if available
  if (cachedCodecCapabilities) {
    return cachedCodecCapabilities
  }

  const capabilities = {
    video_codecs: [],
    audio_codecs: [],
    containers: [],
    max_resolution: null,
    hdr_supported: false,
  }

  // Helper to check if MediaSource supports a type
  const isTypeSupported = (mimeType) => {
    if (typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported) {
      return MediaSource.isTypeSupported(mimeType)
    }
    return false
  }
  const canElementPlay = (mimeType, kind = 'video') => {
    if (typeof document === 'undefined') return false
    const element = document.createElement(kind)
    return !!element.canPlayType && element.canPlayType(mimeType) !== ''
  }

  // Check if MediaCapabilities API is available
  const hasMediaCapabilities = 'mediaCapabilities' in navigator

  if (!hasMediaCapabilities) {
    logger.warn('MediaCapabilities API not available, using MediaSource fallback')
  }

  // Video codec tests - test HLS/MPEG-TS container types since we use HLS streaming
  // Note: Most browsers don't support HEVC in HLS, only Safari does
  const videoTests = [
    {
      codec: 'h264',
      // H.264 in MPEG-TS (HLS segments)
      mimeType: 'video/mp2t; codecs="avc1.640028"',
      fallbackMimeType: 'video/mp4; codecs="avc1.640028"',
      config: {
        type: 'media-source',
        video: {
          contentType: 'video/mp4; codecs="avc1.640028"',
          width: 1920,
          height: 1080,
          bitrate: 5000000,
          framerate: 30,
        },
      },
    },
    {
      codec: 'h265',
      // HEVC in MPEG-TS (HLS segments) - only Safari supports this
      mimeType: 'video/mp2t; codecs="hvc1.1.6.L120.90"',
      fallbackMimeType: 'video/mp4; codecs="hvc1.1.6.L120.90"',
      config: {
        type: 'media-source',
        video: {
          contentType: 'video/mp2t; codecs="hvc1.1.6.L120.90"',
          width: 1920,
          height: 1080,
          bitrate: 5000000,
          framerate: 30,
        },
      },
    },
    {
      codec: 'vp9',
      mimeType: 'video/webm; codecs="vp9"',
      fallbackMimeType: 'video/webm; codecs="vp9"',
      config: {
        type: 'media-source',
        video: {
          contentType: 'video/webm; codecs="vp9"',
          width: 1920,
          height: 1080,
          bitrate: 5000000,
          framerate: 30,
        },
      },
    },
    {
      codec: 'av1',
      mimeType: 'video/mp4; codecs="av01.0.08M.08"',
      fallbackMimeType: 'video/mp4; codecs="av01.0.08M.08"',
      config: {
        type: 'media-source',
        video: {
          contentType: 'video/mp4; codecs="av01.0.08M.08"',
          width: 1920,
          height: 1080,
          bitrate: 5000000,
          framerate: 30,
        },
      },
    },
  ]

  // Audio codec tests
  const audioTests = [
    {
      codec: 'aac',
      config: {
        type: 'media-source',
        audio: {
          contentType: 'audio/mp4; codecs="mp4a.40.2"',
          channels: 2,
          bitrate: 128000,
          samplerate: 48000,
        },
      },
    },
    {
      codec: 'mp3',
      config: {
        type: 'media-source',
        audio: {
          contentType: 'audio/mpeg',
          channels: 2,
          bitrate: 128000,
          samplerate: 48000,
        },
      },
    },
    {
      codec: 'opus',
      config: {
        type: 'media-source',
        audio: {
          contentType: 'audio/webm; codecs="opus"',
          channels: 2,
          bitrate: 128000,
          samplerate: 48000,
        },
      },
    },
    {
      codec: 'flac',
      config: {
        type: 'media-source',
        audio: {
          contentType: 'audio/flac',
          channels: 2,
          bitrate: 1000000,
          samplerate: 48000,
        },
      },
    },
  ]

  // Test video codecs using both MediaSource.isTypeSupported and MediaCapabilities
  // For HLS streaming, we need to test MPEG-TS container support
  for (const test of videoTests) {
    let supported = false

    // First, check MediaSource.isTypeSupported for the HLS container type
    if (isTypeSupported(test.mimeType)) {
      supported = true
      logger.debug(`Video codec ${test.codec} supported via MediaSource (${test.mimeType})`)
    } else if (test.fallbackMimeType && isTypeSupported(test.fallbackMimeType)) {
      // For H.264, the fallback MP4 type works with HLS.js
      // For HEVC, if only MP4 is supported but not MPEG-TS, it won't work with HLS
      if (test.codec === 'h264') {
        supported = true
        logger.debug(
          `Video codec ${test.codec} supported via MediaSource fallback (${test.fallbackMimeType})`,
        )
      }
    }

    // Additionally verify with MediaCapabilities API if available
    if (supported && hasMediaCapabilities) {
      try {
        const result = await navigator.mediaCapabilities.decodingInfo(test.config)
        if (!result.supported) {
          supported = false
          logger.debug(`Video codec ${test.codec} not supported by MediaCapabilities`)
        }
      } catch (e) {
        // MediaCapabilities test failed, but MediaSource said it's supported
        logger.debug(`Video codec ${test.codec} MediaCapabilities test error:`, e.message)
      }
    }

    if (supported) {
      capabilities.video_codecs.push(test.codec)
    } else {
      logger.debug(`Video codec ${test.codec} NOT supported for HLS streaming`)
    }
  }

  // Test audio codecs
  for (const test of audioTests) {
    try {
      if (hasMediaCapabilities) {
        const result = await navigator.mediaCapabilities.decodingInfo(test.config)
        if (result.supported) {
          capabilities.audio_codecs.push(test.codec)
        }
      } else if (isTypeSupported(test.config.audio.contentType)) {
        capabilities.audio_codecs.push(test.codec)
      }
    } catch (e) {
      // Codec not supported or error in test
      logger.debug(`Audio codec ${test.codec} not supported:`, e.message)
    }
  }

  const containerTests = [
    { container: 'mp4', mimeType: 'video/mp4; codecs="avc1.42E01E"', kind: 'video' },
    { container: 'webm', mimeType: 'video/webm; codecs="vp9"', kind: 'video' },
    { container: 'ogg', mimeType: 'video/ogg; codecs="theora"', kind: 'video' },
    { container: 'm4a', mimeType: 'audio/mp4; codecs="mp4a.40.2"', kind: 'audio' },
    { container: 'mp3', mimeType: 'audio/mpeg', kind: 'audio' },
    { container: 'flac', mimeType: 'audio/flac', kind: 'audio' },
  ]

  for (const test of containerTests) {
    if (isTypeSupported(test.mimeType) || canElementPlay(test.mimeType, test.kind)) {
      capabilities.containers.push(test.container)
    }
  }

  // Test max resolution support
  const resolutionTests = [
    { width: 3840, height: 2160, label: '4k' },
    { width: 1920, height: 1080, label: '1080p' },
    { width: 1280, height: 720, label: '720p' },
  ]

  for (const res of resolutionTests) {
    try {
      const result = await navigator.mediaCapabilities.decodingInfo({
        type: 'media-source',
        video: {
          contentType: 'video/mp4; codecs="avc1.640028"',
          width: res.width,
          height: res.height,
          bitrate: 10000000,
          framerate: 30,
        },
      })
      if (result.supported && result.smooth) {
        capabilities.max_resolution = res.label
        break
      }
    } catch (e) {
      // Resolution not smoothly supported (some browsers throw on unknown profiles)
      logger.debug('Resolution capability probe failed', { res: res.label, error: e })
    }
  }

  // Test HDR support (HDR10)
  try {
    const hdrResult = await navigator.mediaCapabilities.decodingInfo({
      type: 'media-source',
      video: {
        contentType: 'video/mp4; codecs="hvc1.2.4.L120.90"',
        width: 1920,
        height: 1080,
        bitrate: 10000000,
        framerate: 30,
        transferFunction: 'pq',
      },
    })
    capabilities.hdr_supported = hdrResult.supported
  } catch (e) {
    // HDR probe rejected: treat as unsupported but log for diagnostics
    logger.debug('HDR capability probe failed', e)
  }

  // Ensure at least h264 and aac are in the list (universal support)
  if (!capabilities.video_codecs.includes('h264')) {
    capabilities.video_codecs.unshift('h264')
  }
  if (!capabilities.audio_codecs.includes('aac')) {
    capabilities.audio_codecs.unshift('aac')
  }
  if (!capabilities.containers.includes('mp4')) {
    capabilities.containers.unshift('mp4')
  }

  logger.debug('Detected codec capabilities:', capabilities)
  cachedCodecCapabilities = capabilities
  return capabilities
}

/**
 * Get cached codec capabilities or detect them
 * @returns {Promise<Object>} Codec capabilities
 */
export async function getCodecCapabilities() {
  if (cachedCodecCapabilities) {
    return cachedCodecCapabilities
  }
  return detectCodecCapabilities()
}

/**
 * Start playback for a media item.
 *
 * Backend behavior (status field in response):
 *   'ready'       → file is available, play token included → start playback
 *   'downloading' → release was found and download started → poll until 'ready'
 *   'searching'   → no release yet, indexer search started → poll until 'ready'
 *
 * Automatically detects and sends client codec capabilities to the server.
 *
 * @param {string} mediaId - Media item GUID
 * @param {Object} options - Playback options
 * @param {string} options.video_codec - Video codec preference (h264, h265, vp9)
 * @param {string} options.audio_codec - Audio codec preference (aac, mp3, opus)
 * @param {string} options.resolution - Resolution preference (1080p, 720p, 480p)
 * @param {string|string[]} options.supported_containers - Supported source containers
 * @param {number} options.client_max_bitrate - Maximum source bitrate in bits per second
 * @param {number} options.max_bitrate - Maximum source bitrate in kbps
 * @param {number} options.crf - Constant Rate Factor for quality (18-28, lower = better quality)
 * @param {string} options.audio_language - Preferred audio language (ISO 639-1 code)
 * @param {string} options.subtitle_language - Preferred subtitle language (ISO 639-1 code)
 * @param {number} options.start_position - Start position in seconds (for resume)
 * @param {string} options.media_source_id - Media file GUID to play
 * @param {number} options.audio_track - Audio stream index to use
 * @param {number} options.subtitle_stream_index - Subtitle stream index to use
 * @returns {Promise} Play response with token, session_id, duration, etc.
 */
export async function startPlayback(mediaId, options = {}) {
  // Detect client codec capabilities
  const capabilities = await getCodecCapabilities()

  const params = {}

  // Add client capabilities
  if (capabilities.video_codecs.length > 0) {
    params.supported_video_codecs = capabilities.video_codecs.join(',')
  }
  if (capabilities.audio_codecs.length > 0) {
    params.supported_audio_codecs = capabilities.audio_codecs.join(',')
  }
  if (capabilities.containers.length > 0) {
    params.supported_containers = capabilities.containers.join(',')
  }
  if (capabilities.max_resolution) {
    params.client_max_resolution = capabilities.max_resolution
  }

  if (options.supported_video_codecs) {
    params.supported_video_codecs = Array.isArray(options.supported_video_codecs)
      ? options.supported_video_codecs.join(',')
      : options.supported_video_codecs
  }
  if (options.supported_audio_codecs) {
    params.supported_audio_codecs = Array.isArray(options.supported_audio_codecs)
      ? options.supported_audio_codecs.join(',')
      : options.supported_audio_codecs
  }
  if (options.supported_containers) {
    params.supported_containers = Array.isArray(options.supported_containers)
      ? options.supported_containers.join(',')
      : options.supported_containers
  }
  if (options.client_max_resolution) {
    params.client_max_resolution = options.client_max_resolution
  }
  const explicitMaxBitrate = options.client_max_bitrate ?? options.max_bitrate
  if (explicitMaxBitrate) {
    const maxBitrate = Number(explicitMaxBitrate)
    if (Number.isFinite(maxBitrate) && maxBitrate > 0) {
      params.client_max_bitrate =
        options.client_max_bitrate !== undefined || maxBitrate >= 100000
          ? Math.round(maxBitrate)
          : Math.round(maxBitrate * 1000)
    }
  }
  if (options.profile_id) params.profile_id = options.profile_id
  if (options.device_guid) params.device_guid = options.device_guid

  // Add optional parameters if provided (these override auto-detection)
  if (options.video_codec) params.video_codec = options.video_codec
  if (options.audio_codec) params.audio_codec = options.audio_codec
  if (options.resolution) params.resolution = options.resolution
  if (options.crf) params.crf = options.crf
  if (options.audio_language) params.audio_language = options.audio_language
  if (options.subtitle_language) params.subtitle_language = options.subtitle_language
  if (options.start_position) params.start_position = options.start_position
  if (options.media_source_id) params.media_source_id = options.media_source_id
  if (options.audio_track !== undefined && options.audio_track !== null) {
    params.audio_track = options.audio_track
  }
  if (options.subtitle_stream_index !== undefined && options.subtitle_stream_index !== null) {
    params.subtitle_stream_index = options.subtitle_stream_index
  }

  const response = await api.post(`/api/play/${mediaId}`, null, { params })
  return response.data
}

/**
 * Seek to a specific position during playback
 * Creates a new transcoding session starting from the seek position
 *
 * @param {string} mediaId - Media item GUID
 * @param {number} position - Position to seek to in seconds
 * @param {string} currentSessionId - Current session ID to terminate (optional)
 * @param {Object} options - Same options as startPlayback
 * @returns {Promise} New play response with updated token and session_id
 */
export async function seekPlayback(mediaId, position, currentSessionId = null, options = {}) {
  const params = {
    position,
    old_session_id: currentSessionId,
    ...options,
  }

  const response = await api.post(`/api/play/${mediaId}/seek`, null, { params })
  return response.data
}

/**
 * Get generated trickplay sprite metadata for a streaming session.
 *
 * @param {string} sessionId - Streaming session ID
 * @param {string} token - Play token
 * @returns {Promise<Object>} Trickplay manifest with sprite URLs and grid metadata
 */
export async function getTrickplayManifest(sessionId, token) {
  const response = await api.get(`/api/stream/${sessionId}/trickplay`, {
    params: { token },
    _skipAuthRetry: true,
  })
  return response.data
}

/**
 * Get HLS playlist URL for a streaming session
 *
 * @param {string} sessionId - Streaming session ID
 * @param {string} token - Play token
 * @returns {string} Full URL to HLS playlist
 */
export function getPlaylistUrl(sessionId, token) {
  const baseUrl = api.defaults.baseURL || window.location.origin
  return `${baseUrl}/api/stream/${sessionId}/playlist.m3u8?token=${token}`
}

/**
 * Get a token-backed direct media file URL.
 *
 * @param {string} token - Play token
 * @returns {string} Full URL to the direct media file stream
 */
export function getDirectFileUrl(token) {
  const baseUrl = api.defaults.baseURL || window.location.origin
  return `${baseUrl}/api/stream/file?token=${token}`
}

/**
 * Get HLS segment URL for a streaming session
 *
 * @param {string} sessionId - Streaming session ID
 * @param {string} segmentName - Segment filename (e.g., "segment_000.ts")
 * @returns {string} Full URL to HLS segment
 */
export function getSegmentUrl(sessionId, segmentName) {
  const baseUrl = api.defaults.baseURL || window.location.origin
  return `${baseUrl}/api/stream/${sessionId}/${segmentName}`
}

/**
 * Get streaming session status
 * Returns transcoding progress, segment count, and playlist ready state
 *
 * @param {string} sessionId - Streaming session ID
 * @param {string} token - Play token
 * @returns {Promise} Status object with is_ready, segments_available, transcoding_complete
 */
export async function getStreamStatus(sessionId, token) {
  const response = await api.get(`/api/stream/${sessionId}/status`, {
    params: { token },
    _skipAuthRetry: true,
  })
  return response.data
}

/**
 * Check if a specific position is available on the server (already transcoded)
 *
 * @param {string} sessionId - Streaming session ID
 * @param {string} token - Play token
 * @param {number} position - Absolute position in seconds to check
 * @param {number} startPosition - Transcode start position in seconds
 * @param {number} segmentDuration - Segment duration in seconds (default 6)
 * @returns {Promise<Object>} Object with available (bool), segment_index, stream_position
 */
export async function checkPositionAvailable(
  sessionId,
  token,
  position,
  startPosition = 0,
  segmentDuration = 6.0,
) {
  const response = await api.get(`/api/stream/${sessionId}/check-position`, {
    params: {
      token,
      position,
      start_position: startPosition,
      segment_duration: segmentDuration,
    },
    _skipAuthRetry: true,
  })
  return response.data
}

/**
 * Stop streaming and cleanup resources
 * Terminates transcoding container and removes temporary files
 * Also deletes the source media file from disk and database by default
 *
 * @param {string} sessionId - Streaming session ID
 * @param {string} token - Play token
 * @param {boolean} deleteLibraryFile - Whether to delete source media file (default: true)
 * @returns {Promise} Confirmation response with cleanup details
 */
export async function stopStreaming(sessionId, token, deleteLibraryFile = true) {
  const response = await api.delete(`/api/stream/${sessionId}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    params: {
      delete_library_file: deleteLibraryFile,
    },
    _skipAuthRetry: true,
  })
  return response.data
}

/**
 * Download HLS playlist for a session (for debugging/testing)
 *
 * @param {string} sessionId - Streaming session ID
 * @param {string} token - Play token
 * @returns {Promise<string>} Playlist content
 */
export async function fetchPlaylist(sessionId, token) {
  const response = await api.get(`/api/stream/${sessionId}/playlist.m3u8`, {
    params: { token },
    responseType: 'text',
  })
  return response.data
}

/**
 * Get media playback info without starting transcoding
 * Useful for checking if media is available before playing
 *
 * @param {string} mediaId - Media item GUID
 * @returns {Promise} Media file info and availability
 */
export async function getPlaybackInfo(mediaId) {
  // Use the unified media API to get file info
  const response = await api.get(`/api/media/${mediaId}`, {
    params: {
      load_files: true,
      load_releases: false,
      load_external_ids: false,
    },
  })
  return response.data
}

/**
 * Check availability status of a media item
 * Returns download/file status without starting playback
 *
 * @param {string} mediaId - Media item GUID
 * @returns {Promise} Availability status object
 */
export async function checkAvailability(mediaId) {
  const response = await api.get(`/api/media/${mediaId}/availability`)
  return response.data
}

// Codec constants for convenience
export const VideoCodecs = {
  H264: 'h264',
  H265: 'h265',
  VP9: 'vp9',
}

export const AudioCodecs = {
  AAC: 'aac',
  MP3: 'mp3',
  OPUS: 'opus',
}

// Resolution constants
export const Resolutions = {
  '4K': '2160p',
  '1080P': '1080p',
  '720P': '720p',
  '480P': '480p',
}

// CRF quality presets (lower = better quality, larger file size)
export const QualityPresets = {
  ULTRA: 18,
  HIGH: 21,
  MEDIUM: 23,
  LOW: 26,
}

// Availability status constants
export const AvailabilityStatus = {
  UNKNOWN: 'unknown',
  AVAILABLE: 'available',
  DOWNLOADABLE: 'downloadable',
  UNAVAILABLE: 'unavailable',
  MISSING: 'missing',
  DOWNLOADING: 'downloading',
}

// Smart Play status constants
export const SmartPlayStatus = {
  READY: 'ready',
  DOWNLOADING: 'downloading',
  SEARCHING: 'searching',
}
