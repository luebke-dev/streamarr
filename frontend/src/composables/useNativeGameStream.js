/**
 * Native game streaming for the desktop app.
 *
 * # Why this exists
 *
 * ADR 001 and the plan's architecture rule are categorical: *the webview is UI
 * chrome, and every video output — media and games — happens natively.* The web
 * client plays games by attaching a WebRTC stream to a `<video>` element, which
 * on the desktop means WebKitGTK decoding and compositing the game inside the
 * webview. That is exactly the path the rule forbids, and it is the path spike
 * 0.2 found unreliable.
 *
 * So on the desktop the game stream is started, decoded and rendered by the
 * **shell**: GStreamer receives the WebRTC stream, draws into its own window, and
 * this composable is the thin part that starts it, forwards input and follows the
 * state.
 *
 * # What it deliberately does not do
 *
 * It does not fall back to the `<video>` path when the shell refuses. A silent
 * fallback would hide the failures that matter most — this build has no
 * `gamestream` feature, GStreamer is missing an element, the server refused the
 * launch — and it would ship the browser path the plan excludes. The error is
 * shown instead, and it says which of those it was.
 *
 * The same reasoning as `useNativePlayback`: one path, no disguise.
 */

import { ref, onUnmounted } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { isDesktopApp } from 'src/utils/desktopPlatform'
import { logger } from 'src/utils/logger'
import { useCouchMode } from 'src/composables/useCouchMode'

/**
 * Whether the desktop should use the native game path.
 *
 * A function rather than a constant so a test can flip it, and it mirrors
 * `usesNativePlayback` for media — the two have to agree, or a desktop user
 * would get mpv for films and a `<video>` for games.
 */
export function usesNativeGameStream() {
  if (typeof window === 'undefined') return false
  const forced = window.__STREAMARR_FORCE_NATIVE_GAME__
  if (forced !== undefined) return Boolean(forced)
  return isDesktopApp()
}

/**
 * Reduces a shell answer into the state the view renders.
 *
 * A plain function so the mapping is testable without a Tauri runtime — the same
 * shape as `reducePlayerEvent` for media.
 */
export function reduceGameOutcome(state, outcome) {
  const next = { ...state, error: null, errorStatus: null }
  if (!outcome) {
    next.error = 'Der Spielestream hat keine Antwort geliefert.'
    return next
  }
  switch (outcome.kind) {
    case 'started':
      next.sessionId = outcome.sessionId
      next.width = outcome.width
      next.height = outcome.height
      next.running = true
      break
    case 'refused':
      next.running = false
      // Carried separately from the message: the UI has to recognise **409**
      // (the ROM is being fetched, so this is a wait rather than an error) and
      // matching on the text would break as soon as the wording changed.
      next.errorStatus = outcome.status ?? null
      // The shell's own message, not a paraphrase: it knows whether the server
      // refused, the transport failed or the profile is missing.
      next.error = outcome.advice
        ? `${outcome.problem} ${outcome.advice}`
        : outcome.problem
      break
    case 'notInBuild':
      next.running = false
      // A distinct case, and worth its own wording: a build without the
      // `gamestream` feature is a legitimate configuration, and a user told
      // "failed" would go looking for a bug that is not there.
      next.error =
        'Dieser Build enthält kein Spiel-Streaming. Installiere die Paketversion, '
        + 'oder baue mit dem Feature `gamestream`.'
      break
    default:
      next.running = false
      next.error = `Unbekannte Antwort: ${outcome.kind}`
  }
  return next
}

/** The state of one game stream, as the view needs it. */
export function emptyGameState() {
  return {
    running: false,
    sessionId: null,
    width: 0,
    height: 0,
    /// The shell's word for the session state, e.g. `streaming`.
    phase: null,
    inputReady: false,
    error: null,
    /// The HTTP status behind a refusal, when there was one.
    errorStatus: null,
    /// How many controller messages have reached the game.
    ///
    /// Reported rather than assumed: the earlier version showed "controller
    /// connected" as a hard-coded string while nothing was forwarded at all.
    inputForwarded: 0,
    /// The last reading from `game_stats`, or `null` before one arrived.
    stats: null,
  }
}

export function useNativeGameStream({ onEnded } = {}) {
  const state = ref(emptyGameState())
  // The controllers are a single resource: while a game runs it owns them, and
  // the couch interface must stop polling or the two would split the event
  // stream between them.
  const couch = useCouchMode()
  let pollTimer = null
  let inputPollTimer = null
  let inputCleanup = null

  /**
   * The size to ask for: the window in physical pixels, even, within limits.
   *
   * Measured here rather than in the shell because only the page knows its own
   * window. The shell clamps again before sending — the server rejects
   * out-of-range values, and a user who dragged the window small should get a
   * stream rather than a validation error about a number they never chose.
   */
  function desiredSize() {
    if (typeof window === 'undefined') return { width: 1280, height: 720 }
    const dpr = window.devicePixelRatio || 1
    const even = (value) => (value % 2 === 0 ? value : value + 1)
    return {
      width: Math.max(64, Math.min(7680, even(Math.round(window.innerWidth * dpr)))),
      height: Math.max(64, Math.min(4320, even(Math.round(window.innerHeight * dpr)))),
    }
  }

  async function start(itemGuid, platform = null) {
    if (!usesNativeGameStream()) {
      state.value = {
        ...emptyGameState(),
        error: 'Der native Spielestream ist nur in der Desktop-App verfügbar.',
      }
      return null
    }
    const { width, height } = desiredSize()
    try {
      // The shell does the launch *and* the pipeline; this call returns as soon
      // as the thread is running, not when the first frame arrives.
      const outcome = await invoke('game_start', {
        request: { mediaGuid: itemGuid, width, height, platform },
      })
      state.value = reduceGameOutcome(state.value, outcome)
      if (state.value.running) {
        // Order matters: the couch poll is stopped *before* this one starts, so
        // no event is drained by the wrong reader in between.
        couch.setSuppressed(true)
        startWatching()
        attachInput()
      }
      return state.value
    } catch (error) {
      // A thrown error is the command itself failing — a different situation
      // from the shell answering `refused`, and it is worth showing as such.
      logger.error('Spielestream konnte nicht gestartet werden:', error)
      state.value = {
        ...emptyGameState(),
        error: String(error?.message || error),
      }
      return null
    }
  }

  /** Follows the session state while the stream runs. */
  function startWatching() {
    stopWatching()
    pollTimer = setInterval(async () => {
      try {
        const phase = await invoke('game_state')
        state.value = { ...state.value, phase }
        // `null` means the shell has no stream any more: it ended on its own.
        if (phase === null || phase === 'ended' || phase === 'stopped' || phase === 'failed') {
          stopWatching()
          detachInput()
          // The controllers go back to the couch interface.
          couch.setSuppressed(false)
          state.value = { ...state.value, running: false }
          onEnded?.(phase)
        }
      } catch (error) {
        logger.warn('Spielzustand nicht abrufbar:', error)
      }
    }, 500)
  }

  function stopWatching() {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /**
   * Starts forwarding controller input to the game.
   *
   * # Why a poll and not an event listener
   *
   * The devices are read by the **shell** (`gilrs`), and the shell hands each
   * event out exactly once. The couch interface and the game therefore cannot
   * both read them — one is the active reader. While a game runs this loop is
   * that reader (`game_pad_input`), and the couch poll is stopped; when the
   * stream ends the two swap back.
   *
   * A pull rather than a push because the page has no handle on the device: it
   * can only ask the shell to drain its queue. 30 ms is under two frames at
   * 60 Hz, which is below what a player can feel, and it costs one function call.
   *
   * Keyboard and mouse are *not* forwarded here, and that is a real limit rather
   * than an oversight: the picture is in a window the shell created, key events
   * go to whichever window holds the focus, and this page cannot send events it
   * never receives. Forwarding them needs the shell's own window to handle its
   * input.
   */
  const PAD_POLL_MS = 30

  function attachInput() {
    detachInput()
    inputPollTimer = setInterval(async () => {
      try {
        // Returns how many messages reached the game, so a caller could show
        // "controller connected" only when that is true rather than assumed.
        state.value = {
          ...state.value,
          inputForwarded: await invoke('game_pad_input'),
        }
      } catch (error) {
        logger.debug('Gamepad-Eingabe nicht weitergeleitet:', error)
      }
    }, PAD_POLL_MS)
    inputCleanup = () => {
      clearInterval(inputPollTimer)
      inputPollTimer = null
    }
  }

  function detachInput() {
    if (inputCleanup) {
      inputCleanup()
      inputCleanup = null
    }
  }

  /** Asks the server to rebuild its pipeline at the current window size. */
  async function matchResolution() {
    const { width, height } = desiredSize()
    const applied = await invoke('game_resize', { width, height }).catch(() => null)
    if (applied) {
      state.value = { ...state.value, width: applied[0], height: applied[1] }
    }
    return applied
  }

  /**
   * Live statistics for the running stream.
   *
   * `game_stats` answers `null` when nothing runs, and the panel shows a dash
   * rather than zeros — "not streaming" and "streaming at 0 fps" are different
   * answers.
   */
  async function fetchStats() {
    if (!usesNativeGameStream()) return null
    try {
      const stats = await invoke('game_stats')
      state.value = { ...state.value, stats }
      return stats
    } catch (error) {
      logger.debug('Statistik nicht abrufbar:', error)
      return null
    }
  }

  async function stop() {
    stopWatching()
    detachInput()
    couch.setSuppressed(false)
    if (!usesNativeGameStream()) return false
    try {
      const wasRunning = await invoke('game_stop')
      state.value = { ...state.value, running: false, phase: 'stopped' }
      return wasRunning
    } catch (error) {
      logger.warn('Spielestream konnte nicht beendet werden:', error)
      return false
    }
  }

  onUnmounted(() => {
    stopWatching()
    detachInput()
  })

  return { state, start, stop, matchResolution, fetchStats }
}
