<template>
  <!-- Prefix mode: render each matched per-user list as its own row -->
  <div v-if="prefixMode">
    <MediaRowSection
      v-for="sub in prefixLists"
      :key="sub.guid"
      :title="getListName(sub)"
      :items="sub.items"
    >
      <template #item="{ item }">
        <PosterCard
          :type="getItemType(item)"
          :title="item.title"
          :image-url="getPosterUrl(item)"
          :subtitle="getItemSubtitle(item)"
          :rating="item.rating"
          :platforms="item.platforms"
          :friend-watchers="item.friend_watchers"
          :content-rating="item.content_rating"
          :min-age="item.min_age"
          @click="$emit('navigate-to-item', item)"
          class="genre-media-card"
        />
      </template>
    </MediaRowSection>
  </div>

  <!-- Normal single-list mode -->
  <MediaRowSection
    v-else
    :title="sectionTitle"
    :items="items"
    :loading="loading"
    :show-see-all="!!listGuid"
    @see-all="viewAll"
  >
    <template #item="{ item }">
      <PosterCard
        :type="getItemType(item)"
        :title="item.title"
        :image-url="getPosterUrl(item)"
        :subtitle="getItemSubtitle(item)"
        :rating="item.rating"
        :platforms="item.platforms"
        :friend-watchers="item.friend_watchers"
        @click="$emit('navigate-to-item', item)"
        class="genre-media-card"
      />
    </template>
  </MediaRowSection>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { cachedApiGet } from 'src/composables/useApiResponseCache'
import { logger } from 'src/utils/logger'
import { useMediaSection } from 'src/composables/useMediaSection'
import { useListTranslation } from 'src/composables/useListTranslation'
import PosterCard from 'src/components/PosterCard.vue'
import MediaRowSection from 'src/components/sections/MediaRowSection.vue'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

defineEmits(['navigate-to-item'])

const router = useRouter()
const { getItemType, getPosterUrl, getItemSubtitle } = useMediaSection()
const { getListName } = useListTranslation()

const items = ref([])
const loading = ref(false)
const listData = ref(null)
const resolvedListGuid = ref(null)
const prefixLists = ref([])
const hasRenderedItems = computed(() =>
  Object.prototype.hasOwnProperty.call(props.section, 'rendered_items'),
)
const hasRenderedPrefixLists = computed(() =>
  Object.prototype.hasOwnProperty.call(props.section, 'rendered_prefix_lists'),
)
const prefixMode = computed(() => !!props.section.config?.list_update_source_prefix)

const listGuid = computed(
  () => resolvedListGuid.value || props.section.rendered_list_guid || props.section.config?.list_guid,
)
const sectionTitle = computed(() => {
  if (listData.value) return getListName(listData.value)
  return props.section.title || 'List'
})

function viewAll() {
  if (listGuid.value) {
    router.push(`/lists/${listGuid.value}`)
  }
}

async function resolveListBySource() {
  const updateSource = props.section.config?.list_update_source
  if (!updateSource) return null
  try {
    const resp = await cachedApiGet(
      '/api/lists',
      {
        params: { owner: 'me', update_source: updateSource, per_page: 1 },
      },
      { ttlMs: 5 * 60_000, staleTtlMs: 30 * 60_000 },
    )
    const list = (resp.data.items || [])[0]
    return list ? list.guid : null
  } catch (error) {
    logger.error('Error resolving list by update_source:', error)
    return null
  }
}

async function loadFromGuid(guid) {
  // Load list metadata for name
  try {
    const listResp = await cachedApiGet(
      `/api/lists/${guid}`,
      {},
      { ttlMs: 5 * 60_000, staleTtlMs: 30 * 60_000 },
    )
    listData.value = listResp.data
  } catch (e) {
    // List metadata is cosmetic for the section header; tolerate fetch failures
    logger.warn('Failed to load list metadata', e)
  }

  const response = await cachedApiGet(
    `/api/lists/${guid}/items`,
    {
      params: { per_page: props.section.config?.max_items || 20 },
    },
    { ttlMs: 2 * 60_000, staleTtlMs: 30 * 60_000 },
  )
  const f = props.section.config?.filters || {}
  return (response.data.items || [])
    .filter((item) => item.item_data)
    .map((item) => ({
      ...item.item_data,
      guid: item.item_data.guid || item.guid,
    }))
    .filter((item) => {
      if (f.has_poster === true && !item.poster_path) return false
      if (f.has_poster === false && item.poster_path) return false
      if (f.has_description === true && !item.description) return false
      if (f.has_description === false && item.description) return false
      return getPosterUrl(item)
    })
}

async function loadPrefixLists() {
  const prefix = props.section.config?.list_update_source_prefix
  if (!prefix) return
  loading.value = true
  try {
    const resp = await cachedApiGet(
      '/api/lists',
      {
        params: { owner: 'me', update_source_prefix: prefix, per_page: 20 },
      },
      { ttlMs: 5 * 60_000, staleTtlMs: 30 * 60_000 },
    )
    const lists = resp.data.items || []
    const out = []
    const max = props.section.config?.max_rows || 3
    for (const l of lists.slice(0, max)) {
      try {
        const items = await loadFromGuid(l.guid)
        if (items.length) {
          out.push({ ...l, items })
        }
      } catch (error) {
        logger.error('Error loading prefix list items:', error)
      }
    }
    prefixLists.value = out
  } catch (error) {
    logger.error('Error loading prefix lists:', error)
    prefixLists.value = []
  } finally {
    loading.value = false
  }
}

async function loadListItems() {
  if (prefixMode.value && hasRenderedPrefixLists.value) {
    prefixLists.value = props.section.rendered_prefix_lists || []
    loading.value = false
    return
  }

  if (hasRenderedItems.value) {
    items.value = props.section.rendered_items || []
    resolvedListGuid.value = props.section.rendered_list_guid || null
    loading.value = false
    return
  }

  if (prefixMode.value) {
    await loadPrefixLists()
    return
  }

  let guid = props.section.config?.list_guid
  if (!guid && props.section.config?.list_update_source) {
    guid = await resolveListBySource()
    resolvedListGuid.value = guid
  }
  if (!guid) return

  loading.value = true
  try {
    items.value = await loadFromGuid(guid)
  } catch (error) {
    logger.error('Error loading list items:', error)
    items.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadListItems)
watch(
  () => [
    props.section.config,
    props.section.rendered_items,
    props.section.rendered_prefix_lists,
    props.section.rendered_list_guid,
  ],
  loadListItems,
  { deep: true },
)
</script>
