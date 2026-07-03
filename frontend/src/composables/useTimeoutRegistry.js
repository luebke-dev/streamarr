import { onUnmounted } from 'vue'

export function useTimeoutRegistry() {
  const timers = new Map()

  function schedule(callback, delay) {
    const timerId = setTimeout(() => {
      timers.delete(timerId)
      callback()
    }, delay)
    timers.set(timerId, null)
    return timerId
  }

  function delay(delayMs) {
    let timerId
    return new Promise((resolve) => {
      timerId = setTimeout(() => {
        timers.delete(timerId)
        resolve(true)
      }, delayMs)
      timers.set(timerId, resolve)
    })
  }

  function clear(timerId) {
    if (!timerId) return
    const resolve = timers.get(timerId)
    clearTimeout(timerId)
    timers.delete(timerId)
    if (resolve) resolve(false)
  }

  function clearAll() {
    for (const [timerId, resolve] of timers) {
      clearTimeout(timerId)
      if (resolve) resolve(false)
    }
    timers.clear()
  }

  onUnmounted(clearAll)

  return {
    schedule,
    delay,
    clear,
    clearAll,
  }
}
