import { describe, it, expect } from 'vitest'

import { realPlayerTime, timelineOffset } from 'src/composables/playbackPosition'

const player = (currentTime, duration) => ({
  currentTime: () => currentTime,
  duration: () => duration,
})

describe('timelineOffset', () => {
  it('adds nothing when playback starts at the beginning', () => {
    expect(timelineOffset(2700, 2700, 0)).toBe(0)
  })

  it('adds the offset for a trimmed stream', () => {
    // Transcode starts at 1500 s, so the player timeline is 1200 s long.
    expect(timelineOffset(1200, 2700, 1500)).toBe(1500)
  })

  it('ignores the offset when the stream covers the whole media', () => {
    // This is the Snowfall case: the response carried a resume position but the
    // stream was full length, so adding the offset doubled the position.
    expect(timelineOffset(2700, 2700, 1500)).toBe(0)
  })

  it('keeps the offset when durations are unknown', () => {
    expect(timelineOffset(0, 0, 1500)).toBe(1500)
  })

  it('accepts a ref-like object', () => {
    expect(timelineOffset(1200, 2700, { value: 1500 })).toBe(1500)
  })
})

describe('realPlayerTime', () => {
  it('reports the absolute position of a trimmed stream', () => {
    expect(realPlayerTime(player(600, 1200), 1500, 2700)).toBe(2100)
  })

  it('does not double count a full-length stream', () => {
    expect(realPlayerTime(player(2100, 2700), 1500, 2700)).toBe(2100)
  })

  it('never reports a position beyond the media', () => {
    // Old, already-saved progress can still arrive from a stale tab.
    expect(realPlayerTime(player(6574, 6574), 0, 2752)).toBe(2752)
  })

  it('behaves like before when the duration is unknown', () => {
    expect(realPlayerTime(player(600, 0), 1500, 0)).toBe(2100)
  })
})
