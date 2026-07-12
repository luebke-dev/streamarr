<template>
  <div v-if="items.length > 0 || loading" class="similar-media-row q-mt-xl">
    <h5 class="text-white q-mb-md">
      {{ $t('recs.similar_to', { title: itemTitle }) }}
    </h5>

    <div v-if="loading" class="flex flex-center q-pa-md">
      <q-spinner size="30px" color="primary" />
    </div>

    <div v-else class="media-scrollable-row">
      <div v-for="item in items" :key="item.guid" class="media-item">
        <PosterCard
          :type="getItemType(item)"
          :title="item.title"
          :image-url="getPosterUrl(item)"
          :subtitle="getItemSubtitle(item)"
          :content-rating="item.content_rating"
          :min-age="item.min_age"
          @click="goToItem(item)"
          class="similar-card"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { logger } from 'src/utils/logger'
import { getSimilarMedia } from 'src/services/mediaComponentsService'
import { useMediaSection } from 'src/composables/useMediaSection'
import PosterCard from 'src/components/PosterCard.vue'

const props = defineProps({
  itemGuid: { type: String, required: true },
  itemTitle: { type: String, default: '' },
  limit: { type: Number, default: 20 },
})

const router = useRouter()
const { getItemType, getPosterUrl, getItemSubtitle } = useMediaSection()

const items = ref([])
const loading = ref(false)
let abortController = null

async function load() {
  if (!props.itemGuid) return
  if (abortController) abortController.abort()
  abortController = new AbortController()
  const signal = abortController.signal

  loading.value = true
  try {
    const data = await getSimilarMedia(props.itemGuid, props.limit, signal)
    items.value = (data || []).filter((i) => getPosterUrl(i))
  } catch (error) {
    if (error.code === 'ERR_CANCELED' || error.name === 'CanceledError') return
    logger.error('Error loading similar items:', error)
    items.value = []
  } finally {
    if (abortController?.signal === signal) {
      loading.value = false
    }
  }
}

function goToItem(item) {
  router.push({ path: `/media/${item.guid}` })
}

watch(() => props.itemGuid, load)
onMounted(load)
onUnmounted(() => {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
})
</script>

<style lang="scss" scoped>
.media-scrollable-row {
  display: flex;
  gap: 16px;
  overflow-x: auto;
  padding-bottom: 8px;
}

.media-item {
  flex: 0 0 auto;
  width: 180px;
}

.similar-card {
  height: 100%;
}
</style>
