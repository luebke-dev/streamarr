<template>
  <q-card flat bordered>
    <q-card-section>
      <div class="text-h6 q-mb-md">
        <q-icon name="mdi-format-list-bulleted" class="q-mr-sm" color="amber" />
        {{ $t('adminUserPage.lists') }}
      </div>

      <div v-if="loading" class="text-center q-pa-lg">
        <q-spinner size="30px" color="primary" />
      </div>

      <div v-else-if="lists.length === 0" class="text-center q-pa-lg text-grey">
        {{ $t('adminUserPage.noLists') }}
      </div>

      <q-table
        v-else
        flat
        bordered
        dark
        :rows="lists"
        :columns="columns"
        row-key="guid"
        :rows-per-page-options="[10, 25]"
      >
        <template #body-cell-visibility="props">
          <q-td :props="props">
            <q-badge
              :color="props.row.visibility === 'PUBLIC' ? 'positive' : 'grey'"
              :label="
                props.row.visibility === 'PUBLIC'
                  ? $t('adminUserPage.listPublic')
                  : $t('adminUserPage.listPrivate')
              "
            />
          </q-td>
        </template>

        <template #body-cell-type="props">
          <q-td :props="props">
            <q-badge
              :color="props.row.list_type === 'SYSTEM' ? 'info' : 'primary'"
              :label="props.row.list_type"
            />
          </q-td>
        </template>
      </q-table>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

defineProps({
  lists: { type: Array, required: true },
  loading: { type: Boolean, default: false },
})

const { t } = useI18n()

const columns = computed(() => [
  {
    name: 'name',
    label: t('adminUserPage.listName'),
    field: 'name',
    align: 'left',
    sortable: true,
  },
  { name: 'type', label: t('adminUserPage.listType'), field: 'list_type', align: 'center' },
  {
    name: 'visibility',
    label: t('adminUserPage.listVisibility'),
    field: 'visibility',
    align: 'center',
  },
  {
    name: 'item_count',
    label: t('adminUserPage.listItems'),
    field: 'item_count',
    align: 'center',
    sortable: true,
  },
  {
    name: 'like_count',
    label: t('adminUserPage.listLikes'),
    field: 'like_count',
    align: 'center',
    sortable: true,
  },
])
</script>
