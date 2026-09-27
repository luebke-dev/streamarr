<!--
  DesktopReportDialog — "Report a problem" for the desktop app.

  Distinct from `ReportProblemDialog.vue`, which reports *content* problems
  ("wrong language", "bad audio") about a specific medium. This one reports a
  *client* problem — something not playing at all, a crash, a black picture — and
  attaches the diagnostics a maintainer needs to answer it.

  Desktop only: the report is assembled by the shell, which is the only place that
  can read mpv's log files and ask for mpv's and GStreamer's versions.

  The preview comes first, deliberately. Sending a diagnostic bundle to a server
  is not something to do quietly: the user sees exactly what would be sent, and
  the command that builds it takes no arguments, so neither the page nor a bug in
  it can widen what leaves the machine.
-->
<template>
  <q-dialog :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)">
    <q-card dark style="min-width: 460px; max-width: 90vw">
      <q-card-section>
        <div class="text-h6">{{ $t('desktopReport.title') }}</div>
        <div class="text-caption text-grey-5">{{ $t('desktopReport.subtitle') }}</div>
      </q-card-section>

      <q-card-section v-if="preview">
        <q-list dense dark>
          <q-item>
            <q-item-section side><q-icon name="mdi-information-outline" /></q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('desktopReport.appVersion') }}</q-item-label>
            </q-item-section>
            <q-item-section side>{{ preview.appVersion }}</q-item-section>
          </q-item>
          <q-item>
            <q-item-section side><q-icon name="mdi-monitor" /></q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('desktopReport.platform') }}</q-item-label>
            </q-item-section>
            <q-item-section side>{{ preview.platform }}</q-item-section>
          </q-item>
          <q-item>
            <q-item-section side><q-icon name="mdi-play-box" /></q-item-section>
            <q-item-section>
              <q-item-label>mpv</q-item-label>
            </q-item-section>
            <q-item-section side>
              <!-- Stated, not omitted: "not installed" is a finding. -->
              {{ preview.mpvVersion || $t('desktopReport.notInstalled') }}
            </q-item-section>
          </q-item>
          <q-item>
            <q-item-section side><q-icon name="mdi-video-box" /></q-item-section>
            <q-item-section>
              <q-item-label>GStreamer</q-item-label>
            </q-item-section>
            <q-item-section side>
              {{ preview.gstreamerVersion || $t('desktopReport.notInBuild') }}
            </q-item-section>
          </q-item>
          <q-item>
            <q-item-section side><q-icon name="mdi-file-document-outline" /></q-item-section>
            <q-item-section>
              <q-item-label>{{ $t('desktopReport.logs') }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <span v-if="preview.hasLogs">
                {{ $t('desktopReport.logCount', { count: preview.logCount, kb: logKb }) }}
              </span>
              <span v-else class="text-grey-6">{{ $t('desktopReport.noLogs') }}</span>
            </q-item-section>
          </q-item>
        </q-list>

        <!-- What is *not* sent. Worth saying explicitly: a user deciding whether
             to press the button needs to know, and "we respect your privacy" is
             not an answer to "does this contain my token". -->
        <div class="text-caption text-grey-6 q-mt-sm">
          {{ $t('desktopReport.excluded') }}
        </div>
      </q-card-section>

      <!-- The collected text, shown when sending failed. A report that could not
           be sent is still valuable, and the user can copy it out. -->
      <q-card-section v-if="failedMessage">
        <q-banner dense class="bg-negative text-white">
          {{ failedProblem }}
        </q-banner>
        <div v-if="failedAdvice" class="text-caption text-grey-5 q-mt-xs">
          {{ failedAdvice }}
        </div>
        <q-input
          :model-value="failedMessage"
          type="textarea"
          readonly
          autogrow
          dark
          outlined
          class="q-mt-sm"
          :aria-label="$t('desktopReport.collected')"
        />
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat :label="$t('common.cancel')" @click="close" />
        <q-btn
          color="primary"
          :label="$t('desktopReport.send')"
          :loading="sending"
          :disable="sending"
          @click="send"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { isDesktopApp } from 'src/utils/desktopPlatform'
import { logger } from 'src/utils/logger'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'sent'])

let invokeFn = null
async function loadShell() {
  if (invokeFn) return true
  try {
    const core = await import('@tauri-apps/api/core')
    invokeFn = core.invoke
    return true
  } catch {
    return false
  }
}

const preview = ref(null)
const sending = ref(false)
const failedProblem = ref('')
const failedAdvice = ref('')
const failedMessage = ref('')

const logKb = computed(() => Math.max(1, Math.round((preview.value?.logBytes || 0) / 1024)))

const isSupported = computed(() => isDesktopApp())

function close() {
  emit('update:modelValue', false)
}

// Loads the preview. The user must see what would be sent *before* deciding to
// send it.
async function loadPreview() {
  failedProblem.value = ''
  failedAdvice.value = ''
  failedMessage.value = ''
  if (!isSupported.value) return
  if (!(await loadShell())) return
  try {
    preview.value = await invokeFn('report_preview')
  } catch (error) {
    logger.warn('Report-Vorschau nicht verfügbar:', error)
    preview.value = null
  }
}

// `immediate` matters and its absence was a real defect: a `watch` without it
// fires only on *change*, so a dialog that is mounted already open — which is how
// this component is used, and how the test mounts it — never loaded the preview
// and showed an empty list. The user would have seen nothing to approve.
watch(() => props.modelValue, (open) => open && loadPreview(), { immediate: true })

async function send() {
  if (!(await loadShell())) return
  sending.value = true
  failedProblem.value = ''
  failedAdvice.value = ''
  failedMessage.value = ''
  try {
    const outcome = await invokeFn('report_problem')
    if (outcome?.kind === 'sent') {
      emit('sent', outcome)
      close()
      return
    }
    // Not thrown but returned: the report was built and could not be delivered,
    // and the collected text is the useful part.
    failedProblem.value = outcome?.problem || ''
    failedAdvice.value = outcome?.advice || ''
    failedMessage.value = outcome?.message || ''
  } catch (error) {
    // A thrown error means the command itself failed, which is a different
    // situation from a server refusing the report.
    logger.error('Bericht konnte nicht erstellt werden:', error)
    failedProblem.value = String(error)
  } finally {
    sending.value = false
  }
}
</script>
