<template>
  <q-page class="q-pa-md">
    <div class="row items-center justify-between q-mb-md">
      <div>
        <div class="text-h4">{{ $t('adminRuntimes.title') }}</div>
        <div class="text-caption text-grey-5">{{ $t('adminRuntimes.subtitle') }}</div>
      </div>
      <q-btn
        color="primary"
        icon="mdi-plus"
        :label="$t('adminRuntimes.createRuntime')"
        no-caps
        @click="openCreate"
      />
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="flex flex-center" style="min-height: 400px">
      <q-spinner color="primary" size="3em" />
    </div>

    <!-- Runtimes List -->
    <q-table
      v-else
      :rows="runtimes"
      :columns="columns"
      row-key="guid"
      :pagination="{ rowsPerPage: 0 }"
      hide-pagination
      flat
      bordered
      dark
    >
      <template v-slot:body-cell-name="props">
        <q-td :props="props">
          <div class="row items-center q-gutter-xs">
            <span class="text-weight-medium">{{ props.row.name }}</span>
            <q-chip
              v-if="props.row.is_builtin"
              dense
              size="sm"
              color="blue-grey-7"
              text-color="white"
              :label="$t('adminRuntimes.builtin')"
            />
          </div>
        </q-td>
      </template>

      <template v-slot:body-cell-docker_image="props">
        <q-td :props="props">
          <code class="runtime-image">{{ props.row.docker_image }}</code>
        </q-td>
      </template>

      <template v-slot:body-cell-runtime_profile="props">
        <q-td :props="props">
          <q-chip dense size="sm" color="deep-purple-6" text-color="white"
            :label="props.row.runtime_profile" />
        </q-td>
      </template>

      <template v-slot:body-cell-state_scope="props">
        <q-td :props="props">
          <q-chip
            dense
            size="sm"
            :color="props.row.state_scope === 'user' ? 'teal-7' : 'grey-8'"
            text-color="white"
            :label="$t(`adminRuntimes.scope.${props.row.state_scope}`)"
          />
        </q-td>
      </template>

      <template v-slot:body-cell-env="props">
        <q-td :props="props">
          <span class="text-grey-5">{{ envCount(props.row.env) }}</span>
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
            @click="openEdit(props.row)"
          >
            <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
          </q-btn>
          <q-btn
            flat
            dense
            round
            icon="mdi-delete"
            color="negative"
            :disable="props.row.is_builtin"
            @click="confirmDelete(props.row)"
          >
            <q-tooltip>
              {{ props.row.is_builtin ? $t('adminRuntimes.builtinLocked') : $t('common.delete') }}
            </q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <!-- Create / Edit Dialog -->
    <q-dialog v-model="showFormDialog" persistent>
      <q-card dark style="min-width: 560px; max-width: 90vw">
        <q-card-section>
          <div class="text-h6">
            {{ editing ? $t('adminRuntimes.editRuntime') : $t('adminRuntimes.createRuntime') }}
          </div>
        </q-card-section>

        <q-form @submit.prevent="save">
          <q-card-section class="q-gutter-md">
            <q-input
              v-model.trim="form.name"
              dense
              outlined
              dark
              :label="$t('adminRuntimes.name')"
              :hint="$t('adminRuntimes.nameHint')"
              :disable="editing && form.is_builtin"
              :rules="[(v) => !!v || $t('adminRuntimes.required')]"
            />
            <q-input
              v-model.trim="form.kind"
              dense
              outlined
              dark
              :label="$t('adminRuntimes.kind')"
              :hint="$t('adminRuntimes.kindHint')"
              :rules="[(v) => !!v || $t('adminRuntimes.required')]"
            />
            <q-input
              v-model.trim="form.docker_image"
              dense
              outlined
              dark
              :label="$t('adminRuntimes.dockerImage')"
              :hint="$t('adminRuntimes.dockerImageHint')"
              :error="Boolean(imageError)"
              :error-message="imageError"
              :rules="[(v) => !!v || $t('adminRuntimes.required')]"
            />
            <div class="row q-col-gutter-md">
              <q-select
                class="col-12 col-sm-6"
                v-model="form.runtime_profile"
                :options="runtimeProfileOptions"
                dense
                outlined
                dark
                emit-value
                map-options
                :label="$t('adminRuntimes.runtimeProfile')"
                :hint="$t('adminRuntimes.runtimeProfileHint')"
              />
              <q-select
                class="col-12 col-sm-6"
                v-model="form.state_scope"
                :options="stateScopeOptions"
                dense
                outlined
                dark
                emit-value
                map-options
                :label="$t('adminRuntimes.stateScope')"
                :hint="$t('adminRuntimes.stateScopeHint')"
              />
            </div>

            <!-- Env key-value editor -->
            <div>
              <div class="row items-center justify-between q-mb-xs">
                <div class="text-subtitle2">{{ $t('adminRuntimes.env') }}</div>
                <q-btn
                  flat
                  dense
                  size="sm"
                  icon="mdi-plus"
                  color="primary"
                  :label="$t('adminRuntimes.addVar')"
                  no-caps
                  @click="addEnvRow"
                />
              </div>
              <div class="text-caption text-grey-5 q-mb-sm">
                {{ $t('adminRuntimes.envHint') }}
              </div>
              <div
                v-for="(row, i) in envRows"
                :key="i"
                class="row q-col-gutter-sm items-center q-mb-xs"
              >
                <q-input
                  class="col"
                  v-model.trim="row.key"
                  dense
                  outlined
                  dark
                  :placeholder="$t('adminRuntimes.envKey')"
                />
                <q-input
                  class="col"
                  v-model="row.value"
                  dense
                  outlined
                  dark
                  :placeholder="$t('adminRuntimes.envValue')"
                />
                <q-btn
                  flat
                  dense
                  round
                  icon="mdi-close"
                  color="negative"
                  @click="removeEnvRow(i)"
                />
              </div>
              <div v-if="envRows.length === 0" class="text-caption text-grey-6">
                {{ $t('adminRuntimes.noEnv') }}
              </div>
            </div>
          </q-card-section>

          <q-card-actions align="right" class="q-pa-md">
            <q-btn flat :label="$t('common.cancel')" color="grey-7" v-close-popup />
            <q-btn
              type="submit"
              :label="$t('common.save')"
              color="primary"
              :loading="saving"
              :disable="Boolean(imageError)"
            />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <!-- Delete Confirmation Dialog -->
    <q-dialog v-model="showDeleteDialog" persistent>
      <q-card dark>
        <q-card-section>
          <div class="text-h6">{{ $t('adminRuntimes.deleteRuntime') }}</div>
        </q-card-section>
        <q-card-section class="q-pt-none">
          {{ $t('adminRuntimes.deleteConfirm', { name: runtimeToDelete?.name }) }}
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" color="grey-7" v-close-popup />
          <q-btn
            flat
            :label="$t('common.delete')"
            color="negative"
            :loading="deleting"
            @click="deleteRuntime"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { logger } from 'src/utils/logger'
import {
  listRuntimes,
  createRuntime,
  updateRuntime,
  removeRuntime,
} from 'src/services/gameRuntimesService'

const { t } = useI18n()
const $q = useQuasar()

const DOCKER_IMAGE_PATTERN = /^[A-Za-z0-9._/:@-]+$/

const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const runtimes = ref([])

const showFormDialog = ref(false)
const editing = ref(false)
const editGuid = ref(null)
const form = ref(emptyForm())
const envRows = ref([])

const showDeleteDialog = ref(false)
const runtimeToDelete = ref(null)

const runtimeProfileOptions = [
  { label: 'gow-app (generic launcher)', value: 'gow-app' },
  { label: 'gow-steam (Steam Big Picture)', value: 'gow-steam' },
  { label: 'none (raw container)', value: 'none' },
]
const stateScopeOptions = computed(() => [
  { label: t('adminRuntimes.scope.game'), value: 'game' },
  { label: t('adminRuntimes.scope.user'), value: 'user' },
])

const columns = computed(() => [
  { name: 'name', label: t('adminRuntimes.name'), field: 'name', align: 'left', sortable: true },
  { name: 'kind', label: t('adminRuntimes.kind'), field: 'kind', align: 'left', sortable: true },
  { name: 'docker_image', label: t('adminRuntimes.dockerImage'), field: 'docker_image', align: 'left' },
  { name: 'runtime_profile', label: t('adminRuntimes.runtimeProfile'), field: 'runtime_profile', align: 'left' },
  { name: 'state_scope', label: t('adminRuntimes.stateScope'), field: 'state_scope', align: 'left' },
  { name: 'env', label: t('adminRuntimes.env'), field: 'env', align: 'center' },
  { name: 'actions', label: t('common.actions'), align: 'center' },
])

const imageError = computed(() => validateDockerImage(form.value.docker_image))

function emptyForm() {
  return {
    name: '',
    kind: '',
    docker_image: '',
    runtime_profile: 'gow-app',
    state_scope: 'game',
    is_builtin: false,
  }
}

function envCount(env) {
  const n = env && typeof env === 'object' ? Object.keys(env).length : 0
  return n === 1 ? t('adminRuntimes.oneVar') : t('adminRuntimes.nVars', { n })
}

function validateDockerImage(value) {
  const image = String(value || '').trim()
  if (!image) return ''
  const invalid =
    image.length > 255 ||
    /^[-/:]/.test(image) ||
    image.endsWith('/') ||
    image.includes('//') ||
    image.includes('..') ||
    !DOCKER_IMAGE_PATTERN.test(image)
  return invalid ? t('adminRuntimes.invalidDockerImage') : ''
}

function addEnvRow() {
  envRows.value.push({ key: '', value: '' })
}
function removeEnvRow(i) {
  envRows.value.splice(i, 1)
}

function loadEnvRows(env) {
  const obj = env && typeof env === 'object' ? env : {}
  return Object.entries(obj).map(([key, value]) => ({ key, value: String(value ?? '') }))
}

function collectEnv() {
  const out = {}
  for (const row of envRows.value) {
    const key = String(row.key || '').trim()
    if (key) out[key] = String(row.value ?? '')
  }
  return out
}

const load = async () => {
  loading.value = true
  try {
    runtimes.value = await listRuntimes()
  } catch (error) {
    logger.error('Error loading game runtimes:', error)
    $q.notify({ type: 'negative', message: t('adminRuntimes.loadFailed') })
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = false
  editGuid.value = null
  form.value = emptyForm()
  envRows.value = []
  showFormDialog.value = true
}

function openEdit(row) {
  editing.value = true
  editGuid.value = row.guid
  form.value = {
    name: row.name,
    kind: row.kind,
    docker_image: row.docker_image,
    runtime_profile: row.runtime_profile,
    state_scope: row.state_scope,
    is_builtin: row.is_builtin,
  }
  envRows.value = loadEnvRows(row.env)
  showFormDialog.value = true
}

async function save() {
  if (validateDockerImage(form.value.docker_image)) return
  saving.value = true
  try {
    const payload = {
      kind: form.value.kind,
      docker_image: form.value.docker_image,
      runtime_profile: form.value.runtime_profile,
      state_scope: form.value.state_scope,
      env: collectEnv(),
    }
    if (editing.value) {
      // Don't send `name` for builtins (backend rejects renaming them).
      if (!form.value.is_builtin) payload.name = form.value.name
      await updateRuntime(editGuid.value, payload)
    } else {
      payload.name = form.value.name
      await createRuntime(payload)
    }
    showFormDialog.value = false
    $q.notify({ type: 'positive', message: t('adminRuntimes.saved') })
    await load()
  } catch (error) {
    logger.error('Error saving runtime:', error)
    const detail = error?.response?.data?.detail
    $q.notify({ type: 'negative', message: detail || t('adminRuntimes.saveFailed') })
  } finally {
    saving.value = false
  }
}

function confirmDelete(row) {
  runtimeToDelete.value = row
  showDeleteDialog.value = true
}

async function deleteRuntime() {
  if (!runtimeToDelete.value) return
  deleting.value = true
  try {
    await removeRuntime(runtimeToDelete.value.guid)
    showDeleteDialog.value = false
    runtimeToDelete.value = null
    $q.notify({ type: 'positive', message: t('adminRuntimes.deleted') })
    await load()
  } catch (error) {
    logger.error('Error deleting runtime:', error)
    const detail = error?.response?.data?.detail
    $q.notify({ type: 'negative', message: detail || t('adminRuntimes.deleteFailed') })
  } finally {
    deleting.value = false
  }
}

onMounted(() => load())
</script>

<style scoped>
.runtime-image {
  font-size: 0.8rem;
  color: #b0bec5;
  word-break: break-all;
}
</style>
