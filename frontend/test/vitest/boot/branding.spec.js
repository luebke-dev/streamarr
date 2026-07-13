import { afterEach, describe, expect, it, vi } from 'vitest'

import { Dark } from 'quasar'
import { applyBranding } from 'src/utils/brandingTheme'

describe('branding boot helpers', () => {
  afterEach(() => {
    document.body.className = ''
    document.documentElement.removeAttribute('style')
    document.getElementById('streamarr-branding-css')?.remove()
  })

  it('applies active theme classes, variables, colors, dark mode and custom css', () => {
    const darkSpy = vi.spyOn(Dark, 'set').mockImplementation(() => {})

    applyBranding(
      { custom_css: '.login { color: red; }' },
      {
        id: 'teal theme',
        dark: true,
        colors: { primary: '#00aaff' },
        variables: { radius: '4px', '--app-density': 'compact' },
        custom_css: '.shell { color: blue; }',
      },
    )

    expect(document.body.classList.contains('streamarr-theme-teal-theme')).toBe(true)
    expect(document.documentElement.style.getPropertyValue('--streamarr-radius')).toBe('4px')
    expect(document.documentElement.style.getPropertyValue('--app-density')).toBe('compact')
    expect(document.documentElement.style.getPropertyValue('--q-primary')).toBe('#00aaff')
    expect(document.getElementById('streamarr-branding-css')?.textContent).toContain(
      '.login { color: red; }',
    )
    expect(document.getElementById('streamarr-branding-css')?.textContent).toContain(
      '.shell { color: blue; }',
    )
    expect(darkSpy).toHaveBeenCalledWith(true)

    darkSpy.mockRestore()
  })

  it('replaces previous theme classes and falls back to default theme class', () => {
    document.body.classList.add('streamarr-theme-old')

    applyBranding({ custom_css: '' }, null)

    expect(document.body.classList.contains('streamarr-theme-old')).toBe(false)
    expect(document.body.classList.contains('streamarr-theme-default')).toBe(true)
  })
})
