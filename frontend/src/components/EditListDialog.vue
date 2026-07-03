<template>
  <q-dialog ref="dialogRef" @hide="onDialogHide">
    <q-card dark style="width: 550px; max-width: 95vw">
      <q-card-section>
        <div class="text-h6">{{ t('listPage.editListTitle') }}</div>
      </q-card-section>

      <q-card-section class="q-pt-none q-gutter-md">
        <q-input
          v-model="form.name"
          :label="t('listPage.listName')"
          outlined
          dense
          :rules="[(val) => !!val || t('listPage.listNameRequired')]"
        />

        <q-input
          v-model="form.description"
          :label="t('listPage.listDescription')"
          outlined
          dense
          type="textarea"
          autogrow
        />

        <!-- Translations -->
        <q-expansion-item
          :label="t('listPage.translations')"
          icon="mdi-translate"
          dense
          header-class="text-grey-4"
        >
          <div class="q-gutter-md q-pa-sm">
            <div v-for="loc in availableLocales" :key="loc" class="q-gutter-sm">
              <div class="text-caption text-grey-5">{{ loc }}</div>
              <q-input
                v-model="form.name_translations[loc]"
                :label="t('listPage.listName') + ` (${loc})`"
                outlined
                dense
              />
              <q-input
                v-model="form.description_translations[loc]"
                :label="t('listPage.listDescription') + ` (${loc})`"
                outlined
                dense
                type="textarea"
                autogrow
              />
            </div>
          </div>
        </q-expansion-item>

        <q-select
          v-model="form.visibility"
          :label="t('listPage.listVisibility')"
          :options="visibilityOptions"
          outlined
          dense
          emit-value
          map-options
        />

        <q-input
          v-model="form.tags"
          :label="t('listPage.listTags')"
          :hint="t('listPage.listTagsHint')"
          outlined
          dense
        />
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat :label="t('common.cancel')" color="grey-7" @click="onDialogCancel" />
        <q-btn
          flat
          :label="t('listPage.save')"
          color="primary"
          :loading="saving"
          :disable="!form.name"
          @click="saveList"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useDialogPluginComponent } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useListsStore } from 'stores/lists'
import { logger } from 'src/utils/logger'

const { t, availableLocales } = useI18n({ useScope: 'global' })
const listsStore = useListsStore()

const props = defineProps({
  list: { type: Object, required: true },
})

defineEmits([...useDialogPluginComponent.emits])

const { dialogRef, onDialogHide, onDialogCancel, onDialogOK } = useDialogPluginComponent()

const saving = ref(false)

function buildTranslations(existing) {
  const result = {}
  for (const loc of availableLocales.value) {
    result[loc] = existing?.[loc] || ''
  }
  return result
}

const form = ref({
  name: props.list.name || '',
  description: props.list.description || '',
  visibility: props.list.visibility || 'PRIVATE',
  tags: props.list.tags || '',
  name_translations: buildTranslations(props.list.name_translations),
  description_translations: buildTranslations(props.list.description_translations),
})

const visibilityOptions = computed(() => [
  { label: t('listPage.public'), value: 'PUBLIC' },
  { label: t('listPage.private'), value: 'PRIVATE' },
  { label: t('listPage.unlisted'), value: 'UNLISTED' },
])

function cleanTranslations(obj) {
  const result = {}
  for (const [k, v] of Object.entries(obj)) {
    if (v && v.trim()) result[k] = v.trim()
  }
  return Object.keys(result).length > 0 ? result : null
}

async function saveList() {
  if (!form.value.name) return

  saving.value = true
  try {
    const updated = await listsStore.updateList(props.list.guid, {
      name: form.value.name,
      description: form.value.description || null,
      visibility: form.value.visibility,
      tags: form.value.tags || null,
      name_translations: cleanTranslations(form.value.name_translations),
      description_translations: cleanTranslations(form.value.description_translations),
    })
    onDialogOK(updated)
  } catch (err) {
    logger.error('Error updating list:', err)
  } finally {
    saving.value = false
  }
}
</script>
