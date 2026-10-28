import { Icon } from './Icons'
import { Badge, stagger } from './ui'
import type { LeaveImpact } from '../types'

const SHIFT = { M: 'Morning', E: 'Evening', N: 'Night' } as Record<string, string>
const HOW = { from_reserve: 'from reserve', moved_shift: 'moved shift', weekly_off_call_in: 'weekly-off call-in' } as Record<string, string>

export default function LeaveImpactPanel({ impact, simulated, onClose }: { impact: LeaveImpact; simulated?: boolean; onClose: () => void }) {
  const ok = impact.shortages.length === 0
  return (
    <section className="panel impact">
      <div className="panel-heading">
        <div>
          <h3>{simulated ? 'Preview — nothing saved' : 'Roster impact'} · {impact.application_id} ({impact.employee_id})</h3>
          <p>{impact.from === impact.to ? impact.from : `${impact.from} → ${impact.to}`}
            {impact.new_version_id ? ` · new draft version #${impact.new_version_id}` : ''}</p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {simulated && <Badge tone="warn">Simulation</Badge>}
          <button className="btn btn-secondary btn-sm" onClick={onClose}><Icon name="x" size={14} /> Close</button>
        </div>
      </div>
      <div className="impact-body">
        <div className="impact-kpis">
          <div style={stagger(0, 70)}><strong>{impact.removed_assignments.length}</strong><span>duty days removed</span></div>
          <div style={stagger(1, 70)}><strong>{impact.replacements.length}</strong><span>replacements</span></div>
          <div style={stagger(2, 70)}><strong>{impact.other_employees_changed}</strong><span>other employees changed</span></div>
          <div style={stagger(3, 70)} className={ok ? 'good' : 'bad'}><strong>{impact.shortage_total_after}</strong><span>shortage after (was {impact.shortage_total_before})</span></div>
        </div>

        {impact.off_day_plan && <div className="impact-note">
          <b>New off-day plan</b> from {impact.off_day_plan.effective_from} ({impact.off_day_plan.continuous_days} continuous leave days):
          weekly off {impact.off_day_plan.previous_weekly_off ?? '—'} → <b>{impact.off_day_plan.weekly_off}</b>
          {impact.off_day_plan.half_duty ? <>, half-duty <b>{impact.off_day_plan.half_duty}</b></> : null}.
        </div>}

        {impact.removed_assignments.length > 0 && <>
          <h4>Removed from duty</h4>
          <div className="chips">{impact.removed_assignments.map(r => <span key={r.date} className="chip">{r.date} · was {r.was}</span>)}</div>
        </>}

        {impact.replacements.length > 0 && <>
          <h4>Replacements / re-optimisation</h4>
          <div className="table-scroll"><table>
            <thead><tr><th>Date</th><th>Shift</th><th>Employee</th><th>Change</th><th>Source</th></tr></thead>
            <tbody>{impact.replacements.slice(0, 40).map((r, i) => <tr key={i}>
              <td className="num">{r.date}</td><td>{SHIFT[r.shift] ?? r.shift}</td><td className="mono">{r.employee_id}</td><td>{r.from ?? '—'} → {r.to}</td><td>{HOW[r.how] ?? r.how}</td>
            </tr>)}</tbody>
          </table></div>
        </>}

        {ok ? <div className="impact-note good">Coverage stays complete (Morning / Evening / Night / Senior).</div> : <>
          <h4>Shortage after change</h4>
          <div className="table-scroll"><table>
            <thead><tr><th>Date</th><th>Shift</th><th>Required</th><th>Assigned</th><th>Missing</th><th>Senior missing</th></tr></thead>
            <tbody>{impact.shortages.map((s, i) => <tr key={i} className="row-bad">
              <td className="num">{s.date}</td><td>{SHIFT[s.shift]}</td><td className="num">{s.required}</td><td className="num">{s.assigned}</td><td className="num short-text">{s.shortage}</td><td className="num">{s.senior_shortage}</td>
            </tr>)}</tbody>
          </table></div>
          {impact.proposals.length > 0 && <>
            <h4>Proposed replacements</h4>
            {impact.proposals.map((p, i) => <div key={i} className="proposal">
              <b>{p.date} · {SHIFT[p.shift]}</b> (missing {p.missing || `${p.senior_missing} senior`}):{' '}
              {p.candidates.length === 0 ? <i>no eligible candidate — manager action needed</i> :
                p.candidates.map(c => <span key={c.employee_id} className="chip" title={c.employee_name}>{c.employee_id} · {c.option.replaceAll('_', ' ')}{c.senior ? ' · senior' : ''}</span>)}
            </div>)}
          </>}
        </>}
      </div>
    </section>
  )
}
