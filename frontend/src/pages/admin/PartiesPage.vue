<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('adminWatchParties.title') }}</div>

    <!-- Stats Cards -->
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-sm-4">
        <q-card flat bordered>
          <q-card-section class="text-center">
            <div class="text-h3 text-primary">{{ parties.length }}</div>
            <div class="text-caption text-grey">{{ $t('adminWatchParties.totalParties') }}</div>
          </q-card-section>
        </q-card>
      </div>
      <div class="col-12 col-sm-4">
        <q-card flat bordered>
          <q-card-section class="text-center">
            <div class="text-h3 text-positive">{{ totalConnected }}</div>
            <div class="text-caption text-grey">{{ $t('adminWatchParties.connectedUsers') }}</div>
          </q-card-section>
        </q-card>
      </div>
      <div class="col-12 col-sm-4">
        <q-card flat bordered>
          <q-card-section class="text-center">
            <div class="text-h3 text-info">{{ totalMembers }}</div>
            <div class="text-caption text-grey">{{ $t('adminWatchParties.totalMembers') }}</div>
          </q-card-section>
        </q-card>
      </div>
    </div>

    <!-- Parties Table -->
    <q-card flat bordered>
      <q-table
        :rows="parties"
        :columns="columns"
        row-key="guid"
        :loading="loading"
        flat
        bordered
        dark
        :rows-per-page-options="[10, 20, 50]"
        :pagination="{ rowsPerPage: 20 }"
        :no-data-label="$t('adminWatchParties.noParties')"
      >
        <!-- Name Column -->
        <template v-slot:body-cell-name="props">
          <q-td :props="props">
            <div class="text-weight-medium">
              {{ props.row.name || $t('watchParty.unnamed') }}
            </div>
            <div class="text-caption text-grey">
              {{ props.row.party_code }}
            </div>
          </q-td>
        </template>

        <!-- Owner Column -->
        <template v-slot:body-cell-owner_name="props">
          <q-td :props="props">
            {{ props.row.owner_name }}
          </q-td>
        </template>

        <!-- Members Column -->
        <template v-slot:body-cell-members="props">
          <q-td :props="props">
            <q-chip
              :color="props.row.connected_count > 0 ? 'positive' : 'grey'"
              text-color="white"
              size="sm"
            >
              {{ props.row.connected_count }} / {{ props.row.member_count }}
            </q-chip>
          </q-td>
        </template>

        <!-- Allow Control Column -->
        <template v-slot:body-cell-allow_control="props">
          <q-td :props="props">
            <q-icon
              :name="props.value ? 'mdi-check-circle' : 'mdi-close-circle'"
              :color="props.value ? 'positive' : 'grey'"
              size="sm"
            />
          </q-td>
        </template>

        <!-- Created Column -->
        <template v-slot:body-cell-created_at="props">
          <q-td :props="props">
            {{ formatDate(props.value) }}
          </q-td>
        </template>

        <!-- Expires Column -->
        <template v-slot:body-cell-expires_at="props">
          <q-td :props="props">
            {{ formatDate(props.value) }}
          </q-td>
        </template>

        <!-- Actions Column -->
        <template v-slot:body-cell-actions="props">
          <q-td :props="props">
            <q-btn
              size="sm"
              color="negative"
              round
              dense
              icon="mdi-stop"
              @click="confirmEnd(props.row)"
            >
              <q-tooltip>{{ $t('adminWatchParties.endParty') }}</q-tooltip>
            </q-btn>
          </q-td>
        </template>
      </q-table>
    </q-card>

    <!-- End Confirmation Dialog -->
    <q-dialog v-model="showEndDialog" persistent>
      <q-card dark>
        <q-card-section class="row items-center">
          <q-avatar icon="mdi-alert" color="negative" text-color="white" />
          <span class="q-ml-sm">{{ $t('adminWatchParties.endConfirm') }}</span>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="$t('common.cancel')" @click="showEndDialog = false" />
          <q-btn
            flat
            :label="$t('adminWatchParties.endParty')"
            color="negative"
            @click="endParty"
            :loading="ending"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'
import { formatDate } from 'src/composables/useMediaFormatters'

const { t } = useI18n()

const parties = ref([])
const loading = ref(false)
const ending = ref(false)
const showEndDialog = ref(false)
const partyToEnd = ref(null)

const totalConnected = computed(() => parties.value.reduce((sum, p) => sum + p.connected_count, 0))

const totalMembers = computed(() => parties.value.reduce((sum, p) => sum + p.member_count, 0))

const columns = computed(() => [
  {
    name: 'name',
    label: t('adminWatchParties.colName'),
    align: 'left',
    field: 'name',
    sortable: true,
  },
  {
    name: 'owner_name',
    label: t('adminWatchParties.colOwner'),
    align: 'left',
    field: 'owner_name',
    sortable: true,
  },
  {
    name: 'media_title',
    label: t('adminWatchParties.colMedia'),
    align: 'left',
    field: 'media_title',
    format: (val) => val || '-',
    sortable: true,
  },
  {
    name: 'members',
    label: t('adminWatchParties.colMembers'),
    align: 'center',
    field: 'member_count',
    sortable: true,
  },
  {
    name: 'allow_control',
    label: t('adminWatchParties.colAllowControl'),
    align: 'center',
    field: 'allow_control',
    sortable: true,
  },
  {
    name: 'created_at',
    label: t('adminWatchParties.colCreated'),
    align: 'left',
    field: 'created_at',
    sortable: true,
  },
  {
    name: 'expires_at',
    label: t('adminWatchParties.colExpires'),
    align: 'left',
    field: 'expires_at',
    sortable: true,
  },
  {
    name: 'actions',
    label: t('common.actions'),
    align: 'center',
    field: 'actions',
  },
])

async function loadParties() {
  loading.value = true
  try {
    const response = await api.get('/api/parties/admin/all')
    parties.value = response.data
  } catch (error) {
    logger.error('Error loading watch parties:', error)
  } finally {
    loading.value = false
  }
}

function confirmEnd(party) {
  partyToEnd.value = party
  showEndDialog.value = true
}

async function endParty() {
  ending.value = true
  try {
    await api.delete(`/api/parties/admin/${partyToEnd.value.guid}`)
    showEndDialog.value = false
    partyToEnd.value = null
    await loadParties()
  } catch (error) {
    logger.error('Error ending party:', error)
  } finally {
    ending.value = false
  }
}

onMounted(() => {
  loadParties()
})
</script>
