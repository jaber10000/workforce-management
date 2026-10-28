import { useMemo, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { codeClass, fmtNum, shortDate } from '../utils'
import type { RosterGrid } from '../types'

/**
 * The roster grid with a crosshair highlight (hover a cell → its day column lights up),
 * a marker for today, and per-day on-duty totals in the footer.
 * Hover state lives here so moving the mouse never re-renders the rest of the page.
 */
export default function RosterGridTable({ grid, rows, today, onCellClick, mineId }: {
  grid: RosterGrid; rows: RosterGrid['rows']; today: string
  onCellClick?: (row: RosterGrid['rows'][number], date: string, code: string) => void; mineId?: string | null
}) {
  const [hc, setHc] = useState(-1)

  const totals = useMemo(() => (['M', 'E', 'N'] as const).map(s =>
    grid.days.map((_, i) => grid.rows.reduce((sum, r) => {
      const c = r.codes[i] ?? ''
      return sum + (c === s ? 1 : c === `${s}-H` ? 0.5 : 0)
    }, 0))), [grid])

  const body = useMemo(() => rows.slice(0, 300).map(r => (
    <tr key={r.employee_id} className={mineId && r.employee_id === mineId ? 'row-mine' : ''}>
      <td className="sticky"><strong>{r.employee_name}</strong><small>{r.employee_id} · {r.role.replace('_', ' ')}</small></td>
      {r.codes.map((c, i) => <td key={i} data-c={i} className={onCellClick ? 'editable' : ''} onClick={onCellClick ? () => onCellClick(r, grid.days[i].date, c) : undefined}><span className={codeClass(c)}>{c}</span></td>)}
    </tr>
  )), [rows, grid.days, onCellClick, mineId])

  const onOver = (e: ReactMouseEvent) => {
    const td = (e.target as HTMLElement).closest<HTMLElement>('td[data-c]')
    setHc(td ? Number(td.dataset.c) : -1)
  }

  return (
    <table className="roster-table" onMouseOver={onOver} onMouseLeave={() => setHc(-1)}>
      <colgroup>
        <col />
        {grid.days.map((d, i) => <col key={d.date} className={hc === i ? 'col-hl' : d.date === today ? 'col-today' : ''} />)}
      </colgroup>
      <thead><tr>
        <th className="sticky">Employee</th>
        {grid.days.map((d, i) => (
          <th key={d.date} className={`${hc === i ? 'hl' : ''} ${d.date === today ? 'today' : ''}`}>
            {d.weekday.slice(0, 3)}<small>{shortDate(d.date)}</small>
          </th>
        ))}
      </tr></thead>
      <tbody>{body}</tbody>
      <tfoot>
        {(['Morning', 'Evening', 'Night'] as const).map((label, k) => (
          <tr key={label}>
            <td className="sticky"><strong>{label}</strong><small>people on duty</small></td>
            {totals[k].map((n, i) => <td key={i} data-c={i} className="num tot">{fmtNum(n)}</td>)}
          </tr>
        ))}
      </tfoot>
    </table>
  )
}
