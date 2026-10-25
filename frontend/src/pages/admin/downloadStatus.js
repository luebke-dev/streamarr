/**
 * Shared download-status presentation maps for the admin area.
 *
 * Centralizing the status -> Quasar color/icon mapping here keeps the admin
 * dashboard and the downloads page from drifting apart (a download must show
 * the same color everywhere, and a newly added status must resolve in every
 * consumer instead of silently falling back to grey).
 */
// The backend stores mixed-case statuses ("Downloading", "Imported"), so every
// lookup normalises first - the previous maps were keyed lowercase only and a
// capitalised status silently fell through to grey + "?".
export const DOWNLOAD_STATUS_KEYS = [
  'pending',
  'queued',
  'downloading',
  'in_progress',
  'paused',
  'importing',
  'completed',
  'imported',
  'failed',
  'cancelled',
]

export const DOWNLOAD_STATUS_COLORS = {
  queued: 'grey-7',
  downloading: 'info',
  in_progress: 'info',
  paused: 'orange',
  importing: 'amber',
  completed: 'positive',
  imported: 'positive',
  failed: 'negative',
  cancelled: 'grey-8',
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
  cancelled: 'mdi-cancel',
}

const normalize = (status) => String(status || '').toLowerCase()

export const downloadStatusColor = (status) =>
  DOWNLOAD_STATUS_COLORS[normalize(status)] || 'grey-7'

export const downloadStatusIcon = (status) =>
  DOWNLOAD_STATUS_ICONS[normalize(status)] || 'mdi-progress-question'

export const isKnownStatus = (status) => DOWNLOAD_STATUS_KEYS.includes(normalize(status))
