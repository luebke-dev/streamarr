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
  }
}

export function useNativeGameStream({ onEnded } = {}) {
  const state = ref(emptyGameState())
  let pollTimer = null
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
   * Sends keyboard and pointer input to the game.
   *
   * The window of the running stream is the **shell's**, not the page's, so the
   * keyboard focus is not here — and that is a real gap rather than an oversight:
   * the shell's game window has to forward its own key events, which needs the
   * GTK window's event handling and therefore belongs in the shell, not in this
   * composable. What this does is stop the page from *pretending*: it does not
   * install listeners that could never receive the events a game needs.
   *
   * Gamepads are unaffected — the shell reads them directly through `gilrs`, which
   * is why the couch and game paths share one reader.
   */
  function attachInput() {
    detachInput()
    // Nothing to attach on the page side; kept as a seam so a future shell that
    // emits input events has one place to subscribe.
    inputCleanup = null
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

  async function stop() {
    stopWatching()
    detachInput()
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

  return { state, start, stop, matchResolution }
}
