import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { Icon, type IconName } from './Icons'

export interface Cmd {
  id: string; label: string; icon: IconName; group: string; run: () => void
  hint?: string; keywords?: string
  /** Only listed once the person starts typing (used for the employee list). */
  searchOnly?: boolean
}

export default function CommandPalette({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: Cmd[] }) {
  const [render, setRender] = useState(open)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) { setRender(true); setQuery(''); setActive(0); return }
    const t = window.setTimeout(() => setRender(false), 180)
    return () => window.clearTimeout(t)
  }, [open])

  useEffect(() => { if (open && render) inputRef.current?.focus() }, [open, render])

  const results = useMemo(() => {
    const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const pool = commands.filter(c => tokens.length > 0 || !c.searchOnly)
    const hits = tokens.length === 0 ? pool : pool.filter(c => {
      const hay = `${c.label} ${c.keywords ?? ''} ${c.group}`.toLowerCase()
      return tokens.every(t => hay.includes(t))
    })
    return hits.slice(0, 40)
  }, [commands, query])

  useEffect(() => { setActive(0) }, [query])
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [active, results])

  if (!render) return null

  const choose = (c: Cmd | undefined) => { if (!c) return; onClose(); c.run() }

  return (
    <div className="cmd-backdrop" data-state={open ? 'open' : 'closed'} role="presentation"
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <section className="cmd" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="cmd-input">
          <Icon name="search" size={18} />
          <input ref={inputRef} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search pages, people and settings…"
            aria-label="Search commands"
            onKeyDown={e => {
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(results.length - 1, a + 1)) }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(0, a - 1)) }
              else if (e.key === 'Enter') { e.preventDefault(); choose(results[active]) }
              else if (e.key === 'Escape') { e.preventDefault(); onClose() }
            }} />
          <kbd>Esc</kbd>
        </div>
        <div className="cmd-list" role="listbox" ref={listRef}>
          {results.length === 0 && <div className="cmd-empty">Nothing matches “{query}”. Try a name, an ID or a page.</div>}
          {results.map((c, i) => (
            <Fragment key={c.id}>
              {(i === 0 || results[i - 1].group !== c.group) && <div className="cmd-group">{c.group}</div>}
              <button type="button" role="option" aria-selected={i === active} data-active={i === active} className={`cmd-item ${i === active ? 'on' : ''}`}
                onMouseMove={() => setActive(i)} onClick={() => choose(c)}>
                <span className="cmd-icon"><Icon name={c.icon} size={16} /></span>
                <span className="cmd-label">{c.label}</span>
                {c.hint && <small>{c.hint}</small>}
              </button>
            </Fragment>
          ))}
        </div>
        <div className="cmd-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>↵</kbd> open</span><span><kbd>Ctrl</kbd><kbd>K</kbd> toggle</span></div>
      </section>
    </div>
  )
}
