import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useLightraysStreaming } from 'src/composables/useLightraysStreaming'

// The composable reads window globals during bindInput, so the tests drive it
// through a mounted component the same way GameStreamView does.
function mountStreaming() {
  let stream
  const wrapper = mount(
    defineComponent({
      setup() {
        stream = useLightraysStreaming()
        return () => null
      },
    }),
  )
  return { stream, wrapper }
}

// Minimal stand-ins for the pieces bindInput attaches listeners to. The
// gamepad path only needs sendInput to reach an open data channel.
function makeVideo() {
  return {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    getBoundingClientRect: () => ({ width: 640, height: 480, top: 0, left: 0 }),
    videoWidth: 640,
    videoHeight: 480,
  }
}

function makePad({ mapping = 'standard', buttons = {}, axes = [0, 0, 0, 0] } = {}) {
  const buttonList = []
  for (let i = 0; i < 17; i++) {
    buttonList.push({ pressed: Boolean(buttons[i]), value: buttons[i] ? 1 : 0 })
  }
  return {
    id: 'Test Pad',
    index: 0,
    mapping,
    connected: true,
    buttons: buttonList,
    axes,
  }
}

describe('useLightraysStreaming gamepad', () => {
  beforeEach(() => {
    vi.stubGlobal('navigator', {
      getGamepads: vi.fn(() => []),
    })
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    // happy-dom has no WebSocket; sendInput reads WebSocket.OPEN when no data
    // channel is open, so the global must exist for the no-op path to run.
    vi.stubGlobal('WebSocket', { OPEN: 1 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('exposes controller state that starts disconnected', () => {
    const { stream } = mountStreaming()
    expect(stream.controllerConnected.value).toBe(false)
    expect(stream.controllerName.value).toBe('')
  })

  it('binds and unbinds gamepad listeners', () => {
    const { stream } = mountStreaming()
    const addSpy = vi.spyOn(window, 'addEventListener')
    const removeSpy = vi.spyOn(window, 'removeEventListener')

    stream.bindInput(makeVideo(), null)
    expect(addSpy).toHaveBeenCalledWith('gamepadconnected', expect.any(Function))
    expect(addSpy).toHaveBeenCalledWith('gamepaddisconnected', expect.any(Function))

    stream.unbindInput()
    expect(removeSpy).toHaveBeenCalledWith('gamepadconnected', expect.any(Function))
    expect(removeSpy).toHaveBeenCalledWith('gamepaddisconnected', expect.any(Function))
  })

  it('starts polling when a pad connects and records its name', () => {
    const { stream } = mountStreaming()
    stream.bindInput(makeVideo(), null)

    window.dispatchEvent(
      Object.assign(new Event('gamepadconnected'), { gamepad: makePad() }),
    )

    expect(stream.controllerConnected.value).toBe(true)
    expect(stream.controllerName.value).toBe('Test Pad')
  })

  it('clears controller state when a pad disconnects', () => {
    const { stream } = mountStreaming()
    stream.bindInput(makeVideo(), null)

    window.dispatchEvent(
      Object.assign(new Event('gamepadconnected'), { gamepad: makePad() }),
    )
    expect(stream.controllerConnected.value).toBe(true)

    window.dispatchEvent(new Event('gamepaddisconnected'))
    expect(stream.controllerConnected.value).toBe(false)
    expect(stream.controllerName.value).toBe('')
  })

  it('keeps polling even before the stream is up', () => {
    // A pad connected before playback must not kill the poll loop: the loop
    // has to stay scheduled so input works once the stream starts.
    const pads = [makePad()]
    navigator.getGamepads = vi.fn(() => pads)

    const { stream } = mountStreaming()
    stream.bindInput(makeVideo(), null)

    // Each frame run by the stubbed requestAnimationFrame is captured, so the
    // test can drive the loop manually and prove it re-schedules itself.
    const raf = globalThis.requestAnimationFrame
    expect(raf).toHaveBeenCalled()
    const tick = raf.mock.calls[0][0]
    raf.mockClear()

    tick()
    expect(raf).toHaveBeenCalledTimes(1)
    expect(stream.controllerConnected.value).toBe(true)
  })

  it('unbind stops the poll loop', () => {
    const { stream } = mountStreaming()
    stream.bindInput(makeVideo(), null)
    stream.unbindInput()
    expect(globalThis.cancelAnimationFrame).toHaveBeenCalled()
  })
})
