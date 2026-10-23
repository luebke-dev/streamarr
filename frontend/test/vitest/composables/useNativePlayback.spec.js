/**
 * The native playback state machine.
 *
 * On the desktop the video is decoded by mpv in its own process, so the page has no
 * media element to read a position from — everything it knows comes from the shell's
 * events. That makes the reducer the whole of the page's understanding of playback, and
 * worth testing on its own rather than only through a rendered component.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn().mockResolvedValue(() => {}) }))
vi.mock('src/utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

import { effectScope } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import {
  applyVideoBackdrop,
  initialPlayerState,
  reducePlayerEvent,
  usesNativePlayback,
  useNativePlayback,
} from 'src/composables/useNativePlayback'

describe('usesNativePlayback', () => {
  it('never uses native playback outside the desktop app', () => {
    // The web build must keep its existing player; the plan excludes changing it.
    expect(usesNativePlayback({ isDesktop: false, contentType: 'movie' })).toBe(false)
    expect(usesNativePlayback({ isDesktop: false, contentType: 'episode' })).toBe(false)
  })

  it('uses native playback for video and audio on the desktop', () => {
    expect(usesNativePlayback({ isDesktop: true, contentType: 'movie' })).toBe(true)
    expect(usesNativePlayback({ isDesktop: true, contentType: 'episode' })).toBe(true)
    expect(usesNativePlayback({ isDesktop: true, contentType: 'audio' })).toBe(true)
  })

  it('does not send books or games to mpv', () => {
    // A book belongs in the reader and a game streams through the Lightrays path. A
    // book handed to mpv would look like a mysterious failure to play anything.
    expect(usesNativePlayback({ isDesktop: true, contentType: 'book' })).toBe(false)
    expect(usesNativePlayback({ isDesktop: true, contentType: 'game' })).toBe(false)
    expect(usesNativePlayback({ isDesktop: true, contentType: undefined })).toBe(false)
  })
})

describe('reducePlayerEvent', () => {
  it('starts from a state that claims nothing', () => {
    const state = initialPlayerState()
    expect(state.active).toBe(false)
    expect(state.position).toBe(0)
    expect(state.error).toBeNull()
    expect(state.notices).toEqual([])
  })

  it('takes the notice and the transcode flag from the started event', () => {
    // These two are what make invisible behaviour visible: whether the server is
    // re-encoding, and whether playback resumed from a stored position.
    const state = reducePlayerEvent(initialPlayerState(), 'player:started', {
      item_guid: 'abc',
      notices: [{ kind: 'resuming', position_seconds: 300 }, { kind: 'transcode' }],
      is_transcode: true,
      is_resuming: true,
      start_position: 300,
    })

    expect(state.active).toBe(true)
    expect(state.itemGuid).toBe('abc')
    // Structured facts, not sentences: the interface renders them in the user's language.
    expect(state.notices).toHaveLength(2)
    expect(state.notices[0]).toEqual({ kind: 'resuming', position_seconds: 300 })
    expect(state.isTranscode).toBe(true)
    expect(state.isResuming).toBe(true)
    expect(state.startPosition).toBe(300)
  })

  it('clears a previous error when a new playback starts', () => {
    // Otherwise a failure from the last attempt would still be on screen during a
    // successful one.
    const failed = { ...initialPlayerState(), error: 'kaputt' }
    const state = reducePlayerEvent(failed, 'player:started', { item_guid: 'x' })
    expect(state.error).toBeNull()
  })

  it('follows position, duration and pause', () => {
    const started = reducePlayerEvent(initialPlayerState(), 'player:started', {})
    const state = reducePlayerEvent(started, 'player:state', {
      position: 12.5,
      duration: 600,
      paused: true,
    })

    expect(state.position).toBe(12.5)
    expect(state.duration).toBe(600)
    expect(state.paused).toBe(true)
  })

  it('keeps the loaded flag once it is set', () => {
    // mpv emits `loaded` through `player:loaded` and never repeats it in subsequent
    // state events; losing it would make the UI think playback never started.
    const loaded = reducePlayerEvent(initialPlayerState(), 'player:loaded', {})
    expect(loaded.loaded).toBe(true)

    const after = reducePlayerEvent(loaded, 'player:state', { position: 1, loaded: false })
    expect(after.loaded).toBe(true)
  })

  it('marks the end without pretending to be paused', () => {
    const state = reducePlayerEvent(
      { ...initialPlayerState(), active: true, paused: true },
      'player:ended',
      {},
    )
    expect(state.ended).toBe(true)
    expect(state.paused).toBe(false)
  })

  it('a stop ends the playback but keeps the position it reached', () => {
    // The position matters after a stop: it is what the shell reports to the server.
    const playing = { ...initialPlayerState(), active: true, position: 250 }
    const state = reducePlayerEvent(playing, 'player:stopped', {})
    expect(state.active).toBe(false)
    expect(state.position).toBe(250)
  })

  it('ignores an unknown event instead of throwing', () => {
    // A newer shell may emit events this build does not know; that must not break
    // playback.
    const before = initialPlayerState()
    const after = reducePlayerEvent(before, 'player:something-new', { x: 1 })
    expect(after).toEqual(before)
  })

  it('does not mutate the state it is given', () => {
    const before = initialPlayerState()
    const frozen = Object.freeze({ ...before })
    // A mutation would throw here, which is the point: the reducer must be pure, or a
    // parent holding a reference would see changes it never asked for.
    expect(() => reducePlayerEvent(frozen, 'player:state', { position: 5 })).not.toThrow()
    expect(before.position).toBe(0)
  })
})

/**
 * Track selection.
 *
 * The tracks come from mpv, not from the browser: a native client has no `TextTrack` API,
 * and the browser's list would describe the stream the player was handed rather than what
 * mpv resolved. That makes these calls the only route to audio and subtitle selection.
 */
describe('native track selection', () => {
  /** Runs the composable inside a scope so its lifecycle hooks have an owner. */
  function withPlayback() {
    const scope = effectScope()
    const playback = scope.run(() => useNativePlayback())
    return { playback, scope }
  }

  it('reads the track list from the shell, not from a media element', async () => {
    invoke.mockResolvedValueOnce({
      audio: [{ id: 1, label: 'English', language: 'eng', selected: true }],
      subtitles: [],
      selectedAudio: 1,
      selectedSubtitle: null,
    })

    const { playback, scope } = withPlayback()
    const tracks = await playback.fetchTracks()

    expect(invoke).toHaveBeenCalledWith('player_tracks')
    expect(tracks.audio).toHaveLength(1)
    expect(tracks.selectedAudio).toBe(1)
    scope.stop()
  })

  it('returns null instead of throwing when nothing is playing', async () => {
    // "Nothing is playing" is not a failure. Throwing here would surface an error dialog
    // for a state the user caused by simply not having started anything.
    invoke.mockRejectedValueOnce(new Error('Der Wiedergabeprozess läuft nicht mehr.'))

    const { playback, scope } = withPlayback()
    await expect(playback.fetchTracks()).resolves.toBeNull()
    scope.stop()
  })

  it('switches the audio track by mpv id', async () => {
    invoke.mockResolvedValue(undefined)

    const { playback, scope } = withPlayback()
    await playback.selectAudioTrack(2)

    expect(invoke).toHaveBeenCalledWith('player_set_property', { name: 'aid', value: 2 })
    scope.stop()
  })

  it('hands the audio choice back to mpv with "auto"', async () => {
    // `null` is the interface's "Automatic". Passing the number 0 or an empty string
    // would be a track id that does not exist, and mpv would keep the current track while
    // the UI showed "Automatic" — a lie the user cannot see through.
    invoke.mockResolvedValue(undefined)

    const { playback, scope } = withPlayback()
    await playback.selectAudioTrack(null)

    expect(invoke).toHaveBeenCalledWith('player_set_property', { name: 'aid', value: 'auto' })
    scope.stop()
  })

  it('turns subtitles off with "no", not with "auto"', async () => {
    // The distinction matters: `auto` lets mpv pick a subtitle, so a user who just turned
    // subtitles off would see them come back at the next scene.
    invoke.mockResolvedValue(undefined)

    const { playback, scope } = withPlayback()
    await playback.selectSubtitleTrack(null)

    expect(invoke).toHaveBeenCalledWith('player_set_property', { name: 'sid', value: 'no' })
    scope.stop()
  })

  it('selects a subtitle track by mpv id', async () => {
    invoke.mockResolvedValue(undefined)

    const { playback, scope } = withPlayback()
    await playback.selectSubtitleTrack(3)

    expect(invoke).toHaveBeenCalledWith('player_set_property', { name: 'sid', value: 3 })
    scope.stop()
  })
})

describe('applyVideoBackdrop', () => {
  beforeEach(() => {
    document.body.className = ''
  })

  it('lets the picture through while a video plays', () => {
    // The shell renders into a subsurface *below* the webview (ADR 003); without this class the
    // page would cover the picture, and the symptom would look like playback failing.
    applyVideoBackdrop(true)

    expect(document.body.classList.contains('streamarr-native-video')).toBe(true)
  })

  it('gives the window its own background back when playback ends', () => {
    applyVideoBackdrop(true)
    applyVideoBackdrop(false)

    expect(document.body.classList.contains('streamarr-native-video')).toBe(false)
  })

  it('coerces anything unexpected rather than leaving a stale class', () => {
    applyVideoBackdrop(true)
    applyVideoBackdrop(undefined)

    expect(document.body.classList.contains('streamarr-native-video')).toBe(false)
  })
})
