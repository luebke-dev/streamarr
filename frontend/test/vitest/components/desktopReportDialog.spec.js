/**
 * DesktopReportDialog — what a report contains, and what it must not.
 *
 * Two things are worth testing here and they are not the rendering:
 *
 *   * **The preview comes before the send.** Uploading a diagnostic bundle is not
 *     something to do quietly, so the dialog asks the shell what it *would* send
 *     when it opens.
 *   * **A failed send keeps the collected text.** A report that could not be
 *     delivered is still valuable, and throwing it away would leave the user with
 *     nothing to paste into a message.
 *
 * The dialog is also the only place the UI reaches these commands, and the
 * commands take no arguments — so there is nothing a bug here could widen.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

const invoke = vi.fn()
vi.mock('@tauri-apps/api/core', () => ({ invoke: (...args) => invoke(...args) }))
vi.mock('src/utils/logger', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}))

let desktop = true
vi.mock('src/utils/desktopPlatform', () => ({ isDesktopApp: () => desktop }))

async function mountDialog(props = {}) {
  const { defineComponent, h } = await import('vue')
  const { mount } = await import('@vue/test-utils')
  const { default: Dialog } = await import('src/components/DesktopReportDialog.vue')
  const Comp = defineComponent({
    components: { Dialog },
    setup() {
      return () => h(Dialog, { modelValue: true, ...props })
    },
  })
  const wrapper = mount(Comp, {
    global: {
      stubs: {
        // Quasar's components are not needed to answer the question; the
        // behaviour is in the script.
        'q-dialog': { template: '<div><slot /></div>' },
        'q-card': { template: '<div><slot /></div>' },
        'q-card-section': { template: '<div><slot /></div>' },
        'q-card-actions': { template: '<div><slot /></div>' },
        'q-list': { template: '<div><slot /></div>' },
        'q-item': { template: '<div><slot /></div>' },
        'q-item-section': { template: '<div><slot /></div>' },
        'q-item-label': { template: '<div><slot /></div>' },
        'q-icon': { template: '<i />' },
        // The label is rendered so a test can click the *send* button rather
        // than whichever button happens to be first — `find('button')` picked
        // "cancel" and the failure looked like a broken send.
        'q-btn': {
          props: ['label'],
          template: '<button @click="$emit(\'click\')">{{ label }}<slot /></button>',
        },
        'q-input': { template: '<textarea />' },
        'q-banner': { template: '<div><slot /></div>' },
      },
      mocks: { $t: (key) => key },
    },
  })
  await new Promise((resolve) => setTimeout(resolve, 0))
  return wrapper
}

/// Clicks the button that sends, identified by its label rather than by position.
async function sendButton(wrapper) {
  const buttons = wrapper.findAll('button')
  const send = buttons.find((b) => b.text().includes('desktopReport.send'))
  if (!send) throw new Error('Senden-Knopf nicht gefunden')
  await send.trigger('click')
}

describe('DesktopReportDialog', () => {
  beforeEach(() => {
    invoke.mockReset()
    desktop = true
    invoke.mockImplementation(async (command) => {
      if (command === 'report_preview') {
        return {
          appVersion: '2026.2.1',
          platform: 'linux-wayland',
          mpvVersion: 'mpv v0.41.0',
          gstreamerVersion: null,
          logCount: 2,
          logBytes: 4096,
          hasLogs: true,
        }
      }
      return undefined
    })
  })

  it('asks for the preview as soon as it opens', async () => {
    await mountDialog()
    // The user must see what would be sent before deciding to send it. Uploading
    // a diagnostic bundle quietly is not acceptable.
    expect(invoke).toHaveBeenCalledWith('report_preview')
    // And it must not have sent anything merely by being opened.
    expect(invoke).not.toHaveBeenCalledWith('report_problem')
  })

  it('does not call the shell in a browser build', async () => {
    desktop = false
    await mountDialog()
    // The report is assembled by the shell; in a browser there is nothing to
    // assemble it from, so no call is made at all.
    expect(invoke).not.toHaveBeenCalled()
  })

  it('shows a missing GStreamer as "not in this build" rather than blank', async () => {
    const wrapper = await mountDialog()
    // `gstreamerVersion: null` is a finding, not a collection failure: this build
    // links no GStreamer, and the user reporting that games do not start needs to
    // know that.
    expect(wrapper.text()).toContain('desktopReport.notInBuild')
  })

  it('reports the log count and size', async () => {
    const wrapper = await mountDialog()
    expect(wrapper.text()).toContain('desktopReport.logCount')
  })

  it('says what is not included', async () => {
    const wrapper = await mountDialog()
    // A user deciding whether to press the button needs a straight answer to
    // "does this contain my token".
    expect(wrapper.text()).toContain('desktopReport.excluded')
  })

  it('keeps the collected report when sending fails', async () => {
    const wrapper = await mountDialog()
    invoke.mockImplementation(async (command) => {
      if (command === 'report_problem') {
        return {
          kind: 'notSent',
          problem: 'Keine Verbindung',
          advice: 'IP-Adresse prüfen',
          message: 'Desktop client report\nApp: 2026.2.1\n',
        }
      }
      return undefined
    })

    await sendButton(wrapper)
    await new Promise((resolve) => setTimeout(resolve, 0))

    // The collected text is the useful part of a failed send; discarding it
    // would leave the user with nothing to paste.
    expect(wrapper.text()).toContain('Keine Verbindung')
    expect(wrapper.text()).toContain('IP-Adresse prüfen')
  })

  it('sends no arguments, so the page cannot widen the report', async () => {
    const wrapper = await mountDialog()
    invoke.mockImplementation(async (command) => {
      if (command === 'report_problem') return { kind: 'sent', bytes: 100, hasLogs: true }
      return undefined
    })

    await sendButton(wrapper)
    await new Promise((resolve) => setTimeout(resolve, 0))

    const call = invoke.mock.calls.find(([command]) => command === 'report_problem')
    expect(call).toBeTruthy()
    // `invoke(name)` with no second argument. A command that accepted a path or
    // a field would be a way for the WebView to read arbitrary files through a
    // "report".
    expect(call[1]).toBeUndefined()
  })
})
