<template>
  <q-page class="flex flex-center login-page" :style="backgroundStyle">
    <div v-if="backgroundTitle" class="bg-title-overlay">
      {{ backgroundTitle }}
    </div>
    <div class="q-pa-md" style="max-width: 400px; width: 100%">
      <div class="text-center q-mb-xl">
        <q-icon name="mdi-lock-question" size="4rem" color="primary" />
        <h4 class="q-mt-md q-mb-none text-white">{{ $t('forgotPassword.title') }}</h4>
        <p class="text-grey-5">{{ $t('forgotPassword.subtitle') }}</p>
      </div>

      <q-card dark class="login-card q-pa-lg">
        <q-card-section>
          <!-- Success state -->
          <div v-if="submitted" class="text-center q-py-md">
            <q-icon name="mdi-email-check" size="3rem" color="positive" class="q-mb-md" />
            <p class="text-grey-3">{{ $t('forgotPassword.successMessage') }}</p>
          </div>

          <div v-else>
            <p class="text-grey-4 q-mb-lg">{{ $t('forgotPassword.description') }}</p>

            <q-form @submit="handleSubmit" class="q-gutter-md">
              <q-input
                v-model="email"
                type="email"
                :label="$t('auth.emailLabel')"
                outlined
                dark
                :rules="[(val) => !!val || $t('auth.emailRequired')]"
                icon="mdi-email"
              />

              <q-btn
                type="submit"
                color="primary"
                size="lg"
                class="full-width"
                :loading="loading"
                icon="mdi-send"
                :label="$t('forgotPassword.sendButton')"
              />
            </q-form>
          </div>
        </q-card-section>
      </q-card>

      <div class="text-center q-mt-lg">
        <q-btn
          flat
          color="grey-4"
          icon="mdi-arrow-left"
          :label="$t('forgotPassword.backToLogin')"
          @click="$router.push('/auth/login')"
        />
      </div>
    </div>
  </q-page>
</template>

<script setup>
import { ref } from 'vue'
import { api } from 'boot/axios'
import { useBackgroundRotation } from 'src/composables/useBackgroundRotation'

const email = ref('')
const loading = ref(false)
const submitted = ref(false)
const { backgroundStyle, backgroundTitle } = useBackgroundRotation()

async function handleSubmit() {
  try {
    loading.value = true
    await api.post('/api/auth/forgot-password', { email: email.value })
    submitted.value = true
  } catch {
    // Show success message regardless to avoid email enumeration
    submitted.value = true
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
@import 'src/css/auth-layout';
</style>
