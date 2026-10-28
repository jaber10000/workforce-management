import { useCallback, useEffect, useState } from 'react'
import { getAudit } from '../api'
import { Banner, EmptyState, stagger } from '../components/ui'
import { Icon } from '../components/Icons'
import { describeEvent } from '../utils'
import type { AuditEntry } from '../types'

const PAGE = 50

export default function AuditPage() {
  const [rows, setRows] = useState<AuditEntry[]>([])
  const [f, setF] = useState({ actor: '', action: '', entity_id: '' })
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try { setRows(await getAudit({ ...f, offset, limit: PAGE })); setError('') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load audit history') }
  }, [f, offset])
  useEffect(() => { const t = window.setTimeout(() => void load(), 250); return () => window.clearTimeout(t) }, [load])
  const set = (k: keyof typeof f, v: string) => { setOffset(0); setF({ ...f, [k]: v }) }

  return (
    <>
      <header className="topbar"><div><div className="eyebrow">Accountability</div><h1>Audit history</h1></div></header>
      {error && <Banner tone="danger">{error}</Banner>}
      <section className="panel" style={stagger(0, 90)}>
        <div className="panel-heading"><div><h3>Who did what, and when</h3><p>Roster creation, edits (old → new value and reason), approvals, rejections, publishing, leave, swaps and sign-ins.</p></div></div>
        <div className="filters">
          <input placeholder="Actor (username)" value={f.actor} onChange={e => set('actor', e.target.value)} aria-label="Actor" />
          <input placeholder="Action, e.g. roster_published" value={f.action} onChange={e => set('action', e.target.value)} aria-label="Action" />
          <input placeholder="Entity ID: LV0001, SW0001, EMP021…" value={f.entity_id} onChange={e => set('entity_id', e.target.value)} aria-label="Entity" />
        </div>
        <div className="table-scroll grid-scroll">
          {rows.length === 0 ? <EmptyState icon="inbox" title="No entries" hint="Try clearing the filters." /> : <table>
            <thead><tr><th>Time</th><th>Action</th><th>By</th><th>Entity</th><th>What changed</th></tr></thead>
            <tbody>{rows.map(a => <tr key={a.id}>
              <td>{new Date(a.created_at).toLocaleString()}</td><td><strong style={{ textTransform: 'capitalize' }}>{a.action.replaceAll('_', ' ')}</strong></td><td>{a.actor}</td>
              <td className="mono">{a.entity_type} {a.entity_id}{a.version_id ? ` · v#${a.version_id}` : ''}</td>
              <td><small>{describeEvent(a.action, a.details)}</small></td>
            </tr>)}</tbody></table>}
        </div>
        <div className="table-footer"><button className="btn btn-secondary btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}><Icon name="chevronLeft" size={14} /> Newer</button>
          <span>Showing {rows.length === 0 ? 0 : offset + 1}–{offset + rows.length}</span>
          <button className="btn btn-secondary btn-sm" disabled={rows.length < PAGE} onClick={() => setOffset(offset + PAGE)}>Older <Icon name="chevronRight" size={14} /></button></div>
      </section>
    </>
  )
}
