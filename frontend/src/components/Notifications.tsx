/**
 * Notifications: small pop-ups (toasts) that confirm a change or report a problem,
 * and a confirmation dialog that replaces the browser's own confirm() box.
 * Components use them through the hooks in hooks/useNotifications.ts.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';
import { useI18n } from '../i18n';
import { ConfirmContext, ToastContext } from '../hooks/useNotifications';
import type { ConfirmOptions, ToastOptions, Toasts } from '../hooks/useNotifications';
import Modal from './Modal';

type ToastKind = 'success' | 'error' | 'info' | 'warning';

interface ToastItem extends ToastOptions {
  id: number;
  kind: ToastKind;
  message: string;
}

const DEFAULT_DURATION: Record<ToastKind, number> = { success: 4000, info: 5000, warning: 6500, error: 7500 };
const MAX_VISIBLE = 4;

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [pending, setPending] = useState<{ options: ConfirmOptions; resolve: (ok: boolean) => void } | null>(null);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);

  const push = useCallback((kind: ToastKind, message: string, options: ToastOptions = {}) => {
    const id = nextId.current++;
    setToasts((all) => {
      // The same message twice in a row is one notification, not two.
      if (all.some((t) => t.kind === kind && t.message === message)) return all;
      return [...all, { id, kind, message, ...options }].slice(-MAX_VISIBLE);
    });
  }, []);

  const toast = useMemo<Toasts>(
    () => ({
      success: (m, o) => push('success', m, o),
      error: (m, o) => push('error', m, o),
      info: (m, o) => push('info', m, o),
      warning: (m, o) => push('warning', m, o),
      dismiss,
    }),
    [push, dismiss],
  );

  const confirm = useCallback(
    (options: ConfirmOptions) => new Promise<boolean>((resolve) => setPending({ options, resolve })),
    [],
  );

  const answer = (ok: boolean) => {
    pending?.resolve(ok);
    setPending(null);
  };

  return (
    <ToastContext.Provider value={toast}>
      <ConfirmContext.Provider value={confirm}>
        {children}
        <ToastViewport toasts={toasts} onDismiss={dismiss} />
        {pending && <ConfirmDialog options={pending.options} onAnswer={answer} />}
      </ConfirmContext.Provider>
    </ToastContext.Provider>
  );
}

/* ── Toasts ────────────────────────────────────────────────────────── */

const ICONS: Record<ToastKind, typeof Info> = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
  warning: AlertTriangle,
};

function ToastViewport({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: number) => void }) {
  return createPortal(
    <div className="toast-viewport" aria-live="polite">
      {toasts.map((item) => (
        <ToastCard key={item.id} item={item} onDismiss={() => onDismiss(item.id)} />
      ))}
    </div>,
    document.body,
  );
}

function ToastCard({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const { t } = useI18n();
  const Icon = ICONS[item.kind];
  const duration = item.duration ?? (item.action ? 9000 : DEFAULT_DURATION[item.kind]);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const start = useCallback(
    (ms: number) => {
      clearTimeout(timer.current);
      if (duration > 0) timer.current = setTimeout(onDismiss, ms);
    },
    [duration, onDismiss],
  );

  useEffect(() => {
    start(duration);
    return () => clearTimeout(timer.current);
  }, [start, duration]);

  return (
    <div
      className={`toast toast-${item.kind}`}
      role={item.kind === 'error' ? 'alert' : 'status'}
      onMouseEnter={() => clearTimeout(timer.current)}
      onMouseLeave={() => start(2000)}
    >
      <Icon size={18} className="toast-icon" />
      <div className="toast-text">
        {item.title && <strong>{item.title}</strong>}
        <span>{item.message}</span>
        {item.action && (
          <button
            className="toast-action"
            onClick={() => {
              item.action!.onClick();
              onDismiss();
            }}
          >
            {item.action.label}
          </button>
        )}
      </div>
      <button className="toast-close" onClick={onDismiss} aria-label={t('Dismiss')}>
        <X size={14} />
      </button>
    </div>
  );
}

/* ── Confirmation ──────────────────────────────────────────────────── */

function ConfirmDialog({ options, onAnswer }: { options: ConfirmOptions; onAnswer: (ok: boolean) => void }) {
  const { t } = useI18n();
  const cancelRef = useRef<HTMLButtonElement>(null);

  // Start on "Cancel" so a stray Enter can't confirm something destructive.
  useEffect(() => cancelRef.current?.focus(), []);

  return (
    <Modal title={options.title} onClose={() => onAnswer(false)}>
      {options.message && <div className="modal-note confirm-message">{options.message}</div>}
      <div className="modal-actions">
        <button ref={cancelRef} className="btn btn-outline" onClick={() => onAnswer(false)}>
          {options.cancelLabel ?? t('Cancel')}
        </button>
        <button className={`btn ${options.danger ? 'btn-danger-solid' : 'btn-ink'}`} onClick={() => onAnswer(true)}>
          {options.confirmLabel ?? t('Confirm')}
        </button>
      </div>
    </Modal>
  );
}
