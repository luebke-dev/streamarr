<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="row items-center q-gutter-md">
        <q-avatar size="80px" color="primary" text-color="white">
          <img
            v-if="user.picture"
            :src="user.picture"
            :alt="`${user.first_name} ${user.last_name}`"
          />
          <span v-else class="text-h4">{{ userInitials }}</span>
        </q-avatar>
        <div class="col">
          <div class="text-h5">{{ user.first_name }} {{ user.last_name }}</div>
          <div class="text-subtitle1 text-grey">{{ user.email }}</div>
          <div class="q-mt-sm">
            <q-badge
              :color="user.is_active ? 'positive' : 'negative'"
              :label="user.is_active ? t('adminUserPage.active') : t('adminUserPage.inactive')"
              class="q-mr-sm"
            />
            <q-badge
              v-if="user.is_superuser"
              color="warning"
              text-color="dark"
              :label="t('adminUserPage.admin')"
            />
            <q-badge
              v-if="user.oidc_provider"
              color="info"
              :label="`OIDC: ${user.oidc_provider}`"
              class="q-ml-sm"
            />
          </div>
        </div>
        <div>
          <q-btn
            color="primary"
            icon="mdi-pencil"
            :label="t('adminUserPage.editUser')"
            @click="$emit('edit', user.guid)"
          />
        </div>
      </div>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  user: {
    type: Object,
    required: true,
  },
})

defineEmits(['edit'])

const { t } = useI18n()

const userInitials = computed(() => {
  const first = props.user.first_name?.[0] || ''
  const last = props.user.last_name?.[0] || ''
  return (first + last).toUpperCase() || '?'
})
</script>
