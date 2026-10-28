import { useCallback, useEffect, useMemo, useState } from 'react'
import { getKpiOverview, getKpiScope, getMyKpi, getTeamPerformance, saveKpiBulk } from '../api'
import { Icon } from '../components/Icons'
import { Badge, Banner, EmptyState, Skeleton, Spinner, Tabs, stagger } from '../components/ui'
import { useToast } from '../components/Toast'
import { downloadCsv, parseKpiCsv, type KpiCsvRow } from '../utils'
import type { AuthUser, Kpi, KpiOverview, KpiScope, MyKpi, TeamPerformance, TeamStats } from '../types'

type Tab = 'me' | 'upload' | 'team' | 'teams'
type Metric = 'quality' | 'attendance' | 'productivity' | 'csat'
const METRICS: { key: Metric; label: string }[] = [{ key: 'quality', label: 'Quality' }, { key: 'attendance', label: 'Attendance' }, { key: 'productivity', label: 'Productivity' }, { key: 'csat', label: 'CSAT' }]
const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}` }
const monthLabel = (p: string) => new Date(`${p}-01T00:00:00`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })
const tone = (v: number | null) => v === null ? 'neutral' : v >= 85 ? 'success' : v >= 70 ? 'info' : 'warn'
const fmt = (v: number | null | undefined) => v === null || v === undefined ? '—' : String(Math.round(v * 10) / 10)

function Delta({ v }: { v: number | null }) {
  if (v === null || v === undefined) return <span className="muted">—</span>
  return <span className={`delta ${v > 0 ? 'up' : v < 0 ? 'down' : ''}`}>{v > 0 ? '▲' : v < 0 ? '▼' : '•'} {Math.abs(v)}</span>
}
function Bars({ items }: { items: { label: string; value: number | null }[] }) {
  return <div className="kpi-bars" role="img" aria-label="Monthly trend (bars start at 50%)">{items.map(i => <div key={i.label} className="kpi-bar">
    <span className="kpi-bar-val">{fmt(i.value)}</span>
    <span className="kpi-bar-col"><i style={{ height: `${Math.max(3, ((i.value ?? 0) - 50) * 2)}%` }} className={i.value === null ? 'empty' : ''} /></span>
    <small>{i.label}</small></div>)}</div>
}
function MetricRows({ values }: { values: Record<Metric, number | null> }) {
  return <div className="metric-rows">{METRICS.map(m => <div key={m.key} className="metric-row"><span>{m.label}</span>
    <span className="meter"><i style={{ width: `${values[m.key] ?? 0}%` }} /></span><b>{fmt(values[m.key])}</b></div>)}</div>
}
const MonthPicker = ({ value, onChange }: { value: string; onChange: (v: string) => void }) =>
  <label className="field inline"><span>Month</span><input type="month" value={value} max={thisMonth()} onChange={e => e.target.value && onChange(e.target.value)} /></label>

/** Monthly KPI. Everyone sees their own; leaders also upload for their team and see team performance. */
export default function KpiPage({ user }: { user: AuthUser }) {
  const isLead = user.role === 'supervisor'
  const isMgr = user.role === 'admin' || user.role === 'manager'
  const hasProfile = !!user.employee_id
  const tabs = useMemo(() => {
    const t: { key: Tab; label: string }[] = []
    if (hasProfile && !isLead) t.push({ key: 'me', label: 'My KPI' })
    if (isLead || isMgr) t.push({ key: 'upload', label: 'Upload KPI' })
    if (isLead || isMgr) t.push({ key: 'team', label: 'Team performance' }, { key: 'teams', label: 'All teams' })
    return t
  }, [hasProfile, isLead, isMgr])
  const [tab, setTab] = useState<Tab | null>(null)
  const active = tab && tabs.some(t => t.key === tab) ? tab : tabs[0]?.key
  return <>
    <header className="topbar"><div><div className="eyebrow">{isLead ? 'Team leader' : isMgr ? 'Oversight' : 'Performance'}</div><h1>KPI</h1></div></header>
    {tabs.length === 0 ? <section className="panel"><EmptyState icon="trending" title="No KPI for this account" hint="Link the account to an employee profile to see a personal KPI." /></section> : <>
      <section className="panel"><Tabs tabs={tabs} value={active as Tab} onChange={setTab} /></section>
      {active === 'me' && <MyKpiView />}
      {active === 'upload' && <UploadView />}
      {active === 'team' && <TeamView user={user} />}
      {active === 'teams' && <CompareView />}
    </>}
  </>
}

function MyKpiView() {
  const [d, setD] = useState<MyKpi | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { getMyKpi(12).then(setD).catch(e => setError(e instanceof Error ? e.message : 'Could not load your KPI')) }, [])
  if (error) return <Banner tone="danger">{error}</Banner>
  if (!d) return <section className="panel pad"><Skeleton w={300} h={60} /></section>
  const best = d.items.length ? d.items.reduce((a, b) => b.score > a.score ? b : a) : null
  const avg = d.items.length ? d.items.reduce((s, i) => s + i.score, 0) / d.items.length : null
  if (!d.latest) return <section className="panel"><EmptyState icon="trending" title="No KPI uploaded yet" hint="Your team leader uploads your KPI at the end of each month. It only appears here, for you." /></section>
  const L = d.latest
  return <>
    <section className="stats">
      <div className="stat-card" style={stagger(0, 90)}><span className="stat-icon"><Icon name="trending" size={22} /></span><div><span className="stat-label">Latest · {monthLabel(L.period)}</span><strong>{fmt(L.score)}%</strong><small>overall score</small></div></div>
      <div className="stat-card" style={stagger(1, 90)}><span className="stat-icon teal"><Icon name="activity" size={22} /></span><div><span className="stat-label">Change vs last month</span><strong><Delta v={d.change} /></strong><small>points</small></div></div>
      <div className="stat-card" style={stagger(2, 90)}><span className="stat-icon violet"><Icon name="checkCircle" size={22} /></span><div><span className="stat-label">Best month</span><strong>{best ? fmt(best.score) : '—'}%</strong><small>{best ? monthLabel(best.period) : ''} · avg {fmt(avg)}%</small></div></div>
    </section>
    <div className="two-col">
      <section className="panel" style={stagger(3, 90)}><div className="panel-heading"><div><h3>Last {d.items.length} months</h3><p>Overall score per month.</p></div></div>
        <div className="pad"><Bars items={d.items.map(i => ({ label: monthLabel(i.period).slice(0, 3), value: i.score }))} /></div></section>
      <section className="panel" style={stagger(4, 90)}><div className="panel-heading"><div><h3>{monthLabel(L.period)} breakdown</h3><p>Uploaded by {L.uploaded_by}.</p></div></div>
        <div className="pad"><MetricRows values={L as unknown as Record<Metric, number | null>} />{L.remarks && <p className="kpi-remark">“{L.remarks}”</p>}</div></section>
    </div>
    <section className="panel" style={stagger(5, 90)}><div className="panel-heading"><div><h3>History</h3></div></div>
      <div className="table-scroll"><table><thead><tr><th>Month</th><th>Overall</th>{METRICS.map(m => <th key={m.key}>{m.label}</th>)}<th>Remarks</th></tr></thead>
        <tbody>{[...d.items].reverse().map((i: Kpi) => <tr key={i.period}><td><strong>{monthLabel(i.period)}</strong></td><td><Badge tone={tone(i.score)}>{fmt(i.score)}%</Badge></td>
          {METRICS.map(m => <td key={m.key}>{fmt(i[m.key])}</td>)}<td className="wrap-cell">{i.remarks ?? '—'}</td></tr>)}</tbody></table></div>
    </section>
  </>
}

type Draft = Partial<Record<Metric | 'score' | 'remarks', string>>
const FIELDS = ['score', 'quality', 'attendance', 'productivity', 'csat'] as const

function UploadView() {
  const toast = useToast()
  const [period, setPeriod] = useState(thisMonth())
  const [scope, setScope] = useState<KpiScope | null>(null)
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string[]>([])
  const [pending, setPending] = useState<{ rows: KpiCsvRow[]; overallIgnored: number } | null>(null)
  const load = useCallback(() => { setScope(null); setDrafts({}); setError(''); getKpiScope(period).then(setScope).catch(e => setError(e instanceof Error ? e.message : 'Could not load')) }, [period])
  useEffect(load, [load])
  const val = (id: string, f: keyof Draft, saved: Kpi | null) => drafts[id]?.[f] ?? (saved && saved[f as keyof Kpi] != null ? String(saved[f as keyof Kpi]) : '')
  const set = (id: string, f: keyof Draft, v: string) => setDrafts(d => ({ ...d, [id]: { ...d[id], [f]: v } }))
  const dirty = Object.keys(drafts)
  const bad = (v?: string) => v !== undefined && v !== '' && (Number.isNaN(Number(v)) || Number(v) < 0 || Number(v) > 100)

  async function save() {
    if (!scope) return
    const rows = dirty.map(id => {
      const saved = scope.people.find(p => p.employee_id === id)?.kpi ?? null
      const r: { employee_id: string; remarks: string | null } & Partial<Record<typeof FIELDS[number], number | null>> = { employee_id: id, remarks: (drafts[id].remarks ?? saved?.remarks ?? '') || null }
      for (const f of FIELDS) { const v = val(id, f, saved); r[f] = v === '' ? null : Number(v) }
      if (drafts[id].score === undefined && METRICS.some(m => drafts[id][m.key] !== undefined)) r.score = null  // metrics changed: recalculate the overall instead of keeping the old one
      return r
    })
    if (rows.some(r => FIELDS.every(f => r[f] == null))) { setError('Every changed row needs the overall score or at least one metric.'); return }
    if (dirty.some(id => FIELDS.some(f => bad(drafts[id][f])))) { setError('Scores must be numbers between 0 and 100.'); return }
    setBusy(true); setError('')
    try {
      const r = await saveKpiBulk(period, rows)
      toast(`${r.created + r.updated} KPI saved for ${monthLabel(period)}${r.rejected ? `, ${r.rejected} rejected` : ''}.`, r.rejected ? 'info' : 'success')
      setResult(r.errors.map(e => `${e.employee_id}: ${e.error}`))
      load()
    } catch (e) { setError(e instanceof Error ? e.message : 'Save failed') } finally { setBusy(false) }
  }
  function template() {
    downloadCsv(`kpi_${period}.csv`, ['employee_id', 'name', 'score', ...METRICS.map(m => m.key), 'remarks'],
      (scope?.people ?? []).map(p => [p.employee_id, p.full_name, p.kpi?.score ?? '', ...METRICS.map(m => p.kpi?.[m.key] ?? ''), p.kpi?.remarks ?? '']))
  }
  function applyCsv(parsed: { rows: KpiCsvRow[]; overallIgnored: number }) {
    const next: Record<string, Draft> = {}
    let skipped = 0
    for (const row of parsed.rows) {
      const p = scope?.people.find(x => x.employee_id.toLowerCase() === row.employee_id.toLowerCase())
      if (!p) { skipped++; continue }
      const d: Draft = {}
      for (const f of FIELDS) if (row[f] !== undefined && row[f] !== '') d[f] = row[f]
      if (row.remarks) d.remarks = row.remarks
      if (Object.keys(d).length) next[p.employee_id] = d
    }
    setDrafts(next)
    const notes = [skipped ? `${skipped} CSV row(s) skipped: not in the people you can upload for.` : '',
      parsed.overallIgnored ? `Overall was calculated as the average of the 4 metrics for ${parsed.overallIgnored} row(s); the Overall column of the file is ignored when all 4 metrics are present.` : ''].filter(Boolean)
    setError(notes.join(' '))
    toast(`${Object.keys(next).length} row(s) loaded for ${monthLabel(period)}. Review and press Save.`, 'info')
  }
  useEffect(() => { if (scope && pending && scope.period === period) { applyCsv(pending); setPending(null) } }, [scope, pending, period]) // eslint-disable-line react-hooks/exhaustive-deps
  async function importCsv(file: File) {
    const parsed = parseKpiCsv(await file.text())
    if (!parsed) { setError('No "employee_id" column found. Keep the header row of the template (employee_id, …); title or note rows above it are fine.'); return }
    if (parsed.rows.length === 0) { setError('The CSV has a header but no people rows.'); return }
    if (parsed.period && parsed.period !== period) {
      if (parsed.period > thisMonth()) { setError(`The file is for ${parsed.period}, which is in the future.`); return }
      setPending(parsed); setPeriod(parsed.period)   // the file says which month it is for: switch, then fill in
      return
    }
    applyCsv(parsed)
  }

  return <section className="panel" style={stagger(0, 90)}>
    <div className="panel-heading"><div><h3>Upload monthly KPI</h3><p>Type values (0–100) or load a CSV, then Save. Leave the overall score empty to use the average of the metrics. You can only upload for the people shown here.</p></div>
      <div className="topbar-actions"><button className="btn btn-neutral btn-sm" onClick={template} disabled={!scope}><Icon name="download" size={15} /> CSV template</button>
        <label className="btn btn-neutral btn-sm" style={{ cursor: 'pointer' }}><Icon name="upload" size={15} /> Load CSV<input type="file" accept=".csv,text/csv" hidden onChange={e => { const f = e.target.files?.[0]; if (f) void importCsv(f); e.target.value = '' }} /></label>
        <button className="btn btn-primary btn-sm" onClick={save} disabled={busy || dirty.length === 0}>{busy ? <Spinner /> : <Icon name="check" size={15} />} Save{dirty.length ? ` (${dirty.length})` : ''}</button></div></div>
    <div className="filters"><MonthPicker value={period} onChange={setPeriod} /></div>
    {error && <div className="pad"><Banner tone="danger" onClose={() => setError('')}>{error}</Banner></div>}
    {result.length > 0 && <div className="pad"><Banner tone="warn" onClose={() => setResult([])}>Not saved: {result.join(' · ')}</Banner></div>}
    {!scope ? <div className="pad"><Skeleton h={120} /></div> : scope.people.length === 0 ? <EmptyState icon="users" title="Nobody to upload for" hint="You are not responsible for any team members yet." /> :
      <div className="table-scroll"><table className="kpi-table"><thead><tr><th>Person</th><th>Overall</th>{METRICS.map(m => <th key={m.key}>{m.label}</th>)}<th>Remarks</th><th>Status</th></tr></thead>
        <tbody>{scope.people.map(p => <tr key={p.employee_id} className={drafts[p.employee_id] ? 'dirty' : ''}>
          <td><strong>{p.full_name}</strong><small>{p.employee_id} · {p.role_pool === 'senior_support' ? 'senior' : 'agent'}</small></td>
          {FIELDS.map(f => <td key={f}><input className={`kpi-in ${bad(drafts[p.employee_id]?.[f]) ? 'bad' : ''}`} inputMode="decimal" aria-label={`${f} for ${p.full_name}`} value={val(p.employee_id, f, p.kpi)} onChange={e => set(p.employee_id, f, e.target.value)} /></td>)}
          <td><input className="kpi-in wide" maxLength={500} aria-label={`remarks for ${p.full_name}`} value={drafts[p.employee_id]?.remarks ?? p.kpi?.remarks ?? ''} onChange={e => set(p.employee_id, 'remarks', e.target.value)} /></td>
          <td>{drafts[p.employee_id] ? <Badge tone="warn">Edited</Badge> : p.kpi ? <Badge tone="success">Saved</Badge> : <Badge tone="neutral">Missing</Badge>}</td></tr>)}</tbody></table></div>}
  </section>
}

function TeamView({ user }: { user: AuthUser }) {
  const mgr = user.role !== 'supervisor'
  const [period, setPeriod] = useState(thisMonth())
  const [teams, setTeams] = useState<string[]>([])
  const [team, setTeam] = useState('')
  const [d, setD] = useState<TeamPerformance | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { if (mgr) getKpiOverview(period).then(o => { setTeams(o.teams.map(t => t.team)); setTeam(t => t || o.teams[0]?.team || '') }).catch(() => undefined) }, [mgr, period])
  useEffect(() => {
    if (mgr && !team) return
    setD(null); setError('')
    getTeamPerformance(period, mgr ? team : undefined).then(setD).catch(e => setError(e instanceof Error ? e.message : 'Could not load'))
  }, [period, team, mgr])
  return <>
    <section className="panel"><div className="filters pad"><MonthPicker value={period} onChange={setPeriod} />
      {mgr && <label className="field inline"><span>Team</span><select value={team} onChange={e => setTeam(e.target.value)}>{teams.map(t => <option key={t}>{t}</option>)}</select></label>}</div></section>
    {error && <Banner tone="danger">{error}</Banner>}
    {!d && !error ? <section className="panel pad"><Skeleton h={90} /></section> : d && <>
      <section className="stats">
        <div className="stat-card" style={stagger(0, 90)}><span className="stat-icon"><Icon name="trending" size={22} /></span><div><span className="stat-label">{d.team} · average</span><strong>{d.average === null ? '—' : `${fmt(d.average)}%`}</strong><small>{monthLabel(d.period)}</small></div></div>
        <div className="stat-card" style={stagger(1, 90)}><span className="stat-icon teal"><Icon name="checkCircle" size={22} /></span><div><span className="stat-label">KPI uploaded</span><strong>{d.reported}/{d.members}</strong><small>{d.members - d.reported} missing</small></div></div>
        <div className="stat-card" style={stagger(2, 90)}><span className="stat-icon violet"><Icon name="activity" size={22} /></span><div><span className="stat-label">Best / lowest</span><strong>{fmt(d.best)} / {fmt(d.lowest)}</strong><small>individual scores</small></div></div>
      </section>
      <div className="two-col">
        <section className="panel" style={stagger(3, 90)}><div className="panel-heading"><div><h3>Team trend</h3><p>Average score, last 6 months.</p></div></div><div className="pad"><Bars items={d.trend.map(t => ({ label: monthLabel(t.period).slice(0, 3), value: t.average }))} /></div></section>
        <section className="panel" style={stagger(4, 90)}><div className="panel-heading"><div><h3>Team metrics</h3><p>Average per metric.</p></div></div><div className="pad"><MetricRows values={d.metrics} /></div></section>
      </div>
      <section className="panel" style={stagger(5, 90)}><div className="panel-heading"><div><h3>Members · ranked</h3><p>Seniors and agents of {d.team}.</p></div></div>
        <div className="table-scroll"><table><thead><tr><th>#</th><th>Person</th><th>Overall</th><th>vs last month</th>{METRICS.map(m => <th key={m.key}>{m.label}</th>)}</tr></thead>
          <tbody>{d.rows.map((r, i) => <tr key={r.employee_id}><td>{r.kpi ? i + 1 : '—'}</td><td><strong>{r.full_name}</strong><small>{r.employee_id}{r.role_pool === 'senior_support' ? ' · senior' : ''}</small></td>
            <td>{r.kpi ? <Badge tone={tone(r.kpi.score)}>{fmt(r.kpi.score)}%</Badge> : <Badge tone="neutral">Not uploaded</Badge>}</td><td><Delta v={r.change} /></td>
            {METRICS.map(m => <td key={m.key}>{fmt(r.kpi?.[m.key])}</td>)}</tr>)}</tbody></table></div></section>
    </>}
  </>
}

function CompareView() {
  const [period, setPeriod] = useState(thisMonth())
  const [d, setD] = useState<KpiOverview | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { setD(null); getKpiOverview(period).then(setD).catch(e => setError(e instanceof Error ? e.message : 'Could not load')) }, [period])
  const row = (t: TeamStats & { is_mine: boolean; rank: number | null }) => <tr key={t.team} className={t.is_mine ? 'mine' : ''}>
    <td>{t.rank ?? '—'}</td><td><strong>{t.team}</strong>{t.is_mine && <> <Badge tone="info" dot={false}>Your team</Badge></>}<small>Leader: {t.leader?.full_name ?? '—'}</small></td>
    <td><div className="bar-cell"><span className="meter"><i style={{ width: `${t.average ?? 0}%` }} /></span><b>{t.average === null ? '—' : `${fmt(t.average)}%`}</b></div></td>
    <td>{t.reported}/{t.members}</td>{METRICS.map(m => <td key={m.key}>{fmt(t.metrics[m.key])}</td>)}</tr>
  return <section className="panel" style={stagger(0, 90)}>
    <div className="panel-heading"><div><h3>Team leaders · overall team performance</h3><p>Each leader is measured by the average KPI of their team. Averages only, no individual scores of other teams.</p></div></div>
    <div className="filters"><MonthPicker value={period} onChange={setPeriod} /></div>
    {error && <div className="pad"><Banner tone="danger">{error}</Banner></div>}
    {!d ? <div className="pad"><Skeleton h={120} /></div> : <div className="table-scroll"><table><thead><tr><th>Rank</th><th>Team</th><th>Average</th><th>Uploaded</th>{METRICS.map(m => <th key={m.key}>{m.label}</th>)}</tr></thead><tbody>{d.teams.map(row)}</tbody></table></div>}
  </section>
}
