import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock vue-i18n so useI18n() works without a full Vue app.
// Empty string return means every `t(key) || 'Fallback'` falls through to the hardcoded fallback.
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: () => '' }),
}))

import { useMediaHelpers } from 'src/composables/useMediaHelpers.js'

const {
  getPosterUrl,
  getBackdropUrl,
  getStillUrl,
  formatRuntime,
  formatFileSize,
  formatDuration,
  formatGenres,
  getMediaStatus,
  isEpisodeFuture,
  formatRating,
  getRatingColor,
  formatRelativeTime,
} = useMediaHelpers()

const TMDB = 'https://image.tmdb.org/t/p'

// ─── getPosterUrl ─────────────────────────────────────────────────────────────

describe('getPosterUrl', () => {
  it('returns null for null media', () => {
    expect(getPosterUrl(null)).toBeNull()
  })

  it('returns null when poster_path is missing', () => {
    expect(getPosterUrl({})).toBeNull()
  })

  it('builds a full TMDB URL for a relative path', () => {
    expect(getPosterUrl({ poster_path: '/abc.jpg' })).toBe(`${TMDB}/w500/abc.jpg`)
  })

  it('passes through absolute URLs unchanged', () => {
    const url = 'https://example.com/image.jpg'
    expect(getPosterUrl({ poster_path: url })).toBe(url)
  })
})

// ─── getBackdropUrl ───────────────────────────────────────────────────────────

describe('getBackdropUrl', () => {
  it('returns null for null media', () => {
    expect(getBackdropUrl(null)).toBeNull()
  })

  it('returns null when backdrop_path is missing', () => {
    expect(getBackdropUrl({})).toBeNull()
  })

  it('builds a full TMDB URL for a relative path', () => {
    expect(getBackdropUrl({ backdrop_path: '/bg.jpg' })).toBe(`${TMDB}/w1280/bg.jpg`)
  })

  it('passes through absolute URLs unchanged', () => {
    const url = 'https://example.com/bg.jpg'
    expect(getBackdropUrl({ backdrop_path: url })).toBe(url)
  })
})

// ─── getStillUrl ─────────────────────────────────────────────────────────────

describe('getStillUrl', () => {
  it('returns null for null media', () => {
    expect(getStillUrl(null)).toBeNull()
  })

  it('returns null when still_path is missing', () => {
    expect(getStillUrl({})).toBeNull()
  })

  it('builds a w300 TMDB URL', () => {
    expect(getStillUrl({ still_path: '/still.jpg' })).toBe(`${TMDB}/w300/still.jpg`)
  })
})

// ─── formatRuntime ────────────────────────────────────────────────────────────

describe('formatRuntime', () => {
  it('returns empty string for null', () => {
    expect(formatRuntime(null)).toBe('')
  })

  it('returns empty string for zero', () => {
    expect(formatRuntime(0)).toBe('')
  })

  it('formats minutes under 1 hour', () => {
    expect(formatRuntime(45)).toBe('45m')
  })

  it('formats hours and minutes', () => {
    expect(formatRuntime(135)).toBe('2h 15m')
  })

  it('formats exactly 1 hour', () => {
    expect(formatRuntime(60)).toBe('1h 0m')
  })
})

// ─── formatFileSize ───────────────────────────────────────────────────────────

describe('formatFileSize', () => {
  it('returns "0 B" for zero', () => {
    expect(formatFileSize(0)).toBe('0 B')
  })

  it('returns "0 B" for null', () => {
    expect(formatFileSize(null)).toBe('0 B')
  })

  it('formats bytes', () => {
    expect(formatFileSize(512)).toBe('512 B')
  })

  it('formats kilobytes', () => {
    expect(formatFileSize(1024)).toBe('1 KB')
  })

  it('formats megabytes', () => {
    expect(formatFileSize(1024 * 1024)).toBe('1 MB')
  })

  it('formats gigabytes', () => {
    expect(formatFileSize(2 * 1024 ** 3)).toBe('2 GB')
  })
})

// ─── formatDuration ───────────────────────────────────────────────────────────

describe('formatDuration (useMediaHelpers)', () => {
  it('returns player zero for zero', () => {
    expect(formatDuration(0)).toBe('0:00')
  })

  it('returns player fallback for null', () => {
    expect(formatDuration(null)).toBe('--:--')
  })

  it('formats seconds under one minute', () => {
    expect(formatDuration(45)).toBe('0:45')
  })

  it('formats seconds into M:SS', () => {
    expect(formatDuration(90)).toBe('1:30')
  })

  it('formats seconds into H:MM:SS', () => {
    expect(formatDuration(3661)).toBe('1:01:01')
  })

  it('pads hours, minutes, and seconds', () => {
    expect(formatDuration(7200)).toBe('2:00:00')
  })
})

// ─── formatGenres ─────────────────────────────────────────────────────────────

describe('formatGenres', () => {
  it('returns empty string for null', () => {
    expect(formatGenres(null)).toBe('')
  })

  it('returns empty string for empty array', () => {
    expect(formatGenres([])).toBe('')
  })

  it('formats an array of genre objects', () => {
    expect(formatGenres([{ name: 'Action' }, { name: 'Drama' }])).toBe('Action, Drama')
  })

  it('formats an array of plain strings', () => {
    expect(formatGenres(['Comedy', 'Thriller'])).toBe('Comedy, Thriller')
  })

  it('formats a single genre', () => {
    expect(formatGenres([{ name: 'Horror' }])).toBe('Horror')
  })
})

// ─── getMediaStatus ───────────────────────────────────────────────────────────

describe('getMediaStatus', () => {
  it('returns "unknown" for null date', () => {
    expect(getMediaStatus(null)).toBe('unknown')
  })

  it('returns "released" for a past date', () => {
    expect(getMediaStatus('2000-01-01')).toBe('released')
  })

  it('returns "upcoming" for a far future date', () => {
    expect(getMediaStatus('2099-12-31')).toBe('upcoming')
  })
})

// ─── isEpisodeFuture ─────────────────────────────────────────────────────────

describe('isEpisodeFuture', () => {
  it('returns true for null (not yet aired)', () => {
    expect(isEpisodeFuture(null)).toBe(true)
  })

  it('returns false for a past date', () => {
    expect(isEpisodeFuture('2000-01-01')).toBe(false)
  })

  it('returns true for a far future date', () => {
    expect(isEpisodeFuture('2099-12-31')).toBe(true)
  })
})

// ─── formatRating ─────────────────────────────────────────────────────────────

describe('formatRating', () => {
  it('returns "N/A" for null', () => {
    expect(formatRating(null)).toBe('N/A')
  })

  it('returns "N/A" for zero', () => {
    expect(formatRating(0)).toBe('N/A')
  })

  it('formats a float with one decimal place and a star', () => {
    expect(formatRating(8.5)).toBe('8.5 ★')
  })

  it('pads an integer to one decimal place', () => {
    expect(formatRating(7)).toBe('7.0 ★')
  })
})

// ─── getRatingColor ───────────────────────────────────────────────────────────

describe('getRatingColor', () => {
  it('returns "grey" for null', () => {
    expect(getRatingColor(null)).toBe('grey')
  })

  it('returns "grey" for zero', () => {
    expect(getRatingColor(0)).toBe('grey')
  })

  it('returns "positive" for rating >= 7', () => {
    expect(getRatingColor(7)).toBe('positive')
    expect(getRatingColor(9.5)).toBe('positive')
  })

  it('returns "warning" for rating >= 5 and < 7', () => {
    expect(getRatingColor(5)).toBe('warning')
    expect(getRatingColor(6.9)).toBe('warning')
  })

  it('returns "negative" for rating < 5', () => {
    expect(getRatingColor(4.9)).toBe('negative')
    expect(getRatingColor(1)).toBe('negative')
  })
})

// ─── formatRelativeTime ───────────────────────────────────────────────────────

describe('formatRelativeTime (useMediaHelpers)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2024-06-01T12:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns "Unknown" for null', () => {
    expect(formatRelativeTime(null)).toBe('Unknown')
  })

  it('returns "just now" for a very recent timestamp', () => {
    expect(formatRelativeTime('2024-06-01T11:59:59Z')).toBe('just now')
  })

  it('returns minutes ago', () => {
    expect(formatRelativeTime('2024-06-01T11:45:00Z')).toBe('15 minutes ago')
  })

  it('uses singular "minute" for 1 minute ago', () => {
    expect(formatRelativeTime('2024-06-01T11:59:00Z')).toBe('1 minute ago')
  })

  it('returns hours ago', () => {
    expect(formatRelativeTime('2024-06-01T10:00:00Z')).toBe('2 hours ago')
  })

  it('returns days ago', () => {
    expect(formatRelativeTime('2024-05-29T12:00:00Z')).toBe('3 days ago')
  })

  it('returns an absolute date after the recent relative window', () => {
    expect(formatRelativeTime('2024-05-18T12:00:00Z')).toBe('May 18, 2024')
  })
})
