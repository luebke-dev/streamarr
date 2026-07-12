<template>
  <q-page padding>
    <div class="row justify-center">
      <div class="col-12 col-md-8 col-lg-6">
        <UserBasicInfoForm
          v-model="user"
          :loading="loading"
          @submit="saveUser"
          @cancel="router.push('/admin/users')"
        />

        <!-- Playback Preferences -->
        <UserPlaybackPreferencesForm :user-guid="route.params.guid" />

        <!-- Permission Overrides (admin only) -->
        <UserPermissionOverridesForm
          :user-guid="route.params.guid"
          @saved="loadEffectivePermissions"
        />

        <!-- Effective Permissions (read-only) -->
        <UserEffectivePermissionsCard :effective-perms="effectivePerms" />
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import {
  getUser,
  updateUser,
  updateUserPassword,
  getUserEffectivePermissions,
} from 'src/services/accessAdminService'
import UserBasicInfoForm from 'src/components/admin/UserBasicInfoForm.vue'
import UserEffectivePermissionsCard from 'src/components/admin/UserEffectivePermissionsCard.vue'
import UserPlaybackPreferencesForm from 'src/components/admin/UserPlaybackPreferencesForm.vue'
import UserPermissionOverridesForm from 'src/components/admin/UserPermissionOverridesForm.vue'

const router = useRouter()
const route = useRoute()
const $q = useQuasar()
const { t } = useI18n()

const loading = ref(false)
const user = ref({
  first_name: '',
  last_name: '',
  email: '',
  password: '',
  is_active: true,
  is_superuser: false,
  ui_language: 'en-US',
  audio_languages: ['en'],
  subtitle_language: null,
})

const effectivePerms = ref(null)

const loadUser = async () => {
  try {
    loading.value = true
    const data = await getUser(route.params.guid)
    // Backward compat: migrate audio_language -> audio_languages
    if (!data.audio_languages && data.audio_language) {
      data.audio_languages = [data.audio_language]
    } else if (!data.audio_languages) {
      data.audio_languages = ['en']
    }
    user.value = {
      ...data,
      password: '',
    }
  } catch (error) {
    logger.error('Error loading user:', error)
    $q.notify({ type: 'negative', message: t('editUser.loadError') })
    router.push('/admin/users')
  } finally {
    loading.value = false
  }
}

const loadEffectivePermissions = async () => {
  try {
    effectivePerms.value = await getUserEffectivePermissions(route.params.guid)
  } catch (error) {
    logger.error('Error loading effective permissions:', error)
  }
}

const saveUser = async () => {
  try {
    loading.value = true

    const userData = {
      first_name: user.value.first_name,
      last_name: user.value.last_name,
      email: user.value.email,
      is_active: user.value.is_active,
      is_superuser: user.value.is_superuser,
      ui_language: user.value.ui_language,
      audio_languages: user.value.audio_languages,
      subtitle_language: user.value.subtitle_language,
    }

    await updateUser(route.params.guid, userData)

    if (user.value.password && user.value.password.trim() !== '') {
      await updateUserPassword(route.params.guid, {
        new_password: user.value.password,
      })
    }

    $q.notify({ type: 'positive', message: t('editUser.saveSuccess') })
    router.push('/admin/users')
  } catch (error) {
    logger.error('Error updating user:', error)
    $q.notify({ type: 'negative', message: t('editUser.saveError') })
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadUser()
  await loadEffectivePermissions()
})
</script>
