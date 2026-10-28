import { useCallback, useEffect, useState } from 'react'

/* ----------------------------------------------------------------- types */
export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'
export type Palette = 'lagoon' | 'indigo' | 'violet' | 'rose' | 'amber' | 'forest'
export type Density = 'comfortable' | 'compact'
export type Radius = 'sharp' | 'soft' | 'round'
export type Motion = 'full' | 'calm'

/** `a`/`b` are only used for the swatch preview; real colours live in palettes.css. */
export const PALETTES: { key: Palette; label: string; a: string; b: string }[] = [
  { key: 'lagoon', label: 'Lagoon', a: '#0a8576', b: '#3b6fe0' },
  { key: 'indigo', label: 'Indigo', a: '#4f46e5', b: '#06a5c9' },
  { key: 'violet', label: 'Orchid', a: '#7c3aed', b: '#e11d74' },
  { key: 'rose', label: 'Rose', a: '#e11d48', b: '#f97316' },
  { key: 'amber', label: 'Amber', a: '#f59e0b', b: '#0f766e' },
  { key: 'forest', label: 'Forest', a: '#15803d', b: '#ca8a04' },
]
const PALETTE_KEYS = PALETTES.map(p => p.key) as readonly Palette[]
const MODES = ['light', 'dark', 'system'] as const
const DENSITIES = ['comfortable', 'compact'] as const
const RADII = ['sharp', 'soft', 'round'] as const
const MOTIONS = ['full', 'calm'] as const

const KEYS = { mode: 'wf-theme', palette: 'wf-palette', density: 'wf-density', radius: 'wf-radius', motion: 'wf-motion' }
const query = () => window.matchMedia('(prefers-color-scheme: dark)')

function readPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    if (v && (allowed as readonly string[]).includes(v)) return v as T
  } catch { /* storage unavailable */ }
  return fallback
}
function writePref(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* ignore */ }
}

export const readStoredMode = (): ThemeMode => readPref(KEYS.mode, MODES, 'system')

export function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === 'system') return query().matches ? 'dark' : 'light'
  return mode
}

/* ------------------------------------------------- animated theme reveal */
// The circular reveal starts from wherever the person last clicked.
let pointer = { x: 0, y: 0 }
if (typeof window !== 'undefined') {
  pointer = { x: window.innerWidth - 80, y: 48 }
  window.addEventListener('pointerdown', e => { pointer = { x: e.clientX, y: e.clientY } }, true)
}
type ViewTransitionDoc = Document & { startViewTransition?: (cb: () => void) => unknown }

function withTransition(update: () => void, animate: boolean) {
  const root = document.documentElement
  const calm = root.dataset.motion === 'calm' || window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const doc = document as ViewTransitionDoc
  if (!animate || calm) { update(); return }
  if (doc.startViewTransition) {
    root.style.setProperty('--vt-x', `${pointer.x}px`)
    root.style.setProperty('--vt-y', `${pointer.y}px`)
    doc.startViewTransition(update)
    return
  }
  root.classList.add('theme-anim')
  window.setTimeout(() => root.classList.remove('theme-anim'), 450)
  update()
}

export function applyTheme(mode: ThemeMode, animate = false) {
  const root = document.documentElement
  const resolved = resolveTheme(mode)
  withTransition(() => { root.dataset.theme = resolved; root.style.colorScheme = resolved }, animate)
}

/** Call once before first render so there is no flash of the wrong theme. */
export function initTheme() {
  const root = document.documentElement
  applyTheme(readStoredMode())
  root.dataset.palette = readPref(KEYS.palette, PALETTE_KEYS, 'lagoon')
  root.dataset.density = readPref(KEYS.density, DENSITIES, 'comfortable')
  root.dataset.radius = readPref(KEYS.radius, RADII, 'soft')
  root.dataset.motion = readPref(KEYS.motion, MOTIONS, 'full')
}

function useAttrPref<T extends string>(key: string, attr: string, allowed: readonly T[], fallback: T, animate: boolean) {
  const [value, setValue] = useState<T>(() => readPref(key, allowed, fallback))
  const set = useCallback((next: T) => {
    setValue(next)
    writePref(key, next)
    withTransition(() => { document.documentElement.dataset[attr] = next }, animate)
  }, [key, attr, animate])
  return [value, set] as const
}

export function useTheme() {
  const [mode, setModeState] = useState<ThemeMode>(readStoredMode)
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(readStoredMode()))
  const [palette, setPalette] = useAttrPref<Palette>(KEYS.palette, 'palette', PALETTE_KEYS, 'lagoon', true)
  const [density, setDensity] = useAttrPref<Density>(KEYS.density, 'density', DENSITIES, 'comfortable', false)
  const [radius, setRadius] = useAttrPref<Radius>(KEYS.radius, 'radius', RADII, 'soft', false)
  const [motion, setMotion] = useAttrPref<Motion>(KEYS.motion, 'motion', MOTIONS, 'full', false)

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next)
    writePref(KEYS.mode, next)
    applyTheme(next, true)
    setResolved(resolveTheme(next))
  }, [])

  // follow the OS when in "system" mode
  useEffect(() => {
    if (mode !== 'system') return
    const mq = query()
    const onChange = () => { applyTheme('system', true); setResolved(resolveTheme('system')) }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [mode])

  const toggle = useCallback(() => setMode(resolved === 'dark' ? 'light' : 'dark'), [resolved, setMode])

  return { mode, resolved, setMode, toggle, palette, setPalette, density, setDensity, radius, setRadius, motion, setMotion }
}

export type ThemeApi = ReturnType<typeof useTheme>
