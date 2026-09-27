/**
 * Native playback for the desktop app.
 *
 * On the desktop the video is decoded by **mpv in its own process**, never by a `<video>`
 * element in the webview (ADR 001: the webview is UI chrome only). So this composable
 * does what the web player does — start playback, follow the position, report progress —
 * but the position comes from the shell's `player:state` events instead of from a media
 * element.
 *
 * # Why the position is reported through `useViewingProgress`
 *
 * Progress reporting is where the resume feature lives: the same endpoints, the same
 * payload, the same authentication. So the native path does not reimplement it — it calls
 * the *same* `updateProgress`, only with a position from a different source. Two
 * implementations of progress reporting would be two chances to disagree about what
 * "watched" means, and the server would have to reconcile them.
 *
 * # What it deliberately does not do
 *
 * It does not fall back to the web player when native playback fails. A silent fallback
 * would hide exactly the failures that matter — a missing mpv, a blocked port, a server
 * that refuses — and it would mean shipping a `<video>` path the plan excludes. The error
 * is shown instead, and the message says what to do.
 */

import { ref, shallowRef, onUnmounted } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { isDesktopApp } from 'src/utils/desktopPlatform'
import { logger } from 'src/utils/logger'

/**
 * The UI state of a native playback, derived from shell events.
 *
 * Kept as a plain reducer so the event handling is testable without a Tauri runtime.
 */
export function reducePlayerEvent(state, eventName, payload) {
  const next = { ...state }
  switch (eventName) {
    case 'player:started':
      next.active = true
      next.itemGuid = payload?.item_guid ?? state.itemGuid
      next.notice = payload?.notice ?? null
      next.isTranscode = Boolean(payload?.is_transcode)
      next.isResuming = Boolean(payload?.is_resuming)
      next.startPosition = payload?.start_position ?? 0
      next.error = null
      break
    case 'player:loaded':
      next.loaded = true
      break
    case 'player:state':
      next.position = payload?.position ?? state.position
      next.duration = payload?.duration ?? state.duration
      next.paused = Boolean(payload?.paused)
      next.ended = Boolean(payload?.ended)
      next.loaded = Boolean(payload?.loaded) || state.loaded
      break
    case 'player:ended':
      // mpv reports the position as the duration when a file ends; the shell decides
      // what to *store* for that (the end-margin rules), so nothing is inferred here.
      next.ended = true
      next.paused = false
      break
    case 'player:stopped':
      next.active = false
      next.loaded = false
      break
    default:
      break
  }
  return next
}

/** The state a playback starts from. */
export function initialPlayerState() {
  return {
    active: false,
    loaded: false,
    ended: false,
    paused: false,
    position: 0,
    duration: 0,
    itemGuid: null,
    notice: null,
    isTranscode: false,
    isResuming: false,
    startPosition: 0,
    error: null,
  }
}

/**
 * Whether native playback should be used for this content.
 *
 * Only video. Books render in a reader and games stream through the Lightrays path, so
 * neither may be sent to mpv — and a book handed to mpv would look like a mysterious
 * failure to play anything.
 */
export function usesNativePlayback({ isDesktop, contentType }) {
  if (!isDesktop) return false
  return contentType === 'movie' || contentType === 'episode' || contentType === 'audio'
}

/**
 * Starts and follows a native playback.
 *
 * `onProgress(currentTime, duration)` is called with positions worth reporting; the caller
 * passes the existing progress reporter so both playback paths share one implementation.
 * Throttling lives in the core crate, so this calls only when the position actually
 * changed enough to matter.
 */
export function useNativePlayback({ onProgress } = {}) {
  const state = ref(initialPlayerState())
  const summary = shallowRef(null)
  const unlisteners = []
  let lastReported = 0

  /** How far the position must move before another report is worth sending. */
  const REPORT_STEP_SECONDS = 10

  function apply(eventName, payload) {
    state.value = reducePlayerEvent(state.value, eventName, payload)
    if (eventName === 'player:state' && typeof onProgress === 'function') {
      const { position, duration } = state.value
      // A pause, a seek backwards or a large step are all worth a report; a steady
      // playback is reported every ten seconds. The server's own rules then decide
      // whether the item counts as watched.
      if (duration > 0 && Math.abs(position - lastReported) >= REPORT_STEP_SECONDS) {
        lastReported = position
        try {
          onProgress(position, duration)
        } catch (error) {
          logger.warn('Fortschritt konnte nicht gemeldet werden:', error)
        }
      }
    }
  }

  /** Subscribes to the shell's player events. */
  async function subscribe() {
    if (!isDesktopApp() || unlisteners.length > 0) return
    for (const name of [
      'player:started',
      'player:loaded',
      'player:state',
      'player:ended',
      'player:stopped',
    ]) {
      unlisteners.push(await listen(name, (event) => apply(name, event.payload)))
    }
  }

  async function unsubscribe() {
    while (unlisteners.length > 0) {
      const off = unlisteners.pop()
      try {
        await off()
      } catch (error) {
        logger.warn('Ereignis konnte nicht abgemeldet werden:', error)
      }
    }
  }

  /** Starts playback of one item. */
  async function start(itemGuid, startOverride = null) {
    state.value = { ...initialPlayerState(), active: true, itemGuid }
    summary.value = null
    lastReported = 0
    try {
      const result = await invoke('play_media', {
        itemGuid,
        startOverride: startOverride ?? null,
      })
      summary.value = result
      state.value = reducePlayerEvent(state.value, 'player:started', result)
      return result
    } catch (error) {
      // The message comes from the shell and already says what to do about it (the
      // diagnosis is produced where the failure is known).
      state.value = { ...state.value, active: false, error: String(error) }
      throw error
    }
  }

  async function stop() {
    try {
      const report = await invoke('player_stop')
      lastReported = 0
      return report
    } catch (error) {
      logger.warn('Wiedergabe konnte nicht beendet werden:', error)
      return null
    }
  }

  async function setPaused(paused) {
    await invoke('player_set_paused', { paused })
  }

  async function seek(seconds, relative = false) {
    await invoke('player_seek', { seconds, relative })
  }

  async function setTrackProperty(name, value) {
    await invoke('player_set_property', { name, value })
  }

  onUnmounted(() => {
    unsubscribe()
  })

  return {
    state,
    summary,
    subscribe,
    unsubscribe,
    start,
    stop,
    setPaused,
    seek,
    setTrackProperty,
  }
}
