import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useTimeoutRegistry } from 'src/composables/useTimeoutRegistry'

function mountRegistry() {
  let registry
  const wrapper = mount(
    defineComponent({
      setup() {
        registry = useTimeoutRegistry()
        return () => null
      },
    }),
  )
  return { registry, wrapper }
}

describe('useTimeoutRegistry', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('resolves delay with true when the timer fires', async () => {
    const { registry, wrapper } = mountRegistry()

    const result = registry.delay(1000)
    await vi.advanceTimersByTimeAsync(1000)

    await expect(result).resolves.toBe(true)
    wrapper.unmount()
  })

  it('resolves delay with false when unmounted before the timer fires', async () => {
    const { registry, wrapper } = mountRegistry()

    const result = registry.delay(1000)
    wrapper.unmount()

    await expect(result).resolves.toBe(false)
  })

  it('clears scheduled callbacks on unmount', async () => {
    const { registry, wrapper } = mountRegistry()
    const callback = vi.fn()

    registry.schedule(callback, 1000)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(1000)

    expect(callback).not.toHaveBeenCalled()
  })
})
