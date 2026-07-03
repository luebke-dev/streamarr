/**
 * Shared option lists for user/group permission editing forms.
 *
 * Static lists are exported as constants. Lists that depend on i18n
 * translations are exported as factory functions that take the `t`
 * function from `useI18n()` and return a fresh array.
 *
 * Used by:
 *  - src/pages/admin/EditUserPage.vue
 *  - src/pages/admin/EditGroupPage.vue
 *  - src/pages/admin/SettingsPage.vue
 */

export const LIBRARY_OPTIONS = ['movies', 'series', 'games', 'books', 'music']

export const VIDEO_QUALITY_OPTIONS = [
  { label: 'SD', value: 'sd' },
  { label: 'HD (720p)', value: 'hd' },
  { label: 'Full HD (1080p)', value: 'fhd' },
  { label: 'UHD (4K)', value: 'uhd' },
]

export function buildAudioQualityOptions(t) {
  return [
    { label: t('adminGroups.audioLossy'), value: 'lossy' },
    { label: t('adminGroups.audioLossless'), value: 'lossless' },
  ]
}

export function buildPeriodOptions(t) {
  return [
    { label: t('adminGroups.perMinute'), value: 1 },
    { label: t('adminGroups.perHour'), value: 60 },
    { label: t('adminGroups.perDay'), value: 1440 },
    { label: t('adminGroups.perWeek'), value: 10080 },
    { label: t('adminGroups.perMonth'), value: 43200 },
  ]
}
