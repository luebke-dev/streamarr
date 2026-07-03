<template>
  <div v-if="pendingRequests.length > 0" class="friend-request-banners">
    <q-banner
      v-for="req in pendingRequests"
      :key="req.guid"
      class="bg-primary text-white friend-request-banner"
    >
      <template v-slot:avatar>
        <q-avatar color="white" text-color="primary" size="md">
          <img
            v-if="req.requester.picture"
            :src="req.requester.picture"
            :alt="getDisplayName(req.requester)"
          />
          <span v-else class="text-caption text-weight-bold">{{ getInitials(req.requester) }}</span>
        </q-avatar>
      </template>

      <div class="banner-content">
        <span class="text-weight-bold">{{ getDisplayName(req.requester) }}</span>
        {{ $t('friends.requestBannerText') }}
      </div>

      <template v-slot:action>
        <q-btn
          flat
          dense
          :label="$t('common.accept')"
          icon="mdi-check"
          :loading="actionLoading === req.guid + '_accept'"
          @click="acceptRequest(req)"
        />
        <q-btn
          flat
          dense
          :label="$t('common.decline')"
          icon="mdi-close"
          :loading="actionLoading === req.guid + '_reject'"
          @click="rejectRequest(req)"
        />
      </template>
    </q-banner>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { useAuthStore } from 'stores/auth'
import { useSettingsStore } from 'stores/settings'
import { api } from 'src/boot/axios'
import { logger } from 'src/utils/logger'
const { t } = useI18n()
const $q = useQuasar()
const authStore = useAuthStore()
const settingsStore = useSettingsStore()

const pendingRequests = ref([])
const actionLoading = ref(null)

const getDisplayName = (user) =>
  user.preferred_username || `${user.first_name} ${user.last_name}`.trim() || user.email

const getInitials = (user) => {
  const name = `${user.first_name || ''} ${user.last_name || ''}`.trim()
  return (
    name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2) || user.email[0].toUpperCase()
  )
}

const loadPendingRequests = async () => {
  try {
    const response = await api.get('/api/friends/pending')
    pendingRequests.value = response.data
  } catch (error) {
    logger.error('Error loading pending friend requests:', error)
  }
}

const acceptRequest = async (req) => {
  actionLoading.value = req.guid + '_accept'
  try {
    await api.post(`/api/friends/${req.guid}/accept`)
    pendingRequests.value = pendingRequests.value.filter((r) => r.guid !== req.guid)
  } catch (error) {
    logger.warn('FriendRequestBanner: accept failed', error)
    $q.notify({ type: 'negative', message: t('common.actionFailed') })
  } finally {
    actionLoading.value = null
  }
}

const rejectRequest = async (req) => {
  actionLoading.value = req.guid + '_reject'
  try {
    await api.post(`/api/friends/${req.guid}/reject`)
    pendingRequests.value = pendingRequests.value.filter((r) => r.guid !== req.guid)
  } catch (error) {
    logger.warn('FriendRequestBanner: reject failed', error)
    $q.notify({ type: 'negative', message: t('common.actionFailed') })
  } finally {
    actionLoading.value = null
  }
}

onMounted(async () => {
  if (authStore.isAuthenticated && settingsStore.isFriendsEnabled) {
    await loadPendingRequests()
  }
})
</script>

<style lang="scss" scoped>
.friend-request-banners {
  width: 100%;
}

.friend-request-banner {
  border-radius: 0;
  margin-bottom: 0;

  &:not(:last-child) {
    border-bottom: 1px solid rgba(255, 255, 255, 0.15);
  }
}

.banner-content {
  flex: 1;
}
</style>
