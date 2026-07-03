// useKeyboardShortcuts — registers a global keydown handler that is
// suppressed when focus is in an editable element (input/textarea/contenteditable).
// `bindings` is a map of key -> handler. The 'preventDefault' flag is on by default.
import { onMounted, onBeforeUnmount } from 'vue'

const isEditableTarget = (target) => {
  if (!target) return false
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (target.isContentEditable) return true
  return false
}

export function useKeyboardShortcuts(bindings, { preventDefault = true } = {}) {
  const onKeydown = (e) => {
    if (isEditableTarget(e.target)) return
    const handler = bindings[e.key]
    if (!handler) return
    if (preventDefault) e.preventDefault()
    handler(e)
  }

  onMounted(() => {
    document.addEventListener('keydown', onKeydown)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeydown)
  })
}
