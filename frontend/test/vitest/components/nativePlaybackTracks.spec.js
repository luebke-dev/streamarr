/**
 * Audio and subtitle selection on the native playback screen.
 *
 * What these pin down is the part that is easy to get wrong and invisible when it
 * is: the player is **mpv**, so the track list has to come from mpv's own tracks.
 * The browser's `textTracks` would describe a stream the player never received,
 * and on the desktop it would be empty — a subtitle menu that lists nothing while
 * the film has three subtitles.
 *
 * The other half is the `null` cases. "Subtitle off" and "no subtitles yet" are
 * different, and mpv spells them differently (`no` versus `auto`); conflating
 * them lets mpv re-select the subtitle the user just turned off.
 */

import { describe, it, expect, vi } from 'vitest'

vi.mock('src/utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

async function mountView(props = {}) {
  const { mount } = await import('@vue/test-utils')
  const View = (await import('src/components/NativePlaybackView.vue')).default
  // Mounted *directly*, not wrapped in a `h()` parent: with a wrapper the
  // emitted events land on the wrapper's vnode and `wrapper.emitted()` on the
  // component sees nothing — which made three tests fail on `undefined` while
  // the component was behaving correctly.
  return mount(View, {
    props: { title: 'Ein Film', ...props },
    global: {
      stubs: {
        'q-btn': { props: ['label'], template: '<button>{{ label }}<slot /></button>' },
      },
      mocks: { $t: (key) => key },
    },
  })
}

const tracks = {
  audio: [
    { id: 1, label: 'English', language: 'eng', selected: true, external: false, codec: 'ac3' },
    { id: 2, label: 'Deutsch', language: 'deu', selected: false, external: false, codec: 'ac3' },
  ],
  subtitles: [
    { id: 3, label: 'Deutsch', language: 'deu', selected: false, external: true, codec: null },
  ],
  selectedAudio: 1,
  selectedSubtitle: null,
}

describe('NativePlaybackView track selection', () => {
  it('lists mpv\'s own tracks, not a browser list', async () => {
    const wrapper = await mountView({ tracks })
    const audio = wrapper.find('[data-test="native-audio-select"]')
    expect(audio.exists()).toBe(true)
    // Both tracks from the shell's answer.
    expect(audio.findAll('option')).toHaveLength(2)
    expect(audio.text()).toContain('English')
    expect(audio.text()).toContain('Deutsch')
  })

  it('marks an external subtitle as such', async () => {
    // Worth surfacing: an external track can vanish when the file is re-encoded,
    // unlike one embedded in the container.
    const wrapper = await mountView({ tracks })
    expect(wrapper.find('[data-test="native-subtitle-select"]').text()).toContain(
      'playPage.nativePlayback.external',
    )
  })

  it('offers an explicit "off" for subtitles', async () => {
    const wrapper = await mountView({ tracks })
    const options = wrapper.find('[data-test="native-subtitle-select"]').findAll('option')
    // One "off" plus the one real track.
    expect(options).toHaveLength(2)
    expect(options[0].text()).toBe('playPage.nativePlayback.subtitlesOff')
  })

  it('shows nothing before a track list has arrived', async () => {
    // `null` means "not read yet"; an empty list would claim the file has no
    // tracks, which is a different statement.
    const wrapper = await mountView({ tracks: null })
    expect(wrapper.find('[data-test="native-tracks"]').exists()).toBe(false)
  })

  /**
   * Fires a `change` the way a browser does.
   *
   * `setValue` on a native `<select>` does not deliver the event in this
   * environment — the two tests below failed silently on `undefined` until this
   * helper was added, which is worth knowing: a test that asserts on an event
   * nobody fired proves nothing.
   */
  async function choose(wrapper, testId, value) {
    const select = wrapper.find(`[data-test="${testId}"]`)
    const el = select.element
    el.value = value
    await select.trigger('change')
  }

  it('reports the selection as a number', async () => {
    const wrapper = await mountView({ tracks })
    await choose(wrapper, 'native-audio-select', '2')
    expect(wrapper.emitted('select-audio')).toBeTruthy()
    // A number, not the string the DOM carries: the shell expects `aid` as an
    // integer and a string would be a silent type error at the mpv boundary.
    expect(wrapper.emitted('select-audio')[0]).toEqual([2])
  })

  it('reports "off" as null, not as an empty selection', async () => {
    // mpv spells off as `no` and "choose for me" as `auto`; passing the wrong one
    // lets mpv re-select what the user just turned off.
    const wrapper = await mountView({ tracks })
    await choose(wrapper, 'native-subtitle-select', '')
    expect(wrapper.emitted('select-subtitle')[0]).toEqual([null])
  })

  it('reports a subtitle track as a number too', async () => {
    const wrapper = await mountView({ tracks })
    await choose(wrapper, 'native-subtitle-select', '3')
    expect(wrapper.emitted('select-subtitle')[0]).toEqual([3])
  })
})
