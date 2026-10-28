import {
  useCallback, useEffect, useLayoutEffect, useRef, useState,
  type CSSProperties, type ReactNode,
} from 'react'
import { Icon, type IconName } from './Icons'
import type { ThemeMode } from '../theme'

/** Sets the CSS custom property used for staggered entrance animations. */
export const stagger = (i: number, step = 40, max = 14): CSSProperties =>
  ({ ['--d' as string]: `${Math.min(i, max) * step}ms` }) as CSSProperties

const reducedMotion = () =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.motion === 'calm'

/* ------------------------------------------------------------------ CountUp */
export function CountUp({ value, duration = 800 }: { value: number; duration?: number }) {
  const [shown, setShown] = useState(0)
  const from = useRef(0)
  useEffect(() => {
    if (reducedMotion()) { setShown(value); from.current = value; return }
    const start = performance.now()
    const a = from.current
    let raf = 0
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / duration)
      const eased = 1 - Math.pow(1 - p, 3)
      const v = a + (value - a) * eased
      setShown(v)
      from.current = v
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])
  return <>{Math.round(shown)}</>
}

/* ------------------------------------------------------------------ Spinner */
export const Spinner = () => <span className="spinner" aria-hidden="true" />

export function Skeleton({ w = '100%', h = 14, r = 8 }: { w?: number | string; h?: number; r?: number }) {
  return <span className="skeleton" style={{ width: w, height: h, borderRadius: r }} />
}

/* ------------------------------------------------------------------- Banner */
type Tone = 'success' | 'danger' | 'info' | 'warn'
const toneIcon: Record<Tone, IconName> = { success: 'checkCircle', danger: 'alert', info: 'info', warn: 'alert' }

export function Banner({ tone, children, onClose }: { tone: Tone; children: ReactNode; onClose?: () => void }) {
  return (
    <div className={`banner banner-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      <Icon name={toneIcon[tone]} size={18} />
      <div className="banner-body">{children}</div>
      {onClose && <button className="banner-close" onClick={onClose} aria-label="Dismiss"><Icon name="x" size={15} /></button>}
    </div>
  )
}

/* -------------------------------------------------------------------- Badge */
export function Badge({ tone, children, dot = true }: { tone: 'success' | 'warn' | 'danger' | 'neutral' | 'info'; children: ReactNode; dot?: boolean }) {
  return <span className={`badge badge-${tone}`}>{dot && <i />}{children}</span>
}

/* -------------------------------------------------------------------- Empty */
export function EmptyState({ icon = 'inbox', title, hint }: { icon?: IconName; title: string; hint?: string }) {
  return (
    <div className="empty-state">
      <span className="empty-icon"><Icon name={icon} size={26} /></span>
      <strong>{title}</strong>
      {hint && <p>{hint}</p>}
    </div>
  )
}

/* -------------------------------------------------------------------- Modal */
export function Modal({ open, onClose, labelledBy, width = 680, children }: {
  open: boolean; onClose: () => void; labelledBy: string; width?: number; children: ReactNode
}) {
  const [render, setRender] = useState(open)
  useEffect(() => {
    if (open) { setRender(true); return }
    const t = window.setTimeout(() => setRender(false), 220)
    return () => window.clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [open, onClose])

  if (!render) return null
  return (
    <div className="modal-backdrop" data-state={open ? 'open' : 'closed'} role="presentation"
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby={labelledBy} style={{ width: `min(${width}px, 100%)` }}>
        {children}
      </section>
    </div>
  )
}

/* ------------------------------------------------------------------ Confirm */
interface ConfirmOptions { title: string; message: string; confirmLabel?: string; tone?: 'danger' | 'primary' }

export function useConfirm() {
  const [open, setOpen] = useState(false)
  const [opts, setOpts] = useState<ConfirmOptions>({ title: '', message: '' })
  const resolver = useRef<(v: boolean) => void>(() => {})

  const confirm = useCallback((o: ConfirmOptions) => new Promise<boolean>(resolve => {
    resolver.current = resolve
    setOpts(o)
    setOpen(true)
  }), [])

  const finish = useCallback((v: boolean) => { setOpen(false); resolver.current(v) }, [])
  const cancel = useCallback(() => finish(false), [finish])

  const dialog = (
    <Modal open={open} onClose={cancel} labelledBy="confirm-title" width={430}>
      <div className="confirm">
        <span className={`confirm-icon ${opts.tone === 'danger' ? 'danger' : ''}`}><Icon name={opts.tone === 'danger' ? 'alert' : 'info'} size={22} /></span>
        <h2 id="confirm-title">{opts.title}</h2>
        <p>{opts.message}</p>
        <div className="modal-actions">
          <button className="btn btn-secondary" onClick={cancel}>Cancel</button>
          <button className={`btn ${opts.tone === 'danger' ? 'btn-danger' : 'btn-primary'}`} onClick={() => finish(true)} autoFocus>{opts.confirmLabel ?? 'Confirm'}</button>
        </div>
      </div>
    </Modal>
  )
  return { confirm, dialog }
}

/* --------------------------------------------------------------------- Tabs */
export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { key: T; label: string }[]; value: T; onChange: (k: T) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [ind, setInd] = useState({ left: 0, width: 0 })
  const signature = tabs.map(t => t.label).join('|')

  const measure = useCallback(() => {
    const el = ref.current?.querySelector<HTMLElement>('[data-on="true"]')
    if (el) setInd({ left: el.offsetLeft, width: el.offsetWidth })
  }, [])
  useLayoutEffect(measure, [value, signature, measure])
  useEffect(() => {
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [measure])

  return (
    <div className="tabs" role="tablist" ref={ref}>
      {tabs.map(t => (
        <button key={t.key} role="tab" aria-selected={value === t.key} data-on={value === t.key}
          className={value === t.key ? 'on' : ''} onClick={() => onChange(t.key)}>{t.label}</button>
      ))}
      <span className="tab-indicator" style={{ transform: `translateX(${ind.left}px)`, width: ind.width }} />
    </div>
  )
}

/* -------------------------------------------------------------- Theme switch */
const themeOptions: { mode: ThemeMode; icon: IconName; label: string }[] = [
  { mode: 'light', icon: 'sun', label: 'Light' },
  { mode: 'system', icon: 'monitor', label: 'System' },
  { mode: 'dark', icon: 'moon', label: 'Dark' },
]

export function ThemeSwitch({ mode, onChange }: { mode: ThemeMode; onChange: (m: ThemeMode) => void }) {
  const idx = themeOptions.findIndex(o => o.mode === mode)
  return (
    <div className="theme-switch" role="radiogroup" aria-label="Colour theme" style={{ ['--i' as string]: idx } as CSSProperties}>
      <span className="theme-thumb" />
      {themeOptions.map(o => (
        <button key={o.mode} role="radio" aria-checked={mode === o.mode} title={o.label} aria-label={o.label}
          className={mode === o.mode ? 'on' : ''} onClick={() => onChange(o.mode)}>
          <Icon name={o.icon} size={15} />
        </button>
      ))}
    </div>
  )
}

/* ---------------------------------------------------------------- Segmented */
export function Segmented<T extends string>({ options, value, onChange, label }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string
}) {
  const idx = Math.max(0, options.findIndex(o => o.value === value))
  return (
    <div className="seg" role="radiogroup" aria-label={label}
      style={{ ['--i' as string]: idx, ['--n' as string]: options.length } as CSSProperties}>
      <span className="seg-thumb" />
      {options.map(o => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value}
          className={value === o.value ? 'on' : ''} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ useMounted */
/** Flips to true one frame after mount so CSS transitions (rings, bars) can animate in. */
export function useMounted() {
  const [on, setOn] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setOn(true))
    return () => cancelAnimationFrame(r)
  }, [])
  return on
}
