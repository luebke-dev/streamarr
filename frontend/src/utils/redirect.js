export function sanitizeRedirect(target) {
  if (typeof target !== 'string' || !target.startsWith('/')) {
    return '/'
  }
  if (target.startsWith('//') || target.startsWith('/\\')) {
    return '/'
  }
  return target
}
