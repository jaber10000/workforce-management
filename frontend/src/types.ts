export type Gender = 'female' | 'male' | 'other' | 'prefer_not_to_say'
export type RolePool = 'general' | 'senior_support' | 'supervisor' | 'other'
export type Weekday = 'Monday' | 'Tuesday' | 'Wednesday' | 'Thursday' | 'Friday' | 'Saturday' | 'Sunday'

export interface Employee {
  id: number
  employee_id: string
  full_name: string
  gender: Gender | null
  phone_number: string | null
  home_thana: string | null
  role_pool: RolePool
  weekly_off_day: Weekday | null
  half_duty_day: Weekday | null
  joining_date: string | null
  is_shift_eligible_morning: boolean
  is_shift_eligible_evening: boolean
  is_shift_eligible_night: boolean
  is_active: boolean
  notes: string | null
  team: string | null
  created_at: string
  updated_at: string
}

export type EmployeePayload = Omit<Employee, 'id' | 'created_at' | 'updated_at'>
export interface EmployeePage { items: Employee[]; total: number; skip: number; limit: number }

// ---- Phase 3: roster engine, leave ----
export type LeaveType = 'Sick' | 'Casual' | 'Annual'
export type LeaveStatus = 'Pending' | 'Approved' | 'Rejected' | 'Cancelled'

export interface Leave {
  id: number; application_id: string; employee_id: string; leave_type: LeaveType
  start_date: string; end_date: string; half_day: boolean; days: number
  status: LeaveStatus; reason: string | null; decided_by: string | null; decision_note: string | null
}
export interface LeavePage { items: Leave[]; total: number; skip: number; limit: number }
export interface LeaveBalance {
  leave_type: LeaveType; year: number; entitlement: number; carried_forward: number; total: number
  used: number; pending: number; remaining: number; available: number; half_day_allowed: boolean
}
export interface LeavePayload {
  employee_id: string; leave_type: LeaveType; start_date: string; end_date: string; half_day: boolean; reason?: string
}
export interface LeaveActionResult {
  leave: Leave; roster_adjustment: string; roster_version: RosterVersion | null
  impact?: LeaveImpact | null; off_day_plan?: OffDayPlanInfo | null
}

export interface ShortageTotals { morning: number; evening: number; night: number; senior: number; total: number }
export interface RosterVersion {
  id: number; roster_key: string; version_no: number; start_date: string; end_date: string
  status: 'draft' | 'approved' | 'rejected' | 'published' | 'superseded'; trigger: string; reason: string | null; base_version_id: number | null
  lock_before: string | null; solver_status: string; objective: number | null; solve_seconds: number
  summary: { shortage?: ShortageTotals; days_with_shortage?: number; changes?: number; warnings?: string[]; employees?: number }
  created_at: string; created_by: string | null; approved_by: string | null; approved_at: string | null
  review_note: string | null; published_by: string | null; published_at: string | null
}
export interface ShiftCoverage {
  required: number; assigned: number; shortage: number
  senior_required: number; senior_assigned: number; senior_shortage: number
}
export interface CoverageDay {
  date: string; weekday: string; status: 'OK' | 'SHORTAGE'; shortage_total: number; senior_shortage_total: number
  shifts: { morning: ShiftCoverage; evening: ShiftCoverage; night: ShiftCoverage }
}
export interface Coverage { totals: ShortageTotals; days: CoverageDay[]; days_with_shortage: number; has_shortage: boolean }
export interface RosterGrid {
  days: { date: string; weekday: string }[]
  rows: { employee_id: string; employee_name: string; role: string; team?: string | null; codes: string[] }[]
}
export interface RosterWarning { type: string; severity: 'danger' | 'info'; message: string; count?: number; employee_ids?: string[] }
export interface RosterDetail { version: RosterVersion; coverage: Coverage; grid: RosterGrid; warnings?: RosterWarning[] }
export interface FairnessRow {
  employee_id: string; employee_name: string; role: string; night_eligible: boolean
  morning: number; evening: number; night: number; total: number; half_duty: number
  leave_days: number; reserve_days: number; max_consecutive_nights: number; undesirable_score: number
}
export interface Fairness {
  summary: { night_pool: number; night_min: number; night_max: number; night_spread: number; night_avg: number; evening_spread: number; total_spread: number }
  overloaded_night: string[]; employees: FairnessRow[]
}
export interface RosterDiff { changes: { employee_id: string; date: string; from: string | null; to: string | null }[] }
export interface AuditEntry { id: number; created_at: string; actor: string; action: string; entity_type?: string; entity_id: string; version_id: number | null; details: Record<string, unknown> }

export interface ImpactShortage { date: string; shift: 'M' | 'E' | 'N'; required: number; assigned: number; shortage: number; senior_shortage: number }
export interface ReplacementCandidate { employee_id: string; employee_name: string; current_code: string; option: string; senior: boolean }
export interface OffDayPlanInfo { employee_id: string; effective_from: string; continuous_days: number; weekly_off: string; half_duty: string | null; previous_weekly_off: string | null }
export interface LeaveImpact {
  application_id: string; employee_id: string; from: string; to: string
  base_version_id: number; new_version_id: number | null
  removed_assignments: { date: string; was: string }[]
  replacements: { date: string; shift: string; employee_id: string; from: string | null; to: string; how: string }[]
  employee_other_changes: { date: string; from: string | null; to: string | null }[]
  change_total: number; other_employees_changed: number
  shortages: ImpactShortage[]; shortage_total_before: number; shortage_total_after: number
  proposals: { date: string; shift: string; missing: number; senior_missing: number; candidates: ReplacementCandidate[] }[]
  off_day_plan: OffDayPlanInfo | null
}
export interface LeaveRosterResult {
  roster_adjustment: string; impact: LeaveImpact | null; off_day_plan: OffDayPlanInfo | null
  simulated?: boolean; roster_version?: RosterVersion | null
}

// ---- app shell ----
export type Page = 'dashboard' | 'employees' | 'roster' | 'leaves' | 'approvals' | 'swaps' | 'audit' | 'users' | 'import' | 'teams' | 'portal' | 'chat' | 'kpi'

export interface AuthUser { username: string; role: 'admin' | 'manager' | 'supervisor' | 'employee'; employee_id: string | null; auth_required?: boolean }
export interface TeamRow { team: string; size: number; supervisors: { employee_id: string; full_name: string }[]; seniors: { employee_id: string; full_name: string }[]; night_eligible: number; male: number; female: number }
export interface TeamPlan { dry_run: boolean; seed: number; changed: number; warnings: string[]; teams: TeamRow[] }
export interface UserRow { username: string; role: string; employee_id: string | null; is_active: boolean }
export interface Swap {
  id: number; swap_id: string; requester_id: string; counterpart_id: string; work_date: string
  status: 'pending_counterpart' | 'pending_manager' | 'approved' | 'rejected' | 'declined' | 'cancelled'
  reason: string | null; decided_by: string | null; decision_note: string | null; result_version_id: number | null
}
export interface RosterHistory {
  roster_key: string; current_version_id: number
  versions: { id: number; version_no: number; status: RosterVersion['status']; trigger: string; reason: string | null; base_version_id: number | null
    created_by: string | null; created_at: string | null; approved_by: string | null; approved_at: string | null; review_note: string | null
    published_by: string | null; published_at: string | null; changes: number; shortage: number }[]
  events: { id: number; time: string | null; actor: string; action: string; version_id: number | null; details: Record<string, unknown> }[]
}

export interface ImportReport {
  dry_run: boolean; sheets: string[]; errors: string[]; warnings: string[]
  employees: { created: number; updated: number; skipped: number } | null
  requirements: number | null
  leaves: { created: number; updated: number } | null
  roster: { version_id: number | null; start_date: string; end_date: string; cells: number; employees: number
    unknown_employee_ids: string[]; not_in_file_active_employees: number; shortage_total: number; days_with_shortage: number } | null
}

export interface Person { employee_id: string; full_name: string; role_pool: string }
export interface TeamCard { team: string | null; size: number; leader: Person | null; leaders?: Person[]; seniors: Person[]; members: (Person & { is_me: boolean })[] }
export interface MyShifts { employee_id: string; published_version_id: number | null; items: { date: string; weekday: string; code: string | null; label: string }[]; next_duty: { date: string; weekday: string; code: string | null; label: string } | null }
export interface TeamRoster { team: string; published_version_id: number | null; days: { date: string; weekday: string }[]; rows: (Person & { weekly_off_day: string | null; codes: string[] })[] }
export interface ChatMessage { id: number; employee_id: string; sender: string; sender_name: string; side: 'employee' | 'staff'; topic: string | null; text: string; has_image: boolean; image_name: string | null; image_size: number | null; created_at: string | null }
export interface ChatThread { employee_id: string; full_name: string; role_pool: string; team: string | null; leader: { employee_id: string; full_name: string } | null; unread: number; last: ChatMessage | null }
export interface ChatDetail { employee: { employee_id: string; full_name: string; team: string | null }; leader: { employee_id: string; full_name: string } | null; me_side: 'employee' | 'staff'; messages: ChatMessage[] }

// ---- people search + KPI ----
export interface PersonHit extends Person { team: string | null; leader: string | null; same_team: boolean }
export interface Kpi { employee_id: string; period: string; score: number; quality: number | null; attendance: number | null; productivity: number | null; csat: number | null; remarks: string | null; uploaded_by: string; updated_at: string | null }
export interface KpiInput { score?: number | null; quality?: number | null; attendance?: number | null; productivity?: number | null; csat?: number | null; remarks?: string | null }
export interface MyKpi { employee_id: string; full_name: string; team: string | null; items: Kpi[]; latest: Kpi | null; change: number | null; is_team_leader: boolean; can_upload: boolean }
export interface KpiScope { period: string; people: (Person & { team: string | null; kpi: Kpi | null })[] }
export interface KpiBulkResult { period: string; created: number; updated: number; rejected: number; errors: { row: number; employee_id: string; error: string }[] }
export interface TeamStats { team: string; leader: { employee_id: string; full_name: string } | null; members: number; reported: number; average: number | null; best: number | null; lowest: number | null; metrics: Record<'quality' | 'attendance' | 'productivity' | 'csat', number | null> }
export interface TeamPerformance extends TeamStats { period: string; rows: (Person & { kpi: Kpi | null; change: number | null })[]; trend: { period: string; average: number | null; reported: number }[] }
export interface KpiOverview { period: string; teams: (TeamStats & { is_mine: boolean; rank: number | null })[] }
