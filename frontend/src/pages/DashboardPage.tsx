import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { getAuditLog, getEmployees, getFairness, getLeaves, getRosterDetail, getVersions } from '../api'
import { Icon } from '../components/Icons'
import { Donut, Ring } from '../components/charts'
import { Badge, Banner, CountUp, EmptyState, Skeleton, stagger, useMounted } from '../components/ui'
import { fmtNum, greeting, shortDate, timeAgo } from '../utils'
import type { AuditEntry, Employee, Fairness, Leave, Page, RosterDetail, RosterVersion } from '../types'

interface Data {
  employees: Employee[]; leaves: Leave[]; version: RosterVersion | null
  detail: RosterDetail | null; fairness: Fairness | null; audit: AuditEntry[]
}

const SHIFTS = [
  { key: 'morning', label: 'Morning', code: 'm' },
  { key: 'evening', label: 'Evening', code: 'e' },
  { key: 'night', label: 'Night', code: 'n' },
] as const

const ROLE_COLORS: Record<string, string> = {
  general: 'var(--brand)', senior_support: 'var(--accent)', supervisor: 'var(--info)', other: 'var(--warn)',
}
const ROLE_LABELS: Record<string, string> = {
  general: 'General', senior_support: 'Senior support', supervisor: 'Supervisor', other: 'Other',
}
const leaveTone = (t: string) => (t === 'Sick' ? 'danger' : t === 'Casual' ? 'info' : 'success') as 'danger' | 'info' | 'success'

export default function DashboardPage({ onNavigate, onAddEmployee }: { onNavigate: (p: Page) => void; onAddEmployee: () => void }) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const mounted = useMounted()

  const load = useCallback(async () => {
    setLoading(true); setError('')
    const [emp, lv, ver, aud] = await Promise.allSettled([
      getEmployees({ is_active: true, limit: 200 }), getLeaves({ limit: 200 }), getVersions(), getAuditLog(),
    ])
    if (emp.status === 'rejected' && lv.status === 'rejected' && ver.status === 'rejected') {
      setError('The server did not respond. Check that the backend is running, then try again.')
      setLoading(false); return
    }
    const version = ver.status === 'fulfilled' ? ver.value[0] ?? null : null
    let detail: RosterDetail | null = null
    let fairness: Fairness | null = null
    if (version) {
      const [d, f] = await Promise.allSettled([getRosterDetail(version.id), getFairness(version.id)])
      if (d.status === 'fulfilled') detail = d.value
      if (f.status === 'fulfilled') fairness = f.value
    }
    setData({
      employees: emp.status === 'fulfilled' ? emp.value.items : [],
      leaves: lv.status === 'fulfilled' ? lv.value.items : [],
      version, detail, fairness,
      audit: aud.status === 'fulfilled' ? aud.value : [],
    })
    setLoading(false)
  }, [])
  useEffect(() => { void load() }, [load])

  const stats = useMemo(() => {
    if (!data) return null
    const days = data.detail?.coverage.days ?? []
    let required = 0, covered = 0
    const perShift = SHIFTS.map(s => {
      let req = 0, asg = 0
      for (const d of days) { req += d.shifts[s.key].required; asg += Math.min(d.shifts[s.key].assigned, d.shifts[s.key].required) }
      required += req; covered += asg
      return { ...s, req, asg, pct: req ? (asg / req) * 100 : 100 }
    })
    const pending = data.leaves.filter(l => l.status === 'Pending')
    const roles = Object.keys(ROLE_LABELS).map(k => ({
      label: ROLE_LABELS[k], color: ROLE_COLORS[k], value: data.employees.filter(e => e.role_pool === k).length,
    }))
    return {
      days, perShift, pending, roles,
      pct: required ? (covered / required) * 100 : null,
      senior: data.employees.filter(e => e.role_pool === 'senior_support').length,
    }
  }, [data])

  const headline = (() => {
    if (!data || !stats) return 'Loading your workspace…'
    if (!data.version) return 'No roster yet. Generate your first draft to see coverage here.'
    const short = data.detail?.coverage.days_with_shortage ?? 0
    const v = `v${data.version.version_no}`
    return short === 0
      ? `Roster ${v} covers every shift across ${stats.days.length} days.`
      : `Roster ${v} is short on ${short} of ${stats.days.length} days.`
  })()

  return (
    <>
      <section className="dash-hero">
        <div>
          <div className="hero-date">{new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}</div>
          <h1>{greeting()}.</h1>
          <p>{headline}</p>
          <div className="hero-actions">
            <button className="btn btn-hero" onClick={() => onNavigate('roster')}><Icon name="zap" size={16} /> Open roster</button>
            <button className="btn btn-hero-ghost" onClick={onAddEmployee}><Icon name="plus" size={16} /> Add employee</button>
            <button className="btn btn-hero-ghost" onClick={() => onNavigate('leaves')}>
              <Icon name="calendarCheck" size={16} /> Review leave{stats && stats.pending.length > 0 ? ` (${stats.pending.length})` : ''}
            </button>
          </div>
        </div>
        <div className="hero-art" aria-hidden="true"><i /><i /><i /><b /><Icon name="sparkles" size={30} /></div>
      </section>

      {error && <Banner tone="danger">{error} <button className="link-inline" onClick={() => void load()}>Try again</button></Banner>}

      <section className="kpi-grid">
        {loading && !data ? [0, 1, 2, 3].map(i => <div key={i} className="stat-card"><Skeleton w={46} h={46} r={14} /><div><Skeleton w={90} h={11} /><br /><Skeleton w={60} h={24} /></div></div>) : <>
          <div className="stat-card" style={stagger(0, 80)}><span className="stat-icon"><Icon name="users" size={22} /></span><div><span className="stat-label">Team size</span><strong><CountUp value={data?.employees.length ?? 0} /></strong><small>{stats?.senior ?? 0} senior support</small></div></div>
          <div className="stat-card" style={stagger(1, 80)}><span className="stat-icon violet"><Icon name="calendarCheck" size={22} /></span><div><span className="stat-label">Leave waiting</span><strong><CountUp value={stats?.pending.length ?? 0} /></strong><small>{stats && stats.pending.length > 0 ? 'Needs a decision' : 'All caught up'}</small></div></div>
          <div className={`stat-card ${stats && stats.pct !== null && stats.pct < 100 ? 'bad' : ''}`} style={stagger(2, 80)}><span className={`stat-icon ${stats && stats.pct !== null && stats.pct < 100 ? 'red' : 'teal'}`}><Icon name={stats && stats.pct !== null && stats.pct < 100 ? 'alert' : 'checkCircle'} size={22} /></span><div><span className="stat-label">Shift cover</span><strong>{stats?.pct == null ? '—' : <><CountUp value={Math.round(stats.pct)} />%</>}</strong><small>{data?.detail ? `M ${fmtNum(data.detail.coverage.totals.morning)} · E ${fmtNum(data.detail.coverage.totals.evening)} · N ${fmtNum(data.detail.coverage.totals.night)} short` : 'No roster generated'}</small></div></div>
          <div className="stat-card" style={stagger(3, 80)}><span className="stat-icon"><Icon name="scale" size={22} /></span><div><span className="stat-label">Night spread</span><strong>{data?.fairness ? data.fairness.summary.night_spread : '—'}</strong><small>{data?.fairness ? `min ${data.fairness.summary.night_min} · max ${data.fairness.summary.night_max}` : 'Needs a roster'}</small></div></div>
        </>}
      </section>

      <section className="dash-grid">
        <div className="panel cover-panel" style={stagger(2, 90)}>
          <div className="panel-heading"><div><h3>Coverage by shift</h3><p>{data?.version ? `Version ${data.version.version_no} · ${shortDate(data.version.start_date)} – ${shortDate(data.version.end_date)}` : 'Generate a roster to see this'}</p></div>
            {data?.version && <Badge tone={data.version.status === 'published' ? 'success' : 'info'}>{data.version.status}</Badge>}</div>
          {stats && data?.version && stats.pct !== null ? <div className="cover-body">
            <Ring value={stats.pct} tone={stats.pct < 100 ? '#f2a20c' : 'var(--brand)'}>
              <strong>{Math.round(stats.pct)}%</strong><span>covered</span>
            </Ring>
            <div className="shift-bars">
              {stats.perShift.map((s, i) => (
                <div key={s.key} className="shift-bar">
                  <div className="shift-bar-top"><span className={`code code-${s.code}`}>{s.code.toUpperCase()}</span><b>{s.label}</b><em>{fmtNum(s.asg)} / {s.req}</em></div>
                  <div className="track"><i className={`fill-${s.code}`} style={{ width: mounted ? `${s.pct}%` : '0%', transitionDelay: `${i * 120}ms` }} /></div>
                </div>
              ))}
            </div>
          </div> : <EmptyState icon="calendar" title="No roster to measure" hint="Open the roster page and generate a draft." />}
        </div>

        <div className="panel" style={stagger(3, 90)}>
          <div className="panel-heading"><div><h3>Team by role</h3><p>Active employees</p></div></div>
          <div className="role-body">
            <Donut segments={stats?.roles ?? []} size={132}><strong>{data?.employees.length ?? 0}</strong><span>people</span></Donut>
            <ul className="role-legend">
              {(stats?.roles ?? []).map(r => <li key={r.label}><i style={{ background: r.color }} />{r.label}<b>{r.value}</b></li>)}
            </ul>
          </div>
        </div>
      </section>

      <section className="panel" style={stagger(4, 90)}>
        <div className="panel-heading"><div><h3>Day by day</h3><p>Hover a bar to see the day. Red days are short of cover.</p></div></div>
        {stats && stats.days.length > 0 ? <div className="day-strip" role="list">
          {stats.days.slice(0, 31).map((d, i) => {
            const req = SHIFTS.reduce((a, s) => a + d.shifts[s.key].required, 0)
            const asg = SHIFTS.reduce((a, s) => a + Math.min(d.shifts[s.key].assigned, d.shifts[s.key].required), 0)
            const pct = req ? (asg / req) * 100 : 100
            return <div key={d.date} role="listitem" className={`day-col ${d.status === 'SHORTAGE' ? 'bad' : ''}`}
              title={`${d.weekday} ${shortDate(d.date)} · ${d.status === 'OK' ? 'fully covered' : `short ${fmtNum(d.shortage_total)}`}`}>
              <div className="day-bar"><i style={{ height: mounted ? `${Math.max(8, pct)}%` : '0%', transitionDelay: `${Math.min(i, 30) * 28}ms` } as CSSProperties} /></div>
              <span>{d.weekday.slice(0, 1)}</span><small>{new Date(d.date + 'T00:00:00').getDate()}</small>
            </div>
          })}
        </div> : <EmptyState icon="activity" title="Nothing to chart yet" hint="Daily cover appears once a roster exists." />}
      </section>

      <section className="dash-grid two">
        <div className="panel" style={stagger(5, 90)}>
          <div className="panel-heading"><div><h3>Leave waiting for a decision</h3><p>Preview the roster impact before approving.</p></div>
            <button className="btn btn-secondary btn-sm" onClick={() => onNavigate('leaves')}>Open leave <Icon name="arrowRight" size={14} /></button></div>
          {stats && stats.pending.length > 0 ? <ul className="feed">
            {stats.pending.slice(0, 5).map((l, i) => <li key={l.id} style={stagger(i, 50)}>
              <span className="feed-dot warn" />
              <div><strong>{l.employee_id}</strong> <Badge tone={leaveTone(l.leave_type)} dot={false}>{l.leave_type}{l.half_day ? ' half' : ''}</Badge>
                <small>{l.start_date}{l.end_date !== l.start_date ? ` → ${l.end_date}` : ''} · {l.days} day{l.days === 1 ? '' : 's'}</small></div>
              <span className="mono">{l.application_id}</span>
            </li>)}
          </ul> : <EmptyState icon="checkCircle" title="No leave waiting" hint="New applications will show up here." />}
        </div>

        <div className="panel" style={stagger(6, 90)}>
          <div className="panel-heading"><div><h3>Recent activity</h3><p>Latest changes to rosters and leave.</p></div></div>
          {data && data.audit.length > 0 ? <ul className="feed">
            {data.audit.slice(0, 6).map((a, i) => <li key={a.id} style={stagger(i, 50)}>
              <span className="feed-dot" />
              <div><strong style={{ textTransform: 'capitalize' }}>{a.action.replaceAll('_', ' ')}</strong><small>{a.actor}{a.version_id ? ` · version #${a.version_id}` : ''}</small></div>
              <span className="muted">{timeAgo(a.created_at)}</span>
            </li>)}
          </ul> : <EmptyState icon="inbox" title="No activity yet" hint="Generate or publish a roster to start the log." />}
        </div>
      </section>
    </>
  )
}
