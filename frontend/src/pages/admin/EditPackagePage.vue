<template>
  <q-page class="q-pa-md">
    <div class="q-mb-md">
      <q-btn flat dense icon="mdi-arrow-left" :label="$t('common.back')" @click="$router.back()" />
    </div>

    <div class="text-h4 q-mb-md">
      {{ isEdit ? $t('adminPackages.editPackage') : $t('adminPackages.createPackage') }}
    </div>

    <q-banner v-if="!stripeConfigured" class="bg-warning text-dark q-mb-md" rounded>
      <template v-slot:avatar><q-icon name="mdi-alert" /></template>
      {{ $t('adminPackages.stripeNotConfigured') }}
    </q-banner>

    <q-card flat bordered>
      <q-card-section v-if="loading" class="text-center">
        <q-spinner color="primary" size="2em" />
      </q-card-section>

      <q-card-section v-else>
        <q-form @submit="save" class="q-gutter-md">
          <q-input
            v-model="form.name"
            :label="$t('adminPackages.name') + ' *'"
            outlined
            dark
            dense
            :rules="[(v) => !!v || $t('common.required')]"
          />

          <q-input
            v-model="form.description"
            :label="$t('adminPackages.description')"
            outlined
            dark
            dense
            type="textarea"
            autogrow
          />

          <q-input
            v-model="form.price"
            :label="$t('adminPackages.priceMonthly') + ' *'"
            outlined
            dark
            dense
            type="number"
            step="0.01"
            min="0.01"
            :hint="$t('adminPackages.priceHint')"
            :rules="[
              (v) => !!v || $t('common.required'),
              (v) => Number(v) > 0 || $t('adminPackages.pricePositive'),
            ]"
          />

          <q-select
            v-model="form.group_id"
            :options="groupOptions"
            :label="$t('adminPackages.group') + ' *'"
            outlined
            dark
            dense
            emit-value
            map-options
            :hint="$t('adminPackages.groupHint')"
            :rules="[(v) => !!v || $t('common.required')]"
          >
            <template v-slot:option="scope">
              <q-item v-bind="scope.itemProps">
                <q-item-section>
                  <q-item-label>{{ scope.opt.label }}</q-item-label>
                  <q-item-label caption>{{ scope.opt.description }}</q-item-label>
                </q-item-section>
              </q-item>
            </template>
          </q-select>

          <q-toggle v-model="form.is_active" :label="$t('common.active')" />

          <div v-if="isEdit && pkg?.stripe_price_id" class="text-caption text-grey-6">
            <q-icon name="mdi-credit-card-outline" /> Stripe price: {{ pkg.stripe_price_id }}
          </div>

          <div class="row q-gutter-sm justify-end">
            <q-btn flat :label="$t('common.cancel')" @click="$router.push('/admin/packages')" />
            <q-btn
              type="submit"
              color="primary"
              :label="isEdit ? $t('common.save') : $t('common.create')"
              :loading="saving"
              :disable="!isEdit && !stripeConfigured"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { logger } from 'src/utils/logger'
import {
  getGroups,
  getStripeConfig,
  getPackage,
  createPackage,
  updatePackage,
} from 'src/services/systemAdminService'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const $q = useQuasar()

const packageId = computed(() => route.params.guid)
const isEdit = computed(() => !!packageId.value)

const loading = ref(false)
const saving = ref(false)
const stripeConfigured = ref(true)
const groups = ref([])
const pkg = ref(null)

const form = reactive({
  name: '',
  description: '',
  price: '',
  group_id: null,
  is_active: true,
})

const groupOptions = computed(() =>
  groups.value.map((g) => ({
    label: g.name,
    value: g.guid,
    description: g.description || '',
  })),
)

async function loadInitial() {
  loading.value = true
  try {
    const [grpRes, cfgRes] = await Promise.all([
      getGroups(),
      getStripeConfig().catch(() => ({ publishable_key: null })),
    ])
    groups.value = grpRes || []
    stripeConfigured.value = !!cfgRes?.publishable_key

    if (isEdit.value) {
      const data = await getPackage(packageId.value)
      pkg.value = data
      form.name = data.name
      form.description = data.description || ''
      form.price = ((data.price_cents || 0) / 100).toFixed(2)
      form.group_id = data.group_id
      form.is_active = data.is_active
    }
  } catch (err) {
    logger.error('Failed to load package form:', err)
    $q.notify({ type: 'negative', message: t('adminPackages.loadError') })
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload = {
      name: form.name,
      description: form.description || null,
      price: Number(form.price),
      group_id: form.group_id,
      is_active: form.is_active,
    }
    if (isEdit.value) {
      await updatePackage(packageId.value, payload)
      $q.notify({ type: 'positive', message: t('adminPackages.saveSuccess') })
    } else {
      await createPackage(payload)
      $q.notify({ type: 'positive', message: t('adminPackages.createSuccess') })
    }
    router.push('/admin/packages')
  } catch (err) {
    logger.error('Failed to save package:', err)
    const detail = err?.response?.data?.detail || t('adminPackages.saveError')
    $q.notify({ type: 'negative', message: detail })
  } finally {
    saving.value = false
  }
}

onMounted(loadInitial)
</script>
