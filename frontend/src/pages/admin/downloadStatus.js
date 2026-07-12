/**
 * Shared download-status presentation maps for the admin area.
 *
 * Centralizing the status -> Quasar color/icon mapping here keeps the admin
 * dashboard and the downloads page from drifting apart (a download must show
 * the same color everywhere, and a newly added status must resolve in every
 * consumer instead of silently falling back to grey).
 */
export const DOWNLOAD_STATUS_COLORS = {
  queued: 'grey-7',
  downloading: 'info',
  in_progress: 'info',
  paused: 'orange',
  importing: 'amber',
  completed: 'positive',
  imported: 'positive',
  failed: 'negative',
}

export const DOWNLOAD_STATUS_ICONS = {
  queued: 'mdi-clock-outline',
  downloading: 'mdi-download',
  in_progress: 'mdi-progress-download',
  paused: 'mdi-pause',
  importing: 'mdi-import',
  completed: 'mdi-check',
  imported: 'mdi-check',
  failed: 'mdi-alert',
}

export const downloadStatusColor = (status) => DOWNLOAD_STATUS_COLORS[status] || 'grey-7'

export const downloadStatusIcon = (status) => DOWNLOAD_STATUS_ICONS[status] || 'mdi-help'
