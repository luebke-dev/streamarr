<template>
  <div v-if="castMembers.length > 0" class="cast-section q-mt-xl">
    <h5 class="text-white q-mb-md">{{ $t('common.cast') }}</h5>
    <div class="cast-scroll-container">
      <div class="cast-grid">
        <q-card
          v-for="castEntry in castMembers"
          :key="castEntry.guid"
          flat
          class="cast-card bg-grey-9 cursor-pointer"
          @click="$router.push(`/person/${castEntry.person.guid}`)"
        >
          <q-img
            v-if="castEntry.person.profile_path"
            :src="getTmdbImageUrl(castEntry.person.profile_path, 'w185')"
            :ratio="2 / 3"
            class="cast-photo"
          >
            <template #error>
              <div class="absolute-full flex flex-center bg-grey-8">
                <q-icon name="mdi-account" size="48px" color="grey-6" />
              </div>
            </template>
          </q-img>
          <div v-else class="cast-photo-placeholder flex flex-center bg-grey-8">
            <q-icon name="mdi-account" size="48px" color="grey-6" />
          </div>
          <q-card-section class="q-pa-sm">
            <div class="text-subtitle2 text-white ellipsis">
              {{ castEntry.person.name }}
            </div>
            <div v-if="castEntry.character" class="text-caption text-grey-5 ellipsis">
              {{ castEntry.character }}
            </div>
            <div v-else-if="castEntry.job" class="text-caption text-grey-5 ellipsis">
              {{ castEntry.job }}
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { getTmdbImageUrl } from 'src/composables/useMediaFormatters'

defineProps({
  castMembers: { type: Array, default: () => [] },
})
</script>

<style lang="scss" scoped>
.cast-section {
  .cast-scroll-container {
    overflow-x: auto;
    padding-bottom: 8px;

    &::-webkit-scrollbar {
      height: 6px;
    }

    &::-webkit-scrollbar-track {
      background: rgba(255, 255, 255, 0.05);
      border-radius: 3px;
    }

    &::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.2);
      border-radius: 3px;
    }
  }

  .cast-grid {
    display: flex;
    gap: 1rem;
    min-width: min-content;
  }

  .cast-card {
    width: 130px;
    min-width: 130px;
    border-radius: 8px;
    overflow: hidden;
    transition: transform 0.2s;

    &:hover {
      transform: translateY(-4px);
    }
  }

  .cast-photo {
    border-radius: 8px 8px 0 0;
  }

  .cast-photo-placeholder {
    width: 100%;
    aspect-ratio: 2 / 3;
    border-radius: 8px 8px 0 0;
  }
}
</style>
