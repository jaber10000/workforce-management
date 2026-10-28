import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { Icon } from './Icons'
import { Segmented, ThemeSwitch } from './ui'
import { PALETTES, type ThemeApi } from '../theme'

export default function ThemePanel({ theme, placement }: { theme: ThemeApi; placement: 'side' | 'bar' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); window.removeEventListener('keydown', onKey) }
  }, [open])

  const current = PALETTES.find(p => p.key === theme.palette) ?? PALETTES[0]

  return (
    <div className={`appearance ${placement}`} ref={ref}>
      <button type="button" className="appearance-btn" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(o => !o)}>
        <span className="swatch" style={{ ['--a' as string]: current.a, ['--b' as string]: current.b } as CSSProperties} />
        <span className="appearance-label">Appearance</span>
        <Icon name="sliders" size={16} />
      </button>
      {open && (
        <div className="appearance-pop" role="dialog" aria-label="Appearance settings">
          <div className="pop-row"><span>Mode</span><ThemeSwitch mode={theme.mode} onChange={theme.setMode} /></div>
          <div className="pop-row stack"><span>Colour theme</span>
            <div className="pal-grid">
              {PALETTES.map(p => (
                <button key={p.key} type="button" className={`pal ${theme.palette === p.key ? 'on' : ''}`} aria-pressed={theme.palette === p.key}
                  onClick={() => theme.setPalette(p.key)}>
                  <span className="swatch lg" style={{ ['--a' as string]: p.a, ['--b' as string]: p.b } as CSSProperties}>
                    {theme.palette === p.key && <Icon name="check" size={14} />}
                  </span>
                  <small>{p.label}</small>
                </button>
              ))}
            </div>
          </div>
          <div className="pop-row"><span>Density</span>
            <Segmented label="Density" value={theme.density} onChange={theme.setDensity}
              options={[{ value: 'comfortable', label: 'Roomy' }, { value: 'compact', label: 'Compact' }]} /></div>
          <div className="pop-row"><span>Corners</span>
            <Segmented label="Corner style" value={theme.radius} onChange={theme.setRadius}
              options={[{ value: 'sharp', label: 'Sharp' }, { value: 'soft', label: 'Soft' }, { value: 'round', label: 'Round' }]} /></div>
          <div className="pop-row"><span>Animation</span>
            <Segmented label="Animation" value={theme.motion} onChange={theme.setMotion}
              options={[{ value: 'full', label: 'Full' }, { value: 'calm', label: 'Calm' }]} /></div>
        </div>
      )}
    </div>
  )
}
