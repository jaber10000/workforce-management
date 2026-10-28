import { FormEvent, useCallback, useEffect, useState } from 'react'
import { getSwaps, requestSwap, swapAction } from '../api'
import { Icon } from '../components/Icons'
import ReasonModal from '../components/ReasonModal'
import { useToast } from '../components/Toast'
import { Badge, Banner, EmptyState, Spinner, stagger } from '../components/ui'
import { isManager } from '../utils'
import type { AuthUser, Swap } from '../types'

const LABEL: Record<Swap['status'], string> = {
  pending_counterpart: 'Waiting for colleague', pending_manager: 'Waiting for manager', approved: 'Approved',
  rejected: 'Rejected', declined: 'Declined', cancelled: 'Cancelled',
}
const tone = (s: Swap['status']) => (s === 'approved' ? 'success' : s.startsWith('pending') ? 'warn' : 'neutral') as 'success' | 'warn' | 'neutral'

export default function SwapsPage({ user }: { user: AuthUser }) {
  const toast = useToast()
  const mgr = isManager(user.role)  // manager/admin; supervisors get read-only review here
  const canAsk = mgr || !!user.employee_id  // a supervisor account without an employee link can review but not request
  const [items, setItems] = useState<Swap[]>([])
  const [form, setForm] = useState({ requester_id: '', counterpart_id: '', work_date: '', reason: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [rejecting, setRejecting] = useState<Swap | null>(null)

  const load = useCallback(async () => {
    try { setItems(await getSwaps()) } catch (e) { setError(e instanceof Error ? e.message : 'Could not load swaps') }
  }, [])
  useEffect(() => { void load() }, [load])

  async function submit(e: FormEvent) {
    e.preventDefault(); setError(''); setBusy('new')
    try {
      const s = await requestSwap({ requester_id: mgr ? form.requester_id.trim() : undefined, counterpart_id: form.counterpart_id.trim(), work_date: form.work_date, reason: form.reason || undefined })
      toast(`${s.swap_id} created — ${LABEL[s.status].toLowerCase()}.`)
      setForm({ requester_id: '', counterpart_id: '', work_date: '', reason: '' }); await load()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not request swap') } finally { setBusy('') }
  }

  async function act(s: Swap, action: Parameters<typeof swapAction>[1], note?: string) {
    setError(''); setBusy(s.swap_id)
    try {
      const r = await swapAction(s.swap_id, action, note) as { warning?: string | null }
      toast(`${s.swap_id}: ${action}${action.endsWith('e') ? 'd' : 'ed'}.${r.warning ? ` ${r.warning}` : ''}`, action === 'approve' || action === 'accept' ? 'success' : 'info')
      setRejecting(null); await load()
    } catch (err) { setRejecting(null); setError(err instanceof Error ? err.message : `Could not ${action}`) } finally { setBusy('') }
  }

  const mine = user.employee_id
  return (
    <>
      <header className="topbar"><div><div className="eyebrow">Shift swap</div><h1>Shift swaps</h1></div></header>
      {error && <Banner tone="danger" onClose={() => setError('')}>{error}</Banner>}
      {canAsk && <section className="panel" style={stagger(0, 90)}>
        <div className="panel-heading"><div><h3>Ask for a swap</h3><p>Two people exchange their shift on one future date. The colleague must agree, then a manager approves. Eligibility, Night→Morning rest, night streaks and Senior cover are checked before and again at approval.</p></div></div>
        <form className="leave-form" onSubmit={submit}>
          {mgr && <label className="field">Employee 1 *<input required value={form.requester_id} onChange={e => setForm({ ...form, requester_id: e.target.value })} placeholder="e.g. EMP021" /></label>}
          <label className="field">{mgr ? 'Employee 2 *' : 'Swap with (employee ID) *'}<input required value={form.counterpart_id} onChange={e => setForm({ ...form, counterpart_id: e.target.value })} placeholder="e.g. EMP044" /></label>
          <label className="field">Date *<input required type="date" value={form.work_date} onChange={e => setForm({ ...form, work_date: e.target.value })} /></label>
          <label className="field wide">Reason<input value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} placeholder="Optional" /></label>
          <button className="btn btn-primary" disabled={busy === 'new'}>{busy === 'new' ? <><Spinner /> Checking…</> : <><Icon name="swap" size={16} /> Request swap</>}</button>
        </form>
      </section>}
      <section className="panel" style={stagger(1, 90)}>
        <div className="panel-heading"><div><h3>Swap requests</h3></div><span className="count-pill">{items.length}</span></div>
        <div className="table-scroll"><table>
          <thead><tr><th>ID</th><th>Date</th><th>People</th><th>Status</th><th>Reason</th><th></th></tr></thead>
          <tbody>{items.length === 0 ? <tr><td colSpan={6}><EmptyState icon="inbox" title="No swap requests" /></td></tr> : items.map(s => <tr key={s.swap_id}>
            <td className="mono">{s.swap_id}</td><td>{s.work_date}</td><td><strong>{s.requester_id}</strong> ⇄ <strong>{s.counterpart_id}</strong></td>
            <td><Badge tone={tone(s.status)}>{LABEL[s.status]}</Badge>{s.decided_by && <small>by {s.decided_by}</small>}{s.decision_note && <small>{s.decision_note}</small>}</td>
            <td>{s.reason ?? '—'}</td>
            <td><div className="actions">
              {s.status === 'pending_counterpart' && (mgr || mine === s.counterpart_id) && <>
                <button className="btn btn-approve btn-sm" disabled={busy === s.swap_id} onClick={() => void act(s, 'accept')}>Accept</button>
                <button className="btn btn-reject btn-sm" disabled={busy === s.swap_id} onClick={() => void act(s, 'decline')}>Decline</button></>}
              {s.status === 'pending_manager' && mgr && <button className="btn btn-primary btn-sm" disabled={busy === s.swap_id} onClick={() => void act(s, 'approve')}><Icon name="check" size={14} /> Approve</button>}
              {mgr && s.status.startsWith('pending') && <button className="btn btn-reject btn-sm" disabled={busy === s.swap_id} onClick={() => setRejecting(s)}>Reject</button>}
              {s.status.startsWith('pending') && (mgr || mine === s.requester_id) && <button className="btn btn-ghost btn-sm" disabled={busy === s.swap_id} onClick={() => void act(s, 'cancel')}>Cancel</button>}
            </div></td>
          </tr>)}</tbody>
        </table></div>
      </section>
      <ReasonModal open={!!rejecting} title={`Reject ${rejecting?.swap_id ?? ''}`} label="Reason" confirmLabel="Reject" tone="danger"
        onClose={() => setRejecting(null)} onSubmit={t => rejecting ? act(rejecting, 'reject', t) : undefined} />
    </>
  )
}
