<template>
  <q-page class="q-pa-md">
    <!-- Back Button -->
    <q-btn
      flat
      icon="mdi-arrow-left"
      :label="$t('adminUserPage.backToUsers')"
      class="q-mb-md"
      @click="$router.push('/admin/users')"
    />

    <!-- Loading State -->
    <div v-if="loading" class="text-center q-pa-xl">
      <q-spinner size="50px" color="primary" />
      <div class="q-mt-md text-grey">{{ $t('adminUserPage.loading') }}</div>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="text-center q-pa-xl">
      <q-icon name="mdi-alert-circle" size="50px" color="negative" />
      <div class="q-mt-md text-negative">{{ error }}</div>
      <q-btn
        color="primary"
        :label="$t('adminUserPage.goBack')"
        class="q-mt-md"
        @click="$router.back()"
      />
    </div>

    <!-- User Details -->
    <div v-else-if="user" class="row q-col-gutter-md">
      <!-- User Header Card -->
      <div class="col-12">
        <UserHeaderCard :user="user" @edit="(guid) => $router.push(`/admin/users/${guid}/edit`)" />
      </div>

      <!-- Account Information -->
      <div class="col-12 col-md-6">
        <q-card flat bordered class="full-height">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-account" class="q-mr-sm" color="primary" />
              {{ $t('adminUserPage.accountInfo') }}
            </div>
            <q-list dense>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.userId') }}</q-item-label>
                  <q-item-label class="text-weight-medium text-mono">{{ user.guid }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-btn flat dense icon="mdi-content-copy" @click="copyToClipboard(user.guid)" />
                </q-item-section>
              </q-item>
              <q-item v-if="user.preferred_username">
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.username') }}</q-item-label>
                  <q-item-label class="text-weight-medium">{{
                    user.preferred_username
                  }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item v-if="user.groups">
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.groups') }}</q-item-label>
                  <q-item-label class="text-weight-medium">{{ user.groups }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item v-if="user.locale">
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.locale') }}</q-item-label>
                  <q-item-label class="text-weight-medium">{{ user.locale }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card-section>
        </q-card>
      </div>

      <!-- Authentication Details -->
      <div class="col-12 col-md-6">
        <q-card flat bordered class="full-height">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-shield-account" class="q-mr-sm" color="secondary" />
              {{ $t('adminUserPage.authentication') }}
            </div>
            <q-list dense>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.authMethod') }}</q-item-label>
                  <q-item-label class="text-weight-medium">
                    {{
                      user.oidc_provider
                        ? `OIDC (${user.oidc_provider})`
                        : $t('adminUserPage.authMethodLocal')
                    }}
                  </q-item-label>
                </q-item-section>
              </q-item>
              <q-item v-if="user.oidc_sub">
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.oidcSubject') }}</q-item-label>
                  <q-item-label class="text-weight-medium text-mono">{{
                    user.oidc_sub
                  }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.lastLogin') }}</q-item-label>
                  <q-item-label class="text-weight-medium">
                    {{ user.last_login ? formatDate(user.last_login) : $t('adminUserPage.never') }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card-section>
        </q-card>
      </div>

      <!-- Timestamps -->
      <div class="col-12 col-md-6">
        <q-card flat bordered class="full-height">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-clock-outline" class="q-mr-sm" color="positive" />
              {{ $t('adminUserPage.timestamps') }}
            </div>
            <q-list dense>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.createdAt') }}</q-item-label>
                  <q-item-label class="text-weight-medium">{{
                    formatDate(user.created_at)
                  }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.updatedAt') }}</q-item-label>
                  <q-item-label class="text-weight-medium">{{
                    formatDate(user.updated_at)
                  }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card-section>
        </q-card>
      </div>

      <!-- Language Preferences -->
      <div class="col-12 col-md-6">
        <q-card flat bordered class="full-height">
          <q-card-section>
            <div class="text-h6 q-mb-md">
              <q-icon name="mdi-translate" class="q-mr-sm" color="warning" />
              {{ $t('adminUserPage.languagePreferences') }}
            </div>
            <q-list dense>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.uiLanguage') }}</q-item-label>
                  <q-item-label class="text-weight-medium">{{
                    user.ui_language || $t('adminUserPage.default')
                  }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.audioLanguages') }}</q-item-label>
                  <q-item-label class="text-weight-medium">
                    <template v-if="user.audio_languages && user.audio_languages.length">
                      <q-badge
                        v-for="(lang, index) in user.audio_languages"
                        :key="lang"
                        color="primary"
                        class="q-mr-xs"
                      >
                        {{ index + 1 }}. {{ lang }}
                      </q-badge>
                    </template>
                    <template v-else-if="user.audio_language">{{ user.audio_language }}</template>
                    <template v-else>{{ $t('adminUserPage.default') }}</template>
                  </q-item-label>
                </q-item-section>
              </q-item>
              <q-item>
                <q-item-section>
                  <q-item-label caption>{{ $t('adminUserPage.subtitleLanguage') }}</q-item-label>
                  <q-item-label class="text-weight-medium">{{
                    user.subtitle_language || $t('adminUserPage.disabled')
                  }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card-section>
        </q-card>
      </div>

      <!-- User Statistics -->
      <div class="col-12">
        <UserActivityStatsCards :stats="stats" />
      </div>

      <!-- Viewing History -->
      <div class="col-12">
        <UserViewingHistorySection
          :items="historyItems"
          :loading="historyLoading"
          v-model:pagination="historyPagination"
          @request="onHistoryRequest"
        />
      </div>

      <!-- Invites -->
      <div class="col-12">
        <UserInvitesSection :invites="userInvites" :loading="invitesLoading" />
      </div>

      <!-- Friendships -->
      <div class="col-12">
        <UserFriendshipsSection
          :friendships="userFriendships"
          :loading="friendshipsLoading"
          :user-guid="route.params.guid"
        />
      </div>

      <!-- Devices -->
      <div class="col-12">
        <UserDevicesSection :devices="userDevices" :loading="devicesLoading" />
      </div>

      <!-- Lists -->
      <div class="col-12">
        <UserListsSection :lists="userLists" :loading="listsLoading" />
      </div>

      <!-- Downloads -->
      <div class="col-12">
        <UserDownloadsSection :downloads="userDownloads" :loading="downloadsLoading" />
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useClipboard } from 'src/composables/useClipboard'
import { useUserDetails } from 'src/composables/useUserDetails'
import { formatDate as formatDateRaw } from 'src/composables/useMediaFormatters'
import UserViewingHistorySection from 'src/components/admin/UserViewingHistorySection.vue'
import UserInvitesSection from 'src/components/admin/UserInvitesSection.vue'
import UserFriendshipsSection from 'src/components/admin/UserFriendshipsSection.vue'
import UserDevicesSection from 'src/components/admin/UserDevicesSection.vue'
import UserListsSection from 'src/components/admin/UserListsSection.vue'
import UserDownloadsSection from 'src/components/admin/UserDownloadsSection.vue'
import UserActivityStatsCards from 'src/components/admin/UserActivityStatsCards.vue'
import UserHeaderCard from 'src/components/admin/UserHeaderCard.vue'

const route = useRoute()
const { t, locale } = useI18n()

const {
  loading,
  error,
  user,
  stats,
  historyLoading,
  historyItems,
  historyPagination,
  onHistoryRequest,
  downloadsLoading,
  userDownloads,
  invitesLoading,
  userInvites,
  friendshipsLoading,
  userFriendships,
  devicesLoading,
  userDevices,
  listsLoading,
  userLists,
  loadAll,
} = useUserDetails(() => route.params.guid, t)

const formatDate = (dateString) =>
  formatDateRaw(dateString, { locale: locale.value, fallback: t('adminUserPage.unknown') })

const { copy } = useClipboard()

const copyToClipboard = (text) => {
  copy(text, {
    successMessage: t('adminUserPage.copied'),
    errorMessage: t('adminUserPage.copyFailed'),
  })
}

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.text-mono {
  font-family: 'Courier New', monospace;
  font-size: 0.9em;
}

.q-dark .bg-blue-1 {
  background-color: rgba(33, 150, 243, 0.15) !important;
}
.q-dark .bg-green-1 {
  background-color: rgba(76, 175, 80, 0.15) !important;
}
.q-dark .bg-orange-1 {
  background-color: rgba(255, 152, 0, 0.15) !important;
}
.q-dark .bg-purple-1 {
  background-color: rgba(156, 39, 176, 0.15) !important;
}
</style>
