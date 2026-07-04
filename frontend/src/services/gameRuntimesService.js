import { api } from 'boot/axios'

// Game-runtimes (container-profile) admin API. Kept in the services layer so
// components don't import `boot/axios` directly (see eslint.config.js — the
// data layer is the one place allowed to talk to axios). A "runtime" is a
// global ContainerProfile: the Docker image + Lightrays runtime_profile +
// shared env + persistent-state scope a game launches with.

/** List all game runtimes, ordered by name. */
export async function listRuntimes() {
  const response = await api.get('/api/game-runtimes')
  return response.data
}

/** Fetch a single runtime by guid. */
export async function getRuntime(guid) {
  const response = await api.get(`/api/game-runtimes/${guid}`)
  return response.data
}

/** Create a new runtime. */
export async function createRuntime(payload) {
  const response = await api.post('/api/game-runtimes', payload)
  return response.data
}

/** Update an existing runtime. */
export async function updateRuntime(guid, payload) {
  const response = await api.put(`/api/game-runtimes/${guid}`, payload)
  return response.data
}

/** Delete a runtime (builtins are rejected by the backend). */
export function removeRuntime(guid) {
  return api.delete(`/api/game-runtimes/${guid}`)
}
