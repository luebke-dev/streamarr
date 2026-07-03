<template>
  <q-card>
    <q-card-section>
      <div class="text-h6">{{ t('editUser.title') }}</div>
    </q-card-section>

    <q-card-section>
      <q-form @submit="$emit('submit')" class="q-gutter-md">
        <q-input
          v-model="model.first_name"
          :label="t('editUser.firstName')"
          :rules="[(val) => !!val || t('editUser.firstNameRequired')]"
          outlined
        />

        <q-input
          v-model="model.last_name"
          :label="t('editUser.lastName')"
          :rules="[(val) => !!val || t('editUser.lastNameRequired')]"
          outlined
        />

        <q-input
          v-model="model.email"
          :label="t('editUser.email')"
          type="email"
          :rules="[
            (val) => !!val || t('editUser.emailRequired'),
            (val) => /.+@.+\..+/.test(val) || t('editUser.emailInvalid'),
          ]"
          outlined
        />

        <q-input
          v-model="model.password"
          :label="t('editUser.password')"
          type="password"
          outlined
          :hint="t('editUser.passwordHint')"
        />

        <q-toggle v-model="model.is_active" :label="t('editUser.active')" />
        <q-toggle v-model="model.is_superuser" :label="t('editUser.superuser')" />

        <q-separator class="q-my-md" />
        <div class="text-subtitle1 q-mb-sm">
          <q-icon name="mdi-translate" class="q-mr-sm" />
          {{ t('editUser.languageSettings') }}
        </div>

        <q-select
          v-model="model.ui_language"
          :options="UI_LANGUAGES"
          :label="t('editUser.uiLanguage')"
          outlined
          emit-value
          map-options
          option-value="value"
          option-label="label"
        >
          <template v-slot:option="scope">
            <q-item v-bind="scope.itemProps">
              <q-item-section avatar>
                <span class="text-h6">{{ scope.opt.flag }}</span>
              </q-item-section>
              <q-item-section>{{ scope.opt.label }}</q-item-section>
            </q-item>
          </template>
          <template v-slot:selected-item="scope">
            <span v-if="scope.opt">{{ scope.opt.flag }} {{ scope.opt.label }}</span>
          </template>
        </q-select>

        <LanguagePrioritySelector
          v-model="model.audio_languages"
          :options="MEDIA_LANGUAGES"
          :label="t('editUser.audioLanguages')"
          :hint="t('editUser.audioLanguagesHint')"
          :dense="false"
        />

        <q-select
          v-model="model.subtitle_language"
          :options="SUBTITLE_LANGUAGES"
          :label="t('editUser.subtitleLanguage')"
          outlined
          emit-value
          map-options
          option-value="value"
          option-label="label"
          clearable
          :hint="t('editUser.subtitleHint')"
        >
          <template v-slot:option="scope">
            <q-item v-bind="scope.itemProps">
              <q-item-section avatar>
                <span class="text-h6">{{ scope.opt.flag }}</span>
              </q-item-section>
              <q-item-section>{{ scope.opt.label }}</q-item-section>
            </q-item>
          </template>
          <template v-slot:selected-item="scope">
            <span v-if="scope.opt">{{ scope.opt.flag }} {{ scope.opt.label }}</span>
          </template>
        </q-select>

        <div class="row q-gutter-sm">
          <q-btn type="submit" color="primary" :label="t('editUser.save')" :loading="loading" />
          <q-btn color="grey-7" :label="t('common.cancel')" @click="$emit('cancel')" />
        </div>
      </q-form>
    </q-card-section>
  </q-card>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import LanguagePrioritySelector from 'src/components/LanguagePrioritySelector.vue'
import { MEDIA_LANGUAGES, SUBTITLE_LANGUAGES, UI_LANGUAGES } from 'src/utils/mediaLanguages'

defineProps({
  loading: { type: Boolean, default: false },
})

defineEmits(['submit', 'cancel'])

const model = defineModel({ type: Object, required: true })

const { t } = useI18n()

</script>
