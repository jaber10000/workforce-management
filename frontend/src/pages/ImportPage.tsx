import { FormEvent, useState } from 'react'
import { importWorkbook } from '../api'
import { Icon } from '../components/Icons'
import { useToast } from '../components/Toast'
import { Badge, Banner, Spinner, stagger } from '../components/ui'
import type { ImportReport } from '../types'

/** Manager/admin only. Always check (dry run) first: nothing is saved until "Import now". */
export default function ImportPage({ onImported }: { onImported: (rosterVersionId: number | null) => void }) {
  const toast = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [weekStart, setWeekStart] = useState('')
  const [parts, setParts] = useState({ employees: true, requirements: true, roster: true })
  const [report, setReport] = useState<ImportReport | null>(null)
  const [busy, setBusy] = useState<'' | 'check' | 'import'>('')
  const [error, setError] = useState('')

  const run = async (dryRun: boolean) => {
    if (!file) return
    setError(''); setBusy(dryRun ? 'check' : 'import')
    try {
      const r = await importWorkbook(file, { dryRun, weekStart: weekStart || undefined, ...parts })
      setReport(r)
      if (!dryRun) { toast('Workbook imported. The roster (if any) is saved as a new draft.'); onImported(r.roster?.version_id ?? null) }
    } catch (err) { setReport(null); setError(err instanceof Error ? err.message : 'Import failed') }
    finally { setBusy('') }
  }
  const check = (e: FormEvent) => { e.preventDefault(); void run(true) }
  const pick = (f: File | null) => { setFile(f); setReport(null); setError('') }

  return (
    <>
      <header className="topbar"><div><div className="eyebrow">Data</div><h1>Excel import</h1></div></header>
      {error && <Banner tone="danger" onClose={() => setError('')}>{error}</Banner>}
      <section className="panel" style={stagger(0, 90)}>
        <div className="panel-heading"><div><h3>Import a workbook</h3>
          <p>Reads Employee_Master, Daily_Requirement, Leave_Applications and Weekly_Roster sheets (the demo layout or the app's own export). An imported roster is saved as a new <b>draft</b> and never changes a published roster. Check first: nothing is saved until you press Import now.</p></div></div>
        <form className="leave-form" onSubmit={check}>
          <label className="field wide">Excel file (.xlsx, max 5 MB) *
            <input type="file" required accept=".xlsx" onChange={e => pick(e.target.files?.[0] ?? null)} /></label>
          <label className="field">Roster start date<input type="date" value={weekStart} onChange={e => { setWeekStart(e.target.value); setReport(null) }} />
            <small>Needed only when the roster columns are Monday…Sunday. Date columns need nothing.</small></label>
          <div className="field wide">
            {(['employees', 'requirements', 'roster'] as const).map(k => (
              <label key={k} style={{ display: 'inline-flex', gap: 6, marginRight: 18 }}>
                <input type="checkbox" checked={parts[k]} onChange={e => { setParts({ ...parts, [k]: e.target.checked }); setReport(null) }} />
                {k === 'employees' ? 'Employees' : k === 'requirements' ? 'Requirements & leave' : 'Roster'}
              </label>))}
          </div>
          <button className="btn btn-secondary" disabled={!file || !!busy}>{busy === 'check' ? <><Spinner /> Checking…</> : <><Icon name="search" size={16} /> Check file</>}</button>
          <button type="button" className="btn btn-primary" disabled={!file || !report || !!busy} onClick={() => void run(false)}>
            {busy === 'import' ? <><Spinner /> Importing…</> : <><Icon name="upload" size={16} /> Import now</>}</button>
        </form>
      </section>

      {report && <section className="panel" style={stagger(1, 90)}>
        <div className="panel-heading"><div><h3>{report.dry_run ? 'Check result (nothing saved yet)' : 'Imported'}</h3><p>Sheets found: {report.sheets.join(', ') || 'none'}</p></div>
          <Badge tone={report.errors.length ? 'warn' : 'success'}>{report.errors.length ? `${report.errors.length} issue(s)` : 'No issues'}</Badge></div>
        <div className="pad">
          <ul>
            {report.employees && <li>Employees: <b>{report.employees.created}</b> new, <b>{report.employees.updated}</b> updated, {report.employees.skipped} skipped</li>}
            {report.requirements != null && <li>Daily requirements: <b>{report.requirements}</b> day(s)</li>}
            {report.leaves && <li>Leave applications: <b>{report.leaves.created}</b> new, <b>{report.leaves.updated}</b> updated</li>}
            {report.roster && <li>Roster draft: <b>{report.roster.cells}</b> shifts for <b>{report.roster.employees}</b> people, {report.roster.start_date} → {report.roster.end_date};
              shortage {report.roster.shortage_total} person-shift(s) on {report.roster.days_with_shortage} day(s)
              {report.roster.unknown_employee_ids.length > 0 && <> · unknown IDs ignored: {report.roster.unknown_employee_ids.join(', ')}</>}</li>}
          </ul>
          {report.warnings.map((w, i) => <Banner key={`w${i}`} tone="info">{w}</Banner>)}
          {report.errors.length > 0 && <Banner tone="danger">Rows with problems are skipped or left empty:<ul>{report.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></Banner>}
        </div>
      </section>}
    </>
  )
}
