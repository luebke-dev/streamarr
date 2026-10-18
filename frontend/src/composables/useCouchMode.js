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

  /** The DOM element behind an id, whichever way it was registered. */
  function elementFor(id) {
    const entry = elements.get(id)
    if (!entry) return null
    return entry.__explicit ? entry.el : entry
  }

  function registerElement(id, el) {
    if (!el) {
      elements.delete(id)
      return
    }
    // Marked so `discover` leaves it alone: an explicit registration is not
    // backed by an attribute, and pruning it would silently drop it.
    elements.set(id, Object.assign(Object.create(null), { el, __explicit: true }))
  }

  /**
   * Finds the focusable elements in the DOM and registers them.
   *
   * # Why a scan rather than explicit registration
   *
   * The first version exposed `registerElement` and expected every component to
   * call it. Nothing ever did — so the layout reported to the shell was always
   * **empty**, the focus grid had no items, `move_focus` returned `None`, and
   * couch mode moved nothing. The mode looked implemented and did nothing, which
   * is the worst state a feature can be in.
   *
   * A marker attribute is the fix: the UI says *what* is focusable
   * (`data-couch-item="<id>"`), and this discovers it. Adding an attribute to a
   * list item is a change nobody forgets, whereas a function call is a change
   * nobody notices missing.
   *
   * `data-couch-decorative="true"` marks something that occupies space but is not
   * reachable — a header or a spacer. It is reported so the shell keeps the
   * geometry intact instead of letting the focus jump across the gap it leaves.
   */
  function discover() {
    if (typeof document === 'undefined') return
    const seen = new Set()
    for (const el of document.querySelectorAll('[data-couch-item]')) {
      const id = el.getAttribute('data-couch-item')
      if (!id) continue
      seen.add(id)
      elements.set(id, el)
    }
    // Elements that vanished from the DOM must not stay in the layout, or the
    // focus would move to something that is no longer on screen.
    //
    // Only *discovered* entries are pruned: an element registered explicitly
    // through `registerElement` is the caller's to remove, and deleting it here
    // would break the one path that does not go through an attribute.
    for (const [id, entry] of [...elements.entries()]) {
      if (entry?.__explicit) continue
      if (!seen.has(id)) elements.delete(id)
    }
  }

  // The rectangles the shell needs. Measured from the DOM because the UI alone
  // knows its layout, and rounded because `getBoundingClientRect` returns
  // sub-pixel values that must not decide which of two tiles is nearer.
  function measureLayout() {
    // Discovered first: the caller cannot be relied upon to register, and an
    // empty layout is indistinguishable from a broken one.
    discover()
    const items = []
    for (const [id, entry] of elements) {
      // Two shapes: a discovered DOM element, or an explicitly registered one.
      const el = entry?.__explicit ? entry.el : entry
      if (!el?.isConnected) continue
      const rect = el.getBoundingClientRect?.()
      if (!rect || rect.width <= 0 || rect.height <= 0) continue
      items.push({
        id,
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
        // A tile that is present but not navigable — a header, a spacer. It
        // occupies space so the focus does not jump across the gap it leaves.
        decorative:
          entry?.__explicit === true
            ? Boolean(el.dataset?.couchDecorative === 'true')
            : el.getAttribute?.('data-couch-decorative') === 'true',
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
      elementFor(effect.id)?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
      return
    }
    if (effect.kind === 'activate') {
      elementFor(effect.id)?.click?.()
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

  /**
   * Whether a game stream owns the controllers right now.
   *
   * `gilrs` hands each event out exactly once, so the couch poll and the game's
   * poll cannot both run: the first that drains the queue wins, and the other
   * silently sees nothing. Whichever mode the user is in decides which one runs.
   */
  const suppressed = ref(false)

  /**
   * Stops or resumes the couch poll because a game took over the controllers.
   *
   * Called by the game stream when it starts and ends. Not a nicety: with both
   * polling, a controller would move a menu highlight *and* the game's character
   * from one button press, or — worse — do neither reliably.
   */
  function setSuppressed(value) {
    suppressed.value = Boolean(value)
    if (suppressed.value) {
      stopPadPolling()
    } else if (active.value) {
      startPadPolling()
    }
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
    // A game has the controllers; draining the queue here would take them from it.
    if (suppressed.value) return
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
    setSuppressed,
    suppressed,
    setFullscreen,
    registerElement,
    reportLayout,
    move,
    activate,
    setActive,
    toggle,
  }
}
