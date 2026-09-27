<!--
  The screen while the shell streams a game.

  Like `NativePlaybackView`, this is deliberately **small**: the picture is drawn
  by GStreamer into the shell's own window, not into this page. What the user
  needs from the page is a way back, the title, and the controls that would
  otherwise be unreachable — because the video window has the focus, not this one.

  # Why the controls live here and not over the video

  The web client draws its toolbar over the `<video>` element. There is no such
  element here, so the toolbar is on this page — which the user sees *before* the
  stream window takes the screen. It is therefore not a video overlay but a
  control panel, and it says so.
-->
<template>
  <div class="native-game" data-test="native-game">
    <div class="native-game__inner">
      <h2 class="native-game__title">{{ title || $t('playPage.gameStreaming') }}</h2>

      <p class="native-game__state" data-test="native-game-state">
        {{ $t(`playPage.nativeGame.phase.${phase}`, { resolution }) }}
      </p>

      <!--
        A failed stream says *which* failure. The shell distinguishes "this build
        has no game streaming", "the server refused" and "the transport failed",
        and collapsing those into one message would send a user looking for the
        wrong problem.
      -->
      <q-banner v-if="state.error" dense class="bg-negative text-white" data-test="native-game-error">
        {{ state.error }}
      </q-banner>

      <div class="native-game__controls">
        <!--
          The web toolbar's five controls, for the one that makes sense without a
          `<video>` element: pointer lock needs an element to lock onto, and the
          pointer belongs to the shell's window here.
        -->
        <q-btn
          v-if="state.running"
          outline
          color="primary"
          icon="mdi-fullscreen"
          :label="$t('playPage.gameFullscreen')"
          no-caps
          data-test="native-game-fullscreen"
          @click="$emit('fullscreen')"
        />
      </div>

      <div class="native-game__actions">
        <!--
          Fullscreen, resolution-match, pointer-lock, stats and disconnect — the
          five controls the web toolbar has. Only the ones that make sense
          without a `<video>` are offered: pointer lock needs an element to lock
          onto, and the pointer is handled by the shell's window.
        -->
        <q-btn
          v-if="state.running"
          outline
          color="primary"
          icon="mdi-monitor-screenshot"
          :label="$t('playPage.gameMatchResolution')"
          no-caps
          data-test="native-game-match"
          @click="$emit('match-resolution')"
        />
        <q-btn
          v-if="state.running"
          outline
          color="primary"
          icon="mdi-bug-outline"
          :label="$t('playPage.gameDebug')"
          no-caps
          data-test="native-game-debug"
          @click="showDebug = !showDebug"
        />
        <q-btn
          color="negative"
          icon="mdi-close"
          :label="$t('playPage.gameDisconnect')"
          no-caps
          data-test="native-game-disconnect"
          @click="$emit('disconnect')"
        />
      </div>

      <!--
        The debug panel shows *measured* values. An earlier version printed a
        hard-coded "controller connected" line, which is worse than an empty
        panel: it asserted something nothing had checked.
      -->
      <div v-if="showDebug" class="native-game__debug" data-test="native-game-debug-panel">
        <div>{{ $t('playPage.gameResolution') }}: {{ resolution }}</div>
        <div>{{ $t('playPage.gameFramesDecoded') }}: {{ state.stats?.frames ?? '—' }}</div>
        <div>{{ $t('playPage.gameBitrate') }}: {{ bitrate }}</div>
        <div>RTT: {{ state.stats?.rtt_ms != null ? `${Math.round(state.stats.rtt_ms)} ms` : '—' }}</div>
        <div>{{ $t('playPage.gameJitter') }}: {{ state.stats?.jitter_ms != null ? `${Math.round(state.stats.jitter_ms)} ms` : '—' }}</div>
        <div>
          {{ $t('playPage.gameController') }}:
          {{ state.inputForwarded > 0 ? $t('playPage.gameControllerConnected') : $t('playPage.gameControllerNone') }}
        </div>
      </div>

      <p class="native-game__hint">{{ $t('playPage.nativeGame.hint') }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  /** The shell's word for the session state, e.g. `streaming`. */
  phase: { type: String, default: 'connecting' },
  state: {
    type: Object,
    default: () => ({ running: false, width: 0, height: 0, error: null, errorStatus: null }),
  },
})

defineEmits(['close', 'disconnect', 'match-resolution', 'fullscreen'])

const showDebug = ref(false)

/**
 * The bitrate, or a dash.
 *
 * The shell's `LiveStats` only carries a bitrate once something measures bytes,
 * and nothing does yet — so this is `—` rather than `0.0 Mbps`. A zero would be a
 * claim about the link that no measurement supports, and a user reporting a
 * stutter would read it as "the stream is dead".
 */
const bitrate = computed(() => {
  const mbps = props.state?.stats?.mbps
  return mbps ? `${mbps.toFixed(1)} Mbps` : '—'
})

const resolution = computed(() =>
  props.state?.width && props.state?.height
    ? `${props.state.width}x${props.state.height}`
    : '—',
)
</script>

<style scoped>
.native-game {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: 2rem;
}
.native-game__inner {
  max-width: 40rem;
  text-align: center;
}
.native-game__actions {
  display: flex;
  gap: 0.5rem;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 1.5rem;
}
.native-game__controls {
  display: flex;
  gap: 0.5rem;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 1rem;
}
.native-game__debug {
  margin-top: 1rem;
  font-family: monospace;
  font-size: 0.85rem;
  opacity: 0.8;
}
.native-game__hint {
  margin-top: 1.5rem;
  font-size: 0.85rem;
  opacity: 0.7;
}
</style>
