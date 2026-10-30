/**
 * Modal — the shared dialog shell: dimmed backdrop, titled card, Escape / click-away to close.
 */

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import { useI18n } from '../i18n';

/** Open dialogs, oldest first: Escape closes only the one on top (a confirmation above Settings, say). */
const openModals: symbol[] = [];

interface ModalProps {
  title: string;
  icon?: ReactNode;
  onClose: () => void;
  /** A wider card. */
  wide?: boolean;
  /** No padding around the content, for dialogs that lay themselves out edge to edge (settings). */
  flush?: boolean;
  children: ReactNode;
}

export default function Modal({ title, icon, onClose, wide = false, flush = false, children }: ModalProps) {
  const { t } = useI18n();
  const id = useRef(Symbol('modal')).current;

  useEffect(() => {
    openModals.push(id);
    return () => {
      openModals.splice(openModals.indexOf(id), 1);
    };
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && openModals[openModals.length - 1] === id && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, id]);

  // Rendered at the end of <body> so a dialog opened from inside a drawer or
  // panel always covers the whole screen (a transformed parent would trap it).
  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div
        className={`modal-card ${wide ? 'modal-wide' : ''} ${flush ? 'modal-flush' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal-header">
          <h3>
            {icon} {title}
          </h3>
          <button className="modal-close" onClick={onClose} aria-label={t('Close')}>
            <X size={16} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
