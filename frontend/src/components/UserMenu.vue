<template>
  <div class="user-menu">
    <q-btn v-if="authStore.isAuthenticated" flat no-caps dense class="text-white">
      <div class="row items-center no-wrap">
        <q-avatar v-if="userAvatar" size="32px" class="q-mr-sm">
          <img :src="userAvatar" alt="" />
        </q-avatar>
        <q-icon v-else name="mdi-account" size="32px" class="q-mr-sm" />
      </div>

      <q-menu>
        <q-list style="min-width: 200px">
          <q-item clickable v-close-popup @click="goToSettings">
            <q-item-section avatar>
              <q-icon name="mdi-cog" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('userMenu.settings') }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item
            v-if="settingsStore.isSubscriptionsEnabled"
            clickable
            v-close-popup
            @click="goToMembership"
          >
            <q-item-section avatar>
              <q-icon name="mdi-wallet-membership" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('userMenu.membership') }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item
            v-if="settingsStore.isFriendsEnabled"
            clickable
            v-close-popup
            @click="goToFriends"
          >
            <q-item-section avatar>
              <q-icon name="mdi-account-group" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('userMenu.friends') }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item
            v-if="settingsStore.isInvitesEnabled"
            clickable
            v-close-popup
            @click="goToInviteFriends"
          >
            <q-item-section avatar>
              <q-icon name="mdi-account-plus" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('userMenu.inviteFriends') }}</q-item-label>
            </q-item-section>
          </q-item>
          <q-item v-if="authStore.isAdmin" clickable v-close-popup @click="goToAdmin">
            <q-item-section avatar>
              <q-icon name="mdi-cogs" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('userMenu.administration') }}</q-item-label>
            </q-item-section>
          </q-item>

          <q-separator />

          <q-item clickable v-close-popup @click="handleLogout">
            <q-item-section avatar>
              <q-icon name="mdi-logout" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('userMenu.logout') }}</q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-menu>
    </q-btn>

    <q-btn
      v-else
      flat
      dense
      no-caps
      icon="mdi-login"
      :label="$t('userMenu.login')"
      class="text-white"
      @click="handleLogin"
    />
  </div>
</template>

<script>
import { defineComponent, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from 'src/stores/auth'
import { useSettingsStore } from 'src/stores/settings'
import { useQuasar } from 'quasar'
import { logger } from 'src/utils/logger'

export default defineComponent({
  name: 'UserMenu',
  setup() {
    const router = useRouter()
    const { t } = useI18n()
    const authStore = useAuthStore()
    const settingsStore = useSettingsStore()
    const $q = useQuasar()

    const userAvatar = computed(() => {
      return authStore.user?.picture || null
    })

    const handleLogin = async () => {
      try {
        await authStore.login()
      } catch (error) {
        logger.error('Login error:', error)
      }
    }

    const handleLogout = async () => {
      $q.dialog({
        title: t('userMenu.logoutConfirmTitle'),
        message: t('userMenu.logoutConfirmMessage'),
        cancel: true,
        persistent: true,
      }).onOk(async () => {
        try {
          await authStore.logout()

          router.push('/auth/login')
        } catch (error) {
          logger.error('Logout error:', error)
        }
      })
    }

    const goToSettings = () => {
      router.push('/settings')
    }

    const goToAdmin = () => {
      router.push('/admin')
    }

    const goToMembership = () => {
      router.push('/membership')
    }

    const goToFriends = () => {
      router.push('/friends')
    }

    const goToInviteFriends = () => {
      router.push('/invite-a-friend')
    }

    return {
      authStore,
      settingsStore,
      userAvatar,
      handleLogin,
      handleLogout,
      goToSettings,
      goToMembership,
      goToAdmin,
      goToFriends,
      goToInviteFriends,
    }
  },
})
</script>

<style scoped>
.user-menu {
  display: flex;
  align-items: center;
}

.q-btn-dropdown {
  max-width: 200px;
}

.q-btn-dropdown .q-btn__content {
  justify-content: flex-start;
}
</style>
