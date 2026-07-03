<template>
  <q-card class="q-mt-md">
    <q-card-section>
      <div class="text-h6">
        <q-icon name="mdi-shield-check" class="q-mr-sm" />
        {{ t('editUser.effectivePermissions') }}
      </div>
      <div class="text-caption text-grey">
        {{ t('editUser.effectivePermissionsHint') }}
      </div>
    </q-card-section>

    <q-separator />

    <q-card-section v-if="effectivePerms">
      <div class="q-gutter-sm">
        <div>
          <strong>{{ t('editUser.source') }}:</strong> {{ effectivePerms.source }}
        </div>
        <div>
          <strong>{{ t('adminGroups.allowedLibraries') }}:</strong>
          {{ effectivePerms.allowed_libraries?.join(', ') || '-' }}
        </div>
        <div>
          <strong>{{ t('adminGroups.maxConcurrentStreams') }}:</strong>
          {{ effectivePerms.max_concurrent_streams }}
        </div>
        <div>
          <strong>{{ t('adminGroups.maxGameStreams') }}:</strong>
          {{ effectivePerms.max_game_streams }}
        </div>
        <div>
          <strong>{{ t('adminGroups.maxVideoQuality') }}:</strong>
          {{ effectivePerms.max_video_quality || '-' }}
        </div>
        <div>
          <strong>{{ t('adminGroups.maxAudioQuality') }}:</strong>
          {{ effectivePerms.max_audio_quality || '-' }}
        </div>
        <div>
          <strong>{{ t('adminGroups.maxConcurrentTranscodings') }}:</strong>
          {{ effectivePerms.max_concurrent_transcodings }}
        </div>
        <div v-if="effectivePerms.group_names?.length">
          <strong>{{ t('editUser.groups') }}:</strong>
          {{ effectivePerms.group_names.join(', ') }}
        </div>
      </div>
    </q-card-section>
    <q-card-section v-else>
      <q-spinner size="sm" class="q-mr-sm" />
      {{ t('common.loading') }}
    </q-card-section>
  </q-card>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  effectivePerms: {
    type: Object,
    default: null,
  },
})

const { t } = useI18n()
</script>
