/**
 * Skip-markers composable for the play page.
 *
 * Owns the reactive bookkeeping for intro / outro / credits skip
 * regions: which region (if any) the current playback position is
 * inside, the show-button computeds, and the auto-skip watcher that
 * jumps the player past the region when the user has chosen 'auto'
 * for that marker mode.
 *
 * Inputs (refs/computed):
 *   - markers: ref to the markers payload
 *       (shape: { markers: [{marker_type,start,end}], outro_start,
 *                outro_end, credits_start, credits_end })
 *   - playbackPrefs: ref to the user preferences
 *       (shape: { skip_intro_mode, skip_outro_mode, skip_credits_mode })
 *   - transcodeStartPosition: ref<number>
 *   - streamPosition: ref<number>
 *   - videoDuration: ref<number>
 *   - onSkip: (seconds: number) => void  — invoked for both auto-skip
 *       and the manual skipToPosition action.
 */

import { computed, watch } from 'vue'

export function useSkipMarkers({
  markers,
  playbackPrefs,
  transcodeStartPosition,
  streamPosition,
  videoDuration,
  onSkip,
}) {
  const realPosition = computed(() => transcodeStartPosition.value + streamPosition.value)

  // Find which intro region (if any) the current position is in
  const activeIntroMarker = computed(() => {
    if (!markers.value?.markers) return null
    const pos = realPosition.value
    return (
      markers.value.markers.find(
        (m) => m.marker_type === 'intro' && pos >= m.start && pos < m.end,
      ) || null
    )
  })

  const inIntroRegion = computed(() => activeIntroMarker.value !== null)

  const inOutroRegion = computed(() => {
    if (!markers.value?.outro_start || !markers.value?.outro_end) return false
    return (
      realPosition.value >= markers.value.outro_start &&
      realPosition.value < markers.value.outro_end
    )
  })

  const inCreditsRegion = computed(() => {
    if (!markers.value?.credits_start) return false
    return realPosition.value >= markers.value.credits_start
  })

  // Show skip button only in "button" mode
  const showSkipIntro = computed(
    () => inIntroRegion.value && playbackPrefs.value?.skip_intro_mode === 'button',
  )
  const showSkipOutro = computed(
    () => inOutroRegion.value && playbackPrefs.value?.skip_outro_mode === 'button',
  )
  const showSkipCredits = computed(
    () => inCreditsRegion.value && playbackPrefs.value?.skip_credits_mode === 'button',
  )

  // Auto-skip watcher: consolidates intro/outro/credits into one reactive subscription.
  let autoSkippedIntro = false
  let autoSkippedOutro = false
  let autoSkippedCredits = false

  watch(
    () => [inIntroRegion.value, inOutroRegion.value, inCreditsRegion.value],
    ([inIntro, inOutro, inCredits]) => {
      if (inIntro && !autoSkippedIntro && playbackPrefs.value?.skip_intro_mode === 'auto') {
        autoSkippedIntro = true
        const end = activeIntroMarker.value?.end
        if (end != null) onSkip(end)
      } else if (!inIntro) {
        autoSkippedIntro = false
      }

      if (inOutro && !autoSkippedOutro && playbackPrefs.value?.skip_outro_mode === 'auto') {
        autoSkippedOutro = true
        onSkip(markers.value.outro_end)
      } else if (!inOutro) {
        autoSkippedOutro = false
      }

      if (inCredits && !autoSkippedCredits && playbackPrefs.value?.skip_credits_mode === 'auto') {
        autoSkippedCredits = true
        onSkip(videoDuration.value)
      } else if (!inCredits) {
        autoSkippedCredits = false
      }
    },
  )

  const skipToPosition = (seconds) => {
    if (seconds != null) onSkip(seconds)
  }

  return {
    realPosition,
    activeIntroMarker,
    showSkipIntro,
    showSkipOutro,
    showSkipCredits,
    skipToPosition,
  }
}
