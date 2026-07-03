import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('src/boot/axios', () => ({
  api: {
    get: vi.fn(),
  },
}))

vi.mock('src/utils/logger', () => ({
  logger: {
    warn: vi.fn(),
  },
}))

import { api } from 'src/boot/axios'
import { useTypedAutocomplete } from 'src/composables/useTypedAutocomplete'

describe('useTypedAutocomplete', () => {
  let router

  beforeEach(() => {
    vi.clearAllMocks()
    router = { push: vi.fn() }
  })

  it('fetches typed autocomplete suggestions', async () => {
    api.get.mockResolvedValueOnce({
      data: {
        items: [{ type: 'media', label: 'Alien', value: 'media-guid' }],
      },
    })

    const autocomplete = useTypedAutocomplete(router)
    const items = await autocomplete.fetchSuggestions('ali')

    expect(items).toHaveLength(1)
    expect(autocomplete.suggestions.value[0].label).toBe('Alien')
    expect(api.get).toHaveBeenCalledWith('/api/suggestions/autocomplete/typed', {
      params: { q: 'ali', limit: 8 },
    })
  })

  it('does not fetch for short queries', async () => {
    const autocomplete = useTypedAutocomplete(router)
    const items = await autocomplete.fetchSuggestions('a')

    expect(items).toEqual([])
    expect(api.get).not.toHaveBeenCalled()
    expect(autocomplete.suggestions.value).toEqual([])
  })

  it('ignores stale responses from earlier requests', async () => {
    let resolveFirst
    api.get
      .mockReturnValueOnce(new Promise((resolve) => (resolveFirst = resolve)))
      .mockResolvedValueOnce({
        data: {
          items: [{ type: 'media', label: 'Blade Runner', value: 'new-guid' }],
        },
      })

    const autocomplete = useTypedAutocomplete(router)
    const first = autocomplete.fetchSuggestions('bla')
    await autocomplete.fetchSuggestions('blade')
    resolveFirst({
      data: {
        items: [{ type: 'media', label: 'Black Rain', value: 'old-guid' }],
      },
    })
    await first

    expect(autocomplete.suggestions.value).toEqual([
      { type: 'media', label: 'Blade Runner', value: 'new-guid' },
    ])
  })

  it('clears pending suggestions', () => {
    const autocomplete = useTypedAutocomplete(router)
    autocomplete.suggestions.value = [{ type: 'year', label: '1982', value: '1982' }]
    autocomplete.loading.value = true

    autocomplete.clearSuggestions()

    expect(autocomplete.suggestions.value).toEqual([])
    expect(autocomplete.loading.value).toBe(false)
  })

  it('routes suggestion types to their target pages', async () => {
    const autocomplete = useTypedAutocomplete(router)

    await autocomplete.navigateSuggestion({ type: 'media', value: 'media-guid' })
    await autocomplete.navigateSuggestion({ type: 'person', value: 'person-guid' })
    await autocomplete.navigateSuggestion({ type: 'studio', value: 'Warner Bros.' })
    await autocomplete.navigateSuggestion({ type: 'year', value: '1999' })
    await autocomplete.navigateSuggestion({ type: 'genre', label: 'Sci-Fi', value: 'Sci-Fi' })

    expect(router.push).toHaveBeenNthCalledWith(1, '/media/media-guid')
    expect(router.push).toHaveBeenNthCalledWith(2, {
      path: '/search',
      query: { person_guid: 'person-guid' },
    })
    expect(router.push).toHaveBeenNthCalledWith(3, {
      path: '/search',
      query: { studio_name: 'Warner Bros.' },
    })
    expect(router.push).toHaveBeenNthCalledWith(4, {
      path: '/search',
      query: { years: '1999' },
    })
    expect(router.push).toHaveBeenNthCalledWith(5, {
      path: '/search',
      query: { q: 'Sci-Fi' },
    })
  })
})
