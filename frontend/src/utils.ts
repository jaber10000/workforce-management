/** Small shared helpers (no React). */

const csvCell = (v: unknown) => {
  const s = v == null ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
}

/** Builds a CSV in the browser and starts a download. A BOM keeps Excel happy with Bangla text. */
export function downloadCsv(filename: string, header: string[], rows: unknown[][]) {
  const body = [header, ...rows].map(r => r.map(csvCell).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + body], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`
  return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
}

export const greeting = () => {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export const isoDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export const fmtNum = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))
export const shortDate = (iso: string) =>
  new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
export const codeClass = (c: string) =>
  `code code-${c.replace('-H', '').toLowerCase()}${c.endsWith('-H') ? ' half' : ''}`

/** One readable line for an audit event: old → new values, reason, who/what. */
export function describeEvent(action: string, d: Record<string, unknown>): string {
  const s = (k: string) => (d[k] === undefined || d[k] === null ? '' : String(d[k]))
  switch (action) {
    case 'roster_cell_edited': return `${s('employee_id')}${d.employee_name ? ` (${s('employee_name')})` : ''} on ${s('date')}: ${s('from')} → ${s('to')} — reason: ${s('reason')}`
    case 'roster_rejected': return `rejected — reason: ${s('note')}`
    case 'roster_approved': return `approved${s('note') ? ` — note: ${s('note')}` : ''}${d.acknowledged_shortage ? ' (shortage acknowledged)' : ''}`
    case 'roster_published': return `published v${s('version_no')}${s('approved_by') ? ` (approved by ${s('approved_by')})` : ''}`
    case 'roster_generated': case 'roster_regenerated': return `v${s('version_no')} (${s('trigger').replaceAll('_', ' ')})${s('reason') ? ` — ${s('reason')}` : ''}${d.changes !== undefined ? `, ${s('changes')} changes` : ''}`
    case 'swap_approved': return `${s('requester')} ${s('requester_code')} ⇄ ${s('counterpart')} ${s('counterpart_code')} on ${s('date')} → v#${s('new_version_id')}`
    case 'swap_requested': return `${s('requester')} ⇄ ${s('counterpart')} on ${s('date')}${s('reason') ? ` — ${s('reason')}` : ''}`
    case 'employee_updated': return `before ${JSON.stringify(d.before)} → after ${JSON.stringify(d.after)}`
    default: return Object.entries(d).filter(([, x]) => typeof x !== 'object' || x === null).map(([k, x]) => `${k}: ${String(x)}`).join(' · ')
  }
}

/** Role helpers - keep in step with Principal.is_manager / is_reviewer in backend/app/api/deps.py. */
export const isManager = (role: string) => role === 'admin' || role === 'manager'
/** Manager-level or supervisor: may see the full roster, leave and swap picture and edit drafts (no approve/publish). */
export const isReviewer = (role: string) => isManager(role) || role === 'supervisor'

/** Small CSV reader: quotes, "" escapes, CRLF/LF, BOM, and comma / semicolon / tab delimiters (picked from the header). */
export function parseCsv(text: string): string[][] {
  const t = text.replace(/^﻿/, '')
  const firstLine = t.split(/\r?\n/).find(l => l.trim()) ?? ''
  const delim = [',', ';', '\t'].map(d => [d, firstLine.split(d).length] as const).sort((a, b) => b[1] - a[1])[0][0]
  const rows: string[][] = []
  let row: string[] = [], cell = '', q = false
  for (let i = 0; i < t.length; i++) {
    const c = t[i]
    if (q) {
      if (c === '"') { if (t[i + 1] === '"') { cell += '"'; i++ } else q = false } else cell += c
    } else if (c === '"') q = true
    else if (c === delim) { row.push(cell); cell = '' }
    else if (c === '\n' || c === '\r') { if (c === '\r' && t[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = '' }
    else cell += c
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row) }
  return rows.map(r => r.map(x => x.trim()))
}

export interface CsvTable { header: string[]; rows: Record<string, string>[]; before: string[][] }
/** Finds the header row (the first row that contains `required`), so title / note rows above it are fine. */
export function parseCsvTable(text: string, required: string): CsvTable | null {
  const all = parseCsv(text)
  const norm = (h: string) => h.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
  const hi = all.findIndex(r => r.some(c => norm(c) === required))
  if (hi < 0) return null
  const header = all[hi].map(norm)
  const rows = all.slice(hi + 1).filter(r => r.some(c => c !== '')).map(r => Object.fromEntries(header.map((h, i) => [h, r[i] ?? '']).filter(([h]) => h)))
  return { header, rows, before: all.slice(0, hi) }
}

export interface KpiCsvRow { employee_id: string; score?: string; quality?: string; attendance?: string; productivity?: string; csat?: string; remarks?: string }
/** KPI file (the downloaded template, or the person-wise sheet with a "Month (YYYY-MM)" line above the header).
 *  The overall column ("overall" / "score") is only used when fewer than 4 metrics are given: with all 4 metrics the
 *  overall is the average of them (what the sheet says: "Overall = average of the 4 metrics"). */
export function parseKpiCsv(text: string): { period: string | null; rows: KpiCsvRow[]; overallIgnored: number } | null {
  const t = parseCsvTable(text, 'employee_id')
  if (!t) return null
  let period: string | null = null
  for (const r of t.before) for (let i = 0; i < r.length; i++) if (/month/i.test(r[i]) && /^\d{4}-(0[1-9]|1[0-2])$/.test(r[i + 1] ?? '')) period = r[i + 1]
  let overallIgnored = 0
  const rows: KpiCsvRow[] = []
  for (const r of t.rows) {
    const id = (r.employee_id ?? '').trim()
    if (!id) continue
    const out: KpiCsvRow = { employee_id: id }
    const metrics = (['quality', 'attendance', 'productivity', 'csat'] as const).filter(m => r[m] !== undefined && r[m] !== '')
    for (const m of metrics) out[m] = r[m]
    const overall = r.overall ?? r.score ?? ''
    if (overall !== '') { if (metrics.length === 4) overallIgnored++; else out.score = overall }
    if (r.remarks) out.remarks = r.remarks
    rows.push(out)
  }
  return { period, rows, overallIgnored }
}
