import { api } from 'boot/axios'
import { useTimeoutRegistry } from 'src/composables/useTimeoutRegistry'

export function useStreamReadiness({ maxAttempts = 30, pollIntervalMs = 1000 } = {}) {
  const timers = useTimeoutRegistry()

  async function waitForHlsStreamReady(sessionId, token) {
    if (!sessionId) return false

    for (let attempts = 0; attempts < maxAttempts; attempts++) {
      try {
        const requestOptions = {
          params: { token },
          validateStatus: (status) => status < 500,
          headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
        }
        const playlistResponse = await api.get(
          `/api/stream/${sessionId}/playlist.m3u8`,
          requestOptions,
        )

        if (playlistResponse.status === 200) {
          const segmentResponse = await api.get(
            `/api/stream/${sessionId}/${sessionId}_000.ts`,
            requestOptions,
          )
          if (segmentResponse.status === 200) return true
        }
      } catch {
        // Keep polling until the stream is actually servable or the timeout expires.
      }

      const shouldContinue = await timers.delay(pollIntervalMs)
      if (!shouldContinue) return false
    }

    return false
  }

  return {
    waitForHlsStreamReady,
    clearStreamReadinessTimers: timers.clearAll,
  }
}
