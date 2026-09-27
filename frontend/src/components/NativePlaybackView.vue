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

      <p v-if="notice" class="native-playback__notice" data-test="notice">
        {{ notice }}
      </p>

      <p class="native-playback__hint">
        Die Wiedergabe läuft im eigenen Fenster (mpv). Mit <kbd>F</kbd> wird es
        vollbild, mit <kbd>Leertaste</kbd> pausiert.
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
          label="Von vorne beginnen"
          no-caps
          @click="$emit('restart')"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, default: '' },
  /** A sentence about resuming or transcoding, produced by the core crate. */
  notice: { type: String, default: null },
  isResuming: { type: Boolean, default: false },
})

defineEmits(['close', 'restart'])
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
