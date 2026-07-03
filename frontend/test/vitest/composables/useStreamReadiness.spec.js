import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('boot/axios', () => ({
  api: {
    get: vi.fn(),
  },
}))

import { api } from 'boot/axios'
import { useStreamReadiness } from 'src/composables/useStreamReadiness'

function mountReadiness(options) {
  let readiness
  const wrapper = mount(
    defineComponent({
      setup() {
        readiness = useStreamReadiness(options)
        return () => null
      },
    }),
  )
  return { readiness, wrapper }
}

describe('useStreamReadiness', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns true after the playlist and first segment are servable', async () => {
    const { readiness, wrapper } = mountReadiness()
    api.get.mockResolvedValueOnce({ status: 200 }).mockResolvedValueOnce({ status: 200 })

    await expect(readiness.waitForHlsStreamReady('sess-1', 'token-1')).resolves.toBe(true)

    expect(api.get).toHaveBeenNthCalledWith(
      1,
      '/api/stream/sess-1/playlist.m3u8',
      expect.objectContaining({ params: { token: 'token-1' } }),
    )
    expect(api.get).toHaveBeenNthCalledWith(
      2,
      '/api/stream/sess-1/sess-1_000.ts',
      expect.objectContaining({ params: { token: 'token-1' } }),
    )
    wrapper.unmount()
  })

  it('returns false after all polling attempts are exhausted', async () => {
    const { readiness, wrapper } = mountReadiness({ maxAttempts: 2, pollIntervalMs: 100 })
    api.get.mockResolvedValue({ status: 404 })

    const result = readiness.waitForHlsStreamReady('sess-2', 'token-2')
    await vi.advanceTimersByTimeAsync(200)

    await expect(result).resolves.toBe(false)
    expect(api.get).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('returns false when unmounted while waiting for the next poll', async () => {
    const { readiness, wrapper } = mountReadiness({ maxAttempts: 3, pollIntervalMs: 100 })
    api.get.mockResolvedValue({ status: 404 })

    const result = readiness.waitForHlsStreamReady('sess-3', 'token-3')
    await vi.advanceTimersByTimeAsync(50)
    wrapper.unmount()

    await expect(result).resolves.toBe(false)
  })
})
