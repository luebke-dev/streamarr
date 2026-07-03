<template>
  <q-card flat bordered class="q-mt-xl">
    <q-card-section>
      <div class="text-h6 text-white">{{ $t('mediaDetail.providerRepairs') }}</div>
    </q-card-section>
    <q-tabs v-model="providerRepairTab" dense align="left" class="text-grey-4">
      <q-tab name="subtitles" icon="mdi-subtitles" :label="$t('mediaDetail.subtitles')" />
      <q-tab
        v-if="isSong"
        name="lyrics"
        icon="mdi-text-box-music-outline"
        :label="$t('mediaDetail.lyrics')"
      />
      <q-tab name="artwork" icon="mdi-image-search" :label="$t('mediaDetail.artwork')" />
    </q-tabs>
    <q-separator dark />
    <q-tab-panels v-model="providerRepairTab" animated class="bg-transparent text-white">
      <q-tab-panel name="subtitles" class="q-gutter-md">
        <div class="row q-col-gutter-sm">
          <div class="col-12 col-sm-3">
            <q-input
              v-model="subtitleSearch.language"
              dense
              outlined
              dark
              :label="$t('mediaDetail.language')"
            />
          </div>
          <div class="col-12 col-sm-3">
            <q-input
              v-model="subtitleSearch.provider"
              dense
              outlined
              dark
              :label="$t('mediaDetail.provider')"
            />
          </div>
          <div class="col-12 col-sm-4">
            <q-input
              v-model="subtitleSearch.query"
              dense
              outlined
              dark
              :label="$t('common.search')"
            />
          </div>
          <div class="col-12 col-sm-2">
            <q-btn
              color="primary"
              icon="mdi-magnify"
              class="full-width"
              :loading="subtitleLoading"
              @click="searchSubtitles"
            />
          </div>
        </div>
        <q-list bordered separator>
          <q-item v-for="item in subtitleResults" :key="`${item.provider}:${item.provider_id}`">
            <q-item-section>
              <q-item-label>{{ item.title || item.file_name || item.provider_id }}</q-item-label>
              <q-item-label caption>
                {{ item.provider }} · {{ item.language }}
                <span v-if="item.match_score != null"> · {{ item.match_score }}</span>
              </q-item-label>
              <div class="row q-gutter-xs q-mt-xs">
                <q-chip
                  v-for="reason in item.match_reasons || []"
                  :key="reason"
                  size="sm"
                  color="blue-grey-8"
                  text-color="white"
                >
                  {{ reason }}
                </q-chip>
              </div>
            </q-item-section>
            <q-item-section side>
              <q-btn
                flat
                round
                icon="mdi-download"
                color="primary"
                :loading="subtitleDownloading === item.provider_id"
                @click="downloadSubtitle(item)"
              />
            </q-item-section>
          </q-item>
        </q-list>
      </q-tab-panel>

      <q-tab-panel v-if="isSong" name="lyrics" class="q-gutter-md">
        <div class="row q-col-gutter-sm">
          <div class="col-12 col-sm-4">
            <q-input
              v-model="lyricsSearch.provider"
              dense
              outlined
              dark
              :label="$t('mediaDetail.provider')"
            />
          </div>
          <div class="col-12 col-sm-6">
            <q-input
              v-model="lyricsSearch.query"
              dense
              outlined
              dark
              :label="$t('common.search')"
            />
          </div>
          <div class="col-12 col-sm-2">
            <q-btn
              color="primary"
              icon="mdi-magnify"
              class="full-width"
              :loading="lyricsLoading"
              @click="searchLyrics"
            />
          </div>
        </div>
        <q-list bordered separator>
          <q-item v-for="item in lyricsResults" :key="`${item.provider}:${item.provider_id}`">
            <q-item-section>
              <q-item-label>{{ item.title || mediaItem?.title }}</q-item-label>
              <q-item-label caption>{{ item.provider }} · {{ item.artist || '-' }}</q-item-label>
              <q-chip
                size="sm"
                :color="item.synced ? 'positive' : 'blue-grey-8'"
                text-color="white"
                class="q-mt-xs"
              >
                {{
                  item.synced ? $t('mediaDetail.syncedLyrics') : $t('mediaDetail.plainLyrics')
                }}
              </q-chip>
            </q-item-section>
            <q-item-section side>
              <q-btn
                flat
                round
                icon="mdi-download"
                color="primary"
                :loading="lyricsDownloading === item.provider_id"
                @click="downloadLyrics(item)"
              />
            </q-item-section>
          </q-item>
        </q-list>
      </q-tab-panel>

      <q-tab-panel name="artwork" class="q-gutter-md">
        <div class="row q-col-gutter-sm">
          <div class="col-12 col-sm-3">
            <q-select
              v-model="artworkSearch.imageType"
              dense
              outlined
              dark
              emit-value
              map-options
              :options="artworkTypeOptions"
              :label="$t('mediaDetail.imageType')"
            />
          </div>
          <div class="col-12 col-sm-3">
            <q-input
              v-model="artworkSearch.language"
              dense
              outlined
              dark
              :label="$t('mediaDetail.language')"
            />
          </div>
          <div class="col-12 col-sm-4">
            <q-input
              v-model="artworkSearch.provider"
              dense
              outlined
              dark
              :label="$t('mediaDetail.provider')"
            />
          </div>
          <div class="col-12 col-sm-2">
            <q-btn
              color="primary"
              icon="mdi-magnify"
              class="full-width"
              :loading="artworkLoading"
              @click="searchArtwork"
            />
          </div>
        </div>
        <q-file
          v-model="artworkUploadFile"
          dense
          outlined
          dark
          accept="image/*"
          :label="$t('mediaDetail.uploadArtwork')"
        >
          <template #after>
            <q-btn
              color="primary"
              icon="mdi-upload"
              :disable="!artworkUploadFile"
              :loading="artworkUploading"
              @click="uploadArtwork"
            />
          </template>
        </q-file>
        <div class="row q-col-gutter-md">
          <div
            v-for="item in artworkResults"
            :key="`${item.provider}:${item.provider_id}`"
            class="col-6 col-sm-3 col-md-2"
          >
            <q-img
              :src="item.thumbnail_url || item.url"
              :ratio="item.image_type === 'poster' ? 2 / 3 : 16 / 9"
              class="rounded-borders bg-grey-9"
            />
            <div class="text-caption text-grey-4 q-mt-xs ellipsis">
              {{ item.provider }} · {{ item.language || '-' }}
            </div>
            <q-btn
              dense
              flat
              color="primary"
              icon="mdi-check"
              :label="$t('common.select')"
              :loading="artworkSelecting === item.provider_id"
              @click="selectArtwork(item)"
            />
          </div>
        </div>
      </q-tab-panel>
    </q-tab-panels>
  </q-card>
</template>

<script setup>
import { toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMediaProviderRepair } from 'src/composables/useMediaProviderRepair'

const props = defineProps({
  mediaItem: {
    type: Object,
    default: null,
  },
  isSong: Boolean,
})

const emit = defineEmits(['media-updated'])
const { t } = useI18n()

const {
  providerRepairTab,
  subtitleSearch,
  subtitleResults,
  subtitleLoading,
  subtitleDownloading,
  lyricsSearch,
  lyricsResults,
  lyricsLoading,
  lyricsDownloading,
  artworkSearch,
  artworkResults,
  artworkLoading,
  artworkSelecting,
  artworkUploadFile,
  artworkUploading,
  artworkTypeOptions,
  searchSubtitles,
  downloadSubtitle,
  searchLyrics,
  downloadLyrics,
  searchArtwork,
  selectArtwork,
  uploadArtwork,
} = useMediaProviderRepair({
  mediaItem: toRef(props, 'mediaItem'),
  t,
  onMediaUpdated: () => emit('media-updated'),
})
</script>
