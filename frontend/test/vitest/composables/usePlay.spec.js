/**
 * Codec capability detection — which decoder is asked, and why that matters.
 *
 * On the desktop the webview does not decode anything: mpv does, in its own process
 * (ADR 001). Probing `navigator.mediaCapabilities` there answers a question about a
 * decoder that never runs, and it answers it wrongly — the webview's HDR verdict reflects
 * WebKitGTK, not the machine.
 *
 * That is the defect these tests pin down (plan task 2.10). The probe now asks the shell
 * on the desktop and keeps the browser path for the web build, where the browser really is
 * the decoder.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('boot/axios', () => ({ api: {} }))
vi.mock('src/utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))

let desktop = false
vi.mock('src/utils/desktopPlatform', () => ({
  isDesktopApp: () => desktop,
}))

// The module caches its result for the session, so each test needs a fresh copy.
async function freshModule() {
  vi.resetModules()
  return import('src/composables/usePlay')
}

describe('codec capability detection', () => {
  beforeEach(() => {
    desktop = false
    vi.clearAllMocks()
  })

  it('asks the shell on the desktop, not the browser', async () => {
    // The whole point: the browser is not the decoder here.
    desktop = true
    const { invoke } = await import('@tauri-apps/api/core')
    invoke.mockResolvedValue({
      videoCodecs: ['h264', 'h265'],
      audioCodecs: ['aac', 'ac3'],
      containers: ['mkv'],
      maxResolution: '4k',
      supportsHdr: true,
    })

    const { detectCodecCapabilities } = await freshModule()
    const caps = await detectCodecCapabilities()

    expect(invoke).toHaveBeenCalledWith('capabilities')
    expect(caps.max_resolution).toBe('4k')
    expect(caps.hdr_supported).toBe(true)
    expect(caps.source).toBe('shell')
  })

  it('does not fall back to the browser probe when the shell cannot answer', async () => {
    // Falling through would produce a confidently wrong answer — the dialog would claim
    // HDR support based on the webview while the machine's own player said otherwise.
    // An empty set is honest; the dialog shows it as unknown.
    desktop = true
    const { invoke } = await import('@tauri-apps/api/core')
    invoke.mockRejectedValue(new Error('Shell nicht erreichbar'))

    const { detectCodecCapabilities } = await freshModule()
    const caps = await detectCodecCapabilities()

    expect(caps.source).toBe('shell-unavailable')
    expect(caps.hdr_supported).toBe(false)
    expect(caps.video_codecs).toEqual([])
  })

  it('marks the browser result as coming from the browser', async () => {
    // The web build keeps its existing probe. Labelling the result makes the origin of
    // every value visible, so a bug report can tell a measurement from a guess.
    desktop = false

    const { detectCodecCapabilities } = await freshModule()
    const caps = await detectCodecCapabilities()

    expect(caps.source).toBe('browser')
  })

  it('does not touch the Tauri API on the web build', async () => {
    // The web build must not depend on a native command that does not exist there.
    desktop = false
    const { invoke } = await import('@tauri-apps/api/core')

    const { detectCodecCapabilities } = await freshModule()
    await detectCodecCapabilities()

    expect(invoke).not.toHaveBeenCalled()
  })

  it('caches the result for the session', async () => {
    // Detection runs several probes; repeating it on every dialog opening would be
    // pointless work.
    desktop = true
    const { invoke } = await import('@tauri-apps/api/core')
    invoke.mockResolvedValue({ videoCodecs: ['h264'], supportsHdr: false })

    const { detectCodecCapabilities } = await freshModule()
    await detectCodecCapabilities()
    await detectCodecCapabilities()

    expect(invoke).toHaveBeenCalledTimes(1)
  })
})
