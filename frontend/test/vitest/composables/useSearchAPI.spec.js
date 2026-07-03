import { describe, it, expect, vi } from 'vitest'

vi.mock('boot/axios', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

import { buildSearchPayload } from 'src/composables/useSearchAPI'

describe('buildSearchPayload', () => {
  it('maps advanced browse filters to the native search request shape', () => {
    const payload = buildSearchPayload('  alien  ', {
      genre_ids: [1, '2'],
      exclude_genre_ids: ['3'],
      platform_ids: ['4'],
      exclude_platform_ids: [5],
      person_guid: 'person-guid',
      exclude_person_guid: 'other-person-guid',
      exclude_containers: ['avi', ' wmv '],
      exclude_content_ratings: ['R'],
      years: ['1979', 1986],
      exclude_years: ['1992'],
      has_poster: 'false',
      is_favorite: 'true',
    })

    expect(payload).toMatchObject({
      query: 'alien',
      genre_ids: [1, 2],
      exclude_genre_ids: [3],
      platform_ids: [4],
      exclude_platform_ids: [5],
      person_guid: 'person-guid',
      exclude_person_guid: 'other-person-guid',
      exclude_containers: ['avi', 'wmv'],
      exclude_content_ratings: ['R'],
      years: [1979, 1986],
      exclude_years: [1992],
      has_poster: false,
      is_favorite: true,
    })
  })
})
