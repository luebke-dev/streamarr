<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-sm">{{ $t('adminTasks.title') }}</div>
    <div class="text-subtitle1 text-grey-7 q-mb-lg">{{ $t('adminTasks.subtitle') }}</div>

    <AsyncState :loading="loading" :error="error" :retry="refresh">
      <div v-for="category in categories" :key="category.id" class="q-mb-lg">
        <div class="text-overline text-grey-6 q-mb-sm">{{ categoryLabel(category.id) }}</div>
        <div class="row q-gutter-md">
          <q-card
            v-for="task in tasksByCategory(category.id)"
            :key="task.id"
            flat
            bordered
            class="task-card"
          >
            <q-card-section>
              <div class="row items-start no-wrap">
                <q-icon
                  :name="categoryIcon(task.category)"
                  size="1.6rem"
                  :color="categoryColor(task.category)"
                  class="q-mr-md q-mt-xs"
                />
                <div class="col">
                  <div class="text-subtitle1 text-weight-medium">{{ taskName(task) }}</div>
                  <div class="text-body2 text-grey-6 q-mt-xs">{{ taskDesc(task) }}</div>
                </div>
              </div>
            </q-card-section>
            <q-card-actions align="right">
              <q-btn
                color="primary"
                :label="
                  runningTask === task.id ? $t('adminTasks.running') : $t('adminTasks.runTask')
                "
                :loading="runningTask === task.id"
                :disable="!!runningTask"
                icon="mdi-play"
                no-caps
                @click="runTask(task)"
              />
            </q-card-actions>
          </q-card>
        </div>
      </div>
    </AsyncState>

    <q-card flat bordered class="q-mt-lg">
      <q-card-section class="row items-center justify-between">
        <div class="text-h6">{{ $t('adminTasks.runHistory') }}</div>
        <div class="row q-gutter-sm">
          <q-select
            v-model="historyStatus"
            :options="historyStatusOptions"
            dense
            outlined
            emit-value
            map-options
            style="min-width: 160px"
            @update:model-value="loadTaskHistory"
          />
          <q-btn flat round dense icon="mdi-refresh" @click="loadTaskHistory" />
        </div>
      </q-card-section>
      <q-table
        :rows="taskHistory"
        :columns="historyColumns"
        row-key="guid"
        :loading="historyLoading"
        flat
        bordered
        dark
        :pagination="{ rowsPerPage: 10 }"
      >
        <template v-slot:body-cell-status="props">
          <q-td :props="props">
            <q-chip
              size="sm"
              :color="historyStatusColor(taskEventExtra(props.row).status)"
              text-color="white"
              :label="taskEventExtra(props.row).status || props.row.event_type"
            />
          </q-td>
        </template>
        <template v-slot:body-cell-run_id="props">
          <q-td :props="props">
            <q-btn
              flat
              dense
              no-caps
              color="primary"
              :label="shortRunId(taskEventExtra(props.row).run_id)"
              @click="loadTaskRun(taskEventExtra(props.row).run_id)"
            />
          </q-td>
        </template>
        <template v-slot:body-cell-created_at="props">
          <q-td :props="props">{{ formatDateTime(props.row.created_at) }}</q-td>
        </template>
      </q-table>
    </q-card>

    <q-dialog v-model="showRunDialog">
      <q-card style="min-width: 520px">
        <q-card-section>
          <div class="text-h6">{{ $t('adminTasks.runDetails') }}</div>
          <div class="text-caption text-grey-6">{{ selectedRun?.run_id }}</div>
        </q-card-section>
        <q-card-section v-if="selectedRun">
          <q-list dense bordered separator>
            <q-item v-for="event in selectedRun.events" :key="event.guid">
              <q-item-section>
                <q-item-label>{{ event.message }}</q-item-label>
                <q-item-label caption>
                  {{ formatDateTime(event.created_at) }} · {{ event.event_type }}
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.close')" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { logger } from 'src/utils/logger'
import {
  getTasks,
  runTask as runTaskApi,
  getTaskHistory,
  getTaskRun,
} from 'src/services/systemAdminService'
import { useAsyncResource } from 'src/composables/useAsyncResource'
import AsyncState from 'src/components/AsyncState.vue'

const { t } = useI18n()

const {
  data: tasks,
  loading,
  error,
  refresh,
} = useAsyncResource(async () => await getTasks(), {
  initial: [],
  immediate: true,
})

const runningTask = ref(null)
const taskHistory = ref([])
const historyLoading = ref(false)
const historyStatus = ref('all')
const showRunDialog = ref(false)
const selectedRun = ref(null)

const historyStatusOptions = computed(() => [
  { value: 'all', label: t('adminTasks.historyAll') },
  { value: 'queued', label: t('adminTasks.historyQueued') },
  { value: 'completed', label: t('adminTasks.historyCompleted') },
  { value: 'failed', label: t('adminTasks.historyFailed') },
])

const historyColumns = computed(() => [
  {
    name: 'created_at',
    label: t('adminTasks.createdAt'),
    field: 'created_at',
    align: 'left',
  },
  {
    name: 'status',
    label: t('adminTasks.status'),
    field: 'event_type',
    align: 'left',
  },
  {
    name: 'run_id',
    label: t('adminTasks.runId'),
    field: 'extra_data',
    align: 'left',
  },
  {
    name: 'message',
    label: t('adminTasks.message'),
    field: 'message',
    align: 'left',
  },
])

const categories = computed(() => {
  const seen = new Set()
  const result = []
  for (const task of tasks.value || []) {
    if (!seen.has(task.category)) {
      seen.add(task.category)
      result.push({ id: task.category })
    }
  }
  return result
})

function tasksByCategory(category) {
  return (tasks.value || []).filter((t) => t.category === category)
}

function categoryLabel(category) {
  const map = {
    downloads: t('adminTasks.categoryDownloads'),
    metadata: t('adminTasks.categoryMetadata'),
    cleanup: t('adminTasks.categoryCleanup'),
    search: t('adminTasks.categorySearch'),
  }
  return map[category] ?? category
}

function categoryIcon(category) {
  const map = {
    downloads: 'mdi-download',
    metadata: 'mdi-database-refresh',
    cleanup: 'mdi-broom',
    search: 'mdi-magnify',
  }
  return map[category] ?? 'mdi-cog'
}

function categoryColor(category) {
  const map = {
    downloads: 'primary',
    metadata: 'secondary',
    cleanup: 'warning',
    search: 'info',
  }
  return map[category] ?? 'grey'
}

function taskName(task) {
  const key = `adminTasks.${task.id}_name`
  const val = t(key)
  return val !== key ? val : task.name
}

function taskDesc(task) {
  const key = `adminTasks.${task.id}_desc`
  const val = t(key)
  return val !== key ? val : task.description
}

async function runTask(task) {
  runningTask.value = task.id
  try {
    await runTaskApi(task.id)
    await loadTaskHistory()
  } catch (err) {
    logger.error('Failed to run task:', err)
  } finally {
    runningTask.value = null
  }
}

function taskEventExtra(entry) {
  if (!entry?.extra_data) return {}
  try {
    return JSON.parse(entry.extra_data)
  } catch {
    return {}
  }
}

function shortRunId(runId) {
  return runId ? runId.slice(0, 8) : '-'
}

function historyStatusColor(status) {
  if (status === 'failed') return 'negative'
  if (status === 'completed') return 'positive'
  if (status === 'queued') return 'info'
  return 'grey'
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString() : '-'
}

async function loadTaskHistory() {
  historyLoading.value = true
  try {
    const data = await getTaskHistory({ status: historyStatus.value, per_page: 50 })
    taskHistory.value = data.items || []
  } catch (err) {
    logger.error('Failed to load task history:', err)
  } finally {
    historyLoading.value = false
  }
}

async function loadTaskRun(runId) {
  if (!runId) return
  try {
    const data = await getTaskRun(runId)
    selectedRun.value = data
    showRunDialog.value = true
  } catch (err) {
    logger.error('Failed to load task run:', err)
  }
}

onMounted(() => {
  loadTaskHistory()
})
</script>

<style scoped>
.task-card {
  min-width: 320px;
  max-width: 420px;
  flex: 1;
}
</style>
