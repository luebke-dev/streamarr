import { api } from 'boot/axios'
import {
  getMediaItem,
  getMediaItemChildren,
  getMediaItemReleases,
} from 'src/composables/useUnifiedMedia'

export function loadMediaItem(guid, options = {}) {
  return getMediaItem(guid, options)
}

export function loadMediaChildren(guid, orderBySequence = true) {
  return getMediaItemChildren(guid, orderBySequence)
}

export function loadMediaReleases(guid, params = {}) {
  return getMediaItemReleases(guid, params)
}

export async function searchMediaReleases(guid) {
  const response = await api.post(`/api/media/${guid}/releases/search`)
  return response.data
}

export async function downloadMediaRelease(guid, releaseGuid) {
  const response = await api.post(`/api/media/${guid}/releases/${releaseGuid}/download`)
  return response.data
}

export async function deleteMediaRelease(guid, releaseGuid) {
  const response = await api.delete(`/api/media/${guid}/releases/${releaseGuid}`)
  return response.data
}

export async function deleteAllMediaReleases(guid) {
  const response = await api.delete(`/api/media/${guid}/releases`)
  return response.data
}

export async function reprobeMediaFile(guid, fileGuid) {
  const response = await api.post(`/api/media/${guid}/files/${fileGuid}/reprobe`)
  return response.data
}

export async function reprobeAllMediaFiles(guid) {
  const response = await api.post(`/api/media/${guid}/files/reprobe-all`)
  return response.data
}

export async function deleteMediaFile(guid, fileGuid) {
  const response = await api.delete(`/api/media/${guid}/files/${fileGuid}`)
  return response.data
}

export async function searchSubtitles(guid, params) {
  const response = await api.get(`/api/media/${guid}/subtitles/search`, { params })
  return response.data
}

export async function downloadSubtitle(guid, payload) {
  const response = await api.post(`/api/media/${guid}/subtitles/download`, payload)
  return response.data
}

export async function searchLyrics(guid, params) {
  const response = await api.get(`/api/media/${guid}/lyrics/search`, { params })
  return response.data
}

export async function downloadLyrics(guid, payload) {
  const response = await api.post(`/api/media/${guid}/lyrics/download`, payload)
  return response.data
}

export async function searchArtwork(guid, params) {
  const response = await api.get(`/api/media/${guid}/images/remote`, { params })
  return response.data
}

export async function selectRemoteArtwork(guid, imageType, payload) {
  const response = await api.put(`/api/media/${guid}/images/${imageType}/remote`, payload)
  return response.data
}

export async function uploadArtwork(guid, imageType, payload) {
  const response = await api.post(`/api/media/${guid}/images/${imageType}/upload`, payload)
  return response.data
}

export async function refreshMetadata(guid) {
  const response = await api.post(`/api/media/${guid}/refresh-metadata`)
  return response.data
}

export async function getMediaAvailability(guid) {
  const response = await api.get(`/api/media/${guid}/availability`)
  return response.data
}

export async function toggleMediaWatch(guid) {
  const response = await api.post(`/api/media/${guid}/watch`)
  return response.data
}

export async function getMediaDownloads(guid) {
  const response = await api.get(`/api/media/${guid}/downloads`)
  return response.data || []
}

export async function getMediaUserData(guid) {
  const response = await api.get(`/api/media/${guid}/user-data`)
  return response.data
}

export async function setMediaLike(guid, liked) {
  const method = liked ? 'delete' : 'post'
  const response = await api[method](`/api/media/${guid}/like`)
  return response.data
}

export async function setMediaPlayed(guid, played) {
  const method = played ? 'delete' : 'post'
  const response = await api[method](`/api/media/${guid}/played`)
  return response.data
}

export async function getInstantMix(guid) {
  const response = await api.get(`/api/suggestions/instant-mix/${guid}`)
  return response.data
}
