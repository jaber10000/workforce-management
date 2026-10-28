import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { Icon, type IconName } from './Icons'

type ToastTone = 'success' | 'info' | 'danger'
type Push = (message: string, tone?: ToastTone) => void
const Ctx = createContext<Push>(() => {})
export const useToast = () => useContext(Ctx)

const icons: Record<ToastTone, IconName> = { success: 'checkCircle', info: 'info', danger: 'alert' }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; message: string; tone: ToastTone }[]>([])
  const push = useCallback<Push>((message, tone = 'success') => {
    const id = Date.now() + Math.random()
    setItems(prev => [...prev.slice(-2), { id, message, tone }])
    window.setTimeout(() => setItems(prev => prev.filter(t => t.id !== id)), 3400)
  }, [])
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toast-host" aria-live="polite">
        {items.map(t => (
          <div key={t.id} className={`toast toast-${t.tone}`}>
            <Icon name={icons[t.tone]} size={17} /><span>{t.message}</span><i className="toast-timer" />
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
