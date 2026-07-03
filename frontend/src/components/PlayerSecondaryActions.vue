<template>
  <!-- Secondary actions: shown inline on desktop, in overflow menu on mobile -->
  <template v-if="!isMobile">
    <!-- Favorite Button -->
    <q-btn
      flat
      round
      dense
      :color="isFavorited ? 'red' : 'white'"
      @click="$emit('toggle-favorite')"
    >
      <q-icon :name="isFavorited ? 'mdi-heart' : 'mdi-heart-outline'" :size="iconSize" />
      <q-tooltip>{{
        isFavorited ? $t('common.removeFromFavorites') : $t('common.addToFavorites')
      }}</q-tooltip>
    </q-btn>

    <!-- Identify Song Button -->
    <q-btn
      flat
      round
      dense
      color="white"
      :loading="identifyingLoading"
      @click="$emit('identify-song')"
    >
      <q-icon name="mdi-waveform" :size="iconSize" />
      <q-tooltip>{{ $t('player.identifySong') }}</q-tooltip>
    </q-btn>

    <!-- Report Problem Button -->
    <q-btn flat round dense color="white" @click="$emit('report-problem')">
      <q-icon name="mdi-flag" :size="iconSize" />
      <q-tooltip>{{ $t('player.reportProblem') }}</q-tooltip>
    </q-btn>

    <!-- Stream Info Button (Admin only) -->
    <q-btn v-if="isSuperuser" flat round dense color="white" @click="$emit('show-info')">
      <q-icon name="mdi-information-outline" :size="iconSize" />
      <q-tooltip>{{ $t('player.streamInfo') }}</q-tooltip>
    </q-btn>
  </template>

  <!-- Mobile overflow menu for secondary actions -->
  <q-btn v-else flat round dense color="white">
    <q-icon name="mdi-dots-vertical" :size="iconSize" />
    <q-menu anchor="top right" self="bottom right" :offset="[0, 8]">
      <q-list style="min-width: 220px">
        <!-- Favorite -->
        <q-item clickable v-close-popup @click="$emit('toggle-favorite')">
          <q-item-section avatar>
            <q-icon
              :name="isFavorited ? 'mdi-heart' : 'mdi-heart-outline'"
              :color="isFavorited ? 'red' : 'white'"
            />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{
              isFavorited ? $t('common.removeFromFavorites') : $t('common.addToFavorites')
            }}</q-item-label>
          </q-item-section>
        </q-item>

        <!-- Identify Song -->
        <q-item clickable v-close-popup @click="$emit('identify-song')">
          <q-item-section avatar>
            <q-icon name="mdi-waveform" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ $t('player.identifySong') }}</q-item-label>
          </q-item-section>
        </q-item>

        <!-- Report Problem -->
        <q-item clickable v-close-popup @click="$emit('report-problem')">
          <q-item-section avatar>
            <q-icon name="mdi-flag" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ $t('player.reportProblem') }}</q-item-label>
          </q-item-section>
        </q-item>

        <!-- Stream Info (Admin only) -->
        <q-item v-if="isSuperuser" clickable v-close-popup @click="$emit('show-info')">
          <q-item-section avatar>
            <q-icon name="mdi-information-outline" />
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ $t('player.streamInfo') }}</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-menu>
  </q-btn>
</template>

<script setup>
defineProps({
  isMobile: { type: Boolean, default: false },
  isFavorited: { type: Boolean, default: false },
  identifyingLoading: { type: Boolean, default: false },
  isSuperuser: { type: Boolean, default: false },
  iconSize: { type: String, default: '24px' },
})

defineEmits(['toggle-favorite', 'identify-song', 'report-problem', 'show-info'])
</script>
