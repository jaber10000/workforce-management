import { FormEvent, useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { applyLeave, decideLeave, getLeaveBalance, getLeaveImpact, getLeaves, previewLeave } from '../api'
import LeaveImpactPanel from '../components/LeaveImpactPanel'
import { Icon } from '../components/Icons'
import { Badge, Banner, EmptyState, Spinner, stagger } from '../components/ui'
import { useToast } from '../components/Toast'
import { isManager, isoDay } from '../utils'
import type { AuthUser, Leave, LeaveActionResult, LeaveBalance, LeaveImpact, LeaveStatus, LeaveType } from '../types'

const statuses: (LeaveStatus | '')[] = ['', 'Pending', 'Approved', 'Rejected', 'Cancelled']
const empty0 = { employee_id: '', leave_type: 'Casual' as LeaveType, start_date: '', end_date: '', half_day: false, reason: '' }
const statusTone = (s: LeaveStatus) => s === 'Approved' ? 'success' : s === 'Pending' ? 'warn' : s === 'Rejected' ? 'danger' : 'neutral'

export default function LeavesPage({ user }: { user: AuthUser }) {
  const toast = useToast()
  const mgr = isManager(user.role)  // manager/admin; supervisors get read-only review here
  const [all, setAll] = useState<Leave[]>([])
  const [status, setStatus] = useState<LeaveStatus | ''>('Pending')
  const [find, setFind] = useState('')
  const [weekOffset, setWeekOffset] = useState(0)
  const [form, setForm] = useState({ ...empty0, employee_id: user.employee_id ?? '' })
  const [balances, setBalances] = useState<LeaveBalance[]>([])
  const [balanceFor, setBalanceFor] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [workingId, setWorkingId] = useState('')
  const [impact, setImpact] = useState<{ data: LeaveImpact; simulated: boolean } | null>(null)

  const refresh = useCallback(async () => {
    try { setAll((await getLeaves({})).items) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load leave applications') }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  async function loadBalance(emp: string) {
    setBalanceFor(emp)
    if (!emp) { setBalances([]); return }
    try { setBalances(await getLeaveBalance(emp)) } catch { setBalances([]) }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setSaving(true); setError(''); setNotice('')
    try {
      const lv = await applyLeave({ ...form, end_date: form.half_day ? form.start_date : form.end_date, reason: form.reason || undefined })
      setNotice(`${lv.application_id} submitted (${lv.days} day).`)
      await loadBalance(form.employee_id)
      setForm({ ...empty0, employee_id: user.employee_id ?? '', leave_type: form.leave_type })
      await refresh()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not submit leave') }
    finally { setSaving(false) }
  }

  async function act(l: Leave, action: 'approve' | 'reject' | 'cancel') {
    setWorkingId(l.application_id); setError(''); setNotice('')
    try {
      const res = await decideLeave(l.application_id, action)
      const r = res as LeaveActionResult
      setNotice(`${l.application_id} ${action}d.${r.roster_adjustment ? ` Roster: ${r.roster_adjustment}.` : ''}`)
      toast(`${l.application_id} ${action}d.`, action === 'approve' ? 'success' : 'info')
      setImpact(r.impact ? { data: r.impact, simulated: false } : null)
      await loadBalance(l.employee_id)
      await refresh()
    } catch (err) { setError(err instanceof Error ? err.message : `Could not ${action}`) }
    finally { setWorkingId('') }
  }

  async function preview(l: Leave) {
    setWorkingId(l.application_id); setError(''); setNotice('')
    try {
      const res = await previewLeave(l.application_id)
      if (res.impact) setImpact({ data: res.impact, simulated: true })
      else setNotice(`${l.application_id}: ${res.roster_adjustment}.`)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not preview') }
    finally { setWorkingId('') }
  }

  async function showImpact(l: Leave) {
    setError('')
    try {
      const res = await getLeaveImpact(l.application_id)
      if (res.impact) setImpact({ data: res.impact, simulated: false })
      else setNotice(`${l.application_id}: no roster impact recorded.`)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not load impact') }
  }

  const items = useMemo(() => all.filter(l =>
    (!status || l.status === status) && (!find || l.employee_id.toLowerCase().includes(find.toLowerCase()) || l.application_id.toLowerCase().includes(find.toLowerCase()))
  ), [all, status, find])
  const counts = useMemo(() => {
    const c: Record<string, number> = { '': all.length }
    for (const l of all) c[l.status] = (c[l.status] ?? 0) + 1
    return c
  }, [all])

  // 21-day timeline of approved + pending leave, starting from this week (or shifted by the arrows)
  const TL_DAYS = 21
  const timeline = useMemo(() => {
    const base = new Date(); base.setHours(0, 0, 0, 0); base.setDate(base.getDate() + weekOffset * 7)
    const day = 86400000
    const days = Array.from({ length: TL_DAYS }, (_, i) => new Date(base.getTime() + i * day))
    const idx = (iso: string) => Math.round((new Date(iso + 'T00:00:00').getTime() - base.getTime()) / day)
    const rows = new Map<string, { from: number; to: number; l: Leave }[]>()
    for (const l of all) {
      if (l.status !== 'Approved' && l.status !== 'Pending') continue
      const from = idx(l.start_date), to = idx(l.end_date)
      if (to < 0 || from > TL_DAYS - 1) continue
      const list = rows.get(l.employee_id) ?? []
      list.push({ from: Math.max(0, from), to: Math.min(TL_DAYS - 1, to), l })
      rows.set(l.employee_id, list)
    }
    return { days, rows: [...rows.entries()].slice(0, 10), total: rows.size, todayIso: isoDay(new Date()) }
  }, [all, weekOffset])

  return (
    <>
      <header className="topbar"><div><div className="eyebrow">Leave management</div><h1>Leave requests</h1></div></header>
      {notice && <Banner tone="success" onClose={() => setNotice('')}>{notice}</Banner>}
      {error && <Banner tone="danger">{error}</Banner>}

      {impact && <LeaveImpactPanel impact={impact.data} simulated={impact.simulated} onClose={() => setImpact(null)} />}

      <section className="two-col">
        <div className="panel" style={stagger(0, 90)}>
          <div className="panel-heading"><div><h3>Apply for leave</h3><p>Approved leave syncs to the roster automatically.</p></div></div>
          <form className="leave-form" onSubmit={submit}>
            <label className="field">Employee ID *<input required readOnly={!mgr} value={form.employee_id} onChange={e => setForm({ ...form, employee_id: e.target.value })} onBlur={e => void loadBalance(e.target.value.trim())} placeholder="e.g. EMP021" /></label>
            <label className="field">Type<select value={form.leave_type} onChange={e => setForm({ ...form, leave_type: e.target.value as LeaveType, half_day: e.target.value === 'Annual' ? false : form.half_day })}><option>Sick</option><option>Casual</option><option>Annual</option></select></label>
            <label className="field">From *<input required type="date" value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} /></label>
            <label className="field">To *<input required={!form.half_day} disabled={form.half_day} type="date" value={form.half_day ? form.start_date : form.end_date} onChange={e => setForm({ ...form, end_date: e.target.value })} /></label>
            <label className="field inline wide"><input type="checkbox" disabled={form.leave_type === 'Annual'} checked={form.half_day} onChange={e => setForm({ ...form, half_day: e.target.checked })} /> Half day (Sick/Casual, single day)</label>
            <label className="field wide">Reason<input value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} placeholder="Optional" /></label>
            <button className="btn btn-primary" disabled={saving}>{saving ? <><Spinner /> Submitting…</> : <><Icon name="send" size={16} /> Submit application</>}</button>
          </form>
        </div>

        <div className="panel" style={stagger(1, 90)}>
          <div className="panel-heading"><div><h3>Leave balance {new Date().getFullYear()}</h3><p>{balanceFor || 'Enter an employee ID to view'}</p></div></div>
          <div className="balance-grid" key={balanceFor}>
            {balances.length === 0 && <div style={{ gridColumn: '1 / -1' }}><EmptyState icon="users" title="No employee selected" hint="Type an ID in the form to see their balance." /></div>}
            {balances.map((b, i) => <div key={b.leave_type} className="balance-card" style={stagger(i, 80)}>
              <span>{b.leave_type}</span><strong>{b.remaining}<small> / {b.total}</small></strong>
              <div className="balance-bar"><i style={{ width: `${b.total ? Math.max(0, Math.min(100, (b.remaining / b.total) * 100)) : 0}%` }} /></div>
              <small>used {b.used} · pending {b.pending}{b.carried_forward ? ` · carried ${b.carried_forward}` : ''}</small>
            </div>)}
          </div>
        </div>
      </section>

      <section className="panel" style={stagger(2, 90)}>
        <div className="panel-heading"><div><h3>Who is away</h3><p>Next three weeks. Striped bars are still waiting for a decision.</p></div>
          <div className="heading-tools">
            <button className="btn btn-secondary btn-sm btn-icon" aria-label="Earlier" onClick={() => setWeekOffset(o => o - 1)}><Icon name="chevronLeft" size={15} /></button>
            <button className="btn btn-secondary btn-sm" onClick={() => setWeekOffset(0)} disabled={weekOffset === 0}>This week</button>
            <button className="btn btn-secondary btn-sm btn-icon" aria-label="Later" onClick={() => setWeekOffset(o => o + 1)}><Icon name="chevronRight" size={15} /></button>
          </div></div>
        {timeline.rows.length === 0 ? <EmptyState icon="calendarCheck" title="Nobody is away in this window" hint="Approved and pending leave appears here." /> : <div className="timeline" style={{ ['--cols' as string]: TL_DAYS } as CSSProperties}>
          <div className="tl-head"><span />{timeline.days.map(d => <span key={d.getTime()} className={`tl-day ${isoDay(d) === timeline.todayIso ? 'today' : ''}`}>
            <small>{d.toLocaleDateString('en-GB', { weekday: 'narrow' })}</small>{d.getDate()}</span>)}</div>
          {timeline.rows.map(([emp, bars], r) => <div key={emp} className="tl-row" style={stagger(r, 45)}>
            <strong>{emp}</strong>
            <div className="tl-track">{bars.map(b => <span key={b.l.id} className={`tl-bar ${b.l.leave_type.toLowerCase()} ${b.l.status === 'Pending' ? 'pending' : ''}`}
              style={{ gridColumn: `${b.from + 1} / ${b.to + 2}` }} title={`${b.l.leave_type} · ${b.l.start_date}${b.l.end_date !== b.l.start_date ? ` → ${b.l.end_date}` : ''} · ${b.l.status}`}>{b.to - b.from > 0 ? b.l.leave_type : b.l.leave_type[0]}</span>)}</div>
          </div>)}
          {timeline.total > timeline.rows.length && <small className="tl-more">and {timeline.total - timeline.rows.length} more people</small>}
        </div>}
      </section>

      <section className="panel" style={stagger(3, 90)}>
        <div className="panel-heading"><div><h3>Applications</h3><p>Approve, reject or cancel.</p></div><span className="count-pill">{items.length} records</span></div>
        <div className="filters"><div className="search-wrap"><Icon name="search" size={17} /><input value={find} onChange={e => setFind(e.target.value)} placeholder="Find by employee or application ID…" aria-label="Find leave" /></div></div>
        <div className="chips-row" role="group" aria-label="Filter by status">
          {statuses.map(st => <button key={st || 'all'} className={`chip-filter ${status === st ? 'on' : ''}`} onClick={() => setStatus(st)}>{st || 'All'}<b>{counts[st] ?? 0}</b></button>)}
        </div>
        <div className="table-scroll"><table>
          <thead><tr><th>ID</th><th>Employee</th><th>Type</th><th>Dates</th><th>Days</th><th>Status</th><th></th></tr></thead>
          {items.length === 0 ? <tbody><tr><td colSpan={7}><EmptyState icon="calendarCheck" title="No applications" hint="Nothing matches this status filter." /></td></tr></tbody> : <tbody className="stagger" key={status}>{items.map((l, i) => <tr key={l.id} style={stagger(i, 30, 12)}>
            <td className="mono">{l.application_id}</td><td><strong>{l.employee_id}</strong></td><td>{l.leave_type}{l.half_day ? ' (half)' : ''}</td>
            <td className="num">{l.start_date}{l.end_date !== l.start_date ? ` → ${l.end_date}` : ''}</td><td className="num">{l.days}</td>
            <td><Badge tone={statusTone(l.status)}>{l.status}</Badge></td>
            <td><div className="actions">
              {mgr && l.status === 'Pending' && <>
                <button className="btn btn-neutral btn-sm" disabled={workingId === l.application_id} onClick={() => void preview(l)} title="See roster impact without saving"><Icon name="eye" size={14} /> Preview</button>
                <button className="btn btn-approve btn-sm" disabled={workingId === l.application_id} onClick={() => void act(l, 'approve')}><Icon name="check" size={14} /> Approve</button>
                <button className="btn btn-reject btn-sm" disabled={workingId === l.application_id} onClick={() => void act(l, 'reject')}><Icon name="x" size={14} /> Reject</button>
              </>}
              {mgr && l.status === 'Approved' && <button className="btn btn-neutral btn-sm" onClick={() => void showImpact(l)}><Icon name="activity" size={14} /> Impact</button>}
              {(l.status === 'Pending' || l.status === 'Approved') && <button className="btn btn-ghost btn-sm" disabled={workingId === l.application_id} onClick={() => void act(l, 'cancel')}>Cancel</button>}
            </div></td>
          </tr>)}</tbody>}
        </table></div>
      </section>
    </>
  )
}
