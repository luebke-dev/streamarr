<template>
  <!--
    The screen while mpv plays.

    It is deliberately *small*: the video is in mpv's own window, so nothing here is the
    film. What the user needs is a way back, the title, and the two things that are
    otherwise invisible — whether the server is transcoding, and whether playback resumed
    from a stored position. A black screen would leave all three unanswered.
  -->
  <div class="native-playback" data-test="native-playback">
    <div class="native-playback__inner">
      <h2 class="native-playback__title">{{ title }}</h2>

      <p
        v-for="(notice, index) in notices"
        :key="index"
        class="native-playback__notice"
        data-test="notice"
      >
        {{ $t(`playPage.nativePlayback.notice.${notice.kind}`, noticeParams(notice)) }}
      </p>

      <p class="native-playback__hint">
        {{ $t('playPage.nativePlayback.hint') }}
      </p>

      <div class="native-playback__actions">
        <q-btn
          color="primary"
          :label="$t('common.close')"
          no-caps
          @click="$emit('close')"
        />
        <q-btn
          v-if="isResuming"
          outline
          color="primary"
          :label="$t('playPage.nativePlayback.restart')"
          no-caps
          @click="$emit('restart')"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * What the player has to say, as structured facts.
 *
 * The core crate produces these as typed variants rather than sentences, because the
 * default language here is `en-US` and a sentence assembled in Rust could not be
 * translated afterwards — the position of a number differs between languages. Each
 * variant carries a `kind`, which is its translation key, plus whatever data the message
 * needs.
 */
defineProps({
  title: { type: String, default: '' },
  notices: { type: Array, default: () => [] },
  isResuming: { type: Boolean, default: false },
})

defineEmits(['close', 'restart'])

/** The interpolation values for one notice, formatted for the current locale. */
function noticeParams(notice) {
  if (notice?.kind !== 'resuming') return {}
  // Formatted here rather than in Rust: a duration is written differently in different
  // locales, and `toLocaleTimeString` knows that.
  const total = Math.max(0, Math.round(notice.position_seconds || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const pad = (value) => String(value).padStart(2, '0')
  return {
    position: hours > 0
      ? `${hours}:${pad(minutes)}:${pad(seconds)}`
      : `${minutes}:${pad(seconds)}`,
  }
}
</script>

<style scoped>
.native-playback {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: 2rem;
}

.native-playback__inner {
  max-width: 32rem;
  text-align: center;
}

.native-playback__title {
  margin-bottom: 1rem;
}

.native-playback__notice {
  opacity: 0.9;
}

.native-playback__hint {
  opacity: 0.7;
  font-size: 0.9rem;
}

.native-playback__actions {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
  margin-top: 1.5rem;
}
</style>
