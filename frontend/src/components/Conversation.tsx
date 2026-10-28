import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchMessageImage, getThread, getTopics, sendMessage } from '../api'
import { Icon } from './Icons'
import { Banner, Spinner } from './ui'
import type { ChatDetail, ChatMessage } from '../types'

const MAX = 3 * 1024 * 1024

function Img({ id, name }: { id: number; name: string | null }) {
  const [src, setSrc] = useState('')
  const [open, setOpen] = useState(false)
  useEffect(() => { let url = ''; fetchMessageImage(id).then(u => { url = u; setSrc(u) }).catch(() => setSrc('')); return () => { if (url) URL.revokeObjectURL(url) } }, [id])
  if (!src) return <div className="chat-img-ph"><Icon name="image" size={18} /> {name ?? 'image'}</div>
  return <>
    <img className="chat-img" src={src} alt={name ?? 'attachment'} onClick={() => setOpen(true)} />
    {open && <div className="modal-backdrop-lite" onClick={() => setOpen(false)} role="dialog" aria-label="Image"><img src={src} alt={name ?? ''} style={{ maxWidth: '92vw', maxHeight: '88vh', borderRadius: 12 }} /></div>}
  </>
}

const toB64 = (f: File) => new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] ?? ''); r.onerror = () => rej(new Error('Could not read the file')); r.readAsDataURL(f) })

/** One employee <-> team leader conversation: text, topic, image attachment. Polls for new messages. */
export default function Conversation({ employeeId, onChanged }: { employeeId: string; onChanged?: () => void }) {
  const [data, setData] = useState<ChatDetail | null>(null)
  const [topics, setTopics] = useState<string[]>([])
  const [text, setText] = useState('')
  const [topic, setTopic] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const count = useRef(0)

  const load = useCallback(async () => {
    try { const d = await getThread(employeeId); setData(d); if (d.messages.length !== count.current) { count.current = d.messages.length; onChanged?.() } }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load the conversation') }
  }, [employeeId, onChanged])
  useEffect(() => { count.current = 0; setData(null); void load(); const t = window.setInterval(() => void load(), 15000); return () => window.clearInterval(t) }, [load])
  useEffect(() => { getTopics().then(setTopics).catch(() => undefined) }, [])
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [data?.messages.length])
  useEffect(() => { if (!file) { setPreview(''); return } const u = URL.createObjectURL(file); setPreview(u); return () => URL.revokeObjectURL(u) }, [file])

  function pick(f: File | undefined) {
    setError('')
    if (!f) return
    if (!/^image\/(png|jpeg|gif|webp)$/.test(f.type)) { setError('Only PNG, JPEG, GIF or WebP images can be sent.'); return }
    if (f.size > MAX) { setError('The image is larger than 3 MB.'); return }
    setFile(f)
  }
  async function send() {
    if (busy || (!text.trim() && !file)) return
    setBusy(true); setError('')
    try {
      await sendMessage(employeeId, { text: text.trim(), topic: topic || undefined, image_b64: file ? await toB64(file) : undefined, image_name: file?.name })
      setText(''); setFile(null); setTopic(''); await load()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not send') } finally { setBusy(false) }
  }

  if (!data) return error ? <Banner tone="danger">{error}</Banner> : <div className="pad"><Spinner /></div>
  const mineSide = data.me_side
  const fmt = (m: ChatMessage) => m.created_at ? new Date(m.created_at).toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''
  return (
    <div className="chat">
      <div className="chat-log" aria-live="polite">
        {data.messages.length === 0 && <p className="hint" style={{ margin: 'auto' }}>No messages yet. {mineSide === 'employee' ? `Write to your team leader${data.leader ? ` (${data.leader.full_name})` : ''} about any observation or problem.` : 'Nothing from this person yet.'}</p>}
        {data.messages.map(m => <div key={m.id} className={`bubble ${m.side === mineSide ? 'mine' : 'theirs'}`}>
          <div className="bubble-head"><b>{m.sender_name}</b>{m.topic && <span className="topic-tag">{m.topic}</span>}<small>{fmt(m)}</small></div>
          {m.text && <p>{m.text}</p>}
          {m.has_image && <Img id={m.id} name={m.image_name} />}
        </div>)}
        <div ref={endRef} />
      </div>
      {error && <Banner tone="danger" onClose={() => setError('')}>{error}</Banner>}
      {preview && <div className="chat-attach"><img src={preview} alt="" /><span>{file?.name}</span><button className="btn btn-ghost btn-sm" onClick={() => setFile(null)}>Remove</button></div>}
      <div className="chat-compose">
        {mineSide === 'employee' && <select aria-label="Topic" value={topic} onChange={e => setTopic(e.target.value)}><option value="">Topic…</option>{topics.map(t => <option key={t}>{t}</option>)}</select>}
        <textarea rows={2} value={text} maxLength={2000} placeholder="Write a message…" onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void send() }} />
        <label className="btn btn-secondary btn-icon" title="Attach an image" aria-label="Attach an image"><Icon name="image" size={18} /><input type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden onChange={e => { pick(e.target.files?.[0]); e.target.value = '' }} /></label>
        <button className="btn btn-primary" disabled={busy || (!text.trim() && !file)} onClick={() => void send()}>{busy ? <Spinner /> : <Icon name="send" size={16} />} Send</button>
      </div>
    </div>
  )
}
