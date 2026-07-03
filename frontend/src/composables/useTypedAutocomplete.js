import { ref } from 'vue'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

const ICONS = {
  media: 'mdi-play-box',
  genre: 'mdi-tag',
  person: 'mdi-account',
  studio: 'mdi-office-building',
  year: 'mdi-calendar',
}

const TYPE_LABEL_KEYS = {
  media: 'searchResultsPage.suggestionMedia',
  genre: 'searchResultsPage.suggestionGenre',
  person: 'searchResultsPage.suggestionPerson',
  studio: 'searchResultsPage.suggestionStudio',
  year: 'searchResultsPage.suggestionYear',
}

export function useTypedAutocomplete(router) {
  const suggestions = ref([])
  const loading = ref(false)
  const error = ref(null)
  let requestId = 0

  async function fetchSuggestions(query, { limit = 8 } = {}) {
    const term = query?.trim() || ''
    requestId += 1
    const currentRequest = requestId

    if (term.length < 2) {
      suggestions.value = []
      loading.value = false
      error.value = null
      return []
    }

    loading.value = true
    error.value = null

    try {
      const response = await api.get('/api/suggestions/autocomplete/typed', {
        params: { q: term, limit },
      })
      const items = response.data?.items || []
      if (currentRequest === requestId) {
        suggestions.value = items
      }
      return items
    } catch (err) {
      if (currentRequest === requestId) {
        logger.warn('[Search] Typed autocomplete failed:', err)
        suggestions.value = []
        error.value = err
      }
      return []
    } finally {
      if (currentRequest === requestId) {
        loading.value = false
      }
    }
  }

  function clearSuggestions() {
    requestId += 1
    suggestions.value = []
    loading.value = false
    error.value = null
  }

  function suggestionIcon(suggestion) {
    return ICONS[suggestion?.type] || 'mdi-magnify'
  }

  function suggestionTypeLabelKey(suggestion) {
    return TYPE_LABEL_KEYS[suggestion?.type] || 'searchResultsPage.suggestionSearch'
  }

  async function navigateSuggestion(suggestion) {
    if (!suggestion) return

    if (suggestion.type === 'media' && suggestion.value) {
      await router.push(`/media/${suggestion.value}`)
      return
    }

    if (suggestion.type === 'person' && suggestion.value) {
      await router.push({
        path: '/search',
        query: { person_guid: suggestion.value },
      })
      return
    }

    if (suggestion.type === 'studio' && suggestion.value) {
      await router.push({
        path: '/search',
        query: { studio_name: suggestion.value },
      })
      return
    }

    if (suggestion.type === 'year' && suggestion.value) {
      await router.push({
        path: '/search',
        query: { years: suggestion.value },
      })
      return
    }

    await router.push({
      path: '/search',
      query: { q: suggestion.label || suggestion.value },
    })
  }

  return {
    suggestions,
    loading,
    error,
    fetchSuggestions,
    clearSuggestions,
    navigateSuggestion,
    suggestionIcon,
    suggestionTypeLabelKey,
  }
}
