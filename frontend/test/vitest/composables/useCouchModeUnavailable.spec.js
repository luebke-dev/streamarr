/**
 * Couch mode when the shell cannot be reached at all.
 *
 * In its own file on purpose. The case needs a module factory that *throws*, and
 * `vi.doMock` is neither hoisted nor reliably undone: leaving it in the main
 * suite made every test after it fail with "no shell calls at all", while its own
 * assertion passed. Vitest isolates files from each other, so a separate file
 * costs nothing and removes the ordering hazard entirely.
 */

import { describe, it, expect, vi } from 'vitest'

// This factory throws when the module is imported — the same thing
// `@tauri-apps/api/core` does outside a Tauri window.
vi.mock('@tauri-apps/api/core', () => {
  throw new Error('not a tauri window')
})
vi.mock('@tauri-apps/api/event', () => {
  throw new Error('not a tauri window')
})
vi.mock('src/utils/desktopPlatform', () => ({ isDesktopApp: () => true }))

describe('useCouchMode without a shell', () => {
  it('reports no support instead of failing to start', async () => {
    const { defineComponent, h } = await import('vue')
    const { mount } = await import('@vue/test-utils')
    const { useCouchMode } = await import('src/composables/useCouchMode')

    let api = null
    const Comp = defineComponent({
      setup() {
        api = useCouchMode()
        return () => h('div')
      },
    })
    mount(Comp)
    await new Promise((resolve) => setTimeout(resolve, 0))

    // The interface stays usable; couch mode is simply unavailable. Throwing
    // here would take the whole window down over a feature the user may not
    // have wanted.
    expect(api.isSupported.value).toBe(false)
  })
})
