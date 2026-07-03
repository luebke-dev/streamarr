<template>
  <div v-if="isShow && children.length > 0" class="children-section full-width q-mt-xl">
    <h5 class="text-white q-mb-md">{{ $t('show.seasons') }}</h5>
    <div class="children-grid full-width">
      <MediaChildCard
        v-for="season in children"
        :key="season.guid"
        :child="season"
        :parent-item="mediaItem"
        kind="season"
        @view-child="$emit('view-child', $event)"
      />
    </div>
  </div>

  <div v-if="isSeason && children.length > 0" class="children-section full-width q-mt-xl">
    <h5 class="text-white q-mb-md">{{ $t('show.episodes') }}</h5>
    <div class="episodes-list">
      <EpisodeListItem
        v-for="episode in children"
        :key="episode.guid"
        :episode="episode"
        @view-child="$emit('view-child', $event)"
        @play-episode="$emit('play-episode', $event)"
      />
    </div>
  </div>

  <div v-if="isArtist && children.length > 0" class="children-section full-width q-mt-xl">
    <h5 class="text-white q-mb-md">{{ $t('artist.discography') }}</h5>
    <div class="children-grid full-width">
      <MediaChildCard
        v-for="album in children"
        :key="album.guid"
        :child="album"
        :parent-item="mediaItem"
        kind="album"
        @view-child="$emit('view-child', $event)"
      />
    </div>
  </div>

  <div v-if="isAlbum && children.length > 0" class="children-section full-width q-mt-xl">
    <h5 class="text-white q-mb-md">{{ $t('album.tracks') }}</h5>
    <template v-for="(disc, discIndex) in groupedTracks" :key="discIndex">
      <h6 v-if="isMultiDisc" class="text-grey-4 q-mt-lg q-mb-sm">Disc {{ disc.discNumber }}</h6>
      <div class="track-list">
        <template v-for="(track, trackIndex) in disc.tracks" :key="track.guid">
          <q-separator v-if="trackIndex > 0" class="bg-grey-8" />
          <div class="track-item cursor-pointer" @click="$emit('play-track', track)">
            <div class="track-number text-grey-5">
              {{ track.sequence_number || '-' }}
            </div>
            <div class="track-info">
              <div class="text-body1 text-white ellipsis">{{ track.title }}</div>
              <div v-if="track.description" class="text-caption text-grey-5 ellipsis">
                {{ track.description }}
              </div>
            </div>
            <div class="track-duration text-grey-5">
              {{ formatTrackDuration(track) || '' }}
            </div>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<script setup>
import EpisodeListItem from 'src/components/EpisodeListItem.vue'
import MediaChildCard from 'src/components/MediaChildCard.vue'

defineEmits(['view-child', 'play-episode', 'play-track'])

defineProps({
  mediaItem: {
    type: Object,
    default: null,
  },
  children: {
    type: Array,
    default: () => [],
  },
  groupedTracks: {
    type: Array,
    default: () => [],
  },
  isShow: Boolean,
  isSeason: Boolean,
  isArtist: Boolean,
  isAlbum: Boolean,
  isMultiDisc: Boolean,
  formatTrackDuration: {
    type: Function,
    required: true,
  },
})
</script>

<style lang="scss" scoped>
.children-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 1rem;
}

.episodes-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.track-list {
  display: flex;
  flex-direction: column;
}

.track-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 10px 12px;
  border-radius: 6px;
  transition: background-color 0.2s;

  &:hover {
    background-color: rgba(255, 255, 255, 0.05);
  }

  & + .track-item {
    border-top: 1px solid rgba(255, 255, 255, 0.05);
  }
}

.track-number {
  width: 32px;
  min-width: 32px;
  text-align: center;
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
}

.track-info {
  flex: 1;
  min-width: 0;
}

.track-duration {
  min-width: 48px;
  text-align: right;
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}
</style>
