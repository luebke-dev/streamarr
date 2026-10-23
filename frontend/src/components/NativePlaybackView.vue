<template>
  <!--
    The screen while mpv plays.

    It is small on purpose, but no longer because "the video is somewhere else": since
    ADR 003 the picture is behind this page, so the panel keeps to the bottom and says only
    what the picture cannot — the title, transcoding, resume, and the track choices.
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

      <!--
        The transport controls. They live here rather than in the web player's bar because there
        is no media element to attach to: every action is a command to the shell, which owns the
        player. Seeking is relative on purpose — the panel shows no precise position, so an
        absolute jump would ask the user to guess a number.
      -->
      <div class="native-playback__transport" data-test="native-transport">
        <q-btn
          flat
          dense
          icon="mdi-rewind-10"
          data-test="native-back-10"
          @click="$emit('seek', -10)"
        />
        <q-btn
          flat
          dense
          :icon="isPaused ? 'mdi-play' : 'mdi-pause'"
          data-test="native-toggle-pause"
          @click="$emit('toggle-pause')"
        />
        <q-btn
          flat
          dense
          icon="mdi-fast-forward-10"
          data-test="native-forward-10"
          @click="$emit('seek', 10)"
        />
        <q-btn
          flat
          dense
          icon="mdi-fullscreen"
          data-test="native-fullscreen"
          @click="$emit('toggle-fullscreen')"
        />
      </div>

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

      <!--
        Audio and subtitle selection.

        mpv decodes, so the language list comes from mpv's own tracks — not from
        the file's `textTracks`, which the browser would describe for a stream the
        player never received. Each dropdown is disabled when there is nothing to
        choose, rather than hidden: a user looking for the control should find it
        and see that there is only one option.
      -->
      <div v-if="tracks" class="native-playback__tracks" data-test="native-tracks">
        <div class="native-playback__track">
          <label for="native-audio-track">{{ $t('playPage.nativePlayback.audioTrack') }}</label>
          <select
            id="native-audio-track"
            :value="tracks.selectedAudio ?? ''"
            data-test="native-audio-select"
            @change="$emit('select-audio', $event.target.value === '' ? null : Number($event.target.value))"
          >
            <option v-for="track in tracks.audio" :key="track.id" :value="track.id">
              {{ track.label }}<template v-if="track.external"> · {{ $t('playPage.nativePlayback.external') }}</template>
            </option>
          </select>
        </div>

        <div class="native-playback__track">
          <label for="native-subtitle-track">{{ $t('playPage.nativePlayback.subtitleTrack') }}</label>
          <select
            id="native-subtitle-track"
            :value="tracks.selectedSubtitle ?? ''"
            data-test="native-subtitle-select"
            @change="$emit('select-subtitle', $event.target.value === '' ? null : Number($event.target.value))"
          >
            <!--
              An explicit "off" entry. mpv spells it `no`, and passing `auto`
              instead would let mpv re-select the subtitle the user just turned
              off — the distinction the composable already makes.
            -->
            <option value="">{{ $t('playPage.nativePlayback.subtitlesOff') }}</option>
            <option v-for="track in tracks.subtitles" :key="track.id" :value="track.id">
              {{ track.label }}<template v-if="track.external"> · {{ $t('playPage.nativePlayback.external') }}</template>
            </option>
          </select>
        </div>
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
  /// Whether the shell currently reports a pause, so the button can show the other action.
  isPaused: { type: Boolean, default: false },
  /**
   * The track list from mpv, or `null` before one has arrived.
   *
   * `null` rather than an empty list: "not read yet" and "this file has no
   * subtitle tracks" are different, and the panel must not claim the second while
   * the first is true.
   */
  tracks: { type: Object, default: null },
})

defineEmits([
  'close',
  'restart',
  'select-audio',
  'select-subtitle',
  'toggle-pause',
  'seek',
  'toggle-fullscreen',
])

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
.native-playback__tracks {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 1.25rem;
}
.native-playback__track {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 12rem;
  text-align: left;
}
.native-playback__track label {
  font-size: 0.8rem;
  opacity: 0.75;
}
.native-playback__track select {
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
  border: 1px solid currentColor;
  background: transparent;
  color: inherit;
}
.native-playback {
  display: flex;
  /* Bottom, not centre: since ADR 003 the video is behind this page, so a centred
     block of text would sit exactly where the picture is. */
  align-items: flex-end;
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

.native-playback__transport {
    display: flex;
    gap: 0.5rem;
    justify-content: center;
    margin-top: 1.25rem;
  }

  .native-playback__actions {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
  margin-top: 1.5rem;
}
</style>
