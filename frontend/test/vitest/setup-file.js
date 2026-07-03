import { config } from '@vue/test-utils'
import { Quasar } from 'quasar'

// @vue/devtools-kit (a pinia dependency) calls localStorage.getItem at module
// evaluation time, before happy-dom fully patches the global. Polyfill here so
// the import never throws, and tests can still call localStorage methods normally.
if (typeof localStorage === 'undefined' || typeof localStorage.getItem !== 'function') {
  const _store = new Map()
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: (k) => _store.get(String(k)) ?? null,
      setItem: (k, v) => _store.set(String(k), String(v)),
      removeItem: (k) => _store.delete(String(k)),
      clear: () => _store.clear(),
      key: (i) => [..._store.keys()][i] ?? null,
      get length() {
        return _store.size
      },
    },
    writable: true,
    configurable: true,
  })
}

// Suppress Vue attr fallthrough warnings in tests
config.global.config.warnHandler = () => null

config.global.plugins = [[Quasar, {}]]
