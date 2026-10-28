import type {
  AuditEntry, Employee, EmployeePage, EmployeePayload, Fairness, LeaveActionResult, Leave,
  LeaveBalance, LeaveImpact, LeavePage, LeavePayload, LeaveRosterResult, ReplacementCandidate, RosterDetail, RosterDiff, RosterVersion,
  AuthUser, ChatDetail, KpiBulkResult, KpiInput, KpiOverview, KpiScope, MyKpi, PersonHit, TeamPerformance, Kpi, ChatMessage, ChatThread, ImportReport, MyShifts, TeamCard, TeamRoster, RosterHistory, Swap, TeamPlan, TeamRow, UserRow,
} from './types'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1'

const TOKEN_KEY = 'wr_token'
export const auth = {
  get token() { try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null } },
  set(token: string | null) { try { if (token) sessionStorage.setItem(TOKEN_KEY, token); else sessionStorage.removeItem(TOKEN_KEY) } catch { /* private mode */ } },
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = auth.token
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options?.headers ?? {}) },
  })
  if (!response.ok) {
    if (response.status === 401 && token) { auth.set(null); window.dispatchEvent(new Event('auth-expired')) }
    const detail = await response.json().catch(() => null)
    const msg = Array.isArray(detail?.detail) ? detail.detail.map((d: { msg: string }) => d.msg).join('; ') : detail?.detail
    throw new Error(msg ?? `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

// ---- auth ----
export async function login(username: string, password: string) {
  const r = await post<AuthUser & { access_token: string }>('/auth/login', { username, password })
  auth.set(r.access_token)
  return r
}
export const getMe = () => request<AuthUser>('/auth/me')
export const logout = () => auth.set(null)
export const getUsers = () => request<UserRow[]>('/auth/users')
export const createUser = (u: { username: string; password: string; role: string; employee_id?: string; full_name?: string; team?: string }) =>
  post<UserRow & { profile_created?: boolean }>('/auth/users', u)
export interface AccountRow { username: string; password?: string; role: string; employee_id?: string; name?: string; team?: string }
export const importAccounts = (rows: AccountRow[]) =>
  post<{ created: number; updated: number; profiles_created: number; rejected: number; errors: { row: number; username: string; error: string }[] }>('/auth/users/bulk', { rows })
export const renameTeamsToLeaders = () => post<{ renamed: Record<string, string>; still_numbered: string[]; teams: TeamRow[] }>('/teams/rename-to-leaders')
export const getTeams = () => request<TeamRow[]>('/teams')
export const autoAssignTeams = (dryRun: boolean, teams = 5, seniorsPerTeam = 2, seed?: number) =>
  post<TeamPlan>(`/teams/auto-assign?dry_run=${dryRun}&teams=${teams}&seniors_per_team=${seniorsPerTeam}${seed !== undefined ? `&seed=${seed}` : ''}`)
export const getMyTeam = () => request<TeamCard>('/me/team')
export const getMyShifts = (days = 14) => request<MyShifts>(`/me/shifts?days=${days}`)
export const getTeamRoster = (days = 14, team?: string) => request<TeamRoster>(`/me/team/roster?days=${days}${team ? `&team=${encodeURIComponent(team)}` : ''}`)
export const searchPeople = (q: string) => request<PersonHit[]>(`/me/search?q=${encodeURIComponent(q)}`)
export const getMyKpi = (months = 12) => request<MyKpi>(`/kpi/me?months=${months}`)
export const getKpiScope = (period: string) => request<KpiScope>(`/kpi/scope?period=${period}`)
export const saveKpi = (employeeId: string, period: string, body: KpiInput) =>
  request<Kpi>(`/kpi/${encodeURIComponent(employeeId)}/${period}`, { method: 'PUT', body: JSON.stringify(body) })
export const saveKpiBulk = (period: string, rows: (KpiInput & { employee_id: string })[]) => post<KpiBulkResult>('/kpi/bulk', { period, rows })
export const getTeamPerformance = (period: string, team?: string) =>
  request<TeamPerformance>(`/kpi/team?period=${period}${team ? `&team=${encodeURIComponent(team)}` : ''}`)
export const getKpiOverview = (period: string) => request<KpiOverview>(`/kpi/overview?period=${period}`)
export const getThreads = () => request<ChatThread[]>('/messages/threads')
export const getUnread = () => request<{ unread: number }>('/messages/unread')
export const getThread = (employeeId: string) => request<ChatDetail>(`/messages/thread/${encodeURIComponent(employeeId)}`)
export const getTopics = () => request<string[]>('/messages/topics')
export const sendMessage = (employeeId: string, body: { text: string; topic?: string; image_b64?: string; image_name?: string }) =>
  post<ChatMessage>(`/messages/thread/${encodeURIComponent(employeeId)}`, body)
export async function fetchMessageImage(id: number): Promise<string> {
  const r = await fetch(`${API}/messages/${id}/image`, { headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {} })
  if (!r.ok) throw new Error('Could not load the image')
  return URL.createObjectURL(await r.blob())
}
export const updateUser = (username: string, patch: Partial<{ password: string; role: string; is_active: boolean }>) =>
  request<UserRow>(`/auth/users/${encodeURIComponent(username)}`, { method: 'PATCH', body: JSON.stringify(patch) })

export function getEmployees(params: { search?: string; role_pool?: string; is_active?: boolean | null; skip?: number; limit?: number }) {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  if (params.role_pool) query.set('role_pool', params.role_pool)
  if (params.is_active !== null && params.is_active !== undefined) query.set('is_active', String(params.is_active))
  query.set('skip', String(params.skip ?? 0))
  query.set('limit', String(params.limit ?? 100))
  return request<EmployeePage>(`/employees?${query.toString()}`)
}

export function createEmployee(payload: EmployeePayload) {
  return request<Employee>('/employees', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateEmployee(employeeId: string, payload: Partial<EmployeePayload>) {
  return request<Employee>(`/employees/${encodeURIComponent(employeeId)}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function deactivateEmployee(employeeId: string) {
  return request<void>(`/employees/${encodeURIComponent(employeeId)}`, { method: 'DELETE' })
}

// ---- leave ----
export function getLeaves(params: { status?: string; employee_id?: string; limit?: number }) {
  const q = new URLSearchParams()
  if (params.status) q.set('status', params.status)
  if (params.employee_id) q.set('employee_id', params.employee_id)
  q.set('limit', String(params.limit ?? 200))
  return request<LeavePage>(`/leaves?${q.toString()}`)
}
export function applyLeave(payload: LeavePayload) {
  return request<Leave>('/leaves', { method: 'POST', body: JSON.stringify(payload) })
}
export function decideLeave(applicationId: string, action: 'approve' | 'reject' | 'cancel') {
  return request<LeaveActionResult | Leave>(`/leaves/${encodeURIComponent(applicationId)}/${action}`, {
    method: 'POST', body: JSON.stringify({ auto_roster: true }),
  })
}
export function previewLeave(applicationId: string, timeLimit = 15) {
  return request<LeaveRosterResult>(`/leaves/${encodeURIComponent(applicationId)}/preview?time_limit_seconds=${timeLimit}`, { method: 'POST' })
}
export function getLeaveImpact(applicationId: string) {
  return request<{ application_id: string; impact: LeaveImpact | null }>(`/leaves/${encodeURIComponent(applicationId)}/impact`)
}
export function getReplacements(versionId: number, workDate: string, shift: string) {
  return request<{ candidates: ReplacementCandidate[] }>(`/roster/versions/${versionId}/replacements?work_date=${workDate}&shift=${shift}`)
}
export function getLeaveBalance(employeeId: string, year?: number) {
  const q = year ? `?year=${year}` : ''
  return request<LeaveBalance[]>(`/leaves/balance/${encodeURIComponent(employeeId)}${q}`)
}

// ---- roster ----
export function getVersions() { return request<RosterVersion[]>('/roster/versions?limit=100') }
export function getRosterDetail(id: number) { return request<RosterDetail>(`/roster/versions/${id}`) }
export function getFairness(id: number) { return request<Fairness>(`/roster/versions/${id}/fairness`) }
export function getDiff(id: number) { return request<RosterDiff>(`/roster/versions/${id}/diff`) }
export function getAuditLog(versionId?: number) {
  return request<AuditEntry[]>(`/roster/audit-log?limit=50${versionId ? `&version_id=${versionId}` : ''}`)
}
export function generateRoster(start_date: string, days: number, time_limit_seconds: number) {
  return request<RosterVersion>('/roster/generate', { method: 'POST', body: JSON.stringify({ start_date, days, time_limit_seconds }) })
}
export function regenerateRoster(base_version_id: number, from_date: string | null, time_limit_seconds: number, reason?: string) {
  return post<RosterVersion>('/roster/regenerate', { base_version_id, from_date, time_limit_seconds, reason: reason || undefined })
}
export function publishRoster(id: number, acknowledge_shortage: boolean) {
  return post<RosterVersion>(`/roster/versions/${id}/publish`, { acknowledge_shortage })
}
export function approveRoster(id: number, acknowledge_shortage: boolean, note?: string) {
  return post<RosterVersion>(`/roster/versions/${id}/approve`, { acknowledge_shortage, note: note || undefined })
}
export function rejectRoster(id: number, note: string) { return post<RosterVersion>(`/roster/versions/${id}/reject`, { note }) }
export function editCell(id: number, employee_id: string, work_date: string, code: string, reason: string) {
  return request<{ code: string }>(`/roster/versions/${id}/assignments`, { method: 'PUT', body: JSON.stringify({ employee_id, work_date, code, reason }) })
}
export const getHistory = (id: number) => request<RosterHistory>(`/roster/versions/${id}/history`)
export async function downloadExport(id: number) {
  const r = await fetch(`${API}/roster/versions/${id}/export.xlsx`, { headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {} })
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Export failed (${r.status})`)
  const name = /filename="([^"]+)"/.exec(r.headers.get('content-disposition') ?? '')?.[1] ?? `roster_${id}.xlsx`
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url)
}
export function getAudit(f: { actor?: string; action?: string; entity_id?: string; offset?: number; limit?: number }) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== '') q.set(k, String(v))
  return request<AuditEntry[]>(`/roster/audit-log?${q.toString()}`)
}

// ---- swaps ----
export const getSwaps = (status?: string) => request<Swap[]>(`/swaps${status ? `?status=${status}` : ''}`)
export const requestSwap = (b: { requester_id?: string; counterpart_id: string; work_date: string; reason?: string }) => post<Swap>('/swaps', b)
export const swapAction = (id: string, action: 'accept' | 'decline' | 'cancel' | 'approve' | 'reject', note?: string) =>
  post<Swap | { swap: Swap; warning: string | null }>(`/swaps/${id}/${action}`, note ? { note } : undefined)

/** Step 7 Excel reports, e.g. downloadReport('/exports/leaves.xlsx?status=Approved'),
 *  downloadReport('/exports/roster/weekly.xlsx?week_start=2026-10-26'), '/exports/employees.xlsx', '/exports/coverage.xlsx?version_id=3'. */
export async function downloadReport(path: string) {
  const r = await fetch(`${API}${path}`, { headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {} })
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `Export failed (${r.status})`)
  const name = /filename="([^"]+)"/.exec(r.headers.get('content-disposition') ?? '')?.[1] ?? 'report.xlsx'
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url)
}
/** Names only - what an employee may see of colleagues (e.g. to pick a swap partner). */
export const getDirectory = () => request<{ employee_id: string; full_name: string; role_pool: string }[]>('/employees/directory')

/** Excel import: raw .xlsx bytes as the body. Dry run (default) saves nothing and returns exact counts. */
export async function importWorkbook(file: File, opts: { dryRun: boolean; weekStart?: string; employees: boolean; requirements: boolean; roster: boolean }) {
  const q = new URLSearchParams({ dry_run: String(opts.dryRun), employees: String(opts.employees), requirements: String(opts.requirements), roster: String(opts.roster), filename: file.name.slice(0, 120) })
  if (opts.weekStart) q.set('week_start', opts.weekStart)
  return request<ImportReport>(`/imports/roster?${q.toString()}`, {
    method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' },
  })
}
