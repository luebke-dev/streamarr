<template>
  <div class="row q-gutter-sm">
    <!-- Play Button -->
    <q-btn
      v-if="showPlay"
      :color="playColor"
      :icon="playIcon"
      :label="$q.screen.gt.lg ? playLabel : ''"
      :outline="playOutline"
      :size="$q.screen.gt.lg ? 'lg' : 'md'"
      @click="$emit('play')"
      :loading="playLoading"
    >
      <q-tooltip v-if="!$q.screen.gt.lg">{{ playLabel }}</q-tooltip>
    </q-btn>

    <!-- Add to List Button -->
    <q-btn
      v-if="showAddToList"
      color="grey-7"
      icon="mdi-playlist-plus"
      :label="$q.screen.gt.lg ? addToListLabel : ''"
      outline
      :size="$q.screen.gt.lg ? 'lg' : 'md'"
      @click="$emit('addToList')"
    >
      <q-tooltip v-if="!$q.screen.gt.lg">{{ addToListLabel }}</q-tooltip>
    </q-btn>

    <!-- Favorite Button -->
    <q-btn
      v-if="showFavorite"
      :color="isFavorited ? 'red' : 'grey-7'"
      :icon="isFavorited ? 'mdi-heart' : 'mdi-heart-outline'"
      :label="$q.screen.gt.lg ? (isFavorited ? removeFromFavoritesLabel : addToFavoritesLabel) : ''"
      :outline="!isFavorited"
      :size="$q.screen.gt.lg ? 'lg' : 'md'"
      @click="$emit('toggleFavorite')"
      :loading="favoriteLoading"
    >
      <q-badge
        v-if="isFavorited && monitored"
        floating
        color="primary"
        rounded
      >
        <q-icon name="mdi-download-circle" size="14px" />
        <q-tooltip>{{ $t('favorites.monitoredTooltip') }}</q-tooltip>
      </q-badge>
      <q-tooltip>{{ isFavorited ? removeFromFavoritesLabel : addToFavoritesLabel }}</q-tooltip>
    </q-btn>

    <!-- Like Button -->
    <q-btn
      v-if="showLike"
      :color="isLiked ? 'primary' : 'grey-7'"
      :icon="isLiked ? 'mdi-thumb-up' : 'mdi-thumb-up-outline'"
      :label="$q.screen.gt.lg ? (isLiked ? unlikeLabel : likeLabel) : ''"
      :outline="!isLiked"
      :size="$q.screen.gt.lg ? 'lg' : 'md'"
      @click="$emit('toggleLike')"
      :loading="likeLoading"
    >
      <q-tooltip>{{ isLiked ? unlikeLabel : likeLabel }}</q-tooltip>
    </q-btn>

    <!-- Played Button -->
    <q-btn
      v-if="showPlayed"
      :color="isPlayed ? 'positive' : 'grey-7'"
      :icon="isPlayed ? 'mdi-check-circle' : 'mdi-check-circle-outline'"
      :label="$q.screen.gt.lg ? (isPlayed ? markUnplayedLabel : markPlayedLabel) : ''"
      :outline="!isPlayed"
      :size="$q.screen.gt.lg ? 'lg' : 'md'"
      @click="$emit('togglePlayed')"
      :loading="playedLoading"
    >
      <q-tooltip>{{ isPlayed ? markUnplayedLabel : markPlayedLabel }}</q-tooltip>
    </q-btn>

    <!-- Search Releases Button -->
    <q-btn
      v-if="showSearchReleases"
      color="grey-7"
      icon="mdi-magnify"
      :label="$q.screen.gt.lg ? searchReleasesLabel : ''"
      outline
      :size="$q.screen.gt.lg ? 'lg' : 'md'"
      @click="$emit('searchReleases')"
      :loading="searchReleasesLoading"
    >
      <q-tooltip v-if="!$q.screen.gt.lg">{{ searchReleasesLabel }}</q-tooltip>
    </q-btn>

    <!-- Instant Mix Button -->
    <q-btn
      v-if="showInstantMix"
      color="grey-7"
      icon="mdi-shuffle-variant"
      :label="$q.screen.gt.lg ? instantMixLabel : ''"
      outline
      :size="$q.screen.gt.lg ? 'lg' : 'md'"
      @click="$emit('instantMix')"
      :loading="instantMixLoading"
    >
      <q-tooltip v-if="!$q.screen.gt.lg">{{ instantMixLabel }}</q-tooltip>
    </q-btn>

    <!-- Refresh Metadata Button -->
    <q-btn
      v-if="showRefreshMetadata"
      color="grey-7"
      icon="mdi-refresh"
      :label="$q.screen.gt.lg ? refreshMetadataLabel : ''"
      outline
      :size="$q.screen.gt.lg ? 'lg' : 'md'"
      @click="$emit('refreshMetadata')"
      :loading="refreshMetadataLoading"
    >
      <q-tooltip v-if="!$q.screen.gt.lg">{{ refreshMetadataLabel }}</q-tooltip>
    </q-btn>

    <!-- Back Button -->
    <q-btn
      v-if="showBack"
      color="grey-7"
      icon="mdi-arrow-left"
      :label="$q.screen.gt.lg ? backLabel : ''"
      outline
      :size="$q.screen.gt.lg ? 'lg' : 'md'"
      @click="$emit('back')"
    >
      <q-tooltip v-if="!$q.screen.gt.lg">{{ backLabel }}</q-tooltip>
    </q-btn>

    <!-- Custom Actions Slot -->
    <slot name="custom-actions"></slot>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'

const $q = useQuasar()
const { t } = useI18n()

const props = defineProps({
  // Visibility props
  showPlay: { type: Boolean, default: true },
  showAddToList: { type: Boolean, default: true },
  showFavorite: { type: Boolean, default: true },
  showLike: { type: Boolean, default: false },
  showPlayed: { type: Boolean, default: false },
  showSearchReleases: { type: Boolean, default: false },
  showInstantMix: { type: Boolean, default: false },
  showRefreshMetadata: { type: Boolean, default: false },
  showBack: { type: Boolean, default: false },

  // State props
  isFavorited: { type: Boolean, default: false },
  monitored: { type: Boolean, default: false },
  isLiked: { type: Boolean, default: false },
  isPlayed: { type: Boolean, default: false },

  // Play button customization
  playIcon: { type: String, default: 'mdi-play' },
  playColor: { type: String, default: 'primary' },
  playOutline: { type: Boolean, default: false },

  // Loading props
  playLoading: { type: Boolean, default: false },
  favoriteLoading: { type: Boolean, default: false },
  likeLoading: { type: Boolean, default: false },
  playedLoading: { type: Boolean, default: false },
  searchReleasesLoading: { type: Boolean, default: false },
  instantMixLoading: { type: Boolean, default: false },
  refreshMetadataLoading: { type: Boolean, default: false },

  // Label props (with defaults from i18n)
  playLabel: { type: String, default: null },
  addToListLabel: { type: String, default: null },
  addToFavoritesLabel: { type: String, default: null },
  removeFromFavoritesLabel: { type: String, default: null },
  likeLabel: { type: String, default: null },
  unlikeLabel: { type: String, default: null },
  markPlayedLabel: { type: String, default: null },
  markUnplayedLabel: { type: String, default: null },
  searchReleasesLabel: { type: String, default: null },
  instantMixLabel: { type: String, default: null },
  refreshMetadataLabel: { type: String, default: null },
  backLabel: { type: String, default: null },
})

// Computed labels with defaults
const playLabel = computed(() => props.playLabel || t('common.play'))
const addToListLabel = props.addToListLabel || t('common.addToList')
const addToFavoritesLabel = props.addToFavoritesLabel || t('common.addToFavorites')
const removeFromFavoritesLabel = props.removeFromFavoritesLabel || t('common.removeFromFavorites')
const likeLabel = props.likeLabel || t('common.like')
const unlikeLabel = props.unlikeLabel || t('common.unlike')
const markPlayedLabel = props.markPlayedLabel || t('common.markPlayed')
const markUnplayedLabel = props.markUnplayedLabel || t('common.markUnplayed')
const searchReleasesLabel = props.searchReleasesLabel || t('common.searchReleases')
const instantMixLabel = props.instantMixLabel || t('common.instantMix')
const refreshMetadataLabel = props.refreshMetadataLabel || t('common.refreshMetadata')
const backLabel = props.backLabel || t('common.back')

defineEmits([
  'play',
  'addToList',
  'toggleFavorite',
  'toggleLike',
  'togglePlayed',
  'searchReleases',
  'instantMix',
  'refreshMetadata',
  'back',
])
</script>
