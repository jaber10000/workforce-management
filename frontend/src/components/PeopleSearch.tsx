import { useEffect, useState } from 'react'
import { searchPeople } from '../api'
import { Icon } from './Icons'
import { Badge, EmptyState, Spinner } from './ui'
import type { PersonHit } from '../types'

const ROLE: Record<string, string> = { general: 'Agent', senior_support: 'Senior agent', supervisor: 'Team leader', other: 'Other' }

/** Type a name or employee ID, see which team that person is in (and who leads it). Names / IDs / team only. */
export default function PeopleSearch() {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<PersonHit[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const term = q.trim()
    if (!term) { setHits(null); setError(''); return }
    setBusy(true)
    const t = window.setTimeout(() => {
      searchPeople(term).then(r => { setHits(r); setError('') }).catch(e => setError(e instanceof Error ? e.message : 'Search failed')).finally(() => setBusy(false))
    }, 250)
    return () => window.clearTimeout(t)
  }, [q])
  return (
    <section className="panel people-search">
      <div className="panel-heading"><div><h3>Find a colleague</h3><p>Search by name or employee ID to see which team they belong to.</p></div></div>
      <div className="filters">
        <div className="search-box"><Icon name="search" size={16} />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Name or employee ID, e.g. EMP002" aria-label="Search colleagues" />
          {busy && <Spinner />}</div>
      </div>
      {error && <p className="pad" style={{ color: 'var(--danger)' }}>{error}</p>}
      {hits && (hits.length === 0 ? <EmptyState icon="search" title="Nobody found" hint="Check the spelling or try the employee ID." /> :
        <ul className="plain-list search-results">{hits.map(h => <li key={h.employee_id}>
          <span><strong>{h.full_name}</strong><small>{h.employee_id} · {ROLE[h.role_pool] ?? h.role_pool}</small></span>
          <span className="search-team">{h.team ? <><strong>{h.team}</strong>{h.leader && h.role_pool !== 'supervisor' && <small>Leader: {h.leader}</small>}</> : <small>No team yet</small>}
            {h.same_team && <Badge tone="success">Your team</Badge>}</span>
        </li>)}</ul>)}
    </section>
  )
}
