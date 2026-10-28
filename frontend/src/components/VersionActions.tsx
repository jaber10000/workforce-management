import { useState } from 'react'
import { approveRoster, publishRoster, rejectRoster } from '../api'
import { Icon } from './Icons'
import { Badge, useConfirm } from './ui'
import ReasonModal from './ReasonModal'
import type { RosterVersion } from '../types'

export const statusTone = (s: RosterVersion['status']) =>
  s === 'published' ? 'success' : s === 'approved' ? 'info' : s === 'rejected' ? 'danger' : s === 'draft' ? 'warn' : 'neutral'

/** Draft → Approve → Publish, or Reject with a saved reason. Buttons only for managers. */
export default function VersionActions({ v, canManage, onDone, onError }: {
  v: RosterVersion; canManage: boolean; onDone: (v: RosterVersion, msg: string) => void; onError: (m: string) => void
}) {
  const { confirm, dialog } = useConfirm()
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState<'approve' | 'reject' | null>(null)
  const short = v.summary.shortage?.total ?? 0

  async function go(label: string, fn: () => Promise<RosterVersion>) {
    setBusy(true); onError('')
    try { const r = await fn(); setModal(null); onDone(r, `${label}: version ${r.version_no} is now ${r.status}.`) }
    catch (e) { setModal(null); onError(e instanceof Error ? e.message : `${label} failed`) }
    finally { setBusy(false) }
  }
  const ackShortage = async (verb: string) => short === 0 || confirm({
    title: `${verb} with shortage?`, message: `This roster still has a shortage of ${short} person-shift(s). It will be recorded that you acknowledged it.`,
    confirmLabel: `${verb} anyway`, tone: 'danger',
  })

  if (v.status === 'published') return <Badge tone="success">Published{v.published_by ? ` by ${v.published_by}` : ''}</Badge>
  if (v.status === 'rejected') return <Badge tone="danger">Rejected</Badge>
  if (v.status === 'superseded') return <Badge tone="neutral">Superseded</Badge>
  if (!canManage) return <Badge tone={statusTone(v.status)}>{v.status}</Badge>

  return (
    <span className="actions">
      {v.status === 'draft' && <button className="btn btn-approve btn-sm" disabled={busy} onClick={async () => { if (await ackShortage('Approve')) setModal('approve') }}><Icon name="check" size={14} /> Approve</button>}
      {v.status === 'approved' && <button className="btn btn-primary btn-sm" disabled={busy} onClick={async () => { if (await ackShortage('Publish')) void go('Publish', () => publishRoster(v.id, short > 0)) }}><Icon name="send" size={14} /> Publish</button>}
      <button className="btn btn-reject btn-sm" disabled={busy} onClick={() => setModal('reject')}><Icon name="x" size={14} /> Reject</button>
      <ReasonModal open={modal === 'approve'} title="Approve this roster" label="Review note" confirmLabel="Approve" onClose={() => setModal(null)}
        intro="Approving locks the draft. It is not visible to employees until it is published."
        onSubmit={t => go('Approve', () => approveRoster(v.id, short > 0, t))} />
      <ReasonModal open={modal === 'reject'} title="Reject this roster" label="Rejection reason" required confirmLabel="Reject" tone="danger" onClose={() => setModal(null)}
        intro="The reason, your name and the time are saved with this version."
        onSubmit={t => go('Reject', () => rejectRoster(v.id, t))} />
      {dialog}
    </span>
  )
}
