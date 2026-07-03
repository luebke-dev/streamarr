<template>
  <section class="results-section">
    <div class="results-section__header">
      <div class="results-section__title">
        <q-icon :name="icon" :color="color" size="1.35rem" />
        <span>{{ label }}</span>
      </div>
      <q-badge :color="color" :label="items.length" />
    </div>
    <div class="results-grid">
      <div v-for="(item, idx) in items" :key="itemKey(item, idx)" class="result-item">
        <slot name="item" :item="item">
          <PosterCard
            :type="getCardType(item)"
            :title="item.title"
            :image-url="getPosterUrl(item)"
            :subtitle="getSubtitle(item)"
            :rating="item.rating"
            :platforms="item.platforms"
            @click="$emit('select', item)"
          />
        </slot>
      </div>
    </div>
  </section>
</template>

<script setup>
import PosterCard from 'components/PosterCard.vue'
import { useMediaTypeMapping } from 'src/composables/useMediaTypeMapping'

const props = defineProps({
  icon: { type: String, required: true },
  color: { type: String, required: true },
  label: { type: String, required: true },
  items: { type: Array, required: true },
  /**
   * Optional key extractor. Defaults to the media-result key resolver.
   */
  keyFn: { type: Function, default: null },
})
defineEmits(['select'])

const { getCardType, getPosterUrl, getResultKey, getSubtitle } = useMediaTypeMapping()

function itemKey(item, idx) {
  if (props.keyFn) return props.keyFn(item, idx)
  return getResultKey(item) ?? idx
}
</script>

<style lang="scss" scoped>
.results-section {
  margin-bottom: 24px;
  padding-bottom: 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.results-section__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.results-section__title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 1.05rem;
  font-weight: 700;

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: 16px;
  align-items: start;
}

.result-item {
  position: relative;
  min-width: 0;
}

@media (max-width: 768px) {
  .results-grid {
    gap: 12px;
    grid-template-columns: repeat(auto-fill, minmax(136px, 1fr));
  }
}

@media (max-width: 480px) {
  .results-grid {
    gap: 10px;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
