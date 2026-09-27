/**
 * The native game path — and the rule it exists to keep.
 *
 * The plan's architecture rule is categorical: *the webview is UI chrome, and
 * every video output — media and games — happens natively* (ADR 001). The web
 * client plays games by attaching a WebRTC stream to a `<video>` element, so on
 * the desktop that would mean WebKitGTK decoding the game inside the webview.
 *
 * These tests pin down the branch that prevents it, because the defect they
 * guard against is invisible: with `usesNativeGameStream()` returning `false` on
 * the desktop, everything still *works* — it just plays through the path the
 * plan forbids, and no error is ever raised.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

const invoke = vi.fn()
vi.mock('@tauri-apps/api/core', () => ({ invoke: (...args) => invoke(...args) }))
vi.mock('src/utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

let desktop = true
vi.mock('src/utils/desktopPlatform', () => ({ isDesktopApp: () => desktop }))

async function freshModule() {
  vi.resetModules()
  return import('src/composables/useNativeGameStream')
}

describe('usesNativeGameStream', () => {
  beforeEach(() => {
    desktop = true
    delete globalThis.window?.__STREAMARR_FORCE_NATIVE_GAME__
  })

  it('is true in the desktop app and false in a browser', async () => {
    const { usesNativeGameStream } = await freshModule()
    expect(usesNativeGameStream()).toBe(true)
    desktop = false
    expect(usesNativeGameStream()).toBe(false)
  })

  it('can be forced, so the other branch is testable', async () => {
    // Without an override the web branch could only be tested by pretending not
    // to be a desktop, which would also change everything else.
    desktop = false
    window.__STREAMARR_FORCE_NATIVE_GAME__ = true
    const { usesNativeGameStream } = await freshModule()
    expect(usesNativeGameStream()).toBe(true)
    delete window.__STREAMARR_FORCE_NATIVE_GAME__
  })
})

describe('reduceGameOutcome', () => {
  it('marks a started stream as running', async () => {
    const { reduceGameOutcome, emptyGameState } = await freshModule()
    const next = reduceGameOutcome(emptyGameState(), {
      kind: 'started',
      sessionId: 's1',
      width: 2560,
      height: 1440,
    })
    expect(next.running).toBe(true)
    expect(next.sessionId).toBe('s1')
    expect(next.width).toBe(2560)
    expect(next.error).toBeNull()
  })

  it('says "this build has no game streaming" for notInBuild', async () => {
    // A distinct case with its own wording. A user told "failed" would look for
    // a bug; a build without the `gamestream` feature is a legitimate
    // configuration and the message should say so.
    const { reduceGameOutcome, emptyGameState } = await freshModule()
    const next = reduceGameOutcome(emptyGameState(), { kind: 'notInBuild' })
    expect(next.running).toBe(false)
    expect(next.error).toContain('gamestream')
    expect(next.error).not.toContain('fehlgeschlagen')
  })

  it('carries the HTTP status of a refusal separately from the message', async () => {
    // The UI has to recognise 409 — "the ROM is being fetched, so this is a
    // wait" — and matching on the message text would break the moment the
    // wording changed.
    const { reduceGameOutcome, emptyGameState } = await freshModule()
    const next = reduceGameOutcome(emptyGameState(), {
      kind: 'refused',
      problem: 'Der Server hat den Start abgelehnt (HTTP 409).',
      advice: 'Die ROM wird geladen.',
      status: 409,
    })
    expect(next.errorStatus).toBe(409)
    expect(next.error).toContain('409')
    expect(next.error).toContain('Die ROM wird geladen')
  })

  it('clears a previous error status on success', async () => {
    const { reduceGameOutcome, emptyGameState } = await freshModule()
    const failed = reduceGameOutcome(emptyGameState(), {
      kind: 'refused',
      problem: 'x',
      advice: null,
      status: 500,
    })
    expect(failed.errorStatus).toBe(500)
    const started = reduceGameOutcome(failed, {
      kind: 'started',
      sessionId: 's',
      width: 1,
      height: 1,
    })
    expect(started.errorStatus).toBeNull()
  })

  it('reports a missing answer rather than pretending success', async () => {
    const { reduceGameOutcome, emptyGameState } = await freshModule()
    const next = reduceGameOutcome(emptyGameState(), null)
    expect(next.running).toBe(false)
    expect(next.error).toBeTruthy()
  })
})

describe('the stream is started in the shell, not in the webview', () => {
  beforeEach(() => {
    invoke.mockReset()
    desktop = true
  })

  it('calls game_start and never touches a video element', async () => {
    invoke.mockImplementation(async (command) => {
      if (command === 'game_start') {
        return { kind: 'started', sessionId: 's1', width: 1920, height: 1080 }
      }
      if (command === 'game_state') return 'streaming'
      return undefined
    })

    const { useNativeGameStream } = await freshModule()
    const { defineComponent, h } = await import('vue')
    const { mount } = await import('@vue/test-utils')
    let api = null
    mount(
      defineComponent({
        setup() {
          api = useNativeGameStream()
          return () => h('div')
        },
      }),
    )

    const result = await api.start('game-guid')
    const call = invoke.mock.calls.find(([c]) => c === 'game_start')
    expect(call).toBeTruthy()
    // The request carries the media guid; the shell performs the launch, so the
    // page never talks to the lightrays endpoint itself.
    expect(call[1].request.mediaGuid).toBe('game-guid')
    expect(result.running).toBe(true)
    await api.stop()
  })

  it('refuses in a browser instead of silently using the web player', async () => {
    // A silent fallback would ship the browser path the plan excludes. The
    // composable says so instead.
    desktop = false
    const { useNativeGameStream } = await freshModule()
    const { defineComponent, h } = await import('vue')
    const { mount } = await import('@vue/test-utils')
    let api = null
    mount(
      defineComponent({
        setup() {
          api = useNativeGameStream()
          return () => h('div')
        },
      }),
    )
    const result = await api.start('g')
    expect(result).toBeNull()
    expect(api.state.value.error).toContain('Desktop-App')
    // Nothing was invoked: the web path is not this composable's business.
    expect(invoke).not.toHaveBeenCalled()
  })

  it('asks for an even size inside the protocol limits', async () => {
    // The server rejects odd or out-of-range dimensions, so the request is
    // clamped before it goes out — a user who dragged the window small should
    // get a stream, not a validation error about a number they never chose.
    invoke.mockImplementation(async (command) => {
      if (command === 'game_start') return { kind: 'started', sessionId: 's', width: 1, height: 1 }
      return 'streaming'
    })
    const { useNativeGameStream } = await freshModule()
    const { defineComponent, h } = await import('vue')
    const { mount } = await import('@vue/test-utils')
    let api = null
    mount(
      defineComponent({
        setup() {
          api = useNativeGameStream()
          return () => h('div')
        },
      }),
    )
    await api.start('g')
    const { request } = invoke.mock.calls.find(([c]) => c === 'game_start')[1]
    expect(request.width % 2).toBe(0)
    expect(request.height % 2).toBe(0)
    expect(request.width).toBeGreaterThanOrEqual(64)
    expect(request.width).toBeLessThanOrEqual(7680)
    await api.stop()
  })

  it('is chosen by useGameLaunch on the desktop, not the web path', async () => {
    // The load-bearing assertion of this whole module. If `useGameLaunch` did
    // not branch here, everything would still *work* — the web client would play
    // the game in a `<video>` inside the webview — and no error would ever be
    // raised. That is exactly the defect this guards: the plan forbids that path,
    // and a working-but-wrong path is the hardest kind to notice.
    invoke.mockImplementation(async (command) => {
      if (command === 'game_start') {
        return { kind: 'started', sessionId: 's', width: 1920, height: 1080 }
      }
      if (command === 'game_state') return 'streaming'
      return undefined
    })

    const { useGameLaunch } = await import('src/composables/useGameLaunch')
    const { defineComponent, h } = await import('vue')
    const { mount } = await import('@vue/test-utils')
    const { ref } = await import('vue')

    const status = ref('idle')
    const loading = ref(false)
    const errorMessage = ref('')
    let api = null
    mount(
      defineComponent({
        setup() {
          api = useGameLaunch({
            uuid: ref('game-guid'),
            status,
            loading,
            errorMessage,
            t: (key) => key,
          })
          return () => h('div')
        },
      }),
    )

    await api.launchGameStream('n64')

    // The shell was asked, and the status moved to the *native* state — not to
    // `game-streaming`, which is the branch that renders `<video>`.
    expect(invoke.mock.calls.some(([c]) => c === 'game_start')).toBe(true)
    expect(status.value).toBe('native-game-streaming')
    // The web path would have needed a session id from the lightrays service;
    // it was never contacted, because the shell did the launch.
    expect(api.gameSessionId.value).toBe('')
    await api.stopNativeGameStream()
  })

  it('treats HTTP 409 as a wait, not as an error', async () => {
    // 409 means the server has started fetching the ROM. The web client shows the
    // download screen and relaunches when it lands; the desktop must do the same,
    // and it can only tell 409 apart from other refusals because the shell carries
    // the status code rather than only a sentence.
    invoke.mockImplementation(async (command) => {
      if (command === 'game_start') {
        return {
          kind: 'refused',
          problem: 'Der Server hat den Start abgelehnt (HTTP 409).',
          advice: 'ROM wird geladen.',
          status: 409,
        }
      }
      return undefined
    })

    const { useGameLaunch } = await import('src/composables/useGameLaunch')
    const { defineComponent, h, ref } = await import('vue')
    const { mount } = await import('@vue/test-utils')

    const status = ref('idle')
    const errorMessage = ref('')
    let api = null
    mount(
      defineComponent({
        setup() {
          api = useGameLaunch({
            uuid: ref('g'),
            status,
            loading: ref(false),
            errorMessage,
            t: (key) => key,
          })
          return () => h('div')
        },
      }),
    )

    await api.launchGameStream(null)
    expect(status.value).toBe('downloading')
    expect(errorMessage.value).toBe('')
  })

  it('shows a real refusal as an error', async () => {
    invoke.mockImplementation(async (command) => {
      if (command === 'game_start') {
        return { kind: 'refused', problem: 'Kein Server.', advice: null, status: 503 }
      }
      return undefined
    })
    const { useGameLaunch } = await import('src/composables/useGameLaunch')
    const { defineComponent, h, ref } = await import('vue')
    const { mount } = await import('@vue/test-utils')
    const status = ref('idle')
    const errorMessage = ref('')
    let api = null
    mount(
      defineComponent({
        setup() {
          api = useGameLaunch({
            uuid: ref('g'),
            status,
            loading: ref(false),
            errorMessage,
            t: (key) => key,
          })
          return () => h('div')
        },
      }),
    )
    await api.launchGameStream(null)
    expect(status.value).toBe('error')
    expect(errorMessage.value).toContain('Kein Server')
  })

  it('stops by telling the shell, which releases the pipeline', async () => {
    invoke.mockImplementation(async (command) => {
      if (command === 'game_start') return { kind: 'started', sessionId: 's', width: 64, height: 64 }
      if (command === 'game_stop') return true
      return 'streaming'
    })
    const { useNativeGameStream } = await freshModule()
    const { defineComponent, h } = await import('vue')
    const { mount } = await import('@vue/test-utils')
    let api = null
    mount(
      defineComponent({
        setup() {
          api = useNativeGameStream()
          return () => h('div')
        },
      }),
    )
    await api.start('g')
    const stopped = await api.stop()
    expect(stopped).toBe(true)
    expect(invoke).toHaveBeenCalledWith('game_stop')
    expect(api.state.value.running).toBe(false)
  })
})
