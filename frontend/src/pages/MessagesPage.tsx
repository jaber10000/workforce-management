import { useCallback, useEffect, useState } from 'react'
import { getThreads } from '../api'
import Conversation from '../components/Conversation'
import { Badge, EmptyState, stagger } from '../components/ui'
import { timeAgo } from '../utils'
import type { AuthUser, ChatThread } from '../types'

/** Employee: one conversation with the team leader. Team leader / manager: inbox of conversations + the open one. */
export default function MessagesPage({ user, onUnread }: { user: AuthUser; onUnread: () => void }) {
  const staff = user.role !== 'employee'
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [open, setOpen] = useState<string | null>(staff ? null : user.employee_id)
  const [q, setQ] = useState('')
  const load = useCallback(async () => { try { setThreads(await getThreads()) } catch { /* shown by the conversation */ } onUnread() }, [onUnread])
  useEffect(() => { void load() }, [load])
  const t0 = threads[0]
  const leader = !staff ? t0?.leader : null

  if (!staff) {
    return <>
      <header className="topbar"><div><div className="eyebrow">Team leader</div><h1>{leader ? `Messages with ${leader.full_name}` : 'Messages'}</h1></div></header>
      {!user.employee_id ? <section className="panel"><EmptyState icon="inbox" title="No employee profile" hint="This account is not linked to an employee profile." /></section>
        : !t0?.team ? <section className="panel"><EmptyState icon="users" title="You are not in a team yet" hint="Your manager will assign you to a team and team leader." /></section>
        : <section className="panel" style={stagger(0, 90)}>
          <div className="panel-heading"><div><h3>Private conversation</h3><p>Only you and your team leader ({t0.team}) can read this. Report an observation or problem, ask about a shift, or send a photo.</p></div></div>
          <Conversation employeeId={user.employee_id} onChanged={load} />
        </section>}
    </>
  }
  const shown = threads.filter(t => !q || t.full_name.toLowerCase().includes(q.toLowerCase()) || t.employee_id.toLowerCase().includes(q.toLowerCase()))
  return <>
    <header className="topbar"><div><div className="eyebrow">{user.role === 'supervisor' ? 'Your team' : 'Oversight'}</div><h1>Team inbox</h1></div></header>
    <div className="inbox">
      <section className="panel inbox-list" style={stagger(0, 90)}>
        <div className="filters"><input placeholder="Find a person…" value={q} onChange={e => setQ(e.target.value)} aria-label="Find a person" /></div>
        {shown.length === 0 ? <EmptyState icon="inbox" title="No conversations" hint={user.role === 'supervisor' ? 'Your team members appear here once they are in your team.' : 'Nobody has written yet.'} /> :
          <ul>{shown.map(t => <li key={t.employee_id}><button className={`thread ${open === t.employee_id ? 'on' : ''}`} onClick={() => setOpen(t.employee_id)}>
            <span><strong>{t.full_name}</strong><small>{t.employee_id}{t.team && user.role !== 'supervisor' ? ` · ${t.team}` : ''}</small>
              <small className="snippet">{t.last ? `${t.last.side === 'employee' ? '' : 'You: '}${t.last.text || '📷 image'}` : 'No messages yet'}</small></span>
            <span className="thread-meta">{t.unread > 0 && <Badge tone="danger">{t.unread}</Badge>}{t.last?.created_at && <small>{timeAgo(t.last.created_at)}</small>}</span>
          </button></li>)}</ul>}
      </section>
      <section className="panel inbox-chat" style={stagger(1, 90)}>
        {open ? <Conversation key={open} employeeId={open} onChanged={load} /> : <EmptyState icon="inbox" title="Select a conversation" />}
      </section>
    </div>
  </>
}
