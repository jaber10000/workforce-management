import { useCallback, useEffect, useState } from 'react'
import { getVersions } from '../api'
import { Badge, Banner, EmptyState, stagger } from '../components/ui'
import { Icon } from '../components/Icons'
import { useToast } from '../components/Toast'
import VersionActions, { statusTone } from '../components/VersionActions'
import { isManager, shortDate, timeAgo } from '../utils'
import type { AuthUser, RosterVersion } from '../types'

export default function ApprovalsPage({ user, onReview }: { user: AuthUser; onReview: (id: number) => void }) {
  const toast = useToast()
  const [items, setItems] = useState<RosterVersion[]>([])
  const [recent, setRecent] = useState<RosterVersion[]>([])
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const all = await getVersions()
      setItems(all.filter(v => v.status === 'draft' || v.status === 'approved'))
      setRecent(all.filter(v => v.status === 'rejected' || v.status === 'published').slice(0, 8))
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not load versions') }
  }, [])
  useEffect(() => { void load() }, [load])
  const mgr = isManager(user.role)  // manager/admin; supervisors get read-only review here

  return (
    <>
      <header className="topbar"><div><div className="eyebrow">Manager review</div><h1>Roster approvals</h1></div></header>
      {error && <Banner tone="danger">{error}</Banner>}
      <section className="panel" style={stagger(0, 90)}>
        <div className="panel-heading"><div><h3>Waiting for a decision</h3><p>Review the draft in the roster calendar, approve it, then publish. Only published rosters are visible to employees.</p></div><span className="count-pill">{items.length} open</span></div>
        <div className="table-scroll"><table>
          <thead><tr><th>Version</th><th>Window</th><th>Origin</th><th>Coverage</th><th>Review status</th><th></th></tr></thead>
          <tbody>{items.length === 0 ? <tr><td colSpan={6}><EmptyState icon="checkCircle" title="Nothing to review" hint="New drafts appear here: generated, re-optimised, or created by a leave approval." /></td></tr> : items.map(v => <tr key={v.id}>
            <td><strong>v{v.version_no}</strong><small>#{v.id}</small></td>
            <td>{shortDate(v.start_date)} – {shortDate(v.end_date)}</td>
            <td>{v.trigger.replaceAll('_', ' ')}<small>by {v.created_by ?? '—'}{v.created_at ? ` · ${timeAgo(v.created_at)}` : ''}{v.reason ? ` · ${v.reason}` : ''}</small></td>
            <td>{(v.summary.shortage?.total ?? 0) > 0 ? <Badge tone="danger">short {v.summary.shortage?.total}</Badge> : <Badge tone="success">Covered</Badge>}</td>
            <td><Badge tone={statusTone(v.status)}>{v.status === 'draft' ? 'Awaiting review' : 'Approved'}</Badge>{v.approved_by && <small>{v.approved_by}{v.approved_at ? ` · ${new Date(v.approved_at).toLocaleString()}` : ''}</small>}</td>
            <td><div className="actions"><button className="btn btn-neutral btn-sm" onClick={() => onReview(v.id)}><Icon name="eye" size={14} /> Review</button>
              <VersionActions v={v} canManage={mgr} onError={setError} onDone={(_, m) => { toast(m); void load() }} /></div></td>
          </tr>)}</tbody>
        </table></div>
      </section>
      <section className="panel" style={stagger(1, 90)}>
        <div className="panel-heading"><div><h3>Recent decisions</h3><p>Rejection reasons, approvers and dates are kept with each version.</p></div></div>
        <div className="table-scroll"><table>
          <thead><tr><th>Version</th><th>Window</th><th>Status</th><th>Approved by</th><th>Note / reason</th></tr></thead>
          <tbody>{recent.length === 0 ? <tr><td colSpan={5} className="empty">No decisions yet.</td></tr> : recent.map(v => <tr key={v.id}>
            <td><strong>v{v.version_no}</strong></td><td>{shortDate(v.start_date)} – {shortDate(v.end_date)}</td>
            <td><Badge tone={statusTone(v.status)}>{v.status}</Badge></td>
            <td>{v.approved_by ?? '—'}{v.approved_at && <small>{new Date(v.approved_at).toLocaleString()}</small>}</td>
            <td>{v.review_note ?? '—'}</td>
          </tr>)}</tbody>
        </table></div>
      </section>
    </>
  )
}
