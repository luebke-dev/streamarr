<template>
  <q-dialog ref="dialogRef" @hide="onDialogHide">
    <q-card dark style="min-width: 400px; max-width: 500px">
      <q-card-section>
        <div class="text-h6">{{ t('common.addToListTitle', { title: mediaTitle }) }}</div>
        <div class="text-body2 text-grey q-mt-xs">{{ t('common.selectList') }}</div>
      </q-card-section>

      <q-card-section class="q-pt-none">
        <!-- Search input -->
        <q-input
          v-if="lists.length > 3"
          v-model="searchQuery"
          :placeholder="t('common.searchLists')"
          outlined
          dense
          class="q-mb-md"
        >
          <template #prepend>
            <q-icon name="mdi-magnify" />
          </template>
          <template v-if="searchQuery" #append>
            <q-icon name="mdi-close" class="cursor-pointer" @click="searchQuery = ''" />
          </template>
        </q-input>

        <!-- Loading state -->
        <div v-if="loadingLists" class="text-center q-pa-md">
          <q-spinner color="primary" size="2em" />
          <div class="text-grey q-mt-sm">{{ t('common.loadingLists') }}</div>
        </div>

        <!-- No lists -->
        <div v-else-if="lists.length === 0" class="text-center q-pa-md">
          <q-icon name="mdi-playlist-plus" size="3em" color="grey-6" />
          <div class="text-grey q-mt-sm">{{ t('common.noListsAvailable') }}</div>
          <div class="text-caption text-grey">{{ t('common.createListFirst') }}</div>
        </div>

        <!-- List items -->
        <q-list v-else separator>
          <q-item
            v-for="list in filteredLists"
            :key="list.guid"
            clickable
            v-ripple
            @click="selectList(list)"
            :disable="addingToList === list.guid"
          >
            <q-item-section avatar>
              <q-icon name="mdi-playlist-play" color="primary" />
            </q-item-section>
            <q-item-section>
              <q-item-label>{{ getListName(list) }}</q-item-label>
              <q-item-label caption
                >{{ list.item_count || 0 }} {{ t('common.items') }}</q-item-label
              >
            </q-item-section>
            <q-item-section side v-if="addingToList === list.guid">
              <q-spinner color="primary" size="1.5em" />
            </q-item-section>
          </q-item>

          <!-- No matching results -->
          <q-item v-if="filteredLists.length === 0 && searchQuery">
            <q-item-section class="text-center text-grey">
              {{ t('common.noListsMatching', { query: searchQuery }) }}
            </q-item-section>
          </q-item>
        </q-list>

        <!-- Create new list -->
        <div class="q-mt-md">
          <q-separator class="q-mb-md" />
          <q-input
            v-model="newListName"
            :placeholder="t('common.createNewList')"
            outlined
            dense
            @keyup.enter="createAndAdd"
          >
            <template #prepend>
              <q-icon name="mdi-plus" />
            </template>
            <template #append>
              <q-btn
                v-if="newListName.trim()"
                flat
                dense
                icon="mdi-check"
                color="primary"
                :loading="creatingList"
                @click="createAndAdd"
              />
            </template>
          </q-input>
        </div>
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat :label="t('common.cancel')" color="grey-7" @click="onDialogCancel" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useDialogPluginComponent } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useListsStore } from 'stores/lists'
import { useAuthStore } from 'stores/auth'
import { useListTranslation } from 'src/composables/useListTranslation'
import { logger } from 'src/utils/logger'

const { t } = useI18n()

const props = defineProps({
  mediaTitle: { type: String, required: true },
  mediaGuid: { type: String, required: true },
  mediaType: { type: String, required: true },
})

defineEmits([...useDialogPluginComponent.emits])
const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()

const listsStore = useListsStore()
const authStore = useAuthStore()
const { getListName } = useListTranslation()

const searchQuery = ref('')
const newListName = ref('')
const loadingLists = ref(false)
const addingToList = ref(null)
const creatingList = ref(false)

const lists = computed(() => listsStore.getUserLists)

const filteredLists = computed(() => {
  if (!searchQuery.value) return lists.value
  const q = searchQuery.value.toLowerCase()
  return lists.value.filter((list) => getListName(list).toLowerCase().includes(q))
})

// Map frontend media types to backend list item types
function getItemType(mediaType) {
  const typeMap = {
    MOVIES: 'movie',
    SHOWS: 'show',
    GAMES: 'game',
  }
  return typeMap[mediaType] || 'movie'
}

async function selectList(list) {
  addingToList.value = list.guid
  try {
    await listsStore.addItemToList(list.guid, {
      item_type: getItemType(props.mediaType),
      item_guid: props.mediaGuid,
    })
    onDialogOK({ list })
  } catch (error) {
    logger.error('Failed to add item to list:', error)
    addingToList.value = null
  }
}

async function createAndAdd() {
  const name = newListName.value.trim()
  if (!name) return

  creatingList.value = true
  try {
    const newList = await listsStore.createList({ name })
    await listsStore.addItemToList(newList.guid, {
      item_type: getItemType(props.mediaType),
      item_guid: props.mediaGuid,
    })
    onDialogOK({ list: newList })
  } catch (error) {
    logger.error('Failed to create list and add item:', error)
  } finally {
    creatingList.value = false
  }
}

onMounted(async () => {
  if (!listsStore.initialized && authStore.user?.guid) {
    loadingLists.value = true
    try {
      await listsStore.fetchUserLists(authStore.user.guid)
    } finally {
      loadingLists.value = false
    }
  }
})
</script>
