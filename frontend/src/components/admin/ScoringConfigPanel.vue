<template>
  <div>
    <q-form @submit.prevent="onSubmit">
      <!-- Resolution Weights -->
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1 q-mb-sm">
            <q-icon name="mdi-monitor-screenshot" class="q-mr-xs" />
            {{ $t('scoringRules.resolution') }}
          </div>
          <div class="q-gutter-sm">
            <WeightRow
              v-for="key in resolutionKeys"
              :key="key"
              :label="key"
              :model-value="form.resolution[key]"
              @update:model-value="form.resolution[key] = $event"
            />
          </div>
        </q-card-section>
      </q-card>

      <!-- Source Weights -->
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1 q-mb-sm">
            <q-icon name="mdi-disc" class="q-mr-xs" />
            {{ $t('scoringRules.source') }}
          </div>
          <div class="q-gutter-sm">
            <WeightRow
              v-for="key in sourceKeys"
              :key="key"
              :label="key"
              :model-value="form.source[key]"
              @update:model-value="form.source[key] = $event"
            />
          </div>
        </q-card-section>
      </q-card>

      <!-- Codec Weights -->
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1 q-mb-sm">
            <q-icon name="mdi-video-box" class="q-mr-xs" />
            {{ $t('scoringRules.codec') }}
          </div>
          <div class="q-gutter-sm">
            <WeightRow
              v-for="key in codecKeys"
              :key="key"
              :label="key"
              :model-value="form.codec[key]"
              @update:model-value="form.codec[key] = $event"
            />
          </div>
        </q-card-section>
      </q-card>

      <!-- Audio Weights -->
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1 q-mb-sm">
            <q-icon name="mdi-volume-high" class="q-mr-xs" />
            {{ $t('scoringRules.audio') }}
          </div>
          <div class="q-gutter-sm">
            <WeightRow
              v-for="key in audioKeys"
              :key="key"
              :label="key"
              :model-value="form.audio[key]"
              @update:model-value="form.audio[key] = $event"
            />
          </div>
        </q-card-section>
      </q-card>

      <!-- Bonuses -->
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1 q-mb-sm">
            <q-icon name="mdi-star-plus" class="q-mr-xs" />
            {{ $t('scoringRules.bonuses') }}
          </div>
          <div class="q-gutter-sm">
            <WeightRow
              label="HDR"
              :model-value="form.hdr_bonus"
              @update:model-value="form.hdr_bonus = $event"
            />
            <WeightRow
              label="Dolby Vision"
              :model-value="form.dolby_vision_bonus"
              @update:model-value="form.dolby_vision_bonus = $event"
            />
            <WeightRow
              v-if="mediaType === 'movies'"
              label="Remux"
              :model-value="form.remux_bonus"
              @update:model-value="form.remux_bonus = $event"
            />
            <WeightRow
              label="PROPER"
              :model-value="form.proper_bonus"
              @update:model-value="form.proper_bonus = $event"
            />
            <WeightRow
              label="REPACK"
              :model-value="form.repack_bonus"
              @update:model-value="form.repack_bonus = $event"
            />
            <WeightRow
              :label="$t('scoringRules.trustedGroupBonus')"
              :model-value="form.trusted_group_bonus"
              @update:model-value="form.trusted_group_bonus = $event"
            />
          </div>
        </q-card-section>
      </q-card>

      <!-- Trusted Groups -->
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1 q-mb-sm">
            <q-icon name="mdi-shield-check" class="q-mr-xs" />
            {{ $t('scoringRules.trustedGroups') }}
          </div>
          <div class="text-caption text-grey-6 q-mb-sm">
            {{ $t('scoringRules.trustedGroupsHint') }}
          </div>
          <q-select
            v-model="form.trusted_groups"
            multiple
            use-chips
            use-input
            new-value-mode="add-unique"
            outlined
            dense
            :label="$t('scoringRules.trustedGroups')"
          />
        </q-card-section>
      </q-card>

      <!-- Blocked Groups -->
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1 q-mb-sm">
            <q-icon name="mdi-shield-off" class="q-mr-xs" />
            {{ $t('scoringRules.blockedGroups') }}
          </div>
          <div class="text-caption text-grey-6 q-mb-sm">
            {{ $t('scoringRules.blockedGroupsHint') }}
          </div>
          <q-select
            v-model="form.blocked_groups"
            multiple
            use-chips
            use-input
            new-value-mode="add-unique"
            outlined
            dense
            :label="$t('scoringRules.blockedGroups')"
          />
        </q-card-section>
      </q-card>

      <!-- Language Scoring -->
      <q-card flat bordered class="q-mb-md">
        <q-card-section>
          <div class="text-subtitle1 q-mb-sm">
            <q-icon name="mdi-translate" class="q-mr-xs" />
            {{ $t('scoringRules.languageSection') }}
          </div>
          <div class="q-gutter-sm">
            <WeightRow
              :label="$t('scoringRules.languageMatchBonus')"
              :model-value="form.language_match_bonus"
              @update:model-value="form.language_match_bonus = $event"
            />
            <WeightRow
              :label="$t('scoringRules.languageMismatchPenalty')"
              :model-value="form.language_mismatch_penalty"
              @update:model-value="form.language_mismatch_penalty = $event"
            />
          </div>
        </q-card-section>
      </q-card>

      <!-- Actions -->
      <div class="row q-gutter-sm">
        <q-btn
          type="submit"
          color="primary"
          icon="mdi-content-save"
          :label="$t('common.save')"
          :loading="saving"
        />
        <q-btn
          flat
          color="negative"
          icon="mdi-restore"
          :label="$t('scoringRules.resetButton')"
          @click="$emit('reset')"
        />
      </div>
    </q-form>
  </div>
</template>

<script setup>
import { ref, watch, computed } from 'vue'
import WeightRow from 'components/admin/WeightRow.vue'

const props = defineProps({
  config: {
    type: Object,
    required: true,
  },
  mediaType: {
    type: String,
    required: true,
  },
  loading: Boolean,
  saving: Boolean,
})

const emit = defineEmits(['save', 'reset'])

// Deep clone to avoid mutating prop
const form = ref(JSON.parse(JSON.stringify(props.config)))

watch(
  () => props.config,
  (newConfig) => {
    form.value = JSON.parse(JSON.stringify(newConfig))
  },
  { deep: true },
)

// Dynamic keys based on what's in the config
const resolutionKeys = computed(() => Object.keys(form.value.resolution || {}))
const sourceKeys = computed(() => Object.keys(form.value.source || {}))
const codecKeys = computed(() => Object.keys(form.value.codec || {}))
const audioKeys = computed(() => Object.keys(form.value.audio || {}))

function onSubmit() {
  emit('save', JSON.parse(JSON.stringify(form.value)))
}
</script>
