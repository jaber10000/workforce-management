import type { ReactNode } from 'react'
import { useMounted } from './ui'

/** Single-value progress ring. Draws itself in on mount. */
export function Ring({ value, size = 140, stroke = 13, tone = 'var(--brand)', children }: {
  value: number; size?: number; stroke?: number; tone?: string; children?: ReactNode
}) {
  const on = useMounted()
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(100, value))
  return (
    <div className="donut" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${Math.round(v)} percent`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={tone} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={on ? c * (1 - v / 100) : c}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 1.2s var(--ease)', filter: 'drop-shadow(0 0 6px var(--brand-ring))' }} />
      </svg>
      <div className="donut-center">{children}</div>
    </div>
  )
}

export interface Segment { label: string; value: number; color: string }

/** Multi-segment donut (e.g. role pools). */
export function Donut({ segments, size = 140, stroke = 16, children }: {
  segments: Segment[]; size?: number; stroke?: number; children?: ReactNode
}) {
  const on = useMounted()
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const total = segments.reduce((a, s) => a + s.value, 0) || 1
  let acc = 0
  return (
    <div className="donut" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
        aria-label={segments.map(s => `${s.label} ${s.value}`).join(', ')}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        {segments.filter(s => s.value > 0).map((s, i) => {
          const len = (s.value / total) * c
          const dash = Math.max(0, len - (segments.length > 1 ? 3 : 0))
          const offset = -acc
          acc += len
          return <circle key={s.label} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={s.color} strokeWidth={stroke}
            strokeDasharray={`${on ? dash : 0} ${c}`} strokeDashoffset={offset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
            style={{ transition: `stroke-dasharray 1s var(--ease) ${i * 110}ms` }} />
        })}
      </svg>
      <div className="donut-center">{children}</div>
    </div>
  )
}
