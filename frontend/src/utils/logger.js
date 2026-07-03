const isDev = process.env.DEV

export const logger = {
  debug: (...args) => isDev && console.debug(...args),
  log: (...args) => isDev && console.log(...args),
  warn: (...args) => isDev && console.warn(...args),
  info: (...args) => isDev && console.info(...args),
  error: (...args) => console.error(...args),
}
