/**
 * The shell transport's own logic.
 *
 * The transport exists because the embedded interface cannot reach the server by itself
 * (measured: the name resolves to an address that does not answer, and the IP pin that
 * fixes it belongs to the shell) and because credentials should not live in two places.
 *
 * What is tested here is the part that has decisions in it: which URL becomes which path,
 * and how a response is rebuilt. The `invoke` boundary itself is covered by the Rust
 * tests and by running the app.
 */

import { describe, it, expect } from 'vitest'
import { toBridgePath } from 'src/utils/shellTransport'

describe('toBridgePath', () => {
  it('keeps a plain path as it is', () => {
    expect(toBridgePath('/api/auth/status')).toBe('/api/auth/status')
  })

  it('keeps the query string, which carries the play capabilities', () => {
    // Spike 0.3: these parameters are query parameters, and losing them makes the
    // server transcode needlessly.
    const path = toBridgePath(
      '/api/play/abc?supported_video_codecs=h264&client_max_resolution=4k',
    )
    expect(path).toBe('/api/play/abc?supported_video_codecs=h264&client_max_resolution=4k')
  })

  it('strips the origin, because the shell decides the host', () => {
    // This is the point of the whole exercise: the page must not have to know the
    // address, and the shell applies the profile's IP pin.
    expect(toBridgePath('https://streamarr.luebke.internal/api/libraries')).toBe('/api/libraries')
    expect(toBridgePath('http://10.10.60.30:8000/api/libraries')).toBe('/api/libraries')
  })

  it('strips the origin but keeps the query string', () => {
    expect(toBridgePath('https://host:9000/api/stream/file?token=t')).toBe(
      '/api/stream/file?token=t',
    )
  })

  it('leaves a relative path without a leading slash usable', () => {
    // axios joins baseURL and url; both shapes can reach here.
    expect(toBridgePath('api/auth/status')).toBe('api/auth/status')
  })

  it('does not mangle a URL with a port and no path', () => {
    expect(toBridgePath('https://host:443')).toBe('/')
  })

  it('passes through something that is not a URL at all', () => {
    // Defensive: the transport must not throw while building a request, because a
    // thrown error would look like a network failure.
    expect(toBridgePath('')).toBe('')
    expect(toBridgePath('///')).toBe('///')
  })

  it('handles an https URL with a fragment without losing the query', () => {
    expect(toBridgePath('https://host/api/x?a=1#frag')).toBe('/api/x?a=1')
  })
})

describe('describeError', () => {
  it('does not turn an object into "[object Object]"', async () => {
    // The defect, seen in the running app: the desktop showed
    // "Die Desktop-App konnte die Anfrage nicht ausführen. [object Object]" — a
    // handled-looking message with no information in it. A Tauri `invoke` rejection
    // is an *object*, and `String(error)` flattens it to nothing.
    const { describeError } = await import('src/utils/shellTransport')
    const text = describeError({ message: 'kein Profil konfiguriert' })
    expect(text).toBe('kein Profil konfiguriert')
    expect(text).not.toContain('[object')
  })

  it('reads the field Tauri actually uses', async () => {
    const { describeError } = await import('src/utils/shellTransport')
    // A command that returned `Err(String)` rejects with the string itself.
    expect(describeError('Der Server antwortet nicht')).toBe('Der Server antwortet nicht')
    // A serialisation or permission failure carries `error`.
    expect(describeError({ error: 'api_request not allowed' })).toBe('api_request not allowed')
  })

  it('prefers a message over the other fields', async () => {
    const { describeError } = await import('src/utils/shellTransport')
    expect(describeError({ message: 'wichtig', error: 'unwichtig' })).toBe('wichtig')
  })

  it('describes an Error with its type', async () => {
    const { describeError } = await import('src/utils/shellTransport')
    // "TypeError: x is not a function" is more useful than "x is not a function":
    // the type says whether it is a bug in the call or in the data.
    expect(describeError(new TypeError('x ist keine Funktion'))).toBe(
      'TypeError: x ist keine Funktion',
    )
  })

  it('always says something, even for an unexpected shape', async () => {
    const { describeError } = await import('src/utils/shellTransport')
    // A shape nobody anticipated must still produce text: returning an empty string
    // would put the message back to being useless.
    for (const value of [null, undefined, 0, false, [], {}, { unbekannt: 1 }, () => {}]) {
      const text = describeError(value)
      expect(text.length).toBeGreaterThan(0)
      expect(text).not.toContain('[object Object]')
    }
  })

  it('does not fail on a circular structure, and still names its fields', async () => {
    const { describeError } = await import('src/utils/shellTransport')
    const circular = { name: 'x' }
    circular.self = circular
    // `JSON.stringify` throws here. My first version asserted `[object Object]` as
    // the fallback; the implementation turned out better — it names the fields, so a
    // circular error still says what it was about. The test follows the code, not
    // the other way round.
    const text = describeError(circular)
    expect(text).toBe('Fehler mit Feldern: name, self')
    expect(text).not.toContain('[object Object]')
  })
})

describe('Tauris eigener IPC-Kanal', () => {
  // The defect this exists for, at unit level: the adapter replaced `globalThis.fetch`,
  // which is also how Tauri sends every command. `invoke` called the adapter, the adapter
  // called `invoke`, and the failure text doubled until the engine threw
  // `RangeError: Out of memory`. At the shell, not one command arrived.
  it('erkennt den IPC-Kanal von Tauri', async () => {
    const { isTauriIpc } = await import('src/utils/shellTransport')
    expect(isTauriIpc('http://ipc.localhost/api_request')).toBe(true)
    expect(isTauriIpc('http://ipc.localhost')).toBe(true)
    expect(isTauriIpc('ipc://localhost/api_request')).toBe(true)
  })

  it('haelt echte Anfragen fuer keine IPC', async () => {
    const { isTauriIpc } = await import('src/utils/shellTransport')
    expect(isTauriIpc('https://streamarr.luebke.internal/api/auth/status')).toBe(false)
    expect(isTauriIpc('/api/auth/status')).toBe(false)
    // A host that merely contains the string must not be caught by the rule.
    expect(isTauriIpc('https://ipc.localhost.example.com/x')).toBe(false)
    expect(isTauriIpc(undefined)).toBe(false)
  })

  it('schluckt den IPC-Aufruf nicht in eine 503-Antwort', async () => {
    // The property that matters. The adapter's whole job is to turn a failure into a
    // 503 response with a `detail`; for its own command channel that is exactly the
    // recursion, so the call has to go past it. Asserted by behaviour rather than by a
    // mock: `shellFetch` captured the real `fetch` when the module loaded, so a spy
    // installed afterwards would prove nothing about which one it calls.
    const { shellFetch } = await import('src/utils/shellTransport')
    const outcome = await shellFetch('http://ipc.localhost/api_request', {
      method: 'POST',
    }).then(
      (response) => ({ swallowed: true, response }),
      (error) => ({ swallowed: false, error }),
    )
    expect(outcome.swallowed).toBe(false)
  })
})

describe('describeError hat eine Obergrenze', () => {
  // A guard against a runaway: an error built from an earlier error's text grows until
  // the engine refuses it. This is what that refusal looked like from the outside.
  it('kuerzt eine ueberlange Beschreibung', async () => {
    const { describeError } = await import('src/utils/shellTransport')
    const out = describeError('x'.repeat(5000))
    expect(out.length).toBeLessThan(700)
    expect(out).toContain('Zeichen')
  })

  it('laesst kurze Beschreibungen unveraendert', async () => {
    const { describeError } = await import('src/utils/shellTransport')
    expect(describeError('kaputt')).toBe('kaputt')
  })
})

describe('toBridgePath', () => {
  it('strips any origin, including the desktop scheme', () => {
    // Measured defect: `tauri://localhost/api/auth/background` went through unchanged, and the
    // shell turned `tauri://localhost` into a host name. The resulting
    // "NameResolution — failed to lookup address" points at DNS, not at this function.
    expect(toBridgePath('tauri://localhost/api/auth/background')).toBe('/api/auth/background')
    expect(toBridgePath('https://streamarr.example/api/items?page=2')).toBe('/api/items?page=2')
  })

  it('leaves a path alone', () => {
    expect(toBridgePath('/api/items?page=2')).toBe('/api/items?page=2')
  })
})
