import { defineStore } from 'pinia'
import { api } from 'boot/axios'
import { logger } from 'src/utils/logger'

export const useBannerStore = defineStore('banners', {
  state: () => ({
    activeBanners: [],
    loading: false,
    error: null,
  }),

  getters: {
    visibleBanners: (state) => {
      return state.activeBanners
    },

    hasBanners: (state) => {
      return state.activeBanners.length > 0
    },
  },

  actions: {
    async fetchActiveBanners() {
      this.loading = true
      this.error = null

      try {
        const response = await api.get('/api/banners/active')
        this.activeBanners = response.data
      } catch (error) {
        logger.error('[BannerStore] Error fetching active banners:', error)
        this.error = error.response?.data?.detail || 'Failed to load banners'
        this.activeBanners = []
      } finally {
        this.loading = false
      }
    },

    async dismissBanner(bannerGuid) {
      try {
        await api.post(`/api/banners/${bannerGuid}/dismiss`)

        // Remove banner from active list
        this.activeBanners = this.activeBanners.filter((banner) => banner.guid !== bannerGuid)

        logger.debug('[BannerStore] Banner dismissed:', bannerGuid)
      } catch (error) {
        logger.error('[BannerStore] Error dismissing banner:', error)
        throw error
      }
    },

    clearBanners() {
      this.activeBanners = []
      this.loading = false
      this.error = null
    },
  },
})
