<template>
  <div class="book-reader">
    <!-- EPUB Reader -->
    <div v-if="format === 'epub'" ref="epubContainer" class="epub-container" />

    <!-- PDF Viewer -->
    <iframe v-else-if="format === 'pdf'" :src="fileUrl" class="pdf-viewer" frameborder="0" />

    <!-- Unsupported format -->
    <div v-else class="flex flex-center column q-pa-xl">
      <q-icon name="mdi-book-alert" size="80px" color="grey-6" />
      <div class="text-h6 text-grey-4 q-mt-md">Format nicht unterstuetzt</div>
      <div class="text-body2 text-grey-6 q-mt-sm">{{ fileName }}</div>
      <q-btn
        class="q-mt-lg"
        color="primary"
        :href="fileUrl"
        target="_blank"
        rel="noopener noreferrer"
        icon="mdi-download"
        :label="$t('common.download')"
      />
    </div>

    <!-- Navigation overlay for EPUB -->
    <div v-if="format === 'epub'" class="epub-nav">
      <q-btn flat round icon="mdi-chevron-left" color="white" size="lg" @click="prevPage" />
      <div class="progress-info">
        <span class="text-grey-4 text-caption">{{ currentLocation }}</span>
        <q-linear-progress
          v-if="progressPct > 0"
          :value="progressPct / 100"
          color="primary"
          track-color="grey-8"
          size="3px"
          class="progress-bar"
        />
      </div>
      <q-btn flat round icon="mdi-chevron-right" color="white" size="lg" @click="nextPage" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

const props = defineProps({
  fileUrl: { type: String, required: true },
  format: { type: String, required: true },
  fileName: { type: String, default: '' },
  mediaGuid: { type: String, default: null },
})

const epubContainer = ref(null)
const currentLocation = ref('')
const progressPct = ref(0)
let rendition = null
let book = null
let saveTimer = null
let lastCfi = null

async function loadSavedProgress() {
  if (!props.mediaGuid) return null
  try {
    const resp = await api.get('/api/viewing-history', {
      params: { content_type: 'book', content_guid: props.mediaGuid },
    })
    const items = resp.data?.items || resp.data || []
    if (items.length > 0) {
      return items[0]
    }
  } catch (e) {
    // No saved progress, or progress endpoint unavailable; start fresh
    logger.debug('No saved reading progress', e)
  }
  return null
}

let saveProgressTimer = null

async function saveProgressNow(percentage, cfi) {
  if (!props.mediaGuid || !percentage) return
  try {
    await api.post('/api/viewing-history', {
      content_type: 'book',
      content_guid: props.mediaGuid,
      progress_seconds: 0,
      duration_seconds: 0,
      progress_percentage: Math.round(percentage * 100) / 100,
      extra_data: cfi ? JSON.stringify({ cfi }) : null,
    })
  } catch (err) {
    logger.warn('Failed to save reading progress:', err.message)
  }
}

function saveProgress(percentage, cfi) {
  if (saveProgressTimer) clearTimeout(saveProgressTimer)
  saveProgressTimer = setTimeout(() => {
    saveProgressTimer = null
    saveProgressNow(percentage, cfi)
  }, 750)
}

async function initEpub() {
  if (props.format !== 'epub' || !epubContainer.value) return

  try {
    const ePub = (await import('epubjs')).default
    book = ePub(props.fileUrl)
    rendition = book.renderTo(epubContainer.value, {
      width: '100%',
      height: '100%',
      spread: 'auto',
      flow: 'paginated',
    })

    rendition.themes.default({
      body: {
        color: '#e0e0e0 !important',
        background: '#1a1a1a !important',
        'font-family': 'Georgia, serif !important',
        'line-height': '1.6 !important',
      },
      'p, div, span, h1, h2, h3, h4, h5, h6, li, td, th, a': {
        color: '#e0e0e0 !important',
      },
      a: { color: '#64b5f6 !important' },
    })

    rendition.on('relocated', (location) => {
      if (location && location.start) {
        const pct = location.start.percentage || 0
        progressPct.value = Math.round(pct * 100)
        currentLocation.value = `${progressPct.value}%`
        lastCfi = location.start.cfi
      }
    })

    // Generate locations for progress tracking
    await book.ready
    await book.locations.generate(1024)

    // Restore saved position
    const saved = await loadSavedProgress()
    if (saved && saved.extra_data) {
      try {
        const extra = JSON.parse(saved.extra_data)
        if (extra.cfi) {
          await rendition.display(extra.cfi)
          logger.info('Restored reading position:', extra.cfi)
        } else {
          await rendition.display()
        }
      } catch (e) {
        // CFI restore failed (e.g. invalid cfi after book update); render from start
        logger.warn('Failed to restore reading position, opening from start', e)
        await rendition.display()
      }
    } else {
      await rendition.display()
    }

    // Auto-save progress every 30 seconds
    saveTimer = setInterval(() => {
      if (progressPct.value > 0) {
        saveProgress(progressPct.value, lastCfi)
      }
    }, 30000)

    // Keyboard navigation
    rendition.on('keyup', handleKey)
    document.removeEventListener('keyup', handleKey)
    document.addEventListener('keyup', handleKey)
  } catch (err) {
    logger.error('Failed to initialize EPUB reader:', err)
  }
}

function handleKey(e) {
  if (e.key === 'ArrowLeft') prevPage()
  else if (e.key === 'ArrowRight') nextPage()
}

function prevPage() {
  if (rendition) rendition.prev()
}

function nextPage() {
  if (rendition) rendition.next()
}

onMounted(() => {
  initEpub()
})

onUnmounted(() => {
  if (saveProgressTimer) clearTimeout(saveProgressTimer)
  if (progressPct.value > 0) {
    saveProgressNow(progressPct.value, lastCfi)
  }
  if (saveTimer) clearInterval(saveTimer)
  document.removeEventListener('keyup', handleKey)
  if (rendition) rendition.destroy()
  if (book) book.destroy()
})

watch(
  () => props.fileUrl,
  () => {
    // Save progress before switching
    if (progressPct.value > 0) {
      saveProgress(progressPct.value, lastCfi)
    }
    if (saveTimer) clearInterval(saveTimer)
    if (rendition) {
      rendition.destroy()
      rendition = null
    }
    if (book) {
      book.destroy()
      book = null
    }
    progressPct.value = 0
    lastCfi = null
    initEpub()
  },
)
</script>

<style scoped>
.book-reader {
  width: 100%;
  height: 100vh;
  background: #1a1a1a;
  position: relative;
}

.epub-container {
  width: 100%;
  height: calc(100vh - 60px);
  padding: 0 40px;
}

.pdf-viewer {
  width: 100%;
  height: 100vh;
  border: none;
}

.epub-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
  background: rgba(0, 0, 0, 0.8);
  z-index: 10;
}

.progress-info {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 80px;
}

.progress-bar {
  width: 120px;
  margin-top: 4px;
}
</style>
