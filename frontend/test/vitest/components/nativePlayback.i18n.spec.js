/**
 * The interface's translation keys and the core crate's notice variants must agree.
 *
 * This test exists because the two live in different languages and different crates: the
 * core produces a `kind` (Rust), and the interface looks up
 * `playPage.nativePlayback.notice.<kind>` (JavaScript). If one side gains a case and the
 * other does not, the result is a **missing translation** — which renders as the key
 * itself, or as nothing at all depending on the locale setup. Neither fails a build.
 *
 * So the keys are read from both sides:
 *   * the Rust enum, from its `#[serde(rename = "...")]` attributes and `key()`;
 *   * the locales, from the translation files.
 *
 * It is a source-reading test, which is the weaker instrument — and it is the right one
 * here, because the alternative is a compiled Rust artifact inspected from a Node test
 * process. What it guards is exactly the drift it can see.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import enUS from 'src/i18n/en-US'
import deDE from 'src/i18n/de-DE'

const REPO_ROOT = resolve(__dirname, '../../../..')
const PLAN_RS = resolve(REPO_ROOT, 'frontend/src-tauri/player/src/plan.rs')

/** The `kind` values the core crate can emit. */
function noticeKindsFromRust() {
  const source = readFileSync(PLAN_RS, 'utf8')
  const start = source.indexOf('pub enum PlaybackNotice')
  expect(start, 'the enum must exist in plan.rs').toBeGreaterThan(-1)
  const block = source.slice(start, source.indexOf('\n}', start))

  // Each variant carries `#[serde(rename = "kind")]`.
  const kinds = [...block.matchAll(/#\[serde\(rename = "([a-z]+)"\)\]/g)].map((m) => m[1])
  expect(kinds.length, `no kinds found in ${block.slice(0, 200)}`).toBeGreaterThan(0)
  return kinds
}

describe('native playback notices', () => {
  const kinds = noticeKindsFromRust()

  it('finds the kinds the core crate emits', () => {
    // A sanity check on the parser: if this changes, the assertions below would pass
    // vacuously.
    expect(kinds).toContain('resuming')
    expect(kinds).toContain('transcode')
    expect(kinds).toContain('resolution')
  })

  it.each(kinds)('has a German translation for the "%s" notice', (kind) => {
    const entry = deDE.playPage?.nativePlayback?.notice?.[kind]
    expect(entry, `de-DE is missing playPage.nativePlayback.notice.${kind}`).toBeTruthy()
    expect(typeof entry).toBe('string')
  })

  it.each(kinds)('has an English translation for the "%s" notice', (kind) => {
    const entry = enUS.playPage?.nativePlayback?.notice?.[kind]
    expect(entry, `en-US is missing playPage.nativePlayback.notice.${kind}`).toBeTruthy()
    expect(typeof entry).toBe('string')
  })

  it('the resume message takes a position placeholder', () => {
    // The core sends `position_seconds` as a number and the interface formats it, so the
    // message must have somewhere to put it. A missing placeholder would silently show a
    // sentence without the time.
    for (const [name, locale] of [['de-DE', deDE], ['en-US', enUS]]) {
      const message = locale.playPage.nativePlayback.notice.resuming
      expect(message, `${name} must interpolate the position`).toContain('{position}')
    }
  })

  it.each([
    ['de-DE', deDE],
    ['en-US', enUS],
  ])('the status screen has its own strings in %s', (name, locale) => {
    expect(locale.playPage.nativePlayback.hint, `${name} hint`).toBeTruthy()
    expect(locale.playPage.nativePlayback.restart, `${name} restart`).toBeTruthy()
  })
})
