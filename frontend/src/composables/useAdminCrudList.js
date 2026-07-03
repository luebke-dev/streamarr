import { ref } from 'vue'
import { logger } from 'src/utils/logger'

/**
 * Admin list composable for q-table pages with true server-side pagination.
 *
 * The page provides a `fetchPage(params)` callback that issues the API
 * request and must return `{ items, total }`. Optionally a `deleteItem(item)`
 * callback wires up the standard "open dialog → confirm → call API → refresh"
 * flow shared by all admin CRUD list pages.
 *
 * @param {Object} options
 * @param {(params: {
 *   page: number,
 *   rowsPerPage: number,
 *   sortBy: string|null,
 *   descending: boolean,
 *   filter: string|null,
 * }) => Promise<{ items: any[], total: number }>} options.fetchPage
 * @param {(item: any) => Promise<void>} [options.deleteItem]
 * @param {Object} [options.initialPagination] q-table pagination defaults.
 * @param {string} [options.errorContext] Used for logger error prefixes.
 */
export function useAdminCrudList({
  fetchPage,
  deleteItem,
  initialPagination = {},
  errorContext = 'admin list',
} = {}) {
  const tableRef = ref()
  const rows = ref([])
  const filter = ref('')
  const loading = ref(false)

  const pagination = ref({
    sortBy: 'created_at',
    descending: true,
    page: 1,
    rowsPerPage: 10,
    rowsNumber: 0,
    ...initialPagination,
  })

  async function onRequest(props) {
    const { page, rowsPerPage, sortBy, descending } = props.pagination
    loading.value = true
    try {
      const { items, total } = await fetchPage({
        page,
        rowsPerPage,
        sortBy,
        descending,
        filter: props.filter ?? null,
      })
      rows.value = items
      pagination.value.rowsNumber = total
      pagination.value.page = page
      pagination.value.rowsPerPage = rowsPerPage
      pagination.value.sortBy = sortBy
      pagination.value.descending = descending
    } catch (error) {
      logger.error(`Error loading ${errorContext}:`, error)
    } finally {
      loading.value = false
    }
  }

  function refresh() {
    tableRef.value?.requestServerInteraction()
  }

  // ---- Delete flow ----
  const showDeleteDialog = ref(false)
  const itemToDelete = ref(null)
  const deleting = ref(false)

  function confirmDelete(item) {
    itemToDelete.value = item
    showDeleteDialog.value = true
  }

  async function performDelete() {
    if (!itemToDelete.value || !deleteItem) return
    deleting.value = true
    try {
      await deleteItem(itemToDelete.value)
      showDeleteDialog.value = false
      itemToDelete.value = null
      refresh()
    } catch (error) {
      logger.error(`Error deleting ${errorContext} item:`, error)
    } finally {
      deleting.value = false
    }
  }

  return {
    // table
    tableRef,
    rows,
    filter,
    loading,
    pagination,
    onRequest,
    refresh,
    // delete
    showDeleteDialog,
    itemToDelete,
    deleting,
    confirmDelete,
    performDelete,
  }
}
