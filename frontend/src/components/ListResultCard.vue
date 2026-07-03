<template>
  <q-card flat class="list-result-card cursor-pointer" @click="$emit('click')">
    <q-card-section>
      <div class="row items-center q-mb-xs">
        <q-icon name="mdi-format-list-bulleted" color="teal" size="sm" class="q-mr-sm" />
        <span class="text-subtitle1 text-white text-weight-medium ellipsis">{{ list.name }}</span>
      </div>
      <div v-if="list.description" class="text-caption text-grey-5 ellipsis q-mb-sm">
        {{ list.description }}
      </div>
      <div class="row items-center q-gutter-sm text-caption text-grey-6">
        <span><q-icon name="mdi-playlist-music" size="xs" /> {{ list.item_count }}</span>
        <span><q-icon name="mdi-heart" size="xs" /> {{ list.like_count }}</span>
        <q-badge
          v-if="list.list_type === 'SYSTEM'"
          color="orange"
          :label="$t('common.system')"
          size="xs"
        />
        <q-badge v-if="list.owner_name" color="grey-7" :label="list.owner_name" size="xs" />
      </div>
    </q-card-section>
  </q-card>
</template>

<script setup>
defineProps({
  list: { type: Object, required: true },
})
defineEmits(['click'])
</script>

<style lang="scss" scoped>
.list-result-card {
  border-radius: 8px;
  min-height: 132px;
  height: 100%;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  transition:
    transform 0.2s,
    box-shadow 0.2s,
    border-color 0.2s,
    background 0.2s;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    border-color: rgba(38, 166, 154, 0.45);
    background: rgba(255, 255, 255, 0.08);
  }
}
</style>
