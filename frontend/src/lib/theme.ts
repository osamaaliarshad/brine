export type Theme = 'light' | 'dark'
export type ThemePreference = Theme | 'system'

const STORAGE_KEY = 'brine-theme'
const CHANGE_EVENT = 'brine-theme-change'

export function getTheme(): Theme {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches === false ? 'light' : 'dark'
}

export function getThemePreference(): ThemePreference {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved === 'light' || saved === 'dark' ? saved : 'system'
  } catch {
    return 'system'
  }
}

/** Apply and remember a theme choice; "system" follows the OS setting. */
export function setThemePreference(preference: ThemePreference): void {
  document.documentElement.dataset.theme = preference === 'system' ? systemTheme() : preference
  try {
    if (preference === 'system') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, preference)
  } catch {
    // Storage can be unavailable (private mode); the theme still applies for this page load.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function setTheme(theme: Theme): void {
  setThemePreference(theme)
}

/** Subscribe to theme changes made anywhere in the app. */
export function onThemeChange(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener)
  return () => window.removeEventListener(CHANGE_EVENT, listener)
}
