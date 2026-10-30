/**
 * Notification hooks:
 *
 *   const toast = useToast();      toast.success('Saved'); toast.error('Could not save');
 *   const confirm = useConfirm();  if (await confirm({ title: 'Delete?', danger: true })) …
 *
 * The provider that renders them is components/Notifications.tsx.
 */

import { createContext, useContext } from 'react';
import type { ReactNode } from 'react';

export interface ToastOptions {
  title?: string;
  /** A button on the toast (e.g. "Upgrade"). */
  action?: { label: string; onClick: () => void };
  /** Milliseconds before it disappears; 0 keeps it until dismissed. */
  duration?: number;
}

export interface ConfirmOptions {
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Style the confirm button as destructive. */
  danger?: boolean;
}

export interface Toasts {
  success: (message: string, options?: ToastOptions) => void;
  error: (message: string, options?: ToastOptions) => void;
  info: (message: string, options?: ToastOptions) => void;
  warning: (message: string, options?: ToastOptions) => void;
  dismiss: (id: number) => void;
}

export type Confirm = (options: ConfirmOptions) => Promise<boolean>;

export const ToastContext = createContext<Toasts | null>(null);
export const ConfirmContext = createContext<Confirm | null>(null);

export function useToast(): Toasts {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <NotificationsProvider>');
  return ctx;
}

export function useConfirm(): Confirm {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error('useConfirm must be used inside <NotificationsProvider>');
  return ctx;
}
