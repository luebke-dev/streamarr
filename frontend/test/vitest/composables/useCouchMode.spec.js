/**
 * Couch / big-picture mode — the split between the UI and the shell.
 *
 * The geometry lives in the Rust core and is reached through the shell's
 * `couch_*` commands. What these tests pin down is the boundary, because that is
 * where the mistakes are:
 *
 *   * The UI reports the layout but never computes a neighbour. A UI-side
 *     "move right" would be a second implementation of `FocusGrid::move_focus`,
 *     and the two would drift.
 *   * A browser build must not evaluate any Tauri import. `@tauri-apps/api/core`
 *     throws outside a Tauri window, so a static import would break the web build
 *     rather than merely lack the feature.
 *   * The pad is read by the shell. A UI-side pad reader could only ever be
 *     driven by the window's own key events.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const invoke = vi.fn()
const listen = vi.fn(async () => () => {})

vi.mock('@tauri-apps/api/core', () => ({ invoke: (...args) => invoke(...args) }))
vi.mock('@tauri-apps/api/event', () => ({ listen: (...args) => listen(...args) }))

let desktop = true
vi.mock('src/utils/desktopPlatform', () => ({
  isDesktopApp: () => desktop,
}))

// The composable is imported per test so each gets a fresh module-level cache.
async function freshModule() {
  vi.resetModules()
  return import('src/composables/useCouchMode')
}

// The last call to a command. The composable reports an empty layout on mount —
// before any element has registered — so a test that registers elements and
// reports again must look at the *latest* call, not the first.
function lastCall(command) {
  const calls = invoke.mock.calls.filter(([name]) => name === command)
  return calls[calls.length - 1]
}

// Every mounted component, so each test can be torn down.
//
// Not mere tidiness: the composable registers a `document`-level `keydown`
// listener and removes it in `onBeforeUnmount`. A test that never unmounts
// leaves that listener alive, and a later test then sees a *previous* instance
// react to its event — which showed up as "an arrow key was swallowed while
// couch mode is off". The production code cleans up; the harness has to let it.
const mounted = []

// A minimal mount helper: the composable's lifecycle hooks need a component.
async function mountComposable(useFn) {
  const { defineComponent, h } = await import('vue')
  const { mount } = await import('@vue/test-utils')
  let api = null
  const Comp = defineComponent({
    setup() {
      api = useFn()
      return () => h('div')
    },
  })
  const wrapper = mount(Comp)
  mounted.push(wrapper)
  // `onMounted` awaits dynamic imports, which need a macrotask to resolve — a
  // microtask drain is not enough. Real timers here, so every test that wants
  // fake ones installs them *after* mounting.
  await new Promise((resolve) => setTimeout(resolve, 0))
  return { api, wrapper }
}

describe('useCouchMode', () => {
  beforeEach(() => {
    invoke.mockReset()
    listen.mockClear()
    desktop = true
    // The state the shell reports on mount, and a sane default for everything
    // else, so a test only has to override what it is about.
    invoke.mockImplementation(async (command) => {
      if (command === 'couch_state') return { focus: null, active: false, pads: 0 }
      if (command === 'couch_pads') return []
      if (command === 'couch_move') return { kind: 'none' }
      if (command === 'couch_intent') return { kind: 'none' }
      if (command === 'set_couch_layout') return { focus: null, active: false, pads: 0 }
      if (command === 'set_couch_mode') return { focus: 'a', active: true, pads: 0 }
      if (command === 'couch_pad_input') return []
      if (command === 'couch_set_fullscreen') return { kind: 'applied', fullscreen: true }
      return undefined
    })
  })

  afterEach(() => {
    // Unmount first, so the composable's own cleanup runs — that is what removes
    // the document listener.
    while (mounted.length > 0) mounted.pop().unmount()
    vi.useRealTimers()
  })

  it('does nothing at all in a browser build', async () => {
    desktop = false
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    // Not one Tauri call: the module is not even imported, so the web build
    // cannot fail on a throwing import.
    expect(invoke).not.toHaveBeenCalled()
    expect(api.isSupported.value).toBe(false)
  })

  it('asks the shell for the pad count instead of assuming one', async () => {
    invoke.mockImplementation(async (command) => {
      if (command === 'couch_state') return { focus: 'x', active: true, pads: 0 }
      if (command === 'couch_pads') return [{ id: 0, name: 'Pad', layout: 'Standard' }]
      return undefined
    })
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    // The shell's reader is the authority: a machine with no controller must be
    // able to say so rather than leaving the user pressing buttons.
    expect(api.pads.value).toBe(1)
  })

  it('measures the layout from the DOM and sends rectangles, not indices', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)

    const element = {
      isConnected: true,
      getBoundingClientRect: () => ({ left: 10, top: 20, width: 200, height: 300 }),
      dataset: {},
      scrollIntoView: vi.fn(),
      click: vi.fn(),
    }
    api.registerElement('a', element)
    await api.reportLayout()

    const call = lastCall('set_couch_layout')
    expect(call).toBeTruthy()
    const items = call[1].items
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ id: 'a', x: 10, y: 20, width: 200, height: 300 })
  })

  it('marks a decorative tile as such instead of dropping it', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)

    const element = {
      isConnected: true,
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 50 }),
      dataset: { couchDecorative: 'true' },
      scrollIntoView: vi.fn(),
      click: vi.fn(),
    }
    api.registerElement('header', element)
    await api.reportLayout()

    const items = lastCall('set_couch_layout')[1].items
    // Present for the geometry — otherwise the focus jumps across the gap it
    // leaves — but marked so the shell will not focus it.
    expect(items[0].decorative).toBe(true)
  })

  it('uses the shell for movement and never computes a neighbour itself', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    api.active.value = true

    await api.move('right')
    expect(invoke).toHaveBeenCalledWith('couch_move', { direction: 'right', steps: 1 })
    // No DOM inspection, no index arithmetic: the decision is the shell's.
    expect(invoke.mock.calls.filter(([c]) => c === 'couch_move')).toHaveLength(1)
  })

  it('applies a focus effect by scrolling the element into view', async () => {
    invoke.mockImplementation(async (command) => {
      if (command === 'couch_state') return { focus: null, active: false, pads: 0 }
      if (command === 'couch_pads') return []
      if (command === 'couch_move') return { kind: 'focus', id: 'b' }
      return undefined
    })
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    api.active.value = true

    const element = {
      isConnected: true,
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 10, height: 10 }),
      dataset: {},
      scrollIntoView: vi.fn(),
      click: vi.fn(),
    }
    api.registerElement('b', element)
    await api.move('down')

    expect(api.focusId.value).toBe('b')
    expect(element.scrollIntoView).toHaveBeenCalled()
  })

  it('applies an activate effect by clicking the element', async () => {
    invoke.mockImplementation(async (command) => {
      if (command === 'couch_state') return { focus: null, active: false, pads: 0 }
      if (command === 'couch_pads') return []
      if (command === 'couch_intent') return { kind: 'activate', id: 'c' }
      return undefined
    })
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    api.active.value = true

    const element = {
      isConnected: true,
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 10, height: 10 }),
      dataset: {},
      scrollIntoView: vi.fn(),
      click: vi.fn(),
    }
    api.registerElement('c', element)
    await api.activate()

    // The UI performs it: only it knows how "open" is expressed in a view.
    expect(element.click).toHaveBeenCalled()
  })

  it('ignores an action while couch mode is off', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    api.active.value = false
    await api.move('right')
    await api.activate()
    expect(invoke.mock.calls.filter(([c]) => c === 'couch_move')).toHaveLength(0)
  })

  it('drives the same path from an arrow key as from the controller', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    api.active.value = true

    // A real DOM event, because that is what the composable listens for. The
    // keyboard path exists so the interface is usable — and testable — without a
    // controller, and it must reach the *same* shell call rather than a second
    // implementation.
    const dispatched = new KeyboardEvent('keydown', { key: 'ArrowRight', cancelable: true })
    document.dispatchEvent(dispatched)
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(invoke).toHaveBeenCalledWith('couch_move', { direction: 'right', steps: 1 })
    expect(dispatched.defaultPrevented).toBe(true)
  })

  it('leaves the arrow keys alone while couch mode is off', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    // Explicitly off *after* mount: the previous test pressed Escape, and the
    // composable is per-instance but the mock call log is not.
    api.active.value = false
    invoke.mockClear()
    const dispatched = new KeyboardEvent('keydown', { key: 'ArrowRight', cancelable: true })
    document.dispatchEvent(dispatched)
    await new Promise((resolve) => setTimeout(resolve, 0))
    // Otherwise an arrow key would be swallowed in the ordinary interface, where
    // it scrolls a page.
    expect(dispatched.defaultPrevented).toBe(false)
    expect(invoke.mock.calls.filter(([c]) => c === 'couch_move')).toHaveLength(0)
  })

  it('closes couch mode on Escape', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    api.active.value = true
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(invoke).toHaveBeenCalledWith('set_couch_mode', { active: false })
  })

  it('asks the shell for the window to go fullscreen, not an element', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    await api.setActive(true)

    // The WebView's own Fullscreen API would make an element fill the page; the
    // couch interface needs the *window* to leave the desktop, which only the
    // shell can ask the window manager for.
    expect(invoke).toHaveBeenCalledWith('couch_set_fullscreen', { fullscreen: true })
    expect(api.fullscreen.value).toBe(true)
    await api.setActive(false)
  })

  it('gives the desktop back when couch mode is left', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    await api.setActive(true)
    invoke.mockClear()
    invoke.mockImplementation(async (command) => {
      if (command === 'couch_set_fullscreen') return { kind: 'applied', fullscreen: false }
      return undefined
    })
    await api.setActive(false)
    expect(invoke).toHaveBeenCalledWith('couch_set_fullscreen', { fullscreen: false })
    expect(api.fullscreen.value).toBe(false)
  })

  it('keeps working when the window manager refuses fullscreen', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    invoke.mockImplementation(async (command) => {
      if (command === 'couch_set_fullscreen') {
        return { kind: 'failed', reason: 'kein Fenstermanager' }
      }
      if (command === 'set_couch_mode') return { focus: null, active: true, pads: 0 }
      return undefined
    })
    await api.setActive(true)
    // The mode is still on and the pad poll still runs: a failed fullscreen
    // request must not take the feature down with it.
    expect(api.active.value).toBe(true)
    expect(api.fullscreen.value).toBe(false)
    await api.setActive(false)
  })

  it('sends a real time base with every pad poll', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    vi.useFakeTimers()
    await api.setActive(true)
    await vi.advanceTimersByTimeAsync(200)

    const polls = invoke.mock.calls.filter(([c]) => c === 'couch_pad_input')
    expect(polls.length).toBeGreaterThan(0)
    // A monotonic millisecond count, not a timestamp: the repeat rule compares
    // it against its own clock in the shell.
    for (const [, args] of polls) {
      expect(typeof args.nowMs).toBe('number')
      expect(args.nowMs).toBeGreaterThanOrEqual(0)
    }
    await api.setActive(false)
  })

  it('stops polling when couch mode is switched off', async () => {
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    vi.useFakeTimers()
    await api.setActive(true)
    await vi.advanceTimersByTimeAsync(200)
    const before = invoke.mock.calls.filter(([c]) => c === 'couch_pad_input').length

    await api.setActive(false)
    await vi.advanceTimersByTimeAsync(500)
    const after = invoke.mock.calls.filter(([c]) => c === 'couch_pad_input').length
    // Without this the shell's device queue is drained forever in the
    // background, which costs CPU and hides input meant for a game.
    expect(after).toBe(before)
  })

  it('turns a pad move intent into a real focus move', async () => {
    invoke.mockImplementation(async (command) => {
      if (command === 'couch_state') return { focus: null, active: false, pads: 1 }
      if (command === 'couch_pads') return [{ id: 0, name: 'Pad', layout: 'Standard' }]
      if (command === 'set_couch_mode') return { focus: null, active: true, pads: 1 }
      if (command === 'set_couch_layout') return { focus: null, active: true, pads: 1 }
      if (command === 'couch_pad_input') {
        return [{ action: 'move', direction: 'down', steps: 2 }]
      }
      if (command === 'couch_move') return { kind: 'focus', id: 'z' }
      return undefined
    })
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    vi.useFakeTimers()
    await api.setActive(true)
    await vi.advanceTimersByTimeAsync(120)

    // `steps: 2` must survive the trip: a late update is entitled to make up for
    // the time it missed, and collapsing it to one step would slow the focus
    // down on a slow frame rate.
    const move = invoke.mock.calls.find(([c]) => c === 'couch_move')
    expect(move).toBeTruthy()
    expect(move[1]).toEqual({ direction: 'down', steps: 2 })
    await api.setActive(false)
  })

  it('drops a pad intent that means nothing', async () => {
    invoke.mockImplementation(async (command) => {
      if (command === 'couch_state') return { focus: null, active: false, pads: 1 }
      if (command === 'couch_pads') return [{ id: 0, name: 'Pad', layout: 'Standard' }]
      if (command === 'set_couch_mode') return { focus: null, active: true, pads: 1 }
      if (command === 'set_couch_layout') return { focus: null, active: true, pads: 1 }
      // A held direction that has not repeated yet. The shell already filtered
      // the no-ops, but the UI must not move on one either.
      if (command === 'couch_pad_input') return [{ action: 'nothing' }]
      return undefined
    })
    const { useCouchMode } = await freshModule()
    const { api } = await mountComposable(useCouchMode)
    vi.useFakeTimers()
    await api.setActive(true)
    await vi.advanceTimersByTimeAsync(120)
    expect(invoke.mock.calls.filter(([c]) => c === 'couch_move')).toHaveLength(0)
    await api.setActive(false)
  })
})
