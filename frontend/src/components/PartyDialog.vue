<template>
  <q-dialog ref="dialogRef" @hide="onDialogHide">
    <q-card dark style="min-width: 400px">
      <q-card-section>
        <div class="text-h6">{{ $t('watchParty.title') }}</div>
      </q-card-section>

      <q-tabs
        v-model="tab"
        dense
        class="text-grey"
        active-color="primary"
        indicator-color="primary"
        align="justify"
      >
        <q-tab name="create" :label="$t('watchParty.create')" />
        <q-tab name="join" :label="$t('watchParty.join')" />
      </q-tabs>

      <q-separator />

      <q-tab-panels v-model="tab" animated>
        <!-- Create Watch Party -->
        <q-tab-panel name="create">
          <div class="q-gutter-md">
            <q-input
              v-model="partyName"
              :label="$t('watchParty.partyName')"
              outlined
              dense
              :placeholder="$t('watchParty.partyNamePlaceholder')"
            />

            <q-toggle
              v-model="allowControl"
              :label="$t('watchParty.allowControl')"
              color="primary"
            />

            <div class="text-caption text-grey">
              {{ $t('watchParty.allowControlHint') }}
            </div>
          </div>
        </q-tab-panel>

        <!-- Join Watch Party -->
        <q-tab-panel name="join">
          <div class="q-gutter-md">
            <q-input
              v-model="joinCode"
              :label="$t('watchParty.partyCode')"
              outlined
              dense
              mask="XXXXXX"
              :placeholder="$t('watchParty.enterCode')"
              :rules="[(val) => (val && val.length === 6) || $t('watchParty.codeRequired')]"
            >
              <template v-slot:prepend>
                <q-icon name="mdi-tag" />
              </template>
            </q-input>

            <div class="text-caption text-grey">
              {{ $t('watchParty.codeHint') }}
            </div>
          </div>
        </q-tab-panel>
      </q-tab-panels>

      <q-separator />

      <q-card-actions align="right">
        <q-btn flat :label="$t('watchParty.cancel')" color="grey-7" @click="onDialogCancel" />
        <q-btn
          flat
          :label="tab === 'create' ? $t('watchParty.create') : $t('watchParty.join')"
          color="primary"
          :loading="loading"
          @click="submit"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useDialogPluginComponent } from 'quasar'
import { useI18n } from 'vue-i18n'
import { usePartyStore } from 'stores/party'
import { useRoute, useRouter } from 'vue-router'
import { logger } from 'src/utils/logger'

const props = defineProps({
  initialTab: {
    type: String,
    default: 'create',
  },
  mediaId: {
    type: String,
    default: null,
  },
  mediaType: {
    type: String,
    default: null,
  },
})

defineEmits([...useDialogPluginComponent.emits])

const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()
useI18n()
const route = useRoute()
const router = useRouter()
const partyStore = usePartyStore()

const tab = ref(props.initialTab)
const loading = ref(false)

// Create party fields
const partyName = ref('')
const allowControl = ref(false)

// Join party fields
const joinCode = ref('')

async function submit() {
  loading.value = true

  try {
    if (tab.value === 'create') {
      await createParty()
    } else {
      await joinParty()
    }

    onDialogOK()
    reset()
  } catch (error) {
    logger.error('Watch party action failed:', error)
  } finally {
    loading.value = false
  }
}

async function createParty() {
  // Try to get media info from props, then fall back to route
  let mediaId = props.mediaId
  let mediaType = props.mediaType

  if (!mediaId && route.params.id) {
    mediaId = route.params.id
    mediaType = route.path.includes('/movies/') ? 'movie' : 'episode'
  }

  // Create party with or without media info
  await partyStore.createParty(mediaId, mediaType, {
    name: partyName.value || null,
    allowControl: allowControl.value,
  })
}

async function joinParty() {
  if (!joinCode.value || joinCode.value.length !== 6) {
    return
  }

  const partyData = await partyStore.joinParty(joinCode.value.toUpperCase())

  // Navigate to PlayPage if the party has active media
  if (partyData?.media_id) {
    router.push({
      name: 'play',
      params: { id: partyData.media_id },
      query: { type: partyData.media_type || 'movie' },
    })
  }
}

function reset() {
  partyName.value = ''
  allowControl.value = false
  joinCode.value = ''
  tab.value = 'create'
}
</script>
