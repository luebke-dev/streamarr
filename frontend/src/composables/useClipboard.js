/**
 * Clipboard helper with built-in success/error notifications.
 *
 * Wraps Quasar's `copyToClipboard` and `Notify.create`. Call the returned
 * `copy(text, { successMessage, errorMessage })` to copy and notify.
 *
 * If `successMessage` or `errorMessage` are falsy, the corresponding
 * notification is suppressed — useful for silent copies where only the
 * side-effect matters.
 *
 * @returns {{ copy: (text: string, opts?: { successMessage?: string, errorMessage?: string, timeout?: number }) => Promise<boolean> }}
 */
import { copyToClipboard, Notify } from 'quasar'
import { logger } from 'src/utils/logger'

export function useClipboard() {
  async function copy(text, { successMessage = '', errorMessage = '', timeout = 1500 } = {}) {
    try {
      await copyToClipboard(text)
      if (successMessage) {
        Notify.create({ type: 'positive', message: successMessage, timeout })
      }
      return true
    } catch (err) {
      logger.warn('Copy to clipboard failed:', err)
      if (errorMessage) {
        Notify.create({ type: 'negative', message: errorMessage, timeout: timeout + 1000 })
      }
      return false
    }
  }

  return { copy }
}
