import { useEffect, useState } from 'react'
import { getMyShifts, getMyTeam, getUnread } from '../api'
import { Icon } from '../components/Icons'
import PeopleSearch from '../components/PeopleSearch'
import { Badge, Banner, EmptyState, Skeleton, stagger } from '../components/ui'
import { codeClass, shortDate } from '../utils'
import type { AuthUser, MyShifts, Page, TeamCard } from '../types'

const ROLE: Record<string, string> = { general: 'General', senior_support: 'Senior agent', supervisor: 'Team leader', other: 'Other' }

/** Employee home: my next shifts (published roster), my team (leader, seniors, members), unread messages. */
export default function MyHomePage({ user, onNavigate }: { user: AuthUser; onNavigate: (p: Page) => void }) {
  const [shifts, setShifts] = useState<MyShifts | null>(null)
  const [team, setTeam] = useState<TeamCard | null>(null)
  const [unread, setUnread] = useState(0)
  const [error, setError] = useState('')
  useEffect(() => {
    getMyShifts(14).then(setShifts).catch(e => setError(e instanceof Error ? e.message : 'Could not load your shifts'))
    getMyTeam().then(setTeam).catch(() => setTeam(null))
    getUnread().then(r => setUnread(r.unread)).catch(() => undefined)
  }, [])
  const next = shifts?.next_duty
  return (
    <>
      <header className="topbar"><div><div className="eyebrow">Welcome back</div><h1>{user.employee_id ? `My home · ${user.employee_id}` : 'My home'}</h1></div></header>
      {error && <Banner tone="danger">{error}</Banner>}

      <section className="panel next-duty" style={stagger(0, 90)}>
        {!shifts ? <Skeleton w={260} h={44} /> : next ? <>
          <span className="stat-icon"><Icon name="calendarCheck" size={24} /></span>
          <div><span className="stat-label">Your next duty</span><strong>{next.weekday}, {shortDate(next.date)}</strong><small>{next.label}</small></div>
          <span className={codeClass(next.code ?? '-')} style={{ fontSize: 22, padding: '8px 16px' }}>{next.code}</span>
        </> : <div><span className="stat-label">Your next duty</span><strong>{shifts.published_version_id ? 'No duty in the next 14 days' : 'No published roster yet'}</strong><small>{shifts.published_version_id ? 'Check the roster page for later dates.' : 'Shifts appear here once your manager publishes the roster.'}</small></div>}
      </section>

      <section className="panel" style={stagger(1, 90)}>
        <div className="panel-heading"><div><h3>My upcoming shifts</h3><p>From the published roster, next 14 days. M = Morning, E = Evening, N = Night, -H = half duty, WO = weekly off.</p></div></div>
        <div className="shift-strip">
          {(shifts?.items ?? Array.from({ length: 14 }, () => null)).map((i, k) => i ? <div key={i.date} className={`shift-day ${k === 0 ? 'today' : ''}`}>
            <small>{i.weekday.slice(0, 3)}</small><b>{shortDate(i.date)}</b>
            {i.code ? <span className={codeClass(i.code)} title={i.label}>{i.code}</span> : <span className="muted" title={i.label}>—</span>}
            {k === 0 && <small className="today-tag">today</small>}
          </div> : <Skeleton key={k} w={64} h={92} r={12} />)}
        </div>
      </section>

      <PeopleSearch />

      <section className="panel" style={stagger(2, 90)}>
        <div className="panel-heading"><div><h3>{team?.team ?? 'My team'}</h3><p>{team?.team ? `${team.size} people. Your team leader is the first person to talk to about any shift or work problem.` : 'You have not been placed in a team yet.'}</p></div>
          {team?.team && <><button className="btn btn-neutral btn-sm" onClick={() => onNavigate('kpi')}><Icon name="trending" size={15} /> My KPI</button> <button className="btn btn-primary btn-sm" onClick={() => onNavigate('chat')}><Icon name="chat" size={15} /> Message my leader{unread > 0 ? ` (${unread} new)` : ''}</button></>}</div>
        {!team?.team ? <EmptyState icon="users" title="No team yet" hint="Your manager will assign you to a team and a team leader." /> : <div className="team-card">
          <div className="team-lead">
            <span className="stat-label">Team leader</span>
            {team.leader ? <div className="person-line"><strong>{team.leader.full_name}</strong><small>{team.leader.employee_id}</small></div> : <small>Not assigned</small>}
            <span className="stat-label" style={{ marginTop: 12 }}>Senior agents</span>
            {team.seniors.length ? team.seniors.map(s => <div key={s.employee_id} className="person-line"><strong>{s.full_name}</strong><small>{s.employee_id}</small></div>) : <small>None</small>}
          </div>
          <div className="team-members">
            <span className="stat-label">Team members ({team.members.length})</span>
            <div className="member-grid">{team.members.map(m => <div key={m.employee_id} className={`member ${m.is_me ? 'me' : ''}`}>
              <strong>{m.full_name}{m.is_me ? ' (you)' : ''}</strong><small>{m.employee_id}</small><Badge tone={m.role_pool === 'supervisor' ? 'info' : m.role_pool === 'senior_support' ? 'success' : 'neutral'}>{ROLE[m.role_pool] ?? m.role_pool}</Badge>
            </div>)}</div>
          </div>
        </div>}
      </section>
    </>
  )
}
