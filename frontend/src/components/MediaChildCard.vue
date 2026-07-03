<template>
  <q-card class="season-card cursor-pointer" @click="$emit('view-child', child)">
    <q-img
      :src="getPosterUrl(child) || getPosterUrl(parentItem)"
      :ratio="isAlbum ? 1 : 2 / 3"
      :class="isAlbum ? 'album-poster' : 'season-poster'"
    >
      <template #error>
        <div class="absolute-full flex flex-center bg-grey-9">
          <q-icon :name="fallbackIcon" size="48px" color="grey-6" />
        </div>
      </template>
    </q-img>
    <q-card-section>
      <div class="text-subtitle2 text-white" :class="{ ellipsis: isAlbum }">{{ child.title }}</div>
      <div v-if="isAlbum" class="text-caption text-grey-5">
        {{ formatYear(child.release_date) }}
      </div>
      <div v-else-if="child.children_count > 0" class="text-caption text-grey-5">
        {{ child.children_count }} {{ $t('show.episodes') }}
      </div>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { computed } from 'vue'
import { useMediaHelpers } from 'src/composables/useMediaHelpers'

const props = defineProps({
  child: { type: Object, required: true },
  parentItem: { type: Object, default: null },
  kind: { type: String, default: 'season' }, // 'season' | 'album'
})

defineEmits(['view-child'])

const { getPosterUrl, formatYear } = useMediaHelpers()

const isAlbum = computed(() => props.kind === 'album')
const fallbackIcon = computed(() => (isAlbum.value ? 'mdi-album' : 'mdi-television'))
</script>
