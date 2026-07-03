<template>
  <div v-if="visible" class="section-container">
    <div class="section-header">
      <h4 class="section-title">{{ title }}</h4>
      <q-btn
        v-if="showSeeAll"
        flat
        dense
        color="grey-4"
        icon="mdi-arrow-right"
        :label="$t('common.seeAll', 'See all')"
        class="see-all-btn"
        @click="$emit('see-all')"
      />
    </div>

    <div class="media-row">
      <div v-if="loading" class="flex flex-center q-pa-md">
        <q-spinner size="30px" color="primary" />
      </div>

      <div v-else-if="items.length === 0 && emptyText" class="media-row-placeholder">
        <div class="placeholder-content">
          <q-icon :name="emptyIcon" size="2em" color="grey-5" />
          <p class="text-grey-5 q-mt-sm">{{ emptyText }}</p>
        </div>
      </div>

      <div v-else class="media-scrollable-row">
        <div v-for="item in items" :key="item.guid || item.id" class="media-item">
          <slot name="item" :item="item">
            <PosterCard
              :type="getItemType(item)"
              :title="item.title"
              :image-url="getPosterUrl(item)"
              :subtitle="getItemSubtitle(item)"
              :rating="item.rating"
              :platforms="item.platforms"
              :content-rating="item.content_rating"
              :min-age="item.min_age"
              class="genre-media-card"
              @click="$emit('item-click', item)"
            />
          </slot>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import PosterCard from 'src/components/PosterCard.vue'
import { useMediaSection } from 'src/composables/useMediaSection'

const props = defineProps({
  title: { type: String, required: true },
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  showSeeAll: { type: Boolean, default: false },
  emptyText: { type: String, default: null },
  emptyIcon: { type: String, default: 'mdi-inbox-outline' },
})

defineEmits(['see-all', 'item-click'])

const { getItemType, getPosterUrl, getItemSubtitle } = useMediaSection()

// Hide entirely when there is no content and no placeholder configured
const visible = computed(() => props.loading || props.items.length > 0 || !!props.emptyText)
</script>
