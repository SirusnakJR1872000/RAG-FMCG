// Toasts (design brief §4.3): success auto-dismisses after 5 s; errors stay until closed.
import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import Icon from './Icon'

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const close = useCallback((id) => setToasts((all) => all.filter((t) => t.id !== id)), [])
  const notify = useCallback((message, tone = 'success') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((all) => [...all, { id, message, tone }])
    if (tone !== 'error') setTimeout(() => close(id), 5000)
  }, [close])
  const value = useMemo(() => notify, [notify])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} role={t.tone === 'error' ? 'alert' : 'status'}
            className={`flex items-start gap-2 rounded-xl border px-4 py-3 text-sm shadow-lg ${
              t.tone === 'error' ? 'border-red-200 bg-danger-bg text-danger'
                : 'border-green-200 bg-success-bg text-success'}`}>
            <Icon name={t.tone === 'error' ? 'alert' : 'check'} size={16} className="mt-0.5" />
            <span className="flex-1">{t.message}</span>
            <button type="button" onClick={() => close(t.id)} aria-label="Dismiss"><Icon name="x" size={14} /></button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
