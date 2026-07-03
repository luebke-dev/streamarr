<template>
  <div v-if="bannerStore.hasBanners" class="global-banners-container">
    <q-banner
      v-for="banner in bannerStore.visibleBanners"
      :key="banner.guid"
      :class="getBannerClass(banner.banner_type)"
      class="global-banner"
      inline-actions
    >
      <template v-slot:avatar>
        <q-icon :name="getBannerIcon(banner.banner_type)" size="md" />
      </template>

      <div class="banner-content">
        <div class="text-weight-bold q-mb-xs">{{ banner.title }}</div>
        <div class="text-body2">
          <template v-for="(part, index) in linkifyParts(banner.message)" :key="index">
            <a
              v-if="part.href"
              :href="part.href"
              target="_blank"
              rel="noopener noreferrer"
              class="banner-link"
            >
              {{ part.text }}
            </a>
            <template v-else>{{ part.text }}</template>
          </template>
        </div>
      </div>

      <template v-slot:action>
        <q-btn
          v-if="banner.dismissible"
          flat
          round
          dense
          icon="mdi-close"
          :aria-label="$t('common.close')"
          @click="dismissBanner(banner.guid)"
        />
      </template>
    </q-banner>
  </div>
</template>

<script setup>
import { onMounted, watch } from 'vue'
import { useBannerStore } from 'stores/banners'
import { useAuthStore } from 'stores/auth'
import { logger } from 'src/utils/logger'

const bannerStore = useBannerStore()
const authStore = useAuthStore()

const URL_PATTERN = /(https?:\/\/[^\s]+)/g

const linkifyParts = (text = '') => {
  const message = String(text ?? '')
  const parts = []
  let lastIndex = 0

  for (const match of message.matchAll(URL_PATTERN)) {
    const url = match[0]
    const index = match.index ?? 0

    if (index > lastIndex) {
      parts.push({ text: message.slice(lastIndex, index) })
    }

    parts.push({ text: url, href: url })
    lastIndex = index + url.length
  }

  if (lastIndex < message.length) {
    parts.push({ text: message.slice(lastIndex) })
  }

  return parts.length ? parts : [{ text: message }]
}

const getBannerClass = (type) => {
  const classes = {
    info: 'bg-info text-white',
    warning: 'bg-warning text-grey-10',
    error: 'bg-negative text-white',
    success: 'bg-positive text-white',
  }
  return classes[type] || classes.info
}

const getBannerIcon = (type) => {
  const icons = {
    info: 'mdi-information',
    warning: 'mdi-alert',
    error: 'mdi-alert-circle',
    success: 'mdi-check-circle',
  }
  return icons[type] || icons.info
}

const dismissBanner = async (bannerGuid) => {
  try {
    await bannerStore.dismissBanner(bannerGuid)
  } catch (error) {
    logger.error('Error dismissing banner:', error)
  }
}

const loadBanners = async () => {
  if (authStore.isAuthenticated) {
    await bannerStore.fetchActiveBanners()
  } else {
    bannerStore.clearBanners()
  }
}

onMounted(loadBanners)
watch(() => authStore.isAuthenticated, loadBanners)
</script>

<style lang="scss" scoped>
.global-banners-container {
  width: 100%;
}

.global-banner {
  border-radius: 0;
  margin-bottom: 0;

  &:not(:last-child) {
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  }
}

.banner-content {
  flex: 1;
}

.banner-link {
  color: inherit;
  font-weight: bold;
  text-decoration: underline;
}
</style>
