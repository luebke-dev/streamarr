<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminPackages.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">{{ $t('adminPackages.subtitle') }}</div>

    <q-card flat bordered>
      <q-card-section>
        <div class="row q-col-gutter-md q-mb-md items-center">
          <div class="col-12 col-md-6">
            <q-input
              v-model="search"
              :label="$t('common.search')"
              outlined
              dark
              dense
              clearable
            >
              <template v-slot:prepend>
                <q-icon name="mdi-magnify" />
              </template>
            </q-input>
          </div>
          <div class="col-12 col-md-6 text-right">
            <q-btn
              color="primary"
              icon="mdi-plus"
              :label="$t('adminPackages.createPackage')"
              @click="$router.push('/admin/packages/create')"
            />
          </div>
        </div>

        <q-banner v-if="!stripeConfigured" class="bg-warning text-dark q-mb-md" rounded>
          <template v-slot:avatar><q-icon name="mdi-alert" /></template>
          {{ $t('adminPackages.stripeNotConfigured') }}
        </q-banner>

        <q-table
          flat
          bordered
          dark
          :rows="filteredPackages"
          :columns="columns"
          :loading="loading"
          row-key="guid"
          binary-state-sort
          :rows-per-page-options="[10, 25, 50, 100]"
          :no-data-label="$t('adminPackages.noPackages')"
        >
          <template v-slot:body-cell-name="props">
            <q-td :props="props">
              <div class="text-weight-medium">{{ props.row.name }}</div>
              <div v-if="props.row.description" class="text-caption text-grey-7">
                {{ props.row.description }}
              </div>
            </q-td>
          </template>

          <template v-slot:body-cell-price="props">
            <q-td :props="props">
              {{ formatPrice(props.row.price_cents, props.row.currency) }}
            </q-td>
          </template>

          <template v-slot:body-cell-group="props">
            <q-td :props="props">
              <q-chip dense size="sm" color="blue" text-color="white">
                <q-icon name="mdi-account-group" size="xs" class="q-mr-xs" />
                {{ groupName(props.row.group_id) }}
              </q-chip>
            </q-td>
          </template>

          <template v-slot:body-cell-stripe="props">
            <q-td :props="props">
              <q-icon
                v-if="props.row.stripe_price_id"
                name="mdi-check-circle"
                color="positive"
                size="sm"
              >
                <q-tooltip>{{ props.row.stripe_price_id }}</q-tooltip>
              </q-icon>
              <q-icon v-else name="mdi-minus-circle" color="grey" size="sm">
                <q-tooltip>{{ $t('adminPackages.notSyncedToStripe') }}</q-tooltip>
              </q-icon>
            </q-td>
          </template>

          <template v-slot:body-cell-is_active="props">
            <q-td :props="props">
              <q-chip :color="props.value ? 'positive' : 'grey'" text-color="white" size="sm" dense>
                {{ props.value ? $t('common.active') : $t('common.inactive') }}
              </q-chip>
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props">
              <q-btn
                flat
                dense
                round
                icon="mdi-pencil"
                color="primary"
                size="sm"
                @click="$router.push(`/admin/packages/${props.row.guid}/edit`)"
              >
                <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
              </q-btn>
              <q-btn
                flat
                dense
                round
                icon="mdi-delete"
                color="negative"
                size="sm"
                @click="confirmDelete(props.row)"
              >
                <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
              </q-btn>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <q-card flat bordered class="q-mt-lg">
      <q-card-section>
        <div class="row items-center justify-between q-mb-md">
          <div>
            <div class="text-h6">{{ $t('adminPackages.pluginRuntimeTitle') }}</div>
            <div class="text-caption text-grey-6">
              {{ $t('adminPackages.pluginRuntimeSubtitle') }}
            </div>
          </div>
          <q-btn
            flat
            round
            dense
            icon="mdi-refresh"
            :loading="pluginLoading"
            @click="loadPluginMetadata"
          />
        </div>

        <q-banner
          v-if="pluginRuntime?.policy?.notes"
          rounded
          class="bg-blue-grey-9 text-white q-mb-md"
        >
          <template v-slot:avatar><q-icon name="mdi-shield-lock" color="info" /></template>
          {{ pluginRuntime.policy.notes }}
        </q-banner>

        <div class="row q-col-gutter-md q-mb-md">
          <div class="col-12 col-md-4">
            <q-list dense bordered>
              <q-item>
                <q-item-section>
                  <q-item-label>{{ $t('adminPackages.installedPlugins') }}</q-item-label>
                  <q-item-label caption>
                    {{ pluginRuntime?.installed_count || 0 }}
                    {{ $t('adminPackages.totalInstalled') }},
                    {{ pluginRuntime?.enabled_count || 0 }}
                    {{ $t('common.enabled') }}
                  </q-item-label>
                </q-item-section>
              </q-item>
              <q-item>
                <q-item-section>
                  <q-item-label>{{ $t('adminPackages.runtimeScope') }}</q-item-label>
                  <q-item-label caption>
                    {{
                      pluginRuntime?.policy?.execution_allowed
                        ? $t('adminPackages.executionAllowed')
                        : $t('adminPackages.metadataOnly')
                    }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </div>

          <div class="col-12 col-md-8">
            <div class="text-subtitle2 q-mb-sm">
              {{ $t('adminPackages.pluginRepositories') }}
            </div>
            <q-list dense bordered separator>
              <q-item v-if="pluginRepositories.length === 0">
                <q-item-section class="text-grey-6">
                  {{ $t('adminPackages.noPluginRepositories') }}
                </q-item-section>
              </q-item>
              <q-item v-for="repository in pluginRepositories" :key="repository.id">
                <q-item-section>
                  <q-item-label>{{ repository.name }}</q-item-label>
                  <q-item-label caption>
                    {{ repository.url }} ·
                    {{ repositoryPluginCount(repository.id) }}
                    {{ $t('adminPackages.installedFromRepository') }}
                  </q-item-label>
                  <q-item-label v-if="syncResults[repository.id]" caption>
                    {{ $t('adminPackages.lastSync') }}:
                    {{ syncResults[repository.id].status }}
                  </q-item-label>
                </q-item-section>
                <q-item-section side>
                  <div class="row q-gutter-xs items-center">
                    <q-chip
                      dense
                      size="sm"
                      :color="repository.enabled ? 'positive' : 'grey'"
                      text-color="white"
                    >
                      {{ repository.enabled ? $t('common.enabled') : $t('common.disabled') }}
                    </q-chip>
                    <q-btn
                      flat
                      dense
                      round
                      icon="mdi-sync"
                      :loading="syncLoading === repository.id"
                      @click="syncRepository(repository)"
                    />
                  </div>
                </q-item-section>
              </q-item>
            </q-list>
          </div>
        </div>

        <q-banner
          v-if="pluginValidation && !pluginValidation.valid"
          rounded
          class="bg-negative text-white q-mb-md"
        >
          <template v-slot:avatar><q-icon name="mdi-alert" color="white" /></template>
          {{ $t('adminPackages.invalidPluginEvents') }}
        </q-banner>

        <q-table
          flat
          bordered
          dark
          :rows="installedPlugins"
          :columns="pluginColumns"
          :loading="pluginLoading"
          row-key="id"
          :no-data-label="$t('adminPackages.noInstalledPlugins')"
        >
          <template v-slot:body-cell-name="props">
            <q-td :props="props">
              <div class="text-weight-medium">{{ props.row.name }}</div>
              <div v-if="props.row.description" class="text-caption text-grey-7">
                {{ props.row.description }}
              </div>
            </q-td>
          </template>
          <template v-slot:body-cell-status="props">
            <q-td :props="props">
              <q-chip
                dense
                size="sm"
                :color="pluginStatusColor(props.row.status)"
                text-color="white"
              >
                {{ pluginStatusLabel(props.row.status) }}
              </q-chip>
            </q-td>
          </template>
          <template v-slot:body-cell-capabilities="props">
            <q-td :props="props">
              <q-chip
                v-for="capability in props.row.capabilities"
                :key="capability"
                dense
                size="sm"
                color="blue-grey"
                text-color="white"
              >
                {{ capability }}
              </q-chip>
              <span v-if="!props.row.capabilities?.length" class="text-grey-6">-</span>
            </q-td>
          </template>
          <template v-slot:body-cell-events="props">
            <q-td :props="props">
              <q-chip
                v-for="issue in pluginIssues(props.row.id)"
                :key="issue.event_type || issue.field"
                dense
                size="sm"
                color="negative"
                text-color="white"
              >
                {{ issue.event_type || issue.field }}
                <q-tooltip>{{ issue.message }}</q-tooltip>
              </q-chip>
              <span v-if="pluginIssues(props.row.id).length === 0">
                {{ props.row.notification_events?.length || 0 }}
              </span>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
    </q-card>

    <ConfirmDeleteDialog
      v-model="showDeleteDialog"
      :message="confirmDeleteMessage"
      :loading="deleting"
      @confirm="deletePackage"
    />
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'
import ConfirmDeleteDialog from 'src/components/ConfirmDeleteDialog.vue'

const { t } = useI18n()
const $q = useQuasar()

const packages = ref([])
const groups = ref([])
const pluginRuntime = ref(null)
const pluginRepositories = ref([])
const installedPlugins = ref([])
const pluginValidation = ref(null)
const loading = ref(false)
const pluginLoading = ref(false)
const syncLoading = ref(null)
const search = ref('')
const showDeleteDialog = ref(false)
const deleting = ref(false)
const selectedPackage = ref(null)
const stripeConfigured = ref(true)
const syncResults = ref({})

const columns = computed(() => [
  { name: 'name', required: true, label: t('adminPackages.name'), align: 'left', field: 'name', sortable: true },
  { name: 'price', label: t('adminPackages.price'), align: 'left', field: 'price_cents', sortable: true },
  { name: 'group', label: t('adminPackages.group'), align: 'left', field: 'group_id' },
  { name: 'stripe', label: t('adminPackages.stripe'), align: 'center', field: 'stripe_price_id' },
  { name: 'is_active', label: t('adminPackages.status'), align: 'left', field: 'is_active', sortable: true },
  { name: 'actions', label: t('common.actions'), align: 'center', field: 'actions' },
])

const pluginColumns = computed(() => [
  { name: 'name', required: true, label: t('adminPackages.name'), align: 'left', field: 'name' },
  { name: 'version', label: t('adminPackages.version'), align: 'left', field: 'version' },
  { name: 'status', label: t('adminPackages.status'), align: 'left', field: 'status' },
  {
    name: 'runtime_kind',
    label: t('adminPackages.runtimeKind'),
    align: 'left',
    field: 'runtime_kind',
  },
  {
    name: 'capabilities',
    label: t('adminPackages.capabilities'),
    align: 'left',
    field: 'capabilities',
  },
  {
    name: 'events',
    label: t('adminPackages.notificationEvents'),
    align: 'left',
    field: 'notification_events',
  },
])

const pluginIssueMap = computed(() => {
  const issues = [
    ...(pluginValidation.value?.invalid_notification_events || []),
    ...(pluginValidation.value?.invalid_capabilities || []),
  ]
  return issues.reduce((acc, issue) => {
    if (!acc[issue.plugin_id]) acc[issue.plugin_id] = []
    acc[issue.plugin_id].push(issue)
    return acc
  }, {})
})

const filteredPackages = computed(() => {
  if (!search.value) return packages.value
  const s = search.value.toLowerCase()
  return packages.value.filter(
    (p) =>
      p.name.toLowerCase().includes(s) ||
      (p.description && p.description.toLowerCase().includes(s)),
  )
})

const confirmDeleteMessage = computed(() =>
  t('adminPackages.confirmDelete', { name: selectedPackage.value?.name || '' }),
)

function formatPrice(cents, currency) {
  return `${((cents || 0) / 100).toFixed(2)} ${(currency || 'EUR').toUpperCase()}`
}

function groupName(groupId) {
  const g = groups.value.find((x) => x.guid === groupId)
  return g ? g.name : groupId
}

function repositoryPluginCount(repositoryId) {
  return installedPlugins.value.filter((plugin) => plugin.source_repository_id === repositoryId)
    .length
}

function pluginIssues(pluginId) {
  return pluginIssueMap.value[pluginId] || []
}

function pluginStatusColor(status) {
  const colors = {
    installed: 'positive',
    disabled: 'grey',
    update_available: 'warning',
    restart_required: 'info',
    failed: 'negative',
    uninstalled: 'grey-8',
  }
  return colors[status] || 'grey'
}

function pluginStatusLabel(status) {
  const labels = {
    installed: t('adminPackages.pluginInstalled'),
    disabled: t('adminPackages.pluginDisabled'),
    update_available: t('adminPackages.pluginUpdateAvailable'),
    restart_required: t('adminPackages.pluginRestartRequired'),
    failed: t('adminPackages.pluginFailed'),
    uninstalled: t('adminPackages.pluginUninstalled'),
  }
  return labels[status] || status
}

async function loadPackages() {
  loading.value = true
  try {
    // active_only=false so admin can see deactivated ones too
    const [pkgRes, grpRes, cfgRes] = await Promise.all([
      api.get('/api/subscriptions/packages', { params: { active_only: false } }),
      api.get('/api/groups'),
      api.get('/api/subscriptions/stripe-config').catch(() => ({ data: { publishable_key: null } })),
    ])
    packages.value = pkgRes.data || []
    groups.value = grpRes.data || []
    stripeConfigured.value = !!cfgRes.data?.publishable_key
  } catch (err) {
    logger.error('Failed to load packages:', err)
    $q.notify({ type: 'negative', message: t('adminPackages.loadError') })
  } finally {
    loading.value = false
  }
}

async function loadPluginMetadata() {
  pluginLoading.value = true
  try {
    const [runtimeRes, repositoriesRes, installedRes, validationRes] = await Promise.all([
      api.get('/api/plugins/runtime-policy'),
      api.get('/api/plugins/repositories'),
      api.get('/api/plugins/installed'),
      api.get('/api/plugins/validation'),
    ])
    pluginRuntime.value = runtimeRes.data
    pluginRepositories.value = repositoriesRes.data || []
    installedPlugins.value = installedRes.data || []
    pluginValidation.value = validationRes.data
  } catch (err) {
    logger.error('Failed to load plugin metadata:', err)
    $q.notify({ type: 'negative', message: t('adminPackages.pluginLoadError') })
  } finally {
    pluginLoading.value = false
  }
}

async function syncRepository(repository) {
  syncLoading.value = repository.id
  try {
    const response = await api.post(`/api/plugins/repositories/${repository.id}/sync`)
    syncResults.value = {
      ...syncResults.value,
      [repository.id]: response.data,
    }
  } catch (err) {
    logger.error('Failed to sync plugin repository:', err)
    $q.notify({ type: 'negative', message: t('adminPackages.pluginSyncError') })
  } finally {
    syncLoading.value = null
  }
}

function confirmDelete(pkg) {
  selectedPackage.value = pkg
  showDeleteDialog.value = true
}

async function deletePackage() {
  if (!selectedPackage.value) return
  deleting.value = true
  try {
    await api.delete(`/api/subscriptions/packages/${selectedPackage.value.guid}`)
    showDeleteDialog.value = false
    selectedPackage.value = null
    await loadPackages()
    $q.notify({ type: 'positive', message: t('adminPackages.deleteSuccess') })
  } catch (err) {
    logger.error('Failed to delete package:', err)
    $q.notify({ type: 'negative', message: t('adminPackages.deleteError') })
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  loadPackages()
  loadPluginMetadata()
})
</script>
