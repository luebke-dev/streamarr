import { api } from 'boot/axios'

// Lightrays game-streaming API. Kept in the services layer so components and
// composables don't import `boot/axios` directly (see eslint.config.js — the
// data layer is the one place allowed to talk to axios).

/**
 * Launch a game-streaming session for a media item.
 * @returns the response payload (session_id, ws_ticket, websocket_url, ice_servers, …)
 */
export async function launchGameSession(
  mediaGuid,
  { width, height, fps = 60, bitrateKbps = 10000, platform = null } = {},
) {
  const response = await api.post(`/api/lightrays/launch/${mediaGuid}`, {
    width,
    height,
    fps,
    bitrate_kbps: bitrateKbps,
    platform,
  })
  return response.data
}

/**
 * List the platforms a game can be played on (N64, PC, …) with per-platform
 * download/availability status, for the player's version picker.
 */
export async function getGamePlatforms(mediaGuid) {
  const response = await api.get(`/api/lightrays/platforms/${mediaGuid}`)
  return response.data
}

/** Stop a running game-streaming session. */
export function stopGameSession(sessionId) {
  return api.post('/api/lightrays/stop', { session_id: sessionId })
}
