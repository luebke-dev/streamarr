<template>
  <q-page class="q-pa-md">
    <div class="row justify-between items-center q-mb-lg">
      <div>
        <h4 class="q-my-none">Create New User</h4>
        <p class="text-grey-6 q-mb-none">Add a new user to the system</p>
      </div>
      <q-btn
        flat
        icon="mdi-arrow-left"
        :label="$t('adminCreateUser.backToUsers')"
        @click="$router.push('/admin/users')"
        class="q-ml-md"
      />
    </div>

    <q-card class="q-pa-lg" style="max-width: 600px">
      <q-form @submit="saveUser" class="q-gutter-md">
        <div class="row q-gutter-md">
          <div class="col">
            <q-input
              filled
              v-model="userForm.first_name"
              :label="$t('adminCreateUser.firstName')"
              lazy-rules
              :rules="[(val) => (val && val.length > 0) || 'Please enter a first name']"
            />
          </div>
          <div class="col">
            <q-input
              filled
              v-model="userForm.last_name"
              :label="$t('adminCreateUser.lastName')"
              lazy-rules
              :rules="[(val) => (val && val.length > 0) || 'Please enter a last name']"
            />
          </div>
        </div>

        <q-input
          filled
          v-model="userForm.email"
          :label="$t('adminCreateUser.email')"
          type="email"
          lazy-rules
          :rules="[
            (val) => (val && val.length > 0) || 'Please enter an email',
            (val) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val) || 'Please enter a valid email',
          ]"
        />

        <q-input
          filled
          v-model="userForm.password"
          :label="$t('adminCreateUser.password')"
          type="password"
          :hint="$t('adminCreateUser.passwordHint')"
        />

        <div class="q-gutter-md">
          <q-toggle v-model="userForm.is_active" :label="$t('adminCreateUser.activeUser')" />
          <q-toggle v-model="userForm.is_superuser" :label="$t('adminCreateUser.administrator')" />
        </div>

        <div class="row q-gutter-md q-mt-lg">
          <q-btn
            flat
            :label="$t('adminCreateUser.cancel')"
            @click="$router.push('/admin/users')"
            class="q-ml-sm"
          />
          <q-btn
            type="submit"
            color="primary"
            :label="$t('adminCreateUser.createUser')"
            :loading="saving"
            icon="mdi-account-plus"
          />
        </div>
      </q-form>
    </q-card>
  </q-page>
</template>

<script>
import { ref } from 'vue'
import { api } from 'boot/axios'
import { useRouter } from 'vue-router'
import { logger } from 'src/utils/logger'

export default {
  setup() {
    const router = useRouter()
    const saving = ref(false)

    const userForm = ref({
      first_name: '',
      last_name: '',
      email: '',
      password: '',
      is_active: true,
      is_superuser: false,
    })

    async function saveUser() {
      saving.value = true
      try {
        const userData = {
          first_name: userForm.value.first_name,
          last_name: userForm.value.last_name,
          email: userForm.value.email,
          is_active: userForm.value.is_active,
          is_superuser: userForm.value.is_superuser,
        }

        if (userForm.value.password && userForm.value.password.trim() !== '') {
          userData.password = userForm.value.password
        }

        await api.post('/api/users', userData)

        router.push('/admin/users')
      } catch (error) {
        logger.error('Error saving user:', error)
      } finally {
        saving.value = false
      }
    }

    return {
      userForm,
      saving,
      saveUser,
    }
  },
}
</script>
