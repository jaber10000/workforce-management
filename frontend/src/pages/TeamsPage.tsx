import { useCallback, useEffect, useState } from 'react'
import { autoAssignTeams, getTeams, renameTeamsToLeaders } from '../api'
import { Icon } from '../components/Icons'
import { useToast } from '../components/Toast'
import { Badge, Banner, EmptyState, Spinner, stagger, useConfirm } from '../components/ui'
import type { TeamRow } from '../types'

export default function TeamsPage({ canEdit }: { canEdit: boolean }) {
  const toast = useToast()
  const { confirm, dialog } = useConfirm()
  const [teams, setTeams] = useState<TeamRow[]>([])
  const [preview, setPreview] = useState<{ teams: TeamRow[]; changed: number; warnings: string[]; seed: number } | null>(null)
  const [count, setCount] = useState(5)
  const [seniors, setSeniors] = useState(2)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => { try { setTeams(await getTeams()) } catch (e) { setError(e instanceof Error ? e.message : 'Could not load teams') } }, [])
  useEffect(() => { void load() }, [load])

  async function plan() {
    setBusy('plan'); setError('')
    try { setPreview(await autoAssignTeams(true, count, seniors)) } catch (e) { setError(e instanceof Error ? e.message : 'Could not build the plan') } finally { setBusy('') }
  }
  async function save() {
    if (!await confirm({ title: 'Save this team split?', message: `This re-assigns ${preview?.changed ?? 0} employee(s). Existing rosters are not changed.`, confirmLabel: 'Save teams' })) return
    setBusy('save'); setError('')
    try { const r = await autoAssignTeams(false, count, seniors, preview?.seed); toast(`Teams saved (${r.changed} employees moved).`); setPreview(null); await load() }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not save teams') } finally { setBusy('') }
  }

  const numbered = teams.filter(t => /^Team \d+$/.test(t.team))
  async function rename() {
    setBusy('rename'); setError('')
    try { const r = await renameTeamsToLeaders(); toast(`${Object.keys(r.renamed).length} team(s) renamed after their leader.`); await load() }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not rename') } finally { setBusy('') }
  }
  const show = preview?.teams ?? teams
  const unassigned = teams.find(t => t.team === 'Unassigned')
  return (
    <>
      <header className="topbar"><div><div className="eyebrow">Organisation</div><h1>Teams</h1></div></header>
      {error && <Banner tone="danger" onClose={() => setError('')}>{error}</Banner>}
      {canEdit && <section className="panel" style={stagger(0, 90)}>
        <div className="panel-heading"><div><h3>Split into teams</h3><p>Every active employee is placed into a team at random, with one supervisor (the team is named after this leader) and the chosen number of senior agents. Sizes are equal (±1) and night-eligible people, gender and weekly-off days are spread evenly. Preview, shuffle again if you like, then save exactly the plan you see.</p></div></div>
        <div className="control-row">
          <label className="field">Teams<input type="number" min={1} max={20} value={count} onChange={e => setCount(Number(e.target.value))} /></label>
          <label className="field">Senior agents per team<input type="number" min={0} max={10} value={seniors} onChange={e => setSeniors(Number(e.target.value))} /></label>
          <button className="btn btn-secondary" disabled={!!busy} onClick={() => void plan()}>{busy === 'plan' ? <><Spinner /> Planning…</> : <><Icon name="eye" size={16} /> {preview ? 'Shuffle again' : 'Random split (preview)'}</>}</button>
          {preview && <button className="btn btn-primary" disabled={!!busy} onClick={() => void save()}>{busy === 'save' ? <><Spinner /> Saving…</> : <><Icon name="check" size={16} /> Save these teams</>}</button>}
        </div>
      </section>}
      {canEdit && numbered.length > 0 && !preview && <Banner tone="info">
        {numbered.map(t => t.team).join(', ')} {numbered.length === 1 ? 'is' : 'are'} still numbered. Teams are named after their leader ("Team Arif").{' '}
        <button className="btn btn-primary btn-sm" disabled={!!busy} onClick={() => void rename()}>{busy === 'rename' ? <Spinner /> : null} Name teams after their leaders</button></Banner>}
      {preview && preview.warnings.map(w => <Banner key={w} tone="info">{w}</Banner>)}
      {preview && <Banner tone="info">Preview only: nothing is saved yet. {preview.changed} employee(s) would change team.</Banner>}
      {!preview && unassigned && unassigned.size > 0 && <Banner tone="info">{unassigned.size} active employee(s) have no team yet.</Banner>}
      <section className="panel" style={stagger(1, 90)}>
        <div className="table-scroll"><table>
          <thead><tr><th>Team</th><th>Members</th><th>Supervisor</th><th>Senior agents</th><th>Night-eligible</th><th>Male / Female</th></tr></thead>
          <tbody>{show.length === 0 ? <tr><td colSpan={6}><EmptyState icon="users" title="No teams yet" hint={canEdit ? 'Press “Random split (preview)” to build them.' : 'A manager has not split the staff into teams yet.'} /></td></tr> : show.map(t => <tr key={t.team}>
            <td><strong>{t.team}</strong></td><td className="num">{t.size}</td>
            <td>{t.supervisors.length ? t.supervisors.map(s => <div key={s.employee_id}>{s.full_name}<small>{s.employee_id}</small></div>) : <Badge tone="warn">none</Badge>}</td>
            <td>{t.seniors.length ? t.seniors.map(s => <div key={s.employee_id}>{s.full_name}<small>{s.employee_id}</small></div>) : <Badge tone="warn">none</Badge>}</td>
            <td className="num">{t.night_eligible}</td><td className="num">{t.male} / {t.female}</td>
          </tr>)}</tbody>
        </table></div>
      </section>
      {dialog}
    </>
  )
}
