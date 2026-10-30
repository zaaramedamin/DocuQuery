/**
 * Close a popover / menu when the user clicks outside it or presses Escape.
 */

import { useEffect, useRef } from 'react';

export function useDismiss<T extends HTMLElement>(open: boolean, onDismiss: () => void) {
  const ref = useRef<T>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onDismiss();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDismiss();
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onDismiss]);

  return ref;
}
