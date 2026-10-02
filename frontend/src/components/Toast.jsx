import { createContext, useCallback, useContext, useRef, useState } from 'react';
import Icon from './Icon.jsx';

const ToastContext = createContext(() => {});
const ICONS = { success: 'check-circle', error: 'x-circle', info: 'bolt', warn: 'alert' };

/** App-wide toast notifications: short, non-blocking, announced to screen readers. */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const seq = useRef(0);

  const dismiss = useCallback((id) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);
  const toast = useCallback((message, tone = 'info', ms = 6000) => {
    const id = ++seq.current;
    setToasts((ts) => [...ts.slice(-3), { id, message, tone }]);
    if (ms) setTimeout(() => dismiss(id), ms);
  }, [dismiss]);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <Icon name={ICONS[t.tone] || 'bolt'} />
            <span>{t.message}</span>
            <button className="icon-btn sm" onClick={() => dismiss(t.id)} aria-label="Dismiss notification">
              <Icon name="close" size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
