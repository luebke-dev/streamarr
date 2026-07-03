<template>
  <div v-if="platforms.length > 0 || loading" class="section-container">
    <div class="section-header">
      <h4 class="section-title">{{ sectionTitle }}</h4>
    </div>

    <div class="media-row">
      <div v-if="loading" class="flex flex-center q-pa-md">
        <q-spinner size="30px" color="primary" />
      </div>

      <div v-else class="media-scrollable-row">
        <div
          v-for="platform in platforms"
          :key="platform.id"
          class="platform-item"
          role="button"
          tabindex="0"
          @click="navigateToPlatform(platform)"
          @keydown.enter="navigateToPlatform(platform)"
          @keydown.space.prevent="navigateToPlatform(platform)"
        >
          <q-card flat class="platform-card bg-grey-9 cursor-pointer">
            <q-card-section class="flex flex-center column q-pa-md" style="min-height: 120px">
              <q-img
                v-if="platform.logo_url"
                :src="platform.logo_url"
                fit="contain"
                style="max-width: 80px; max-height: 60px"
                class="q-mb-sm"
              />
              <q-icon
                v-else
                name="mdi-gamepad-variant"
                size="2.5em"
                color="grey-6"
                class="q-mb-sm"
              />
              <div class="text-caption text-white text-center text-weight-medium">
                {{ platform.name }}
              </div>
            </q-card-section>
          </q-card>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

const props = defineProps({
  section: { type: Object, required: true },
  mediaType: { type: String, default: null },
})

const router = useRouter()
const { t } = useI18n()

const platforms = ref([])
const loading = ref(false)

const sectionTitle = computed(() => props.section.title || t('common.platforms', 'Platforms'))

function navigateToPlatform(platform) {
  const params = new URLSearchParams()
  params.set('platform_id', platform.id)
  params.set('media_type', 'GAMES')
  router.push(`/search?${params.toString()}`)
}

async function loadPlatforms() {
  loading.value = true
  try {
    const [platformRes, configRes] = await Promise.all([
      api.get('/api/platforms'),
      api.get('/api/libraries/games/config').catch(() => ({ data: {} })),
    ])
    const allPlatforms = platformRes.data || []
    const allowed = configRes.data?.allowed_platforms

    // Filter to allowed platforms if configured
    if (allowed && allowed.length > 0) {
      platforms.value = allPlatforms.filter((p) => allowed.includes(p.name))
    } else {
      platforms.value = allPlatforms
    }
  } catch (error) {
    logger.error('Error loading platforms:', error)
  } finally {
    loading.value = false
  }
}

onMounted(loadPlatforms)
</script>

<style lang="scss" scoped>
.platform-item {
  flex: 0 0 140px;
}

.platform-card {
  border-radius: 12px;
  transition:
    transform 0.2s,
    box-shadow 0.2s;

  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  }
}
</style>
