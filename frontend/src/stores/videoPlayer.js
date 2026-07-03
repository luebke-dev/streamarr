import { defineStore } from 'pinia'

/**
 * Central state for the video player (PlayPage).
 *
 * Mirrors the role that `stores/audioPlayer.js` plays for music: it holds the
 * streaming/control state that was previously spread across ~25 loose `ref()`
 * declarations in PlayPage.vue and injected into ~20 composables as parameters.
 *
 * Design notes:
 *   - The Video.js player instance itself (`videoJsPlayer`) intentionally stays
 *     in the component (it is DOM-near and must be disposed with the component).
 *     Only the *control* state lives here.
 *   - `currentAudioStreamIndex` is the single source of truth for the selected
 *     audio track (the ffmpeg `-map 0:a:N` stream index that is sent to the
 *     backend). `useMediaTracks` derives its list-index view from this value
 *     instead of holding a second copy.
 *   - `seek()` / `startPlayback()` are exposed as actions that delegate to
 *     handlers registered by PlayPage once the player controls are wired up.
 *     This replaces the forward-reference closures (`onSeek`, `onAvailable`)
 *     that previously had to be threaded through several composables.
 */
export const useVideoPlayerStore = defineStore('videoPlayer', {
  state: () => ({
    // Playback lifecycle
    status: '', // 'streamable', 'downloading', 'no-release', 'error', ...
    errorMessage: '',

    // Streaming session
    sessionId: '',
    playToken: '',
    directStreamUrl: '',
    playbackTargetOptions: {},

    // Positions / timing
    transcodeStartPosition: 0, // Position where the current transcode started
    streamPosition: 0, // Current position within the active stream
    videoDuration: 0, // Real duration of the full media (from metadata)
    duration: 0, // Duration reported by the player for the current source
    bufferedAmount: 0,

    // Player status flags
    isPlaying: false,
    isSeeking: false,

    // Track selection (single source of truth)
    currentAudioStreamIndex: null, // ffmpeg audio stream index (-map 0:a:N)
    currentMediaSourceId: null, // Selected MediaFile GUID

    // Track lists loaded from the unified streams API (owned by useMediaTracks)
    audioTracks: [],
    subtitleTracks: [],
    qualityLevels: [],

    // Handlers registered by PlayPage (kept out of reactive control flow)
    _seekHandler: null,
    _startPlaybackHandler: null,
  }),

  getters: {
    hasError: (state) => state.status === 'error',
    // Real (absolute) playback position = transcode offset + stream position
    realPosition: (state) => state.transcodeStartPosition + state.streamPosition,
  },

  actions: {
    /**
     * Register the seek handler (3-tier seek). PlayPage calls this once
     * usePlayerControls has produced `handleSeek`; composables that need to
     * seek (remote control, watch-party sync, skip markers) call `seek()`.
     */
    registerSeekHandler(fn) {
      this._seekHandler = fn
    },

    /** Register the startPlayback trigger (owned by PlayPage). */
    registerStartPlaybackHandler(fn) {
      this._startPlaybackHandler = fn
    },

    /** Seek to an absolute position; delegates to the registered handler. */
    seek(position) {
      return this._seekHandler ? this._seekHandler(position) : undefined
    },

    /** Start playback; delegates to the registered handler. */
    startPlayback() {
      return this._startPlaybackHandler ? this._startPlaybackHandler() : undefined
    },

    /**
     * Reset the streaming/session state for new content. Mirrors the fields
     * that PlayPage's resetState() previously cleared for these refs. Track
     * lists and the selected audio track are intentionally left untouched —
     * useMediaTracks reloads them per content and the backend re-supplies the
     * audio track, matching the previous behaviour.
     */
    reset() {
      this.status = ''
      this.errorMessage = ''
      this.sessionId = ''
      this.playToken = ''
      this.directStreamUrl = ''
      this.playbackTargetOptions = {}
      this.duration = 0
      this.videoDuration = 0
      this.currentMediaSourceId = null
    },
  },
})
