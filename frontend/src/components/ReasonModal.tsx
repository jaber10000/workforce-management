import { useEffect, useState, type ReactNode } from 'react'
import { Modal } from './ui'

/** Small dialog that asks for a note / reason. `required` enforces a minimum length before submitting. */
export default function ReasonModal({ open, title, intro, label, required = false, minLength = 3, confirmLabel = 'Confirm', tone = 'primary', extra, onSubmit, onClose }: {
  open: boolean; title: string; intro?: string; label: string; required?: boolean; minLength?: number
  confirmLabel?: string; tone?: 'primary' | 'danger'; extra?: ReactNode
  onSubmit: (text: string) => void | Promise<void>; onClose: () => void
}) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) setText('') }, [open])
  const ok = !required || text.trim().length >= minLength
  async function go() {
    if (!ok || busy) return
    setBusy(true)
    try { await onSubmit(text.trim()) } finally { setBusy(false) }
  }
  return (
    <Modal open={open} onClose={onClose} labelledBy="reason-title" width={460}>
      <div className="confirm" style={{ textAlign: 'left' }}>
        <h2 id="reason-title">{title}</h2>
        {intro && <p>{intro}</p>}
        {extra}
        <label className="field">{label}{required ? ` * (min ${minLength} characters)` : ' (optional)'}
          <textarea rows={3} value={text} autoFocus onChange={e => setText(e.target.value)} maxLength={500} />
        </label>
        <div className="modal-actions">
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className={`btn ${tone === 'danger' ? 'btn-danger' : 'btn-primary'}`} disabled={!ok || busy} onClick={() => void go()}>{confirmLabel}</button>
        </div>
      </div>
    </Modal>
  )
}
