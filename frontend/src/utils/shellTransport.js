/**
 * The desktop shell's HTTP transport for the embedded interface.
 *
 * # Why this exists
 *
 * The interface is a browser application: it builds URLs and calls the API with axios.
 * In the desktop app that cannot work on its own, for two measured reasons.
 *
 * First, **the webview cannot reach the server.** `streamarr.luebke.internal` resolves
 * to an address that does not answer, so every request hung for 20 seconds (measured).
 * The app copes with an IP pin, which only the shell holds; entering the IP directly
 * instead fails TLS, because the certificate covers `*.luebke.internal` and nothing else
 * (also measured). So the page has no way to reach the server by itself.
 *
 * Second, **credentials would live in two places.** The page keeps tokens in
 * `localStorage`, where any script on the page can read them; the shell keeps them in the
 * OS keyring. Whichever wins, the other is a stale copy — and a stale refresh token is
 * worse than none, because the server rotates them on every use and rejects a replay.
 *
 * So on desktop every API call is executed by the shell, which owns the address, the pin
 * and the credentials. The rest of the application is unchanged: it still calls
 * `fetch`, and this adapter answers. On the web nothing here is used at all, so the
 * existing browser behaviour and the existing tests are untouched.
 */

import { isDesktopApp } from 'src/utils/desktopPlatform'
import { invoke } from '@tauri-apps/api/core'
import { logger } from 'src/utils/logger'

/**
 * Turns a request URL into a path for the shell.
 *
 * The origin is dropped on purpose: the shell decides which host to talk to, using the
 * active profile and its IP pin. A URL that points somewhere else entirely therefore
 * cannot redirect the app's credentials — the shell refuses a foreign host.
 */
export function toBridgePath(url) {
  // A request to a different origin is a bug in this adapter, not a feature: the shell
  // always talks to the configured server.
  if (/^https?:\/\//i.test(url)) {
    try {
      const parsed = new URL(url)
      return `${parsed.pathname}${parsed.search}`
    } catch {
      return url
    }
  }
  return url
}

/** Base64 to bytes, for binary bodies. */
function base64ToBytes(base64) {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

/**
 * Runs one request through the shell.
 *
 * Returns a `Response`, so axios (and anything else expecting a fetch response) needs no
 * knowledge of the shell. A transport failure comes back as a **response with status 503
 * and a JSON `detail`**, not as a thrown error: the shell's diagnosis is meant to be
 * shown to the user, and the application's existing error handling already renders a
 * `detail` from a response.
 */
async function shellFetch(input, init = {}) {
  const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase()

  // Headers, from both the Request and the init, since either may carry them.
  const headers = []
  const collect = (source) => {
    if (!source) return
    if (source instanceof Headers) {
      source.forEach((value, key) => headers.push([key, value]))
    } else if (Array.isArray(source)) {
      source.forEach(([key, value]) => headers.push([key, String(value)]))
    } else {
      Object.entries(source).forEach(([key, value]) => headers.push([key, String(value)]))
    }
  }
  if (input instanceof Request) collect(input.headers)
  collect(init.headers)

  // A body may arrive as a string, a URLSearchParams or something else; the shell takes
  // text, so it is normalised here rather than in Rust.
  let body
  if (typeof init.body === 'string') {
    body = init.body
  } else if (init.body instanceof URLSearchParams) {
    body = init.body.toString()
  }

  try {
    // The shell answers with { status, status_text, headers, body|body_base64 }.
    // See frontend/src-tauri/src/commands/bridge.rs.
    const response = await invoke('api_request', {
      method,
      path: toBridgePath(rawUrl),
      headers,
      body,
      timeoutMs: null,
    })

    const responseHeaders = new Headers()
    for (const [key, value] of response.headers || []) {
      // Content-Length and the encoding headers describe the shell's own transfer and
      // would be wrong once the body is rebuilt here — a wrong `content-encoding` makes
      // the browser try to decompress plain JSON.
      const lowered = key.toLowerCase()
      if (lowered === 'content-length' || lowered === 'content-encoding' ||
          lowered === 'transfer-encoding' || lowered === 'content-security-policy') {
        continue
      }
      try {
        responseHeaders.append(key, value)
      } catch {
        // A header name the browser rejects is not worth failing a request over.
      }
    }

    let responseBody = null
    if (response.body_base64 !== undefined) {
      responseBody = base64ToBytes(response.body_base64)
    } else if (response.body !== undefined) {
      responseBody = response.body
    }

    return new Response(responseBody, {
      status: response.status,
      statusText: response.status_text,
      headers: responseHeaders,
    })
  } catch (error) {
    // The command itself failed — no profile, or the shell could not be reached. Unlike
    // a server error this is not the server's fault, so it is reported as such.
    logger.error('Shell-Transport fehlgeschlagen:', error)
    return new Response(
      JSON.stringify({
        detail: 'Die Desktop-App konnte die Anfrage nicht ausführen. ' + describeError(error),
      }),
      {
        status: 503,
        statusText: 'Service Unavailable',
        headers: { 'content-type': 'application/json' },
      },
    )
  }
}

/**
 * A readable description of a thrown value.
 *
 * `String(error)` is not good enough here and the failure was visible in the running
 * app: a Tauri `invoke` rejection is an **object**, so `String(error)` produced the
 * literal text `[object Object]`. The user saw
 * "Die Desktop-App konnte die Anfrage nicht ausführen. [object Object]" — a message
 * with no information in it, which is worse than no message, because it looks like a
 * handled error.
 *
 * The order matters. Tauri rejects with a string for a command that returned `Err`, and
 * with an object carrying `message`/`error` for a serialisation or permission failure.
 * A JSON dump is the last resort: it always says *something*, even for a shape nobody
 * anticipated.
 */
export function describeError(error) {
  if (error === null || error === undefined) return 'Unbekannter Fehler'
  if (typeof error === 'string') return error
  if (typeof error === 'number' || typeof error === 'boolean') return String(error)
  if (error instanceof Error) {
    // `name` first: "TypeError: x is not a function" is more useful than the message
    // alone, and the stack's first line already carries it.
    return error.message ? `${error.name}: ${error.message}` : error.name
  }
  if (typeof error === 'object') {
    for (const key of ['message', 'error', 'detail', 'reason']) {
      const value = error[key]
      if (typeof value === 'string' && value) return value
    }
    try {
      const text = JSON.stringify(error)
      // `JSON.stringify` returns `undefined` for a function, and `"{}"` for an object
      // with no enumerable properties; both are unhelpful, so they fall through.
      if (text && text !== '{}') return text
    } catch {
      // A circular structure is not worth failing over.
    }
  }
  // The last resort, and it must not be `Object.prototype.toString`: for a plain
  // object that returns `"[object Object]"`, which is the exact text this function
  // exists to eliminate. My own test caught the fallback doing it anyway — for an
  // empty object and an empty array, both of which stringify to `"{}"`/`"[]"` and
  // were therefore skipped above.
  const entries = Object.keys(error)
  if (entries.length > 0) return `Fehler mit Feldern: ${entries.join(', ')}`
  return Array.isArray(error) ? 'Leerer Fehler (Liste)' : 'Leerer Fehler (Objekt)'
}

/** Installs the adapter, or does nothing outside the desktop app. */
export function installShellTransport() {
  if (!isDesktopApp()) return
  const target = globalThis
  if (target.fetch === shellFetch) return
  target.fetch = shellFetch
  logger.info('Desktop: API-Aufrufe laufen über die Shell (Adresse, Pin und Token dort).')
}

export { shellFetch }
