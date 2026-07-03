<template>
  <div>
    <q-form @submit.prevent="onSubmit">
      <div class="text-caption text-grey-6 q-mb-sm">
        {{ $t('qualityProfile.orderHint') }}
      </div>

      <q-list bordered separator class="rounded-borders q-mb-md">
        <q-item v-for="(item, idx) in form.items" :key="item.id" dense>
          <q-item-section side>
            <div class="column">
              <q-btn
                flat dense round size="sm" icon="mdi-chevron-up"
                :disable="idx === 0"
                @click="move(idx, -1)"
              />
              <q-btn
                flat dense round size="sm" icon="mdi-chevron-down"
                :disable="idx === form.items.length - 1"
                @click="move(idx, 1)"
              />
            </div>
          </q-item-section>

          <q-item-section side>
            <q-checkbox
              v-model="item.allowed"
              :aria-label="$t('qualityProfile.allowed')"
            />
          </q-item-section>

          <q-item-section>
            <q-item-label :class="{ 'text-grey-6': !item.allowed }">
              {{ labelFor(item.id) }}
            </q-item-label>
            <q-item-label caption>{{ item.id }}</q-item-label>
          </q-item-section>

          <q-item-section side>
            <q-radio
              v-model="form.cutoff"
              :val="item.id"
              :disable="!item.allowed"
              :label="$t('qualityProfile.cutoff')"
            />
          </q-item-section>
        </q-item>
      </q-list>

      <q-toggle
        v-model="form.upgrade_allowed"
        :label="$t('qualityProfile.upgradeAllowed')"
        class="q-mb-md"
      />
      <div class="text-caption text-grey-6 q-mb-md">
        {{ $t('qualityProfile.cutoffHint') }}
      </div>

      <div class="row q-gutter-sm">
        <q-btn
          type="submit"
          color="primary"
          :loading="saving"
          :label="$t('common.save')"
          icon="mdi-content-save"
        />
        <q-btn
          flat
          color="grey-7"
          :label="resetLabel"
          icon="mdi-restore"
          @click="$emit('reset')"
        />
      </div>
    </q-form>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  // QualityProfile: { name, items:[{id,allowed}], cutoff, upgrade_allowed, scoring }
  profile: { type: Object, required: true },
  // canonical ladder: [{ id, label, kind }]
  qualities: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
  variant: { type: String, default: 'standard' }, // 'standard' | 'favorites'
})

const emit = defineEmits(['save', 'reset'])

const clone = (o) => JSON.parse(JSON.stringify(o))

// Ensure every canonical rung appears (so admins can enable rungs the stored
// profile omitted), preserving the stored order first.
const buildForm = () => {
  const p = clone(props.profile)
  const known = new Set((p.items || []).map((i) => i.id))
  const items = [...(p.items || [])]
  for (const q of props.qualities) {
    if (!known.has(q.id)) items.push({ id: q.id, allowed: false })
  }
  return {
    name: p.name || 'default',
    items,
    cutoff: p.cutoff || null,
    upgrade_allowed: p.upgrade_allowed !== false,
    scoring: p.scoring ?? null,
  }
}

const form = ref(buildForm())

watch(
  () => [props.profile, props.qualities],
  () => {
    form.value = buildForm()
  },
  { deep: true },
)

const labelMap = computed(() => {
  const m = {}
  for (const q of props.qualities) m[q.id] = q.label
  return m
})
const labelFor = (id) => labelMap.value[id] || id

const resetLabel = computed(() =>
  props.variant === 'favorites'
    ? t('qualityProfile.clearFavorites')
    : t('qualityProfile.resetDefault'),
)

const move = (idx, delta) => {
  const j = idx + delta
  if (j < 0 || j >= form.value.items.length) return
  const arr = form.value.items
  ;[arr[idx], arr[j]] = [arr[j], arr[idx]]
}

const onSubmit = () => {
  const payload = clone(form.value)
  // Drop a cutoff that points at a disallowed/absent rung.
  const allowedIds = new Set(
    payload.items.filter((i) => i.allowed).map((i) => i.id),
  )
  if (!allowedIds.has(payload.cutoff)) {
    payload.cutoff = [...allowedIds][allowedIds.size - 1] || null
  }
  emit('save', payload)
}
</script>
