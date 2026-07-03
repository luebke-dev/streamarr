import { defineBoot } from '#q-app/wrappers'
import { api } from 'src/boot/axios'
import { logger } from 'src/utils/logger'
import { applyBranding } from 'src/utils/brandingTheme'

export default defineBoot(async () => {
  if (typeof document === 'undefined') return

  try {
    const [configurationResponse, themeResponse] = await Promise.all([
      api.get('/api/branding/configuration'),
      api.get('/api/branding/themes/active', { validateStatus: (status) => status < 500 }),
    ])

    applyBranding(
      configurationResponse.data || {},
      themeResponse.status === 200 ? themeResponse.data : null,
    )
  } catch (error) {
    logger.debug('Failed to load public branding theme:', error)
  }
})
