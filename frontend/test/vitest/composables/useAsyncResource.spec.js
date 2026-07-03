import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('src/utils/logger', () => ({
  logger: { debug: vi.fn(), log: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))

import { useAsyncResource } from 'src/composables/useAsyncResource'

/** Create a promise with externally controllable resolve/reject. */
function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useAsyncResource basics', () => {
  it('sets data and toggles loading around a single refresh', async () => {
    const gate = deferred()
    const { data, loading, error, refresh } = useAsyncResource(() => gate.promise)

    const run = refresh()
    expect(loading.value).toBe(true)

    gate.resolve('result')
    await run

    expect(data.value).toBe('result')
    expect(loading.value).toBe(false)
    expect(error.value).toBeNull()
  })
})

describe('useAsyncResource out-of-order protection', () => {
  it('keeps data from the newer run when the older run resolves later', async () => {
    const gates = []
    const fetcher = vi.fn(() => {
      const gate = deferred()
      gates.push(gate)
      return gate.promise
    })
    const { data, loading, refresh } = useAsyncResource(fetcher)

    const oldRun = refresh()
    const newRun = refresh()

    // Newer run finishes first.
    gates[1].resolve('new-data')
    await newRun
    expect(data.value).toBe('new-data')
    expect(loading.value).toBe(false)

    // Older run resolves afterwards — must not overwrite the newer result.
    gates[0].resolve('stale-data')
    await oldRun
    expect(data.value).toBe('new-data')
    expect(loading.value).toBe(false)
  })

  it('keeps loading true until the youngest run finishes when the older run completes first', async () => {
    const gates = []
    const fetcher = vi.fn(() => {
      const gate = deferred()
      gates.push(gate)
      return gate.promise
    })
    const { data, loading, refresh } = useAsyncResource(fetcher)

    const oldRun = refresh()
    const newRun = refresh()

    // Older run finishes while the newer one is still in flight.
    gates[0].resolve('stale-data')
    await oldRun
    expect(data.value).toBeNull()
    expect(loading.value).toBe(true)

    // Only the youngest run ends the loading state and sets data.
    gates[1].resolve('new-data')
    await newRun
    expect(data.value).toBe('new-data')
    expect(loading.value).toBe(false)
  })

  it('ignores an error from a superseded run', async () => {
    const gates = []
    const fetcher = vi.fn(() => {
      const gate = deferred()
      gates.push(gate)
      return gate.promise
    })
    const { data, loading, error, refresh } = useAsyncResource(fetcher)

    const oldRun = refresh()
    const newRun = refresh()

    gates[1].resolve('new-data')
    await newRun

    // The stale run fails afterwards — error/data/loading must stay untouched.
    gates[0].reject(new Error('stale failure'))
    await oldRun

    expect(error.value).toBeNull()
    expect(data.value).toBe('new-data')
    expect(loading.value).toBe(false)
  })

  it('records the error of the latest run', async () => {
    const gate = deferred()
    const { data, loading, error, refresh } = useAsyncResource(() => gate.promise)

    const run = refresh()
    gate.reject(new Error('latest failure'))
    await run

    expect(error.value).toBeInstanceOf(Error)
    expect(error.value.message).toBe('latest failure')
    expect(data.value).toBeNull()
    expect(loading.value).toBe(false)
  })
})
