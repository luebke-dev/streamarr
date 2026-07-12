import { defineStore } from 'pinia'
import { LocalStorage } from 'quasar'
import { api } from 'src/boot/axios'
import { formatTime } from 'src/composables/useMediaFormatters'
import { logger } from 'src/utils/logger'

export const useAudioPlayerStore = defineStore('audioPlayer', {
  state: () => ({
    // Current track info
    currentTrack: null, // { guid, title, artist, albumTitle, albumArt, duration, mediaGuid }
    // Playback state
    isPlaying: false,
    currentTime: 0,
    duration: 0,
    volume: LocalStorage.getItem('audio-player-volume') ?? 0.8,
    // Queue
    queue: [],
    queueIndex: -1,
    // Shuffle back-history: indices of tracks played, so Previous can retrace
    // the shuffled order instead of walking the queue linearly
    _shuffleHistory: [],
    // Repeat / shuffle
    repeat: LocalStorage.getItem('audio-player-repeat') || 'off', // 'off', 'all', 'one'
    shuffle: LocalStorage.getItem('audio-player-shuffle') || false,
    // UI state
    isVisible: false,
    isLoading: false,
    error: null, // terminal playback failures only
    statusMessage: null, // transient status text (e.g. "still downloading")
    lyrics: null,
    lyricsLoading: false,
    lyricsError: null,
    // Audio element reference (managed outside Vue reactivity)
    _audio: null,
    _loadId: 0,
    _lastProgressReport: null,
  }),

  getters: {
    hasTrack: (state) => state.currentTrack !== null,
    progress: (state) => (state.duration > 0 ? state.currentTime / state.duration : 0),
    hasNext: (state) =>
      state.shuffle
        ? state.queue.length > 1 || state.repeat === 'all'
        : state.queueIndex < state.queue.length - 1 || state.repeat === 'all',
    hasPrevious: (state) =>
      state.shuffle
        ? state._shuffleHistory.length > 0 || state.repeat === 'all'
        : state.queueIndex > 0 || state.repeat === 'all',
    formattedCurrentTime: (state) => formatTime(state.currentTime),
    formattedDuration: (state) => formatTime(state.duration),
  },

  actions: {
    /**
     * Initialize the audio element (call once on app mount)
     */
    init() {
      if (this._audio) return
      const audio = new Audio()
      audio.volume = this.volume

      audio.addEventListener('timeupdate', () => {
        this.currentTime = audio.currentTime
        this._maybeReportProgress()
      })
      audio.addEventListener('durationchange', () => {
        this.duration = audio.duration || 0
      })
      audio.addEventListener('ended', () => {
        this._onTrackEnded()
      })
      audio.addEventListener('playing', () => {
        this.isPlaying = true
        this.isLoading = false
      })
      audio.addEventListener('pause', () => {
        this.isPlaying = false
      })
      audio.addEventListener('waiting', () => {
        this.isLoading = true
      })
      audio.addEventListener('error', () => {
        this.error = 'Failed to play audio'
        this.isLoading = false
        this.isPlaying = false
      })

      this._audio = audio
    },

    /**
     * Play a single track immediately.
     * @param {Object} track - Track info: { guid, title, artist, albumTitle, albumArt, duration }
     * @param {Array} [albumTracks] - Optional: full album track list for queueing
     */
    async play(track, albumTracks = null) {
      this.init()
      this.error = null
      this.statusMessage = null
      this._shuffleHistory = []

      if (albumTracks && albumTracks.length > 0) {
        this.queue = albumTracks
        this.queueIndex = albumTracks.findIndex((t) => t.guid === track.guid)
        if (this.queueIndex === -1) this.queueIndex = 0
      } else {
        this.queue = [track]
        this.queueIndex = 0
      }

      await this._loadAndPlay(track)
    },

    /**
     * Play all tracks from an album
     * @param {Array} tracks - Array of track objects
     */
    async playAlbum(tracks) {
      if (!tracks || tracks.length === 0) return
      this.queue = [...tracks]
      this.queueIndex = 0
      this._shuffleHistory = []
      await this._loadAndPlay(tracks[0])
    },

    /**
     * Add tracks to the end of the queue
     */
    addToQueue(tracks) {
      if (Array.isArray(tracks)) {
        this.queue.push(...tracks)
      } else {
        this.queue.push(tracks)
      }
    },

    /**
     * Internal: load a track's audio source and start playback
     */
    async _loadAndPlay(track) {
      const loadId = ++this._loadId
      this.isLoading = true
      this.isVisible = true

      try {
        // Get the audio source URL — may poll while downloading
        // Keep old track playing until URL is ready
        const audioUrl = await this._getAudioUrl(track.guid, loadId)
        if (loadId !== this._loadId) return
        if (!audioUrl) {
          this.error = 'No audio file available'
          this.isLoading = false
          return
        }

        // Now switch to the new track
        this.currentTrack = track
        this.lyrics = null
        this.lyricsError = null
        this._lastProgressReport = null
        this._audio.src = audioUrl
        await this._audio.play()
        this.loadLyrics(track.guid)
      } catch (err) {
        if (loadId !== this._loadId) return
        logger.error('Failed to play track:', err)
        this.error = 'Failed to play audio'
        this.isLoading = false
      }
    },

    /**
     * Get audio URL for a track — polls until file is ready if still downloading
     */
    async _getAudioUrl(mediaGuid, loadId) {
      const maxAttempts = 120 // ~10 min at 5s intervals
      const pollInterval = 5000

      const requestPlayback = async () => {
        const response = await api.post(`/api/play/${mediaGuid}`, null, {
          params: { supported_audio_codecs: 'aac,mp3,opus,flac,vorbis' },
        })
        return response.data
      }

      try {
        let playback = await requestPlayback()

        for (let attempt = 0; playback.status && playback.status !== 'ready'; attempt++) {
          if (attempt >= maxAttempts || loadId !== this._loadId) return null

          // File not ready yet — show transient status (NOT an error) and poll
          // the read-only availability endpoint until the file is on disk
          this.statusMessage = playback.message || `Status: ${playback.status}`
          await new Promise((resolve) => setTimeout(resolve, pollInterval))
          if (loadId !== this._loadId) return null

          const availabilityResp = await api.get(`/api/media/${mediaGuid}/availability`)
          if ((availabilityResp.data || {}).status === 'available') {
            playback = await requestPlayback()
          }
        }

        if (loadId !== this._loadId) return null

        this.error = null
        this.statusMessage = null
        const baseUrl = api.defaults.baseURL || window.location.origin
        const { token, audio_only, session_id } = playback

        if (audio_only && token) {
          return `${baseUrl}/api/stream/audio/file?token=${encodeURIComponent(token)}`
        }

        if (session_id && token) {
          return `${baseUrl}/api/stream/${session_id}/playlist.m3u8?token=${encodeURIComponent(token)}`
        }
      } catch (err) {
        logger.warn('Could not get audio stream:', err.message)
      }
      return null
    },

    pause() {
      if (this._audio) this._audio.pause()
    },

    resume() {
      if (this._audio) this._audio.play()
    },

    togglePlay() {
      if (this.isPlaying) {
        this.pause()
      } else {
        this.resume()
      }
    },

    /**
     * Pick a random queue index for shuffle, excluding the current track so it
     * doesn't play twice in a row (unless the queue has a single track).
     */
    _pickShuffleIndex() {
      if (this.queue.length <= 1) return 0
      let idx
      do {
        idx = Math.floor(Math.random() * this.queue.length)
      } while (idx === this.queueIndex)
      return idx
    },

    async next() {
      if (this.queue.length === 0) return

      let nextIndex
      if (this.shuffle) {
        // Remember where we are so Previous can retrace the shuffled order
        if (this.queueIndex >= 0) this._shuffleHistory.push(this.queueIndex)
        nextIndex = this._pickShuffleIndex()
      } else {
        nextIndex = this.queueIndex + 1
        if (nextIndex >= this.queue.length) {
          if (this.repeat === 'all') {
            nextIndex = 0
          } else {
            this.isPlaying = false
            return
          }
        }
      }

      this.queueIndex = nextIndex
      await this._loadAndPlay(this.queue[nextIndex])
    },

    async previous() {
      // If more than 3 seconds in, restart current track
      if (this.currentTime > 3) {
        this.seek(0)
        return
      }

      if (this.shuffle) {
        // Retrace the shuffled play order via history
        if (this._shuffleHistory.length > 0) {
          const prevIndex = this._shuffleHistory.pop()
          this.queueIndex = prevIndex
          await this._loadAndPlay(this.queue[prevIndex])
        } else {
          this.seek(0)
        }
        return
      }

      let prevIndex = this.queueIndex - 1
      if (prevIndex < 0) {
        if (this.repeat === 'all') {
          prevIndex = this.queue.length - 1
        } else {
          this.seek(0)
          return
        }
      }

      this.queueIndex = prevIndex
      await this._loadAndPlay(this.queue[prevIndex])
    },

    seek(time) {
      if (this._audio) {
        this._audio.currentTime = time
        this.currentTime = time
      }
    },

    seekPercent(percent) {
      if (this._audio && this.duration > 0) {
        this.seek(percent * this.duration)
      }
    },

    setVolume(vol) {
      this.volume = Math.max(0, Math.min(1, vol))
      if (this._audio) this._audio.volume = this.volume
      LocalStorage.set('audio-player-volume', this.volume)
    },

    toggleRepeat() {
      const modes = ['off', 'all', 'one']
      const idx = modes.indexOf(this.repeat)
      this.repeat = modes[(idx + 1) % modes.length]
      LocalStorage.set('audio-player-repeat', this.repeat)
    },

    toggleShuffle() {
      this.shuffle = !this.shuffle
      this._shuffleHistory = []
      LocalStorage.set('audio-player-shuffle', this.shuffle)
    },

    clearQueue() {
      this.queue = []
      this.queueIndex = -1
      this._shuffleHistory = []
    },

    close() {
      this._loadId++
      if (this._audio) {
        this._audio.pause()
        this._audio.src = ''
      }
      this.currentTrack = null
      this.isPlaying = false
      this.isVisible = false
      this.currentTime = 0
      this.duration = 0
      this.error = null
      this.statusMessage = null
      this.lyrics = null
      this.lyricsError = null
      this.clearQueue()
    },

    async loadLyrics(mediaGuid = null) {
      const guid = mediaGuid || this.currentTrack?.guid
      if (!guid) return null
      this.lyricsLoading = true
      this.lyricsError = null
      try {
        const response = await api.get(`/api/media/${guid}/lyrics`)
        this.lyrics = response.data
        return this.lyrics
      } catch (error) {
        this.lyrics = null
        if (error.response?.status !== 404) {
          this.lyricsError = 'Failed to load lyrics'
          logger.debug('Failed to load lyrics:', error)
        }
        return null
      } finally {
        this.lyricsLoading = false
      }
    },

    _onTrackEnded() {
      // Report completion before moving on
      this._reportProgress(true)

      if (this.repeat === 'one') {
        this._audio.currentTime = 0
        this._audio.play()
        return
      }
      this.next()
    },

    /**
     * Report playback progress to viewing history (throttled to every 30s)
     */
    _maybeReportProgress() {
      const now = Date.now()
      if (!this._lastProgressReport || now - this._lastProgressReport > 30_000) {
        this._lastProgressReport = now
        this._reportProgress(false)
      }
    },

    /**
     * Send progress update to backend
     */
    async _reportProgress(completed) {
      if (!this.currentTrack?.guid) return
      const dur = this._audio?.duration
      if (!dur || !isFinite(dur)) return

      try {
        await api.post('/api/viewing-history', {
          content_type: 'music',
          song_guid: this.currentTrack.guid,
          progress_seconds: Math.floor(completed ? dur : this.currentTime),
          duration_seconds: Math.floor(dur),
        })
      } catch (err) {
        logger.debug('Failed to report playback progress:', err)
      }
    },

    removeFromQueue(index) {
      if (index < 0 || index >= this.queue.length) return
      this.queue.splice(index, 1)
      // Stored history indices no longer map to the mutated queue
      this._shuffleHistory = []
      if (index < this.queueIndex) {
        this.queueIndex--
      } else if (index === this.queueIndex) {
        // Currently playing track was removed
        if (this.queue.length === 0) {
          this.close()
        } else {
          this.queueIndex = Math.min(this.queueIndex, this.queue.length - 1)
          this._loadAndPlay(this.queue[this.queueIndex])
        }
      }
    },
  },
})
