import { useEffect, useMemo, useState, type CSSProperties } from 'react'

const COLORS = ['var(--brand)', 'var(--brand-2)', 'var(--accent)', 'var(--warn)', 'var(--info)', 'var(--success)']

/** One short burst of confetti. Increase `burst` to fire it again. */
export default function Confetti({ burst }: { burst: number }) {
  const [live, setLive] = useState(0)
  useEffect(() => {
    if (!burst) return
    setLive(burst)
    const t = window.setTimeout(() => setLive(0), 2000)
    return () => window.clearTimeout(t)
  }, [burst])

  const pieces = useMemo(() => Array.from({ length: 46 }, (_, i) => {
    const angle = (i / 46) * Math.PI * 2 + Math.random() * 0.5
    const dist = 140 + Math.random() * 260
    return {
      id: i,
      style: {
        ['--tx' as string]: `${Math.cos(angle) * dist}px`,
        ['--ty' as string]: `${Math.sin(angle) * dist - 120}px`,
        ['--rot' as string]: `${Math.random() * 720 - 360}deg`,
        background: COLORS[i % COLORS.length],
        animationDelay: `${Math.random() * 90}ms`,
        width: 6 + Math.random() * 6, height: 9 + Math.random() * 7,
      } as CSSProperties,
    }
  }), [live]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!live) return null
  return <div className="confetti" aria-hidden="true">{pieces.map(p => <i key={p.id} style={p.style} />)}</div>
}
