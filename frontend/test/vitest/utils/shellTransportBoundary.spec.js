/**
 * What crosses the `invoke` boundary, asserted at that boundary.
 *
 * The other transport spec tests the module's own decisions. This one replaces `invoke`
 * and looks at what actually gets sent, because both defects found in the running app
 * were invisible in the module's own logic and obvious here:
 *
 * 1. **The body never left.** `POST /api/auth/local/login` arrived at the shell with
 *    `body=0`, and the server answered `422 {"loc":["body"],"msg":"Field required"}`. It
 *    looks like a credential problem and is a missing body.
 * 2. **The shell's own command channel went through the adapter.** `invoke` is
 *    `fetch('http://ipc.localhost/<command>')`, so replacing `globalThis.fetch`
 *    intercepted it: `invoke` called the adapter, the adapter called `invoke`, and the
 *    failure text doubled until the engine threw `RangeError: Out of memory`.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

/** Every call the adapter made to the shell, in order. */
const calls = []

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (command, args) => {
    calls.push({ command, args })
    return Promise.resolve({
      status: 200,
      status_text: 'OK',
      headers: [['content-type', 'application/json']],
      body: '{"ok":true}',
    })
  },
}))

beforeEach(() => {
  calls.length = 0
})

async function load() {
  return import('src/utils/shellTransport')
}

describe('der Body erreicht die Shell', () => {
  it('liest ihn aus einem Request-Objekt, wie axios es uebergibt', async () => {
    const { shellFetch } = await load()
    const payload = JSON.stringify({ email: 'a@b.c', password: 'geheim' })
    const request = new Request('https://streamarr.example/api/auth/local/login', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: payload,
    })

    await shellFetch(request)

    expect(calls).toHaveLength(1)
    expect(calls[0].command).toBe('api_request')
    expect(calls[0].args.method).toBe('POST')
    expect(calls[0].args.path).toBe('/api/auth/local/login')
    // The assertion the running app needed: without it the login goes out empty.
    expect(calls[0].args.body).toBe(payload)
  })

  it('nimmt den Body auch aus init', async () => {
    const { shellFetch } = await load()
    await shellFetch('/api/x', { method: 'POST', body: '{"a":1}' })
    expect(calls[0].args.body).toBe('{"a":1}')
  })

  it('schickt bei einem Request ohne Body auch keinen', async () => {
    const { shellFetch } = await load()
    await shellFetch('https://streamarr.example/api/auth/status')
    expect(calls[0].args.body).toBeUndefined()
  })

  it('wandelt ein Objekt in JSON, statt es zu verlieren', async () => {
    // A caller that forgot to serialise must not lose the payload silently.
    const { shellFetch } = await load()
    await shellFetch('/api/x', { method: 'POST', body: { a: 1 } })
    expect(calls[0].args.body).toBe('{"a":1}')
  })

  it('haelt den ganzen Pfad samt Query', async () => {
    const { shellFetch } = await load()
    await shellFetch('https://streamarr.example/api/play/abc?client_max_resolution=4k', {
      method: 'POST',
    })
    expect(calls[0].args.path).toBe('/api/play/abc?client_max_resolution=4k')
  })
})

describe('Tauris Kommandokanal geht nicht durch den Adapter', () => {
  it('ruft fuer einen IPC-Aufruf kein invoke', async () => {
    const { shellFetch } = await load()
    // The native `fetch` is what the module captured, so this really leaves the adapter
    // — and in this environment it fails, which is fine: asserted is that the adapter
    // did **not** turn it into an `invoke`, because that is the recursion.
    await shellFetch('http://ipc.localhost/api_request', { method: 'POST' }).catch(() => {})
    expect(calls).toHaveLength(0)
  })
})
