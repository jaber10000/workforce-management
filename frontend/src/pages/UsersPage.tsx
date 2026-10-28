import { FormEvent, useCallback, useEffect, useState } from 'react'
import { createUser, getUsers, importAccounts, updateUser } from '../api'
import { parseCsvTable } from '../utils'
import { Icon } from '../components/Icons'
import { useToast } from '../components/Toast'
import { Badge, Banner, stagger } from '../components/ui'
import type { UserRow } from '../types'

export default function UsersPage() {
  const toast = useToast()
  const [users, setUsers] = useState<UserRow[]>([])
  const [form, setForm] = useState({ username: '', password: '', role: 'employee', employee_id: '', full_name: '', team: '' })
  const [error, setError] = useState('')
  const [importNote, setImportNote] = useState('')

  const load = useCallback(async () => { try { setUsers(await getUsers()) } catch (e) { setError(e instanceof Error ? e.message : 'Could not load users') } }, [])
  useEffect(() => { void load() }, [load])

  async function submit(e: FormEvent) {
    e.preventDefault(); setError('')
    try {
      const r = await createUser({ username: form.username, password: form.password, role: form.role, employee_id: form.employee_id.trim() || undefined, full_name: form.full_name.trim() || undefined, team: form.team.trim() || undefined })
      toast(`${form.username} created${r.profile_created ? ' together with the employee profile' : ''}.`)
      setForm({ username: '', password: '', role: 'employee', employee_id: '', full_name: '', team: '' }); await load()
    }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not create user') }
  }
  async function importFile(file: File) {
    setError(''); setImportNote('')
    const t = parseCsvTable(await file.text(), 'username')
    if (!t) { setError('No "username" column found. Expected columns: username, password, role, employee_id, name, team.'); return }
    const rows = t.rows.map(r => ({ username: r.username ?? '', password: r.password ?? '', role: (r.role || 'employee').toLowerCase(), employee_id: r.employee_id || undefined, name: r.name || r.full_name || undefined, team: r.team || undefined })).filter(r => r.username)
    if (!rows.length) { setError('The CSV has no account rows.'); return }
    try {
      const r = await importAccounts(rows)
      setImportNote(`${r.created} created, ${r.updated} updated (passwords set as listed), ${r.profiles_created} employee profile(s) created, ${r.rejected} rejected.${r.errors.length ? ' Problems: ' + r.errors.slice(0, 8).map(e => `${e.username}: ${e.error}`).join(' · ') : ''}`)
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : 'Import failed') }
  }
  async function patch(u: UserRow, body: Parameters<typeof updateUser>[1], msg: string) {
    setError('')
    try { await updateUser(u.username, body); toast(`${u.username}: ${msg}`, 'info'); await load() } catch (err) { setError(err instanceof Error ? err.message : 'Update failed') }
  }

  return (
    <>
      <header className="topbar"><div><div className="eyebrow">Administration</div><h1>Users &amp; roles</h1></div></header>
      {error && <Banner tone="danger" onClose={() => setError('')}>{error}</Banner>}
      <section className="panel" style={stagger(0, 90)}>
        <div className="panel-heading"><div><h3>Add user</h3><p>Employees see the published roster and manage their own leave and swaps. Supervisors review rosters, leave and swaps and can edit drafts, but cannot approve, publish, import, export or see phone, thana and notes (Employee ID is optional; if the ID has no profile yet, add the full name and the profile is created with the account). Managers also approve, publish and import. Admins also manage users.</p></div></div>
        <form className="leave-form" onSubmit={submit}>
          <label className="field">Username *<input required minLength={3} value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} /></label>
          <label className="field">Password * (min 8)<input required minLength={8} type="password" autoComplete="new-password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /></label>
          <label className="field">Role<select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}><option value="employee">Employee</option><option value="supervisor">Supervisor</option><option value="manager">Manager</option><option value="admin">Admin</option></select></label>
          <label className="field">Employee ID{form.role === 'employee' ? ' *' : ' (optional)'}<input required={form.role === 'employee'} value={form.employee_id} onChange={e => setForm({ ...form, employee_id: e.target.value })} /></label>
          <label className="field">Full name{form.employee_id.trim() ? ' (needed if this ID has no profile yet)' : ''}<input value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} placeholder="Creates the profile if missing" /></label>
          <label className="field">Team<input value={form.team} onChange={e => setForm({ ...form, team: e.target.value })} placeholder="e.g. Team Rahim (usually set by the auto split)" /></label>
          <button className="btn btn-primary">Create user</button>
        </form>
      </section>
      <section className="panel" style={stagger(1, 90)}>
        <div className="panel-heading"><div><h3>Import accounts (CSV)</h3><p>Columns: username, password, role, employee_id, name, team. New accounts are created and existing ones get the listed password and role, so this also repairs accounts that do not log in. Missing employee profiles are created from the name column.</p></div>
          <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer' }}><Icon name="upload" size={15} /> Choose CSV<input type="file" accept=".csv,text/csv" hidden onChange={e => { const f = e.target.files?.[0]; if (f) void importFile(f); e.target.value = '' }} /></label></div>
        {importNote && <div className="pad"><Banner tone="info" onClose={() => setImportNote('')}>{importNote}</Banner></div>}
        <div className="table-scroll"><table>
          <thead><tr><th>Username</th><th>Role</th><th>Employee</th><th>Status</th><th></th></tr></thead>
          <tbody>{users.map(u => <tr key={u.username}><td><strong>{u.username}</strong></td><td>{u.role}</td><td className="mono">{u.employee_id ?? '—'}</td>
            <td><Badge tone={u.is_active ? 'success' : 'neutral'}>{u.is_active ? 'Active' : 'Disabled'}</Badge></td>
            <td><div className="actions">
              <button className="btn btn-neutral btn-sm" onClick={() => void patch(u, { is_active: !u.is_active }, u.is_active ? 'disabled' : 'enabled')}>{u.is_active ? 'Disable' : 'Enable'}</button>
              <button className="btn btn-neutral btn-sm" onClick={() => { const p = window.prompt('New password (min 8 characters)'); if (p && p.length >= 8) void patch(u, { password: p }, 'password reset') }}>Reset password</button>
            </div></td></tr>)}</tbody>
        </table></div>
      </section>
    </>
  )
}
