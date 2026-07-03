/**
 * Lightweight client-side pagination helper for admin pages that load all
 * rows once and then filter/sort/page locally.
 *
 * `loadAll()` is invoked at most once per "session" (or whenever the cache is
 * cleared via the returned `invalidate()` function). The returned `paginate`
 * fits the `fetchPage` signature expected by `useAdminCrudList`.
 *
 * @param {Object} options
 * @param {() => Promise<any[]>} options.loadAll Fetches the full row set.
 * @param {(row: any, filter: string) => boolean} options.matchFilter
 *   Returns true if the row matches the (lowercased) filter.
 */
export function useCachedClientPagination({ loadAll, matchFilter }) {
  let cache = []

  async function ensureLoaded() {
    if (cache.length === 0) {
      cache = await loadAll()
    }
  }

  function applyFilter(filter) {
    if (!filter) return cache
    const needle = filter.toLowerCase()
    return cache.filter((row) => matchFilter(row, needle))
  }

  function applySort(arr, sortBy, descending) {
    if (!sortBy) return arr
    return [...arr].sort((a, b) => {
      const av = a[sortBy]
      const bv = b[sortBy]
      if (av < bv) return descending ? 1 : -1
      if (av > bv) return descending ? -1 : 1
      return 0
    })
  }

  async function paginate({ page, rowsPerPage, sortBy, descending, filter }) {
    await ensureLoaded()
    const filtered = applyFilter(filter)
    const sorted = applySort(filtered, sortBy, descending)
    const start = (page - 1) * rowsPerPage
    const count = rowsPerPage === 0 ? sorted.length : rowsPerPage
    return {
      items: sorted.slice(start, start + count),
      total: filtered.length,
    }
  }

  function invalidate() {
    cache = []
  }

  return { paginate, invalidate }
}
