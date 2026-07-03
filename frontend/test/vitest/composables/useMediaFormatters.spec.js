import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  formatFileSize,
  formatDuration,
  formatDate,
  formatAirDate,
  formatYear,
  formatRelativeTime,
  formatRelativeDate,
} from 'src/composables/useMediaFormatters.js'

describe('formatFileSize', () => {
  it('returns "0 B" for zero', () => {
    expect(formatFileSize(0)).toBe('0 B')
  })

  it('returns "0 B" for null', () => {
    expect(formatFileSize(null)).toBe('0 B')
  })

  it('formats bytes', () => {
    expect(formatFileSize(500)).toBe('500 B')
  })

  it('formats kilobytes', () => {
    expect(formatFileSize(1024)).toBe('1 KB')
  })

  it('formats megabytes', () => {
    expect(formatFileSize(1024 * 1024)).toBe('1 MB')
  })

  it('formats gigabytes', () => {
    expect(formatFileSize(1.5 * 1024 * 1024 * 1024)).toBe('1.5 GB')
  })
})

describe('formatDuration (useMediaFormatters)', () => {
  it('returns player-style fallbacks for zero and missing input', () => {
    expect(formatDuration(0)).toBe('0:00')
    expect(formatDuration(null)).toBe('--:--')
    expect(formatDuration(undefined)).toBe('--:--')
  })

  it('formats seconds into M:SS', () => {
    expect(formatDuration(125)).toBe('2:05')
  })

  it('formats seconds into H:MM:SS', () => {
    expect(formatDuration(3723)).toBe('1:02:03')
  })
})

describe('formatYear', () => {
  it('returns "TBA" for null', () => {
    expect(formatYear(null)).toBe('TBA')
  })

  it('returns "TBA" for empty string', () => {
    expect(formatYear('')).toBe('TBA')
  })

  it('extracts year from a date string', () => {
    expect(formatYear('2023-06-15')).toBe('2023')
  })
})

describe('formatDate', () => {
  it('returns "Unknown" for null', () => {
    expect(formatDate(null)).toBe('Unknown')
  })

  it('returns a formatted date string', () => {
    const result = formatDate('2023-01-15T12:00:00Z', 'en-US')
    expect(result).toContain('2023')
    expect(result).toContain('Jan')
  })
})

describe('formatAirDate', () => {
  it('returns "To be announced" for null', () => {
    expect(formatAirDate(null)).toBe('To be announced')
  })

  it('returns a formatted date string', () => {
    const result = formatAirDate('2023-04-01', 'en-US')
    expect(result).toContain('2023')
    expect(result).toContain('April')
  })
})

describe('formatRelativeTime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2024-01-15T12:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns "" for null', () => {
    expect(formatRelativeTime(null)).toBe('')
  })

  it('returns "just now" for very recent date', () => {
    expect(formatRelativeTime('2024-01-15T11:59:59Z')).toBe('just now')
  })

  it('returns minutes ago', () => {
    expect(formatRelativeTime('2024-01-15T11:45:00Z')).toBe('15 minutes ago')
  })

  it('returns singular "minute ago"', () => {
    expect(formatRelativeTime('2024-01-15T11:59:00Z')).toBe('1 minute ago')
  })

  it('returns hours ago', () => {
    expect(formatRelativeTime('2024-01-15T10:00:00Z')).toBe('2 hours ago')
  })

  it('returns singular "hour ago"', () => {
    expect(formatRelativeTime('2024-01-15T11:00:00Z')).toBe('1 hour ago')
  })

  it('returns days ago for older dates', () => {
    expect(formatRelativeTime('2024-01-12T12:00:00Z')).toBe('3 days ago')
  })
})

describe('formatRelativeDate', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2024-01-15T12:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns "" for null', () => {
    expect(formatRelativeDate(null)).toBe('')
  })

  it('returns "tomorrow" for next day', () => {
    expect(formatRelativeDate('2024-01-16T12:00:00Z')).toBe('tomorrow')
  })

  it('returns "in N days" for within a week', () => {
    expect(formatRelativeDate('2024-01-20T12:00:00Z')).toBe('in 5 days')
  })

  it('returns "in 2 weeks" for 8 days away', () => {
    expect(formatRelativeDate('2024-01-23T12:00:00Z')).toBe('in 2 weeks')
  })

  it('returns "in N months" for longer ranges', () => {
    const result = formatRelativeDate('2024-03-15T12:00:00Z')
    expect(result).toMatch(/in \d+ months?/)
  })
})
