import { api } from 'boot/axios'

// --- Banners ---

export async function getBanners(params) {
  const response = await api.get('/api/banners', { params })
  return response.data
}

export async function getBanner(guid) {
  const response = await api.get(`/api/banners/${guid}`)
  return response.data
}

export async function createBanner(data) {
  const response = await api.post('/api/banners', data)
  return response.data
}

export async function updateBanner(guid, data) {
  const response = await api.put(`/api/banners/${guid}`, data)
  return response.data
}

export async function deleteBanner(guid) {
  const response = await api.delete(`/api/banners/${guid}`)
  return response.data
}

// --- Page layouts ---

export async function getPageLayouts() {
  const response = await api.get('/api/page-layouts')
  return response.data
}

export async function getPageLayout(guid) {
  const response = await api.get(`/api/page-layouts/${guid}`)
  return response.data
}

export async function createPageLayout(data) {
  const response = await api.post('/api/page-layouts', data)
  return response.data
}

export async function updatePageLayout(guid, data) {
  const response = await api.put(`/api/page-layouts/${guid}`, data)
  return response.data
}

export async function deletePageLayout(guid) {
  const response = await api.delete(`/api/page-layouts/${guid}`)
  return response.data
}

export async function updateSectionsOrder(layoutGuid, sectionOrder) {
  const response = await api.put(`/api/page-layouts/${layoutGuid}/sections-order`, {
    section_order: sectionOrder,
  })
  return response.data
}

// --- Page layout sections ---

export async function createPageLayoutSection(layoutGuid, payload) {
  const response = await api.post(`/api/page-layouts/${layoutGuid}/sections`, payload)
  return response.data
}

export async function updatePageLayoutSection(layoutGuid, sectionGuid, payload) {
  const response = await api.put(
    `/api/page-layouts/${layoutGuid}/sections/${sectionGuid}`,
    payload,
  )
  return response.data
}

export async function deletePageLayoutSection(layoutGuid, sectionGuid) {
  const response = await api.delete(`/api/page-layouts/${layoutGuid}/sections/${sectionGuid}`)
  return response.data
}

// --- Reference data ---

export async function getLibraries() {
  const response = await api.get('/api/libraries')
  return response.data
}

export async function getGenres() {
  const response = await api.get('/api/genres')
  return response.data
}

export async function getLists(params) {
  const response = await api.get('/api/lists', { params })
  return response.data
}

export async function getPlatforms() {
  const response = await api.get('/api/platforms')
  return response.data
}

// --- Lists administration ---

export async function getAdminLists(params) {
  const response = await api.get('/api/lists/admin/all', { params })
  return response.data
}

export async function deleteAdminList(guid) {
  const response = await api.delete(`/api/lists/admin/${guid}`)
  return response.data
}
