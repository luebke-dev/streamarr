// useCouchMode — the big-picture interface's focus and controller handling.
//
// Phase 5 of the desktop-app plan. The geometry lives in the Rust core
// (`desktop/player/src/couch.rs`, `pad.rs`) and is reached through the shell's
// `couch_*` commands; this composable is the thin layer that reports the layout
// and performs what the shell decides.
//
// Why the decisions are not made here, in one sentence: "move right" means *the
// nearest item to the right*, which is not `index + 1` in any layout where rows
// have different lengths. A second implementation in the UI would drift from the
// one the pad reader uses, and the drift would show up as a controller that
// moves somewhere different from where the arrow keys go.
//
// Everything here is therefore a translation: DOM rectangles out, shell commands
// in, effects applied to the DOM.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isDesktopApp } from 'src/utils/desktopPlatform'

// The shell calls, imported lazily so a browser build never evaluates them.
// `@tauri-apps/api/core` throws outside a Tauri window, and a static import
// would make the web build fail to start rather than merely lack the feature.
let invokeFn = null
let listenFn = null

async function loadShell() {
  if (invokeFn && listenFn) return true
  try {
    const core = await import('@tauri-apps/api/core')
    const event = await import('@tauri-apps/api/event')
    invokeFn = core.invoke
    listenFn = event.listen
    return true
  } catch {
    return false
  }
}

// How often the pad is polled for input while couch mode is on.
//
// 60 ms is a compromise with a reason: the repeat rule is time-based and lives in
// the shell, so polling faster gains nothing but CPU, and polling slower adds
// visible lag to the *first* press of a direction — the one that has no delay.
const PAD_POLL_MS = 60

// The state is module-level, because couch mode is one global mode rather than
// per-component state.
//
// This is not a style choice. A per-call `ref` would mean two components using
// the composable each get their own `active` flag, their own focus and — worse —
// their own pad poll timer, all draining the same device queue in the shell.
// Two pollers would also fight over the repeat clock: the shell sees each
// reading twice, and a held direction moves twice as fast. Found while writing
// the toolbar button, which would have been the second caller.
const active = ref(false)
const focusId = ref(null)
const pads = ref(0)
const available = ref(false)
const fullscreenState = ref(false)

// Element references are global for the same reason: the focus is one focus.
const elements = new Map()

let pollTimer = null
let unlistenPad = null
let startedAt = null
let refCount = 0
let hasResizeListener = false

export function useCouchMode() {
  // Kept below as local aliases so the rest of the module reads as before.

  const isSupported = computed(() => available.value)

  function registerElement(id, el) {
    if (!el) {
      elements.delete(id)
      return
    }
    elements.set(id, el)
  }

  // The rectangles the shell needs. Measured from the DOM because the UI alone
  // knows its layout, and rounded because `getBoundingClientRect` returns
  // sub-pixel values that must not decide which of two tiles is nearer.
  function measureLayout() {
    const items = []
    for (const [id, el] of elements) {
      if (!el?.isConnected) continue
      const rect = el.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) continue
      items.push({
        id,
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
        // A tile that is present but not navigable — a header, a spacer. It
        // occupies space so the focus does not jump across the gap it leaves.
        decorative: el.dataset?.couchDecorative === 'true',
      })
    }
    return items
  }

  async function reportLayout() {
    if (!available.value) return
    await invokeFn('set_couch_layout', { items: measureLayout() })
  }

  // Applies what the shell decided. The shell returns *effects*, not a new focus
  // position, because only the UI knows how "activate" is expressed.
  function applyEffect(effect) {
    if (!effect || effect.kind === 'none') return
    if (effect.kind === 'focus') {
      focusId.value = effect.id
      elements.get(effect.id)?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
      return
    }
    if (effect.kind === 'activate') {
      elements.get(effect.id)?.click?.()
    }
    // `back` and `menu` are left to the caller: the composable has no business
    // deciding what "back" means in a given view.
    return effect
  }

  async function move(direction, steps = 1) {
    if (!available.value || !active.value) return
    applyEffect(await invokeFn('couch_move', { direction, steps }))
  }

  async function activate() {
    if (!available.value || !active.value) return
    applyEffect(await invokeFn('couch_intent', { intent: 'activate' }))
  }

  // Fullscreen follows couch mode: entering it should fill the screen, leaving
  // it should give the desktop back. Done through the shell because the WebView's
  // own Fullscreen API makes an *element* fullscreen inside the page, not the
  // window.
  async function setFullscreen(fullscreen) {
    if (!available.value) return null
    const outcome = await invokeFn('couch_set_fullscreen', { fullscreen }).catch(() => null)
    if (outcome?.kind === 'failed') {
      // Not a dialog: the interface is still usable in a window, and a failed
      // window-manager request is not something a user can act on.
      return outcome
    }
    fullscreenState.value = outcome?.fullscreen ?? fullscreen
    return outcome
  }

  async function setActive(value) {
    if (!available.value) return
    const state = await invokeFn('set_couch_mode', { active: value })
    // The shell answers with its own view of the state, and the UI takes it as
    // the authority rather than assuming the switch succeeded.
    active.value = state?.active ?? value
    focusId.value = state?.focus ?? focusId.value
    if (value) {
      await reportLayout()
      await setFullscreen(true)
      startPadPolling()
    } else {
      stopPadPolling()
      await setFullscreen(false)
    }
  }

  async function toggle() {
    await setActive(!active.value)
  }

  // The pad is read by the shell, so input arrives as an event rather than as a
  // DOM event. The poll loop exists because gilrs has no notification: it is a
  // queue the shell drains, and this is the drain's clock.
  function startPadPolling() {
    stopPadPolling()
    if (!available.value) return
    startedAt = performance.now()
    pollTimer = setInterval(async () => {
      if (!active.value) return
      // The shell owns the device: `couch_pad_input` drains the controller queue
      // and returns one intent per input, already filtered of no-ops. The clock
      // is passed in rather than read in Rust so the repeat rule uses one time
      // base, and so it stays testable without sleeping.
      const intents = await invokeFn('couch_pad_input', {
        nowMs: Math.round(performance.now() - startedAt),
      }).catch(() => [])
      for (const intent of intents) {
        if (intent.action === 'move') {
          await move(intent.direction, intent.steps)
        } else if (intent.action === 'activate') {
          await activate()
        }
      }
    }, PAD_POLL_MS)
  }

  function stopPadPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  // Arrow keys and Enter drive the same path as a controller, so the interface is
  // usable on a keyboard — which is also how it can be tested without a pad.
  function onKeydown(event) {
    if (!active.value || !available.value) return
    const map = {
      ArrowUp: 'up',
      ArrowDown: 'down',
      ArrowLeft: 'left',
      ArrowRight: 'right',
    }
    const direction = map[event.key]
    if (direction) {
      event.preventDefault()
      move(direction)
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      activate()
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      setActive(false)
    }
  }

  onMounted(async () => {
    refCount += 1
    if (!isDesktopApp()) return
    // Only the first mount loads the shell and installs the listeners; a second
    // component must not install a second copy of either.
    if (unlistenPad !== null) return
    available.value = await loadShell()
    if (!available.value) return
    const state = await invokeFn('couch_state')
    active.value = state.active
    focusId.value = state.focus
    // The pad count comes from the shell's own reader, not from a guess: a
    // machine with no controller must be able to say so.
    const connected = await invokeFn('couch_pads').catch(() => [])
    pads.value = connected.length
    // The controller's own events, if a future build emits them.
    unlistenPad = await listenFn?.('couch-intent', (event) => {
      applyEffect(event.payload)
    })
    document.addEventListener('keydown', onKeydown)
    // One report on mount: the first layout is what makes the focus exist at all.
    await nextTick()
    await reportLayout()
  })

  onBeforeUnmount(() => {
    refCount -= 1
    // Torn down only when the last user goes away. A component unmounting while
    // another still shows the mode must not stop the pad reader.
    if (refCount > 0) return
    stopPadPolling()
    if (unlistenPad) {
      unlistenPad()
      unlistenPad = null
    }
    document.removeEventListener('keydown', onKeydown)
    elements.clear()
  })

  // A resize changes every rectangle, so the shell's geometry has to be rebuilt.
  // Without this, resizing the window makes "right" move to the wrong tile.
  // Installed once, with the first mount.
  if (typeof window !== 'undefined' && !hasResizeListener) {
    hasResizeListener = true
    let resizeTimer = null
    const onResize = () => {
      if (!active.value) return
      clearTimeout(resizeTimer)
      // Debounced: a drag fires continuously, and each report replaces the whole
      // layout.
      resizeTimer = setTimeout(() => {
        reportLayout()
      }, 150)
    }
    window.addEventListener('resize', onResize)
    // Deliberately never removed: the listener is installed once for the
    // application's lifetime and the state it touches is module-level. Removing
    // it on one component's unmount would disarm the others.
    void resizeTimer
  }

  watch(active, (value) => {
    if (value) nextTick(reportLayout)
  })

  return {
    active,
    focusId,
    pads,
    fullscreen: fullscreenState,
    isSupported,
    setFullscreen,
    registerElement,
    reportLayout,
    move,
    activate,
    setActive,
    toggle,
  }
}
