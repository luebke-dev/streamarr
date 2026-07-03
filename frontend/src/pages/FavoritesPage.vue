<template>
  <q-page class="flex flex-center" style="min-height: 70vh">
    <q-spinner-dots size="50px" color="primary" />
  </q-page>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from 'src/stores/auth'
import { useListsStore } from 'src/stores/lists'
import { logger } from 'src/utils/logger'

const router = useRouter()
const authStore = useAuthStore()
const listsStore = useListsStore()

onMounted(async () => {
  try {
    if (!authStore.initialized) await authStore.initialize()
    if (!listsStore.initialized && authStore.user?.guid) {
      await listsStore.fetchUserLists(authStore.user.guid)
    }

    // Find the FAVORITES list
    const favList = listsStore.getUserLists.find((l) => l.list_type === 'FAVORITES')
    if (favList) {
      router.replace(`/lists/${favList.guid}`)
    } else {
      router.replace('/')
    }
  } catch (err) {
    logger.error('Error redirecting to favorites list:', err)
    router.replace('/')
  }
})
</script>
