import { FormEvent, useState } from 'react'
import { getMe, login } from '../api'
import { Logo } from '../components/Icons'
import { Banner, Spinner } from '../components/ui'
import type { AuthUser } from '../types'

export default function LoginPage({ onLogin }: { onLogin: (u: AuthUser) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try { await login(username.trim(), password); onLogin(await getMe()) }
    catch (err) { setError(err instanceof Error ? err.message : 'Login failed') }
    finally { setBusy(false) }
  }
  return (
    <div className="login-wrap">
      <form className="panel login-card" onSubmit={submit}>
        <Logo size={46} />
        <h1>Workforce Roster</h1>
        <p className="hint">Sign in with the account your administrator created.</p>
        {error && <Banner tone="danger">{error}</Banner>}
        <label className="field">Username<input autoFocus required autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} /></label>
        <label className="field">Password<input required type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
        <button className="btn btn-primary" disabled={busy}>{busy ? <><Spinner /> Signing in…</> : 'Sign in'}</button>
      </form>
    </div>
  )
}
