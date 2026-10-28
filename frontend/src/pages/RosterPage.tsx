import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  downloadExport, editCell, generateRoster, getAuditLog, getDiff, getFairness, getHistory, getRosterDetail, getVersions,
  regenerateRoster,
} from '../api'
import { Icon } from '../components/Icons'
import { Badge, Banner, EmptyState, Skeleton, Spinner, Tabs, stagger, useConfirm } from '../components/ui'
import RosterGridTable from '../components/RosterGridTable'
import Confetti from '../components/Confetti'
import ReasonModal from '../components/ReasonModal'
import VersionActions, { statusTone } from '../components/VersionActions'
import { useToast } from '../components/Toast'
import { codeClass, describeEvent, downloadCsv, fmtNum as fmt, isManager, isoDay, isReviewer, shortDate } from '../utils'
import type { AuditEntry, AuthUser, Fairness, RosterDetail, RosterDiff, RosterHistory, RosterVersion } from '../types'

type Tab = 'grid' | 'coverage' | 'fairness' | 'changes' | 'history' | 'audit'
const CODES = ['M', 'E', 'N', 'M-H', 'E-H', 'N-H', 'R', 'WO', '-']
export default function RosterPage({ user, openId }: { user: AuthUser; openId?: number | null }) {
  const mgr = isManager(user.role)        // generate, approve, publish, export, audit log
  const rev = isReviewer(user.role)       // manager + supervisor: full roster review and draft editing
  const { confirm, dialog } = useConfirm()
  const toast = useToast()
  const [burst, setBurst] = useState(0)
  const today = isoDay(new Date())
  const [versions, setVersions] = useState<RosterVersion[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [detail, setDetail] = useState<RosterDetail | null>(null)
  const [fairness, setFairness] = useState<Fairness | null>(null)
  const [diff, setDiff] = useState<RosterDiff | null>(null)
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [tab, setTab] = useState<Tab>('grid')
  const [start, setStart] = useState('2026-10-26')
  const [days, setDays] = useState(14)
  const [fromDate, setFromDate] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [role, setRole] = useState('')
  const [team, setTeam] = useState('')
  const [teamInit, setTeamInit] = useState(false)
  const [query, setQuery] = useState('')
  const [reason, setReason] = useState('')
  const [week, setWeek] = useState(-1)
  const [history, setHistory] = useState<RosterHistory | null>(null)
  const [cell, setCell] = useState<{ id: string; name: string; date: string; code: string } | null>(null)
  const [newCode, setNewCode] = useState('M')
  const [reasonModal, setReasonModal] = useState(false)

  const loadVersions = useCallback(async (pick?: number) => {
    const list = await getVersions()
    setVersions(list)
    setSelected(prev => pick ?? prev ?? openId ?? list[0]?.id ?? null)
  }, [])

  useEffect(() => { loadVersions().catch(e => setError(e instanceof Error ? e.message : 'Could not load versions')) }, [loadVersions])

  useEffect(() => {
    if (selected == null) { setDetail(null); return }
    setError('')
    setWeek(-1)
    getRosterDetail(selected).then(setDetail).catch(e => setError(e instanceof Error ? e.message : 'Could not load roster'))
    if (rev) {
      getFairness(selected).then(setFairness).catch(() => setFairness(null))
      getDiff(selected).then(setDiff).catch(() => setDiff(null))
      getHistory(selected).then(setHistory).catch(() => setHistory(null))
    }
    if (mgr) getAuditLog(selected).then(setAudit).catch(() => setAudit([]))
  }, [selected, mgr, rev])
  const refreshDetail = useCallback(async () => {
    if (selected == null) return
    setDetail(await getRosterDetail(selected))
    if (rev) { getDiff(selected).then(setDiff).catch(() => undefined); getHistory(selected).then(setHistory).catch(() => undefined) }
    if (mgr) getAuditLog(selected).then(setAudit).catch(() => undefined)
  }, [selected, mgr, rev])

  async function run(label: string, fn: () => Promise<RosterVersion>) {
    setBusy(label); setError(''); setNotice('')
    try {
      const v = await fn()
      await loadVersions(v.id)
      setNotice(`${label} complete: version ${v.version_no} (${v.status}).`)
      
    } catch (e) {
      setError(e instanceof Error ? e.message : `${label} failed`)
    } finally { setBusy('') }
  }

  async function saveCell(text: string) {
    if (!cell || !detail) return
    try {
      await editCell(detail.version.id, cell.id, cell.date, newCode, text)
      toast(`${cell.id} on ${shortDate(cell.date)}: ${cell.code} → ${newCode}`)
      setCell(null); setReasonModal(false); await refreshDetail()
    } catch (e) { setReasonModal(false); setError(e instanceof Error ? e.message : 'Edit failed') }
  }

  const rows = useMemo(() => (detail?.grid.rows ?? []).filter(r =>
    (!role || r.role === role) && (!team || (r.team ?? '') === team) &&
    (!query || r.employee_id.toLowerCase().includes(query.toLowerCase()) || r.employee_name.toLowerCase().includes(query.toLowerCase()))
  ), [detail, role, query, team])

  const v = detail?.version
  const locked = v?.status === 'approved' || v?.status === 'published'
  const weeks = detail ? Math.ceil(detail.grid.days.length / 7) : 0
  const view = useMemo(() => {
    if (!detail || week < 0) return detail?.grid
    const a = week * 7, b = a + 7
    return { ...detail.grid, days: detail.grid.days.slice(a, b), rows: detail.grid.rows.map(r => ({ ...r, codes: r.codes.slice(a, b) })) }
  }, [detail, week])
  const teamNames = useMemo(() => [...new Set((detail?.grid.rows ?? []).map(r => r.team).filter((t): t is string => !!t))].sort(), [detail])
  const myTeam = useMemo(() => detail?.grid.rows.find(r => r.employee_id === user.employee_id)?.team ?? null, [detail, user.employee_id])
  useEffect(() => { if (!teamInit && detail) { setTeamInit(true); if (user.role === 'supervisor' && myTeam) setTeam(myTeam) } }, [detail, teamInit, myTeam, user.role])
  const viewRows = useMemo(() => rows.map(r => { if (week < 0) return r; const a = week * 7; return { ...r, codes: r.codes.slice(a, a + 7) } }), [rows, week])
  const cov = detail?.coverage
  const shortDays = cov?.days.filter(d => d.status === 'SHORTAGE') ?? []
  const maxScore = Math.max(1, ...(fairness?.employees.map(e => e.undesirable_score) ?? [1]))

  const tabs: { key: Tab; label: string }[] = [
    { key: 'grid', label: 'Roster grid' },
    { key: 'coverage', label: 'Coverage validation' },
    { key: 'fairness', label: 'Fairness' },
    { key: 'changes', label: `Changes (${diff?.changes.length ?? 0})` },
    { key: 'history', label: 'Version history' },
    { key: 'audit', label: 'Audit log' },
  ].filter(t => (t.key === 'audit' ? mgr : rev || t.key === 'grid' || t.key === 'coverage')) as { key: Tab; label: string }[]

  return (
    <>
      <header className="topbar">
        <div><div className="eyebrow">Automatic roster engine</div><h1>Roster calendar</h1></div>
        {v && mgr && <button className="btn btn-secondary" onClick={() => void downloadExport(v.id).catch(e => setError(e instanceof Error ? e.message : 'Export failed'))}><Icon name="download" size={16} /> Export Excel</button>}
      </header>

      {mgr && <section className="panel engine-controls">
        {busy && <span className="progress" />}
        <div className="control-row">
          <label className="field">Start date<input type="date" value={start} onChange={e => setStart(e.target.value)} /></label>
          <label className="field">Days<input type="number" min={1} max={62} value={days} onChange={e => setDays(Number(e.target.value))} /></label>
          <button className="btn btn-primary" disabled={!!busy} onClick={() => void run('Generate', () => generateRoster(start, days, 30))}>
            {busy === 'Generate' ? <><Spinner /> Optimising…</> : <><Icon name="zap" size={16} /> Generate draft roster</>}
          </button>
        </div>
        {v && <div className="control-row">
          <label className="field">Re-optimise from<input type="date" value={fromDate} min={v.start_date} max={v.end_date} onChange={e => setFromDate(e.target.value)} /></label>
          <button className="btn btn-secondary" disabled={!!busy || (locked && reason.trim().length < 3)} onClick={() => void run('Re-optimise', () => regenerateRoster(v.id, fromDate || null, 30, reason.trim() || undefined))}>
            {busy === 'Re-optimise' ? <><Spinner /> Optimising…</> : <><Icon name="refresh" size={16} /> Re-optimise as new version</>}
          </button>
          <label className="field">Change reason{locked ? ' *' : ''}<input value={reason} onChange={e => setReason(e.target.value)} placeholder={locked ? 'Required for approved / published rosters' : 'Optional'} /></label>
        </div>}
        {busy && <p className="hint">Solver is running (up to ~30s for 200+ employees)…</p>}
      </section>}

      {notice && <Banner tone="success" onClose={() => setNotice('')}>{notice}</Banner>}
      {error && <Banner tone="danger">{error}</Banner>}

      {versions.length === 0 && !busy && <section className="panel">
        <EmptyState icon="calendar" title="No roster yet" hint={mgr ? 'Import employees, then press “Generate draft roster”.' : 'No roster has been published yet.'} />
      </section>}

      {versions.length > 0 && <section className="panel">
        <div className="panel-heading"><div><h3>Versions</h3><p>Every regeneration is a new, immutable version. Published history never changes.</p></div><span className="count-pill">{versions.length} versions</span></div>
        <div className="version-list">
          {versions.map((x, i) => <button key={x.id} className={`version-chip ${selected === x.id ? 'on' : ''}`} style={stagger(i, 45, 10)} onClick={() => setSelected(x.id)}>
            <strong>v{x.version_no}</strong><span>{shortDate(x.start_date)} – {shortDate(x.end_date)}</span>
            <Badge tone={statusTone(x.status)}>{x.status}</Badge>
            <small>{x.trigger.replaceAll('_', ' ')}{x.summary.shortage?.total ? ` · short ${fmt(x.summary.shortage.total)}` : ''}</small>
          </button>)}
        </div>
      </section>}

      {selected != null && !detail && !error && <section className="stats">
        {[0, 1, 2].map(i => <div key={i} className="stat-card"><Skeleton w={46} h={46} r={14} /><div><Skeleton w={80} h={11} /><br /><Skeleton w={140} h={24} /><br /><Skeleton w={110} h={11} /></div></div>)}
      </section>}

      {v && cov && <div key={v.id}>
        <section className="stats">
          <div className="stat-card" style={stagger(0, 90)}><span className="stat-icon"><Icon name="calendar" size={22} /></span><div><span className="stat-label">Window</span><strong>{shortDate(v.start_date)} – {shortDate(v.end_date)}</strong><small>v{v.version_no} · {v.status}{v.lock_before ? ` · locked before ${shortDate(v.lock_before)}` : ''}</small></div></div>
          <div className={`stat-card ${cov.has_shortage ? 'bad' : ''}`} style={stagger(1, 90)}><span className={`stat-icon ${cov.has_shortage ? 'red' : 'teal'}`}><Icon name={cov.has_shortage ? 'alert' : 'checkCircle'} size={22} /></span><div><span className="stat-label">Coverage</span><strong>{cov.has_shortage ? `${cov.days_with_shortage} day(s) short` : 'Fully covered'}</strong><small>M {fmt(cov.totals.morning)} · E {fmt(cov.totals.evening)} · N {fmt(cov.totals.night)} · Senior {fmt(cov.totals.senior)}</small></div></div>
          <div className="stat-card" style={stagger(2, 90)}><span className="stat-icon violet"><Icon name="scale" size={22} /></span><div><span className="stat-label">Night fairness</span><strong>spread {fairness?.summary.night_spread ?? '—'}</strong><small>min {fairness?.summary.night_min} · max {fairness?.summary.night_max} · avg {fairness?.summary.night_avg}</small></div></div>
        </section>

        <section className="panel review-bar" style={stagger(2, 90)}>
          <div><span className="stat-label">Review status</span>
            <div><Badge tone={statusTone(v.status)}>{v.status}</Badge> <small>created by {v.created_by ?? '—'}{v.created_at ? ` · ${new Date(v.created_at).toLocaleString()}` : ''}</small></div>
            {v.approved_by && <small>{v.status === 'rejected' ? 'Rejected' : 'Approved'} by {v.approved_by}{v.approved_at ? ` · ${new Date(v.approved_at).toLocaleString()}` : ''}</small>}
            {v.review_note && <small>{v.status === 'rejected' ? 'Rejection reason' : 'Note'}: {v.review_note}</small>}
            {v.reason && <small>Change reason: {v.reason}</small>}
          </div>
          <VersionActions v={v} canManage={mgr} onError={setError}
            onDone={async (r, m) => { setNotice(m); if (r.status === 'published') { setBurst(b => b + 1); toast(m) } await loadVersions(r.id); await refreshDetail() }} />
        </section>

        {rev && (detail?.warnings ?? []).map(w => <Banner key={w.type} tone={w.severity === 'danger' ? 'danger' : 'info'}>{w.message}{w.employee_ids?.length ? ` (${w.employee_ids.slice(0, 8).join(', ')}${w.employee_ids.length > 8 ? '…' : ''})` : ''}</Banner>)}
        {cov.has_shortage && <Banner tone="danger">
          <strong>Manpower shortage detected</strong>
          <ul>{shortDays.slice(0, 6).map(d => <li key={d.date}>{d.weekday} {shortDate(d.date)} —{' '}
            {(['morning', 'evening', 'night'] as const).filter(s => d.shifts[s].shortage > 0).map(s => `${s} short ${fmt(d.shifts[s].shortage)}`).join(', ')}
            {d.senior_shortage_total > 0 ? ` · senior short ${fmt(d.senior_shortage_total)}` : ''}</li>)}
            {shortDays.length > 6 && <li>…and {shortDays.length - 6} more day(s)</li>}</ul>
        </Banner>}
        {(v.summary.warnings ?? []).map(w => <Banner key={w} tone="info">{w}</Banner>)}

        <section className="panel" style={stagger(3, 90)}>
          <Tabs tabs={tabs} value={tab} onChange={setTab} />

          <div className="tab-body" key={tab}>
            {tab === 'grid' && <>
              <div className="filters" style={{ paddingTop: 18 }}>
                <div className="search-wrap"><Icon name="search" size={17} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search employee…" aria-label="Search employee" /></div>
                {teamNames.length > 0 && <select value={team} onChange={e => setTeam(e.target.value)} aria-label="Team"><option value="">All teams</option>{teamNames.map(t => <option key={t}>{t}</option>)}</select>}
                <select value={role} onChange={e => setRole(e.target.value)} aria-label="Role"><option value="">All roles</option><option value="general">General</option><option value="senior_support">Senior</option><option value="supervisor">Supervisor</option></select>
                <button className="btn btn-secondary btn-sm" onClick={() => {
                  downloadCsv(`roster-v${v.version_no}.csv`, ['Employee ID', 'Name', 'Role', ...detail.grid.days.map(d => d.date)],
                    rows.map(r => [r.employee_id, r.employee_name, r.role, ...r.codes]))
                  toast(`Exported ${rows.length} rows from version ${v.version_no}.`)
                }} disabled={rows.length === 0}><Icon name="download" size={14} /> CSV</button>
                <div className="legend">{['M', 'E', 'N', 'R', 'WO', 'SL', 'CL', 'AL'].map(c => <span key={c} className={codeClass(c)}>{c}</span>)}<small>-H = half duty</small></div>
              </div>
              {weeks > 1 && <div className="week-pager">
                <button className="btn btn-secondary btn-sm" disabled={week === 0} onClick={() => setWeek(week < 0 ? 0 : week - 1)}><Icon name="chevronLeft" size={14} /></button>
                <button className={`btn btn-sm ${week < 0 ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setWeek(-1)}>Full window</button>
                {Array.from({ length: weeks }, (_, i) => <button key={i} className={`btn btn-sm ${week === i ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setWeek(i)}>Week {i + 1}</button>)}
                <button className="btn btn-secondary btn-sm" disabled={week >= weeks - 1} onClick={() => setWeek(week + 1)}><Icon name="chevronRight" size={14} /></button>
              </div>}
              {rev && v.status === 'draft' && <p className="pad hint">Click any cell to change a shift. A reason is required and the old and new value are saved in the audit log.</p>}
              {rev && locked && <p className="pad hint">This version is {v.status} and read-only. To change it, re-optimise with a reason: that creates a new draft version which must be approved and published again.</p>}
              <div className="table-scroll grid-scroll">
                <RosterGridTable grid={view ?? detail.grid} rows={viewRows} today={today} mineId={user.employee_id}
                  onCellClick={rev && v.status === 'draft' ? (r, date, code) => { if (user.role === 'supervisor' && myTeam && r.team !== myTeam) { toast(`${r.employee_name} is in ${r.team ?? 'no team'}. You can only change ${myTeam}.`, 'info'); return } setCell({ id: r.employee_id, name: r.employee_name, date, code }); setNewCode(code) } : undefined} />
                {rows.length === 0 && <EmptyState icon="search" title="No matching employees" hint="Try a different search or role filter." />}
              </div>
            </>}

            {tab === 'coverage' && <div className="table-scroll grid-scroll"><table>
              <thead><tr><th>Date</th><th>Morning</th><th>Evening</th><th>Night</th><th>Senior (M/E/N)</th><th>Status</th></tr></thead>
              <tbody>{cov.days.map(d => <tr key={d.date} className={d.status === 'SHORTAGE' ? 'row-bad' : ''}>
                <td><strong>{d.weekday.slice(0, 3)} {shortDate(d.date)}</strong></td>
                {(['morning', 'evening', 'night'] as const).map(s => <td key={s} className="num"><div className="cov-cell"><span>{fmt(d.shifts[s].assigned)} / {d.shifts[s].required}{d.shifts[s].shortage > 0 && <span className="short-tag">−{fmt(d.shifts[s].shortage)}</span>}</span><span className="cov-bar"><i className={d.shifts[s].shortage > 0 ? 'bad' : ''} style={{ width: `${d.shifts[s].required ? Math.min(100, (d.shifts[s].assigned / d.shifts[s].required) * 100) : 100}%` }} /></span></div></td>)}
                <td className="num">{(['morning', 'evening', 'night'] as const).map(s => <span key={s} className={d.shifts[s].senior_shortage > 0 ? 'short-text' : ''}>{fmt(d.shifts[s].senior_assigned)}/{d.shifts[s].senior_required} </span>)}</td>
                <td><Badge tone={d.status === 'OK' ? 'success' : 'danger'}>{d.status === 'OK' ? 'OK' : 'Shortage'}</Badge></td>
              </tr>)}</tbody></table></div>}

            {tab === 'fairness' && fairness && <>
              <p className="pad hint">Night spread {fairness.summary.night_spread} · evening spread {fairness.summary.evening_spread} · total-shift spread {fairness.summary.total_spread}. Sorted by undesirable score (3×Night + Evening).</p>
              <div className="table-scroll grid-scroll"><table>
                <thead><tr><th>Employee</th><th>M</th><th>E</th><th>N</th><th>Total</th><th>Half</th><th>Leave</th><th>Max N streak</th><th>Score</th></tr></thead>
                <tbody>{[...fairness.employees].sort((a, b) => b.undesirable_score - a.undesirable_score).slice(0, 100).map(r => <tr key={r.employee_id}>
                  <td><strong>{r.employee_name}</strong><small>{r.employee_id}</small></td><td className="num">{r.morning}</td><td className="num">{r.evening}</td>
                  <td className="num">{r.night_eligible ? <strong>{r.night}</strong> : <span className="muted">—</span>}</td><td className="num">{r.total}</td><td className="num">{r.half_duty}</td><td className="num">{r.leave_days}</td><td className="num">{r.max_consecutive_nights}</td>
                  <td className="num"><strong>{r.undesirable_score}</strong><span className="minibar"><i style={{ width: `${(r.undesirable_score / maxScore) * 100}%` }} /></span></td>
                </tr>)}</tbody></table></div>
            </>}

            {tab === 'changes' && <div className="table-scroll grid-scroll">
              {!diff || diff.changes.length === 0 ? <EmptyState icon="check" title="No changes" hint="This version matches its base version." /> : <table>
                <thead><tr><th>Date</th><th>Employee</th><th>From</th><th>To</th></tr></thead>
                <tbody>{diff.changes.slice(0, 400).map((c, i) => <tr key={i}><td>{shortDate(c.date)}</td><td className="mono">{c.employee_id}</td><td><span className={codeClass(c.from ?? '-')}>{c.from ?? '—'}</span></td><td><span className={codeClass(c.to ?? '-')}>{c.to ?? '—'}</span></td></tr>)}</tbody></table>}
            </div>}

            {tab === 'history' && <div className="pad">
              {!history ? <EmptyState icon="inbox" title="No history" /> : <>
                <p className="hint">All versions of this roster window. Old versions are never changed; open one to view exactly what it looked like.</p>
                <div className="table-scroll"><table>
                  <thead><tr><th>Version</th><th>Status</th><th>Created</th><th>Approved / rejected</th><th>Published</th><th>Changes</th><th></th></tr></thead>
                  <tbody>{history.versions.map(h => <tr key={h.id}>
                    <td><strong>v{h.version_no}</strong><small>{h.trigger.replaceAll('_', ' ')}{h.reason ? ` · ${h.reason}` : ''}</small></td>
                    <td><Badge tone={statusTone(h.status)}>{h.status}</Badge></td>
                    <td>{h.created_by ?? '—'}<small>{h.created_at ? new Date(h.created_at).toLocaleString() : ''}</small></td>
                    <td>{h.approved_by ?? '—'}<small>{h.approved_at ? new Date(h.approved_at).toLocaleString() : ''}{h.review_note ? ` · ${h.review_note}` : ''}</small></td>
                    <td>{h.published_by ?? '—'}<small>{h.published_at ? new Date(h.published_at).toLocaleString() : ''}</small></td>
                    <td className="num">{h.changes}{h.shortage ? <small>short {h.shortage}</small> : null}</td>
                    <td><button className="btn btn-neutral btn-sm" disabled={h.id === selected} onClick={() => { setSelected(h.id); setTab('grid') }}>{h.id === selected ? 'Viewing' : 'View'}</button></td>
                  </tr>)}</tbody></table></div>
                <h4 style={{ margin: '18px 0 8px' }}>Events</h4>
                <div className="table-scroll"><table><thead><tr><th>Time</th><th>Action</th><th>By</th><th>Details</th></tr></thead>
                  <tbody>{history.events.map(e => <tr key={e.id}><td>{e.time ? new Date(e.time).toLocaleString() : ''}</td><td><strong style={{ textTransform: 'capitalize' }}>{e.action.replaceAll('_', ' ')}</strong></td><td>{e.actor}</td><td><small>{describeEvent(e.action, e.details)}</small></td></tr>)}</tbody></table></div>
              </>}
            </div>}

            {tab === 'audit' && <div className="table-scroll grid-scroll">
              {audit.length === 0 ? <EmptyState icon="inbox" title="No audit entries yet" /> : <table>
                <thead><tr><th>Time</th><th>Action</th><th>By</th><th>Details</th></tr></thead>
                <tbody>{audit.map(a => <tr key={a.id}><td>{new Date(a.created_at).toLocaleString()}</td><td><strong style={{ textTransform: 'capitalize' }}>{a.action.replaceAll('_', ' ')}</strong></td><td>{a.actor}</td>
                  <td><small>{describeEvent(a.action, a.details)}</small></td></tr>)}</tbody></table>}
            </div>}
          </div>
        </section>
      </div>}
      <Confetti burst={burst} />
      {cell && !reasonModal && <div className="modal-backdrop-lite" role="dialog" aria-modal="true" onClick={() => setCell(null)}>
        <div className="panel cell-edit" onClick={e => e.stopPropagation()}>
          <h3>Change shift</h3>
          <p className="hint">{cell.name} ({cell.id}) · {shortDate(cell.date)} · now <strong>{cell.code}</strong></p>
          <label className="field">New value<select value={newCode} onChange={e => setNewCode(e.target.value)}>{CODES.map(c => <option key={c}>{c}</option>)}</select></label>
          <div className="modal-actions"><button className="btn btn-secondary" onClick={() => setCell(null)}>Cancel</button>
            <button className="btn btn-primary" disabled={newCode === cell.code} onClick={() => setReasonModal(true)}>Next: add reason</button></div>
        </div></div>}
      <ReasonModal open={reasonModal} title="Reason for this change" required confirmLabel="Save change" label="Change reason"
        intro={cell ? `${cell.id} on ${cell.date}: ${cell.code} → ${newCode}` : undefined} onClose={() => setReasonModal(false)} onSubmit={saveCell} />
      {dialog}
    </>
  )
}
