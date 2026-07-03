import { describe, it, expect, vi } from 'vitest'
import { reactive } from 'vue'

import { useSearchFilters } from 'src/composables/useSearchFilters'

function makeRoute(query = {}) {
  const route = reactive({ query })
  const router = {
    replace: vi.fn(({ query: nextQuery }) => {
      route.query = nextQuery
    }),
  }
  return { route, router }
}

describe('useSearchFilters', () => {
  it('normalizes array filters from repeated and comma-separated query values', () => {
    const { route, router } = makeRoute({
      genre_ids: ['1', '2'],
      exclude_platform_ids: '5,6',
      exclude_containers: ['avi', 'wmv'],
      years: '1999,2001',
    })

    const { filters, onQueryChange } = useSearchFilters(route, router)
    const seen = []
    onQueryChange((query, activeFilters) => {
      seen.push({ query, activeFilters })
    })

    expect(filters.value.genre_ids).toEqual([1, 2])
    expect(filters.value.exclude_platform_ids).toEqual([5, 6])
    expect(filters.value.exclude_containers).toEqual(['avi', 'wmv'])
    expect(filters.value.years).toEqual([1999, 2001])
    expect(seen[0].activeFilters.genre_ids).toEqual([1, 2])
    expect(seen[0].activeFilters.exclude_containers).toEqual(['avi', 'wmv'])
  })

  it('writes multi-value filters back to the route query and removes empty values', () => {
    const { route, router } = makeRoute({
      q: 'space',
      genre_id: '1',
      genre_ids: ['1'],
    })
    const { filters } = useSearchFilters(route, router)

    filters.value = {
      ...filters.value,
      genre_id: null,
      genre_ids: [2, 3],
      exclude_genre_ids: [],
      exclude_content_ratings: ['R', 'NC-17'],
      years: [1999],
    }

    expect(router.replace).toHaveBeenCalledWith({
      query: {
        q: 'space',
        genre_ids: ['2', '3'],
        exclude_content_ratings: ['R', 'NC-17'],
        years: ['1999'],
      },
    })
  })
})
