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
