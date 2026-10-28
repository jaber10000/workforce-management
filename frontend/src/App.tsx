import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { auth, createEmployee, deactivateEmployee, getEmployees, getMe, getMyTeam, getUnread, logout, updateEmployee } from './api'
import DashboardPage from './pages/DashboardPage'
import RosterPage from './pages/RosterPage'
import LeavesPage from './pages/LeavesPage'
import LoginPage from './pages/LoginPage'
import ApprovalsPage from './pages/ApprovalsPage'
import SwapsPage from './pages/SwapsPage'
import AuditPage from './pages/AuditPage'
import UsersPage from './pages/UsersPage'
import ImportPage from './pages/ImportPage'
import TeamsPage from './pages/TeamsPage'
import MyHomePage from './pages/MyHomePage'
import TeamPortalPage from './pages/TeamPortalPage'
import MessagesPage from './pages/MessagesPage'
import KpiPage from './pages/KpiPage'
import { Icon, Logo, type IconName } from './components/Icons'
import { Badge, Banner, CountUp, EmptyState, Modal, Skeleton, Spinner, stagger, useConfirm, useMounted } from './components/ui'
import { ToastProvider, useToast } from './components/Toast'
import ThemePanel from './components/ThemePanel'
import CommandPalette, { type Cmd } from './components/CommandPalette'
import { PALETTES, useTheme } from './theme'
import { downloadCsv, isManager, isoDay } from './utils'
import type { AuthUser, Employee, EmployeePayload, Gender, Page, RolePool, Weekday } from './types'

type SortKey = 'name' | 'role' | 'thana' | 'off' | 'status'
type View = 'table' | 'cards'

const weekdays: Weekday[] = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const emptyForm: EmployeePayload = {
  employee_id: '', full_name: '', gender: null, phone_number: '', home_thana: '',
  role_pool: 'general', weekly_off_day: null, half_duty_day: null, joining_date: null,
  is_shift_eligible_morning: true, is_shift_eligible_evening: true,
  is_shift_eligible_night: false, is_active: true, notes: '', team: null,
}
const roleLabels: Record<RolePool, string> = {
  general: 'General', senior_support: 'Senior Support', supervisor: 'Supervisor', other: 'Other',
}
const NAV: { key: Page; label: string; icon: IconName }[] = [
  { key: 'dashboard', label: 'Overview', icon: 'dashboard' },
  { key: 'employees', label: 'Employees', icon: 'users' },
  { key: 'roster', label: 'Roster calendar', icon: 'calendar' },
  { key: 'leaves', label: 'Leave requests', icon: 'calendarCheck' },
  { key: 'swaps', label: 'Shift swaps', icon: 'swap' },
  { key: 'approvals', label: 'Approvals', icon: 'stamp' },
  { key: 'audit', label: 'Audit history', icon: 'history' },
  { key: 'portal', label: 'My team', icon: 'users' },
  { key: 'chat', label: 'Team chat', icon: 'chat' },
  { key: 'kpi', label: 'KPI', icon: 'trending' },
  { key: 'teams', label: 'Teams', icon: 'users' },
  { key: 'import', label: 'Excel import', icon: 'upload' },
  { key: 'users', label: 'Users & roles', icon: 'users' },
]
const NAV_ROLES: Record<string, string[]> = { portal: ['supervisor'], chat: ['supervisor', 'employee'], teams: ['manager', 'admin', 'supervisor'], approvals: ['manager', 'admin'], audit: ['manager', 'admin'], import: ['manager', 'admin'], users: ['admin'] }
const PAGES = ['dashboard', 'employees', 'roster', 'leaves', 'swaps', 'approvals', 'audit', 'portal', 'chat', 'kpi', 'teams', 'import', 'users'] as const

const initials = (name: string) => name.trim().split(/\s+/).map(p => p[0]).slice(0, 2).join('').toUpperCase()
const avatarTone = (id: string) => { let h = 0; for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0; return `av-${h % 6}` }
const isMac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform)

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try { const v = localStorage.getItem(key); if (v && (allowed as readonly string[]).includes(v)) return v as T } catch { /* ignore */ }
  return fallback
}

export default function App() {
  return <ToastProvider><AuthGate /></ToastProvider>
}

/** Works with auth off (server returns an open-mode admin) and with auth on (shows the sign-in page). */
function AuthGate() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [needLogin, setNeedLogin] = useState(false)
  const [checking, setChecking] = useState(true)
  useEffect(() => {
    getMe().then(u => { setUser(u); setNeedLogin(false) }).catch(() => setNeedLogin(true)).finally(() => setChecking(false))
    const onExpired = () => { setUser(null); setNeedLogin(true) }
    window.addEventListener('auth-expired', onExpired)
    return () => window.removeEventListener('auth-expired', onExpired)
  }, [])
  if (checking) return <div className="login-wrap"><Spinner /></div>
  if (needLogin || !user) return <LoginPage onLogin={u => { setUser(u); setNeedLogin(false) }} />
  return <AppShell key={user.username} user={user} onLogout={() => { logout(); setUser(null); setNeedLogin(true) }} />
}

function AppShell({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const mgr = isManager(user.role)  // supervisors review but cannot approve, publish or edit employee records
  const [teamName, setTeamName] = useState<string | null>(null)
  const [unread, setUnread] = useState(0)
  const refreshUnread = useCallback(() => { getUnread().then(r => setUnread(r.unread)).catch(() => undefined) }, [])
  useEffect(() => {
    if (user.role === 'supervisor' || user.role === 'employee') getMyTeam().then(t => setTeamName(t.team)).catch(() => undefined)
    refreshUnread(); const t = window.setInterval(refreshUnread, 30000); return () => window.clearInterval(t)
  }, [user, refreshUnread])
  const nav = NAV.filter(n => !NAV_ROLES[n.key] || NAV_ROLES[n.key].includes(user.role))
    .map(n => n.key === 'portal' && teamName ? { ...n, label: teamName } : n.key === 'chat' && user.role !== 'employee' ? { ...n, label: 'Team inbox' } : n)
  const [reviewId, setReviewId] = useState<number | null>(null)
  const theme = useTheme()
  const toast = useToast()
  const mounted = useMounted()
  const { confirm, dialog: confirmDialog } = useConfirm()
  const searchRef = useRef<HTMLInputElement>(null)
  const [page, setPage] = useState<Page>(() => readStored('wf-page', PAGES, 'dashboard'))
  const [cmdOpen, setCmdOpen] = useState(false)
  const [employees, setEmployees] = useState<Employee[]>([])
  const [search, setSearch] = useState('')
  const [role, setRole] = useState<RolePool | ''>('')
  const [showInactive, setShowInactive] = useState(false)
  const [view, setView] = useState<View>(() => readStored('wf-emp-view', ['table', 'cards'] as const, 'table'))
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'name', dir: 1 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<EmployeePayload>(emptyForm)
  const [saving, setSaving] = useState(false)

  useEffect(() => { try { localStorage.setItem('wf-page', page) } catch { /* ignore */ } }, [page])
  useEffect(() => { try { localStorage.setItem('wf-emp-view', view) } catch { /* ignore */ } }, [view])

  // Role is filtered in the browser so the role chips can show counts for everyone.
  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getEmployees({ search, is_active: showInactive ? null : true, limit: 200 })
      setEmployees(data.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load employees')
    } finally {
      setLoading(false)
    }
  }, [search, showInactive])

  useEffect(() => { void refresh() }, [refresh])

  const closeModal = useCallback(() => setModalOpen(false), [])

  function openCreate() {
    setEditingId(null)
    setForm({ ...emptyForm })
    setModalOpen(true)
  }

  function openEdit(employee: Employee) {
    setEditingId(employee.employee_id)
    const { id, created_at, updated_at, ...payload } = employee
    void id; void created_at; void updated_at
    setForm(payload)
    setModalOpen(true)
  }

  function setField<K extends keyof EmployeePayload>(key: K, value: EmployeePayload[K]) {
    setForm(previous => ({ ...previous, [key]: value }))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      if (editingId) await updateEmployee(editingId, form)
      else await createEmployee(form)
      setModalOpen(false)
      toast(editingId ? `${editingId} updated.` : `${form.employee_id} added to the team.`)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save employee')
    } finally {
      setSaving(false)
    }
  }

  async function deactivate(employee: Employee) {
    const ok = await confirm({
      title: `Deactivate ${employee.full_name}?`,
      message: `${employee.employee_id} will no longer be eligible for roster planning. You can still find them under "Include inactive".`,
      confirmLabel: 'Deactivate', tone: 'danger',
    })
    if (!ok) return
    try {
      await deactivateEmployee(employee.employee_id)
      toast(`${employee.employee_id} deactivated.`, 'info')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not deactivate employee')
    }
  }

  /* ----------------------------------------------------- derived directory data */
  const visible = useMemo(() => {
    const val = (e: Employee): string | number => {
      switch (sort.key) {
        case 'name': return e.full_name.toLowerCase()
        case 'role': return roleLabels[e.role_pool]
        case 'thana': return (e.home_thana ?? '~').toLowerCase()
        case 'off': return e.weekly_off_day ? weekdays.indexOf(e.weekly_off_day) : 9
        default: return e.is_active ? 0 : 1
      }
    }
    return employees
      .filter(e => !role || e.role_pool === role)
      .sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * sort.dir })
  }, [employees, role, sort])

  const roleCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const e of employees) c[e.role_pool] = (c[e.role_pool] ?? 0) + 1
    return c
  }, [employees])

  const offSpread = useMemo(() => weekdays.map(d => employees.filter(e => e.weekly_off_day === d).length), [employees])
  const eligibility = useMemo(() => [
    { code: 'm', label: 'Morning', n: employees.filter(e => e.is_shift_eligible_morning).length },
    { code: 'e', label: 'Evening', n: employees.filter(e => e.is_shift_eligible_evening).length },
    { code: 'n', label: 'Night', n: employees.filter(e => e.is_shift_eligible_night).length },
  ], [employees])
  const offMax = Math.max(1, ...offSpread)
  const eligMax = Math.max(1, ...eligibility.map(x => x.n))

  const activeCount = visible.filter(e => e.is_active).length
  const seniorCount = visible.filter(e => e.role_pool === 'senior_support').length
  const pageIdx = Math.max(0, nav.findIndex(n => n.key === page))

  function toggleSort(key: SortKey) {
    setSort(s => (s.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: 1 }))
  }

  function exportCsv() {
    downloadCsv(`employees-${isoDay(new Date())}.csv`,
      ['Employee ID', 'Name', 'Role', 'Team', 'Gender', 'Phone', 'Home thana', 'Weekly off', 'Half duty', 'Joining date', 'Morning', 'Evening', 'Night', 'Active'],
      visible.map(e => [e.employee_id, e.full_name, roleLabels[e.role_pool], e.team ?? '', e.gender ?? '', e.phone_number ?? '', e.home_thana ?? '',
        e.weekly_off_day ?? '', e.half_duty_day ?? '', e.joining_date ?? '',
        e.is_shift_eligible_morning ? 'Y' : '', e.is_shift_eligible_evening ? 'Y' : '', e.is_shift_eligible_night ? 'Y' : '', e.is_active ? 'Y' : 'N']))
    toast(`Exported ${visible.length} employee${visible.length === 1 ? '' : 's'} to CSV.`)
  }

  const sortTh = (key: SortKey, label: string) => (
    <th aria-sort={sort.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      <button className={`th-sort ${sort.key === key ? 'on' : ''}`} onClick={() => toggleSort(key)}>
        {label}<Icon name="arrowUp" size={12} className={`icon sort-ico ${sort.key === key && sort.dir === -1 ? 'desc' : ''}`} />
      </button>
    </th>
  )

  /* -------------------------------------------------------- keyboard shortcuts */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmdOpen(o => !o); return }
      const t = e.target as HTMLElement
      const typing = t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement
      if (e.key === '/' && !typing && page === 'employees') { e.preventDefault(); searchRef.current?.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [page])

  const commands: Cmd[] = !cmdOpen ? [] : [
    ...nav.map(n => ({ id: `go-${n.key}`, label: `Go to ${n.label}`, icon: n.icon, group: 'Navigate', keywords: n.key, run: () => setPage(n.key) })),
    ...(!mgr ? [] : [{ id: 'add', label: 'Add employee', icon: 'plus' as const, group: 'Actions', keywords: 'new create hire', run: () => { setPage('employees'); openCreate() } }]),
    { id: 'export', label: 'Export employees as CSV', icon: 'download', group: 'Actions', keywords: 'download excel', run: exportCsv },
    { id: 'mode-light', label: 'Light mode', icon: 'sun', group: 'Appearance', keywords: 'theme', run: () => theme.setMode('light') },
    { id: 'mode-dark', label: 'Dark mode', icon: 'moon', group: 'Appearance', keywords: 'theme night', run: () => theme.setMode('dark') },
    { id: 'mode-system', label: 'Match system appearance', icon: 'monitor', group: 'Appearance', keywords: 'theme auto', run: () => theme.setMode('system') },
    ...PALETTES.map(p => ({ id: `pal-${p.key}`, label: `Colour theme: ${p.label}`, icon: 'palette' as IconName, group: 'Appearance', keywords: 'palette accent', run: () => theme.setPalette(p.key) })),
    { id: 'density', label: theme.density === 'compact' ? 'Use roomy density' : 'Use compact density', icon: 'list', group: 'Appearance', keywords: 'dense spacing', run: () => theme.setDensity(theme.density === 'compact' ? 'comfortable' : 'compact') },
    { id: 'motion', label: theme.motion === 'calm' ? 'Turn animation on' : 'Calm animation down', icon: 'sparkles', group: 'Appearance', keywords: 'reduce motion', run: () => theme.setMotion(theme.motion === 'calm' ? 'full' : 'calm') },
    ...employees.map(e => ({
      id: `emp-${e.employee_id}`, label: e.full_name, hint: e.employee_id, icon: 'users' as IconName, group: 'Employees', searchOnly: true,
      keywords: `${e.employee_id} ${e.phone_number ?? ''} ${e.home_thana ?? ''}`, run: () => { setPage('employees'); openEdit(e) },
    })),
  ]

  const shiftTags = (e: Employee) => (
    <div className="shift-tags">
      {e.is_shift_eligible_morning && <span className="code code-m" title="Morning">M</span>}
      {e.is_shift_eligible_evening && <span className="code code-e" title="Evening">E</span>}
      {e.is_shift_eligible_night && <span className="code code-n" title="Night">N</span>}
    </div>
  )

  return (
    <div className="app-shell">
      <header className="mobile-bar">
        <div className="brand"><Logo size={34} /><div className="brand-text"><b>Workforce</b><span>Roster</span></div></div>
        <div className="mobile-tools">
          <button className="btn btn-ghost btn-icon" onClick={() => setCmdOpen(true)} aria-label="Search"><Icon name="search" /></button>
          <ThemePanel theme={theme} placement="bar" />
        </div>
      </header>

      <aside className="sidebar">
        <div className="brand"><Logo /><div className="brand-text"><b>Workforce</b><span>Roster</span></div></div>
        <div className="nav-label">Workspace</div>
        <nav className="nav" style={{ ['--idx' as string]: pageIdx, ['--n' as string]: nav.length } as CSSProperties}>
          <span className="nav-indicator" />
          {nav.map(n => (
            <button key={n.key} className={`nav-item ${page === n.key ? 'selected' : ''}`} onClick={() => setPage(n.key)} aria-current={page === n.key ? 'page' : undefined}>
              <Icon name={n.icon} size={19} /><span>{n.label}</span>{n.key === 'chat' && unread > 0 && <b className="nav-badge" aria-label={`${unread} unread`}>{unread}</b>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button className="cmd-hint" onClick={() => setCmdOpen(true)}>
            <Icon name="search" size={16} /><span>Search anywhere</span><kbd>{isMac ? '⌘ K' : 'Ctrl K'}</kbd>
          </button>
          <ThemePanel theme={theme} placement="side" />
          <div className="user-chip"><span className={`avatar ${avatarTone(user.username)}`}>{initials(user.username)}</span>
            <div><b>{user.username}</b><small>{user.role}{user.employee_id ? ` · ${user.employee_id}` : ''}</small></div>
            {auth.token && <button className="btn btn-ghost btn-icon" onClick={onLogout} aria-label="Sign out" title="Sign out"><Icon name="logout" size={16} /></button>}</div>
          <div className="status-line"><i className="pulse-dot" /> Phase 5 · Approval &amp; production</div>
        </div>
      </aside>

      <main className="main">
        <div className="page" key={page}>
          {page === 'dashboard' ? (user.role === 'employee' ? <MyHomePage user={user} onNavigate={setPage} /> : <DashboardPage onNavigate={setPage} onAddEmployee={() => { setPage('employees'); openCreate() }} />)
            : page === 'portal' && user.role === 'supervisor' ? <TeamPortalPage user={user} onNavigate={setPage} />
            : page === 'chat' ? <MessagesPage user={user} onUnread={refreshUnread} />
            : page === 'kpi' ? <KpiPage user={user} />
            : page === 'roster' ? <RosterPage key={reviewId ?? 'r'} user={user} openId={reviewId} /> : page === 'leaves' ? <LeavesPage user={user} />
            : page === 'swaps' ? <SwapsPage user={user} />
            : page === 'approvals' && mgr ? <ApprovalsPage user={user} onReview={id => { setReviewId(id); setPage('roster') }} />
            : page === 'audit' && mgr ? <AuditPage />
            : page === 'teams' && user.role !== 'employee' ? <TeamsPage canEdit={mgr} />
            : page === 'import' && mgr ? <ImportPage onImported={id => { if (id) { setReviewId(id); setPage('roster') } }} />
            : page === 'users' && user.role === 'admin' ? <UsersPage /> : <>
            <header className="topbar">
              <div><div className="eyebrow">Workforce operations</div><h1>Employee management</h1></div>
              <div className="topbar-actions">
                <button className="btn btn-secondary" onClick={exportCsv} disabled={visible.length === 0}><Icon name="download" size={16} /> Export CSV</button>
                {mgr && <button className="btn btn-primary" onClick={openCreate}><Icon name="plus" size={17} /> Add employee</button>}
              </div>
            </header>

            <section className="stats">
              <div className="stat-card" style={stagger(0, 90)}><span className="stat-icon"><Icon name="users" size={22} /></span><div><span className="stat-label">Employees shown</span><strong><CountUp value={visible.length} /></strong><small>Based on current filters</small></div></div>
              <div className="stat-card" style={stagger(1, 90)}><span className="stat-icon teal"><Icon name="checkCircle" size={22} /></span><div><span className="stat-label">Active in view</span><strong><CountUp value={activeCount} /></strong><small>Eligible for roster planning</small></div></div>
              <div className="stat-card" style={stagger(2, 90)}><span className="stat-icon violet"><Icon name="shield" size={22} /></span><div><span className="stat-label">Senior support</span><strong><CountUp value={seniorCount} /></strong><small>Within current results</small></div></div>
            </section>

            <section className="insights">
              <div className="panel" style={stagger(2, 90)}>
                <div className="panel-heading"><div><h3>Weekly off spread</h3><p>People resting on each weekday. Uneven bars make roster gaps.</p></div></div>
                <div className="mini-bars">
                  {weekdays.map((d, i) => <div key={d} className="mini-bar" title={`${d}: ${offSpread[i]}`}>
                    <b>{offSpread[i]}</b>
                    <div className="mini-track"><i style={{ height: mounted ? `${Math.max(offSpread[i] ? 6 : 0, (offSpread[i] / offMax) * 100)}%` : '0%', transitionDelay: `${i * 70}ms` }} /></div>
                    <span>{d.slice(0, 3)}</span>
                  </div>)}
                </div>
              </div>
              <div className="panel" style={stagger(3, 90)}>
                <div className="panel-heading"><div><h3>Shift eligibility</h3><p>People who can be rostered on each shift.</p></div></div>
                <div className="elig">
                  {eligibility.map((x, i) => <div key={x.code} className="elig-row">
                    <span className={`code code-${x.code}`}>{x.code.toUpperCase()}</span><b>{x.label}</b>
                    <div className="track"><i className={`fill-${x.code}`} style={{ width: mounted ? `${(x.n / eligMax) * 100}%` : '0%', transitionDelay: `${i * 120}ms` }} /></div>
                    <em>{x.n}</em>
                  </div>)}
                </div>
              </div>
            </section>

            {error && <Banner tone="danger">{error}</Banner>}

            <section className="panel" style={stagger(4, 90)}>
              <div className="panel-heading"><div><h3>Team directory</h3><p>Search, sort and maintain employee records. Press / to search.</p></div>
                <div className="heading-tools">
                  <div className="view-toggle" role="group" aria-label="Directory view">
                    <button className={view === 'table' ? 'on' : ''} onClick={() => setView('table')} aria-pressed={view === 'table'} title="Table view"><Icon name="list" size={16} /></button>
                    <button className={view === 'cards' ? 'on' : ''} onClick={() => setView('cards')} aria-pressed={view === 'cards'} title="Card view"><Icon name="grid" size={16} /></button>
                  </div>
                  <span className="count-pill">{visible.length} records</span>
                </div></div>
              <div className="filters">
                <div className="search-wrap"><Icon name="search" size={17} /><input ref={searchRef} value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by name, ID, phone or thana…" aria-label="Search employees" /></div>
                <label className="check-filter"><input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)} /> Include inactive</label>
              </div>
              <div className="chips-row" role="group" aria-label="Filter by role">
                <button className={`chip-filter ${role === '' ? 'on' : ''}`} onClick={() => setRole('')}>All<b>{employees.length}</b></button>
                {(Object.keys(roleLabels) as RolePool[]).map(r => (
                  <button key={r} className={`chip-filter ${role === r ? 'on' : ''}`} onClick={() => setRole(role === r ? '' : r)}>{roleLabels[r]}<b>{roleCounts[r] ?? 0}</b></button>
                ))}
              </div>

              {view === 'table' ? <div className="table-scroll">
                <table>
                  <thead><tr>{sortTh('name', 'Employee')}{sortTh('role', 'Role / pool')}<th>Gender</th>{sortTh('thana', 'Home thana')}{sortTh('off', 'Weekly off')}<th>Shift eligibility</th>{sortTh('status', 'Status')}<th></th></tr></thead>
                  {loading && employees.length === 0 ? <tbody>
                    {Array.from({ length: 6 }, (_, i) => <tr key={i}>
                      <td><div className="skeleton-cell"><Skeleton w={38} h={38} r={12} /><div><Skeleton w={130} h={13} /><br /><Skeleton w={90} h={10} /></div></div></td>
                      {Array.from({ length: 7 }, (_, j) => <td key={j}><Skeleton w={j === 6 ? 24 : 70} h={13} /></td>)}
                    </tr>)}
                  </tbody> : visible.length === 0 ? <tbody><tr><td colSpan={8}>
                    <EmptyState icon="users" title="No employees found" hint="Add a new employee or change your filters." />
                  </td></tr></tbody> : <tbody className="stagger" style={{ opacity: loading ? .55 : 1, transition: 'opacity .2s' }}>
                    {visible.map((employee, i) => <tr key={employee.employee_id} style={stagger(i, 28, 12)}>
                      <td><div className="person"><div className={`avatar ${avatarTone(employee.employee_id)}`}>{initials(employee.full_name)}</div><div><strong>{employee.full_name}</strong><small>{employee.employee_id}{employee.phone_number ? ` · ${employee.phone_number}` : ''}</small></div></div></td>
                      <td><span className={`role-tag ${employee.role_pool}`}>{roleLabels[employee.role_pool]}</span>{employee.team && <small style={{ display: 'block' }}>{employee.team}</small>}</td>
                      <td style={{ textTransform: 'capitalize' }}>{employee.gender ? employee.gender.replaceAll('_', ' ') : '—'}</td>
                      <td>{employee.home_thana || '—'}</td>
                      <td>{employee.weekly_off_day || '—'}</td>
                      <td>{shiftTags(employee)}</td>
                      <td><Badge tone={employee.is_active ? 'success' : 'neutral'}>{employee.is_active ? 'Active' : 'Inactive'}</Badge></td>
                      <td><div className="actions row-actions">
                        {mgr && <button className="btn btn-neutral btn-sm" title="Edit employee" onClick={() => openEdit(employee)}><Icon name="pencil" size={14} /> Edit</button>}
                        {mgr && employee.is_active && <button className="btn btn-reject btn-sm btn-icon" title="Deactivate employee" aria-label="Deactivate employee" onClick={() => void deactivate(employee)}><Icon name="userX" size={15} /></button>}
                      </div></td>
                    </tr>)}
                  </tbody>}
                </table>
              </div> : <div className="card-area">
                {visible.length === 0 ? <EmptyState icon="users" title="No employees found" hint="Add a new employee or change your filters." /> :
                  <div className="emp-grid" style={{ opacity: loading ? .55 : 1 }}>
                    {visible.map((e, i) => <article key={e.employee_id} className={`emp-card ${e.is_active ? '' : 'off'}`} style={stagger(i, 30, 12)}>
                      <div className="emp-top">
                        <div className={`avatar lg ${avatarTone(e.employee_id)}`}>{initials(e.full_name)}</div>
                        <div className="emp-name"><strong>{e.full_name}</strong><small>{e.employee_id}</small></div>
                        <Badge tone={e.is_active ? 'success' : 'neutral'}>{e.is_active ? 'Active' : 'Inactive'}</Badge>
                      </div>
                      <div className="emp-meta"><span className={`role-tag ${e.role_pool}`}>{roleLabels[e.role_pool]}</span><span>{e.home_thana || 'No thana'}</span></div>
                      <dl className="emp-facts">
                        <div><dt>Weekly off</dt><dd>{e.weekly_off_day || '—'}</dd></div>
                        <div><dt>Half duty</dt><dd>{e.half_duty_day || '—'}</dd></div>
                      </dl>
                      <div className="emp-foot">{shiftTags(e)}
                        <div className="actions">
                          {mgr && <button className="btn btn-neutral btn-sm" onClick={() => openEdit(e)}><Icon name="pencil" size={14} /> Edit</button>}
                          {mgr && e.is_active && <button className="btn btn-reject btn-sm btn-icon" aria-label="Deactivate employee" onClick={() => void deactivate(e)}><Icon name="userX" size={15} /></button>}
                        </div></div>
                    </article>)}
                  </div>}
              </div>}
              <div className="table-footer"><span>Showing {visible.length} records (maximum 200 in this view)</span><button className="btn btn-secondary btn-sm" onClick={() => void refresh()} disabled={loading}>{loading ? <Spinner /> : <Icon name="refresh" size={14} />} Refresh</button></div>
            </section>
          </>}
        </div>
      </main>

      <Modal open={modalOpen} onClose={closeModal} labelledBy="modal-title">
        <div className="modal-head"><div><div className="eyebrow">Employee profile</div><h2 id="modal-title">{editingId ? `Edit ${editingId}` : 'Add employee'}</h2></div><button className="close" onClick={closeModal} aria-label="Close"><Icon name="x" size={18} /></button></div>
        <form onSubmit={submit}>
          <div className="form-grid">
            <label className="field">Employee ID *<input required maxLength={30} disabled={!!editingId} value={form.employee_id} onChange={e => setField('employee_id', e.target.value)} placeholder="e.g. EMP201" /></label>
            <label className="field">Full name *<input required maxLength={150} value={form.full_name} onChange={e => setField('full_name', e.target.value)} placeholder="Employee full name" /></label>
            <label className="field">Gender<select value={form.gender ?? ''} onChange={e => setField('gender', (e.target.value || null) as Gender | null)}><option value="">Not specified</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option><option value="prefer_not_to_say">Prefer not to say</option></select></label>
            <label className="field">Phone number<input value={form.phone_number ?? ''} onChange={e => setField('phone_number', e.target.value || null)} placeholder="Phone number" /></label>
            <label className="field">Team<input value={form.team ?? ''} onChange={e => setField('team', e.target.value || null)} placeholder="e.g. Team Rahim (usually set by the auto split)" /></label>
            <label className="field">Home thana<input value={form.home_thana ?? ''} onChange={e => setField('home_thana', e.target.value || null)} placeholder="Thana / area" /></label>
            <label className="field">Role / pool<select value={form.role_pool} onChange={e => setField('role_pool', e.target.value as RolePool)}>{Object.entries(roleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="field">Joining date<input type="date" value={form.joining_date ?? ''} onChange={e => setField('joining_date', e.target.value || null)} /></label>
            <label className="field">Weekly off day<select value={form.weekly_off_day ?? ''} onChange={e => setField('weekly_off_day', (e.target.value || null) as Weekday | null)}><option value="">Not set</option>{weekdays.map(day => <option key={day}>{day}</option>)}</select></label>
            <label className="field">Half-duty day<select value={form.half_duty_day ?? ''} onChange={e => setField('half_duty_day', (e.target.value || null) as Weekday | null)}><option value="">Not set</option>{weekdays.map(day => <option key={day}>{day}</option>)}</select></label>
          </div>
          <div className="eligibility"><strong>Shift eligibility</strong><div className="eligibility-row">
            <label><input type="checkbox" checked={form.is_shift_eligible_morning} onChange={e => setField('is_shift_eligible_morning', e.target.checked)} /> Morning (M)</label>
            <label><input type="checkbox" checked={form.is_shift_eligible_evening} onChange={e => setField('is_shift_eligible_evening', e.target.checked)} /> Evening (E)</label>
            <label><input type="checkbox" checked={form.is_shift_eligible_night} onChange={e => setField('is_shift_eligible_night', e.target.checked)} /> Night (N)</label>
          </div></div>
          <label className="full-label">Notes<textarea rows={2} value={form.notes ?? ''} onChange={e => setField('notes', e.target.value || null)} placeholder="Optional notes" /></label>
          <div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={closeModal}>Cancel</button><button className="btn btn-primary" disabled={saving}>{saving ? <><Spinner /> Saving…</> : editingId ? 'Save changes' : 'Create employee'}</button></div>
        </form>
      </Modal>
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} commands={commands} />
      {confirmDialog}
    </div>
  )
}
