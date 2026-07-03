<template>
  <q-page class="friends-page q-pa-md">
    <div class="row items-center q-mb-lg">
      <div class="col">
        <h1 class="text-h4 q-mb-none">{{ $t('friends.title') }}</h1>
        <p class="text-subtitle1 text-grey-6 q-mb-none">{{ $t('friends.subtitle') }}</p>
      </div>
    </div>

    <!-- Add Friend Card -->
    <q-card flat bordered class="q-mb-md">
      <q-card-section>
        <div class="text-h6 q-mb-sm">
          <q-icon name="mdi-account-plus" class="q-mr-sm" />
          {{ $t('friends.addFriend') }}
        </div>
        <p class="text-caption text-grey-6 q-mb-md">{{ $t('friends.addFriendHint') }}</p>
        <div class="row q-gutter-sm items-center">
          <q-input
            v-model="friendEmail"
            :label="$t('friends.emailLabel')"
            type="email"
            filled
            dense
            class="col"
            :error="!!friendEmailError"
            :error-message="friendEmailError"
            @keyup.enter="sendFriendRequest"
          >
            <template v-slot:prepend>
              <q-icon name="mdi-email-outline" />
            </template>
          </q-input>
          <q-btn
            color="primary"
            icon="mdi-account-plus"
            :label="$t('friends.sendRequest')"
            :loading="sendingRequest"
            @click="sendFriendRequest"
            unelevated
          />
        </div>
      </q-card-section>
    </q-card>

    <!-- Incoming Requests -->
    <template v-if="pendingReceived.length > 0">
      <div class="text-subtitle2 q-mb-sm text-grey-7">
        <q-icon name="mdi-account-clock" class="q-mr-xs" />
        {{ $t('friends.pendingIncoming') }}
        <q-badge color="primary" class="q-ml-xs">{{ pendingReceived.length }}</q-badge>
      </div>
      <q-card flat bordered class="q-mb-md">
        <q-list separator>
          <q-item v-for="req in pendingReceived" :key="req.guid">
            <q-item-section avatar>
              <q-avatar color="primary" text-color="white">
                <img
                  v-if="req.requester.picture"
                  :src="req.requester.picture"
                  :alt="getDisplayName(req.requester)"
                />
                <span v-else>{{ getInitials(req.requester) }}</span>
              </q-avatar>
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ getDisplayName(req.requester) }}</q-item-label>
              <q-item-label caption>{{ req.requester.email }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <div class="row q-gutter-xs">
                <q-btn
                  flat
                  round
                  dense
                  icon="mdi-check"
                  color="positive"
                  :loading="actionLoading === req.guid + '_accept'"
                  @click="acceptRequest(req)"
                >
                  <q-tooltip>{{ $t('common.accept') }}</q-tooltip>
                </q-btn>
                <q-btn
                  flat
                  round
                  dense
                  icon="mdi-close"
                  color="negative"
                  :loading="actionLoading === req.guid + '_reject'"
                  @click="confirmReject(req)"
                >
                  <q-tooltip>{{ $t('common.decline') }}</q-tooltip>
                </q-btn>
              </div>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card>
    </template>

    <!-- Sent Requests -->
    <template v-if="pendingSent.length > 0">
      <div class="text-subtitle2 q-mb-sm text-grey-7">
        <q-icon name="mdi-account-arrow-right" class="q-mr-xs" />
        {{ $t('friends.pendingOutgoing') }}
      </div>
      <q-card flat bordered class="q-mb-md">
        <q-list separator>
          <q-item v-for="req in pendingSent" :key="req.guid">
            <q-item-section avatar>
              <q-avatar color="grey-4" text-color="grey-8">
                <img
                  v-if="req.addressee.picture"
                  :src="req.addressee.picture"
                  :alt="getDisplayName(req.addressee)"
                />
                <span v-else>{{ getInitials(req.addressee) }}</span>
              </q-avatar>
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ getDisplayName(req.addressee) }}</q-item-label>
              <q-item-label caption>{{ req.addressee.email }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-chip color="grey-4" text-color="grey-8" dense size="sm">
                <q-icon name="mdi-clock-outline" class="q-mr-xs" size="xs" />
                {{ $t('invite.status.pending') }}
              </q-chip>
            </q-item-section>
            <q-item-section side>
              <q-btn
                flat
                round
                dense
                icon="mdi-close"
                color="grey-7"
                :loading="actionLoading === req.guid + '_remove'"
                @click="confirmWithdraw(req)"
              >
                <q-tooltip>{{ $t('friends.withdrawConfirm') }}</q-tooltip>
              </q-btn>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card>
    </template>

    <!-- Friends List -->
    <div class="text-subtitle2 q-mb-sm text-grey-7">
      <q-icon name="mdi-account-group" class="q-mr-xs" />
      {{ $t('friends.title') }}
      <q-badge color="grey-5" text-color="grey-9" class="q-ml-xs">{{ friends.length }}</q-badge>
    </div>
    <q-card flat bordered>
      <q-inner-loading :showing="loadingFriends" />
      <q-list v-if="friends.length > 0" separator>
        <q-item v-for="friendship in friends" :key="friendship.guid">
          <q-item-section avatar>
            <q-avatar color="primary" text-color="white">
              <img
                v-if="getFriend(friendship).picture"
                :src="getFriend(friendship).picture"
                :alt="getDisplayName(getFriend(friendship))"
              />
              <span v-else>{{ getInitials(getFriend(friendship)) }}</span>
            </q-avatar>
          </q-item-section>
          <q-item-section>
            <q-item-label>{{ getDisplayName(getFriend(friendship)) }}</q-item-label>
            <q-item-label caption>{{ getFriend(friendship).email }}</q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn
              flat
              round
              dense
              icon="mdi-account-remove"
              color="grey-7"
              :loading="actionLoading === friendship.guid + '_remove'"
              @click="confirmRemove(friendship)"
            >
              <q-tooltip>{{ $t('friends.removeConfirm') }}</q-tooltip>
            </q-btn>
          </q-item-section>
        </q-item>
      </q-list>
      <q-card-section v-else-if="!loadingFriends" class="text-center text-grey-5 q-py-xl">
        <q-icon name="mdi-account-group-outline" size="3rem" class="q-mb-sm" />
        <div>{{ $t('friends.noFriends') }}</div>
      </q-card-section>
    </q-card>

    <!-- Confirm Action Dialog -->
    <q-dialog v-model="showConfirmDialog" persistent>
      <q-card>
        <q-card-section class="row items-center">
          <q-avatar :icon="confirmDialogIcon" :color="confirmDialogColor" text-color="white" />
          <span class="q-ml-sm">{{ confirmDialogMessage }}</span>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" @click="showConfirmDialog = false" />
          <q-btn
            flat
            :label="confirmDialogAction"
            :color="confirmDialogColor"
            @click="executeConfirmedAction"
            :loading="actionLoading !== null"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script>
import { defineComponent, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { api } from 'src/boot/axios'
import { logger } from 'src/utils/logger'

export default defineComponent({
  name: 'FriendsPage',
  setup() {
    const { t } = useI18n()
    const $q = useQuasar()
    const notifyError = (err, context) => {
      logger.warn(`FriendsPage: ${context} failed`, err)
      $q.notify({ type: 'negative', message: t('common.actionFailed') })
    }

    const friends = ref([])
    const pendingReceived = ref([])
    const pendingSent = ref([])
    const loadingFriends = ref(false)
    const friendEmail = ref('')
    const friendEmailError = ref('')
    const sendingRequest = ref(false)
    const actionLoading = ref(null)
    const currentUserId = ref(null)

    const showConfirmDialog = ref(false)
    const confirmDialogMessage = ref('')
    const confirmDialogAction = ref('')
    const confirmDialogColor = ref('negative')
    const confirmDialogIcon = ref('mdi-alert')
    const pendingAction = ref(null)

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

    const getFriend = (friendship) => {
      if (!currentUserId.value) return friendship.requester
      return friendship.requester.guid === currentUserId.value
        ? friendship.addressee
        : friendship.requester
    }

    const loadFriends = async () => {
      loadingFriends.value = true
      try {
        const [friendsRes, pendingRes, sentRes, meRes] = await Promise.all([
          api.get('/api/friends'),
          api.get('/api/friends/pending'),
          api.get('/api/friends/sent'),
          api.get('/api/auth/me'),
        ])
        friends.value = friendsRes.data
        pendingReceived.value = pendingRes.data
        pendingSent.value = sentRes.data
        currentUserId.value = meRes.data.guid
      } catch (err) {
        notifyError(err, 'loadFriends')
      } finally {
        loadingFriends.value = false
      }
    }

    const validateEmail = (email) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)

    const sendFriendRequest = async () => {
      friendEmailError.value = ''
      if (!friendEmail.value) {
        friendEmailError.value = t('friends.emailRequired')
        return
      }
      if (!validateEmail(friendEmail.value)) {
        friendEmailError.value = t('friends.emailInvalid')
        return
      }
      sendingRequest.value = true
      try {
        await api.post('/api/friends/request', { email: friendEmail.value })
        friendEmail.value = ''
        await loadFriends()
      } catch (err) {
        const detail = err.response?.data?.detail || ''
        const knownErrors = {
          'no user': 'no_user',
          yourself: 'self_request',
          'already friends': 'already_friends',
          'already pending': 'already_pending',
          'cannot send': 'blocked',
        }
        const matched = Object.entries(knownErrors).find(([phrase]) =>
          detail.toLowerCase().includes(phrase),
        )
        if (matched) {
          friendEmailError.value = t(`friends.errors.${matched[1]}`)
        } else {
          notifyError(err, 'sendFriendRequest')
        }
      } finally {
        sendingRequest.value = false
      }
    }

    const acceptRequest = async (req) => {
      actionLoading.value = req.guid + '_accept'
      try {
        await api.post(`/api/friends/${req.guid}/accept`)
        await loadFriends()
      } catch (err) {
        notifyError(err, 'acceptRequest')
      } finally {
        actionLoading.value = null
      }
    }

    const confirmReject = (req) => {
      confirmDialogMessage.value = t('friends.rejectConfirm')
      confirmDialogAction.value = t('common.decline')
      confirmDialogColor.value = 'negative'
      confirmDialogIcon.value = 'mdi-account-remove'
      pendingAction.value = async () => {
        actionLoading.value = req.guid + '_reject'
        try {
          await api.post(`/api/friends/${req.guid}/reject`)
          await loadFriends()
        } catch (err) {
          notifyError(err, 'rejectRequest')
        } finally {
          actionLoading.value = null
        }
      }
      showConfirmDialog.value = true
    }

    const confirmWithdraw = (req) => {
      confirmDialogMessage.value = t('friends.withdrawConfirm')
      confirmDialogAction.value = t('common.withdraw')
      confirmDialogColor.value = 'grey'
      confirmDialogIcon.value = 'mdi-account-arrow-left'
      pendingAction.value = async () => {
        actionLoading.value = req.guid + '_remove'
        try {
          await api.delete(`/api/friends/${req.guid}`)
          await loadFriends()
        } catch (err) {
          notifyError(err, 'withdrawRequest')
        } finally {
          actionLoading.value = null
        }
      }
      showConfirmDialog.value = true
    }

    const confirmRemove = (friendship) => {
      confirmDialogMessage.value = t('friends.removeConfirm')
      confirmDialogAction.value = t('common.remove')
      confirmDialogColor.value = 'negative'
      confirmDialogIcon.value = 'mdi-account-remove'
      pendingAction.value = async () => {
        actionLoading.value = friendship.guid + '_remove'
        try {
          await api.delete(`/api/friends/${friendship.guid}`)
          await loadFriends()
        } catch (err) {
          notifyError(err, 'removeFriend')
        } finally {
          actionLoading.value = null
        }
      }
      showConfirmDialog.value = true
    }

    const executeConfirmedAction = async () => {
      if (pendingAction.value) {
        await pendingAction.value()
        pendingAction.value = null
      }
      showConfirmDialog.value = false
    }

    onMounted(() => {
      loadFriends()
    })

    return {
      friends,
      pendingReceived,
      pendingSent,
      loadingFriends,
      friendEmail,
      friendEmailError,
      sendingRequest,
      actionLoading,
      getDisplayName,
      getInitials,
      getFriend,
      sendFriendRequest,
      acceptRequest,
      confirmReject,
      confirmWithdraw,
      confirmRemove,
      showConfirmDialog,
      confirmDialogMessage,
      confirmDialogAction,
      confirmDialogColor,
      confirmDialogIcon,
      executeConfirmedAction,
    }
  },
})
</script>

<style scoped>
.friends-page {
  max-width: 800px;
  margin: 0 auto;
}
</style>
