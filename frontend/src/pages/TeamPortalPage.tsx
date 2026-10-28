import { useEffect, useMemo, useState } from 'react'
import { getLeaves, getMyTeam, getSwaps, getTeamRoster, getUnread } from '../api'
import { Icon } from '../components/Icons'
import PeopleSearch from '../components/PeopleSearch'
import { Badge, Banner, EmptyState, stagger } from '../components/ui'
import { codeClass, shortDate } from '../utils'
import type { AuthUser, Leave, Page, Swap, TeamCard, TeamRoster } from '../types'

/** Team leader portal: everything about my own team in one place (members, shifts, leave, swaps, messages). */
export default function TeamPortalPage({ user, onNavigate }: { user: AuthUser; onNavigate: (p: Page) => void }) {
  const [team, setTeam] = useState<TeamCard | null>(null)
  const [roster, setRoster] = useState<TeamRoster | null>(null)
  const [leaves, setLeaves] = useState<Leave[]>([])
  const [swaps, setSwaps] = useState<Swap[]>([])
  const [unread, setUnread] = useState(0)
  const [error, setError] = useState('')
  useEffect(() => {
    getMyTeam().then(setTeam).catch(e => setError(e instanceof Error ? e.message : 'Could not load your team'))
    getTeamRoster(14).then(setRoster).catch(() => setRoster(null))
    getLeaves({ limit: 200 }).then(r => setLeaves(r.items)).catch(() => undefined)
    getSwaps().then(setSwaps).catch(() => undefined)
    getUnread().then(r => setUnread(r.unread)).catch(() => undefined)
  }, [])
  const ids = useMemo(() => new Set((team?.members ?? []).map(m => m.employee_id)), [team])
  const pendingLeave = leaves.filter(l => ids.has(l.employee_id) && l.status === 'Pending')
  const openSwaps = swaps.filter(s => (ids.has(s.requester_id) || ids.has(s.counterpart_id)) && s.status.startsWith('pending'))
  const name = (id: string) => team?.members.find(m => m.employee_id === id)?.full_name ?? id
  const today = roster?.rows.filter(r => ['M', 'E', 'N', 'M-H', 'E-H', 'N-H'].includes(r.codes[0] ?? '')).length ?? 0

  if (!user.employee_id || (team && !team.team)) return <>
    <header className="topbar"><div><div className="eyebrow">Team leader</div><h1>My team</h1></div></header>
    {error && <Banner tone="danger">{error}</Banner>}
    <section className="panel"><EmptyState icon="users" title="No team yet" hint="Link this account to your employee profile and ask a manager to run the team split." /></section>
  </>

  return (
    <>
      <header className="topbar"><div><div className="eyebrow">Team leader portal</div><h1>{team?.team ?? 'My team'}</h1></div>
        <div className="topbar-actions">
          <button className="btn btn-secondary" onClick={() => onNavigate('roster')}><Icon name="calendar" size={16} /> Team roster &amp; draft edits</button>
          <button className="btn btn-secondary" onClick={() => onNavigate('kpi')}><Icon name="trending" size={16} /> Team KPI</button>
          <button className="btn btn-primary" onClick={() => onNavigate('chat')}><Icon name="chat" size={16} /> Team inbox{unread > 0 ? ` (${unread})` : ''}</button></div></header>
      {error && <Banner tone="danger">{error}</Banner>}

      <section className="stats">
        <div className="stat-card" style={stagger(0, 90)}><span className="stat-icon"><Icon name="users" size={22} /></span><div><span className="stat-label">Team size</span><strong>{team?.size ?? '—'}</strong><small>{team?.seniors.length ?? 0} senior agent(s)</small></div></div>
        <div className="stat-card" style={stagger(1, 90)}><span className="stat-icon teal"><Icon name="clock" size={22} /></span><div><span className="stat-label">On duty today</span><strong>{roster ? today : '—'}</strong><small>published roster</small></div></div>
        <div className="stat-card" style={stagger(2, 90)}><span className="stat-icon violet"><Icon name="inbox" size={22} /></span><div><span className="stat-label">Needs attention</span><strong>{pendingLeave.length + openSwaps.length + unread}</strong><small>{pendingLeave.length} leave · {openSwaps.length} swaps · {unread} messages</small></div></div>
      </section>

      <PeopleSearch />

      <section className="panel" style={stagger(3, 90)}>
        <div className="panel-heading"><div><h3>Team shifts · next 14 days</h3><p>{roster?.published_version_id ? 'Published roster. Draft changes are made in Roster calendar (filtered to your team).' : 'No published roster covers these days yet.'}</p></div></div>
        <div className="table-scroll grid-scroll">
          {!roster || roster.rows.length === 0 ? <EmptyState icon="calendar" title="Nothing to show" /> : <table className="roster-table">
            <thead><tr><th className="sticky">Member</th>{roster.days.map(d => <th key={d.date}>{d.weekday.slice(0, 3)}<small>{shortDate(d.date)}</small></th>)}</tr></thead>
            <tbody>{roster.rows.map(r => <tr key={r.employee_id}>
              <td className="sticky"><strong>{r.full_name}</strong><small>{r.employee_id} · {r.role_pool === 'supervisor' ? 'leader' : r.role_pool === 'senior_support' ? 'senior' : 'member'}{r.weekly_off_day ? ` · off ${r.weekly_off_day.slice(0, 3)}` : ''}</small></td>
              {r.codes.map((c, i) => <td key={i}>{c ? <span className={codeClass(c)}>{c}</span> : <span className="muted">·</span>}</td>)}
            </tr>)}</tbody></table>}
        </div>
      </section>

      <div className="two-col">
        <section className="panel" style={stagger(4, 90)}>
          <div className="panel-heading"><div><h3>Leave requests · my team</h3><p>Pending, for your review. Managers decide.</p></div><button className="btn btn-neutral btn-sm" onClick={() => onNavigate('leaves')}>Open</button></div>
          {pendingLeave.length === 0 ? <EmptyState icon="checkCircle" title="Nothing pending" /> : <ul className="plain-list">{pendingLeave.slice(0, 8).map(l => <li key={l.application_id}><strong>{name(l.employee_id)}</strong><small>{l.leave_type} · {shortDate(l.start_date)} – {shortDate(l.end_date)}</small><Badge tone="warn">Pending</Badge></li>)}</ul>}
        </section>
        <section className="panel" style={stagger(5, 90)}>
          <div className="panel-heading"><div><h3>Shift swaps · my team</h3><p>Open requests involving your people.</p></div><button className="btn btn-neutral btn-sm" onClick={() => onNavigate('swaps')}>Open</button></div>
          {openSwaps.length === 0 ? <EmptyState icon="checkCircle" title="No open swaps" /> : <ul className="plain-list">{openSwaps.slice(0, 8).map(s => <li key={s.swap_id}><strong>{name(s.requester_id)} ⇄ {name(s.counterpart_id)}</strong><small>{shortDate(s.work_date)}</small><Badge tone="warn">{s.status === 'pending_counterpart' ? 'Waiting colleague' : 'Waiting manager'}</Badge></li>)}</ul>}
        </section>
      </div>

      <section className="panel" style={stagger(6, 90)}>
        <div className="panel-heading"><div><h3>Members</h3></div></div>
        <div className="member-grid pad">{team?.members.map(m => <div key={m.employee_id} className={`member ${m.is_me ? 'me' : ''}`}>
          <strong>{m.full_name}{m.is_me ? ' (you)' : ''}</strong><small>{m.employee_id}</small><Badge tone={m.role_pool === 'supervisor' ? 'info' : m.role_pool === 'senior_support' ? 'success' : 'neutral'}>{m.role_pool === 'supervisor' ? 'Leader' : m.role_pool === 'senior_support' ? 'Senior' : 'Member'}</Badge></div>)}</div>
      </section>
    </>
  )
}
