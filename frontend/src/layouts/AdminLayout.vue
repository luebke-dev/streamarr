<template>
  <q-layout view="lHh Lpr lFf">
    <q-header class="bg-dark">
      <q-toolbar>
        <q-btn
          flat
          dense
          round
          icon="mdi-menu"
          :aria-label="$t('drawer.menu')"
          @click="toggleLeftDrawer"
        />

        <q-toolbar-title> {{ settingsStore.getSiteName }} </q-toolbar-title>

        <q-space />

        <UserMenu />
      </q-toolbar>
    </q-header>

    <q-drawer v-model="leftDrawerOpen" show-if-above bordered>
      <q-list dense>
        <q-item-label header>{{ $t('adminMenu.menu') }}</q-item-label>
        <DrawerItem icon="mdi-speedometer" :title="$t('adminMenu.dashboard')" to="/admin/" />
        <DrawerItem icon="mdi-download" :title="$t('adminMenu.downloads')" to="/admin/downloads" />
        <DrawerItem
          :title="$t('adminMenu.activeSessions')"
          to="/admin/active-sessions"
          icon="mdi-monitor-eye"
        />
        <DrawerItem icon="mdi-home" :title="$t('adminMenu.home')" to="/" />

        <q-item-label header>{{ $t('adminMenu.libraries') }}</q-item-label>

        <DrawerItem icon="mdi-movie" :title="$t('movies')" to="/admin/libraries/movies" />
        <DrawerItem icon="mdi-television" :title="$t('shows')" to="/admin/libraries/shows" />
        <DrawerItem icon="mdi-gamepad-variant" :title="$t('games')" to="/admin/libraries/games" />
        <DrawerItem icon="mdi-music" :title="$t('music')" to="/admin/libraries/music" />
        <DrawerItem icon="mdi-book" :title="$t('books')" to="/admin/libraries/books" />

        <q-item-label header>{{ $t('adminMenu.usersSection') }}</q-item-label>
        <DrawerItem icon="mdi-account" :title="$t('adminMenu.users')" to="/admin/users" />
        <DrawerItem icon="mdi-account-group" :title="$t('adminMenu.groups')" to="/admin/groups" />
        <DrawerItem
          icon="mdi-account-multiple-plus"
          :title="$t('adminMenu.invites')"
          to="/admin/invites"
        />
        <DrawerItem
          icon="mdi-monitor-cellphone"
          :title="$t('adminMenu.devices')"
          to="/admin/devices"
        />
        <DrawerItem
          icon="mdi-format-list-bulleted"
          :title="$t('adminMenu.lists')"
          to="/admin/lists"
        />
        <DrawerItem
          icon="mdi-auto-fix"
          :title="$t('adminMenu.smartCollections')"
          to="/admin/smart-collections"
        />
        <DrawerItem
          icon="mdi-image-multiple"
          :title="$t('adminMenu.overlays')"
          to="/admin/overlays"
        />
        <DrawerItem
          icon="mdi-pencil-box-multiple"
          :title="$t('adminMenu.massOperations')"
          to="/admin/mass-operations"
        />
        <DrawerItem
          icon="mdi-view-dashboard-edit"
          :title="$t('adminMenu.pageLayouts')"
          to="/admin/page-layouts"
        />
        <q-item-label header>{{ $t('adminMenu.system') }}</q-item-label>
        <DrawerItem icon="mdi-bullhorn" :title="$t('adminMenu.banners')" to="/admin/banners" />
        <!-- Packages + vouchers belong to the subscription/payment flow.
             Hide them when subscriptions are disabled in admin settings. -->
        <template v-if="settingsStore.isSubscriptionsEnabled">
          <DrawerItem
            icon="mdi-package-variant-closed"
            :title="$t('adminMenu.packages')"
            to="/admin/packages"
          />
          <DrawerItem
            icon="mdi-ticket-percent"
            :title="$t('adminMenu.vouchers')"
            to="/admin/vouchers"
          />
        </template>
        <DrawerItem icon="mdi-cog" :title="$t('adminMenu.settings')" to="/admin/settings" />
        <DrawerItem
          icon="mdi-file-arrow-left-right"
          :title="$t('adminMenu.transcoding')"
          to="/admin/transcoding"
        />
        <DrawerItem
          icon="mdi-cloud-download"
          :title="$t('adminMenu.downloaders')"
          to="/admin/downloaders"
        />
        <DrawerItem
          icon="mdi-database-search"
          :title="$t('adminMenu.indexers')"
          to="/admin/indexers"
        />
        <DrawerItem
          icon="mdi-cloud-search"
          :title="$t('adminMenu.metadata')"
          to="/admin/metadata"
        />
        <DrawerItem icon="mdi-cogs" :title="$t('adminMenu.tasks')" to="/admin/tasks" />
        <DrawerItem icon="mdi-monitor-cellphone" :title="$t('adminMenu.logs')" to="/admin/logs" />
        <DrawerItem icon="mdi-account-group" :title="$t('adminMenu.parties')" to="/admin/parties" />
      </q-list>
    </q-drawer>

    <q-page-container>
      <!-- Global Banners -->
      <GlobalBanners />
      <FriendRequestBanner />

      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import DrawerItem from 'components/DrawerItem.vue'
import UserMenu from 'components/UserMenu.vue'
import GlobalBanners from 'components/GlobalBanners.vue'
import FriendRequestBanner from 'components/FriendRequestBanner.vue'
import { useSettingsStore } from 'src/stores/settings'

const leftDrawerOpen = ref(false)
const settingsStore = useSettingsStore()

function toggleLeftDrawer() {
  leftDrawerOpen.value = !leftDrawerOpen.value
}

onMounted(async () => {
  await Promise.all([
    settingsStore.fetchSiteName(),
    settingsStore.fetchSubscriptionSettings(),
  ])
})
</script>
